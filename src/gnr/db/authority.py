"""The transport-agnostic handler core — `AuthoritySource`.

All registry logic lives here, Sema types in / Sema types out. The rabbit
consumer and the FastAPI façade (step 5) are thin adapters that translate a
request into one of these calls and a result back onto their transport; they
hold no logic of their own. Keeping the backing store behind this interface is
also what makes the registry's authority swappable later (a single-writer
Postgres today, a distributed/on-chain record behind the same surface tomorrow).
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

from collections.abc import Iterable

from gnr.db.alias_ledger import claim_alias
from gnr.db.models import ConnectivityEdgeSql, GNodeSql
from gnr.db.session import SessionLocal
from gnr.db.validate import is_forest_root, parent_alias, validate_registry
from gnr.sema.enums import GNodeStatus
from gnr.sema.property_format import LeftRightDot, UUID4Str
from gnr.sema.types import (
    ConnectivityEdgeGt,
    GNodeForest,
    GNodeGt,
    GNodeReparentCmd,
)


class ReparentError(Exception):
    """A re-parent command could not be applied; the whole transaction rolls back."""


@dataclass(frozen=True)
class EdgeView:
    """Active connectivity edges incident on a GNode, parent side and child side."""

    parents: list[ConnectivityEdgeGt]
    children: list[ConnectivityEdgeGt]


# ---- pure alias-rewrite logic (no DB — unit-testable) ----------------------

def in_subtree(alias: LeftRightDot, prefix: LeftRightDot) -> bool:
    """True if `alias` is `prefix` itself or a descendant of it (materialized path)."""
    return alias == prefix or alias.startswith(prefix + ".")


def rewrite_alias(alias: LeftRightDot, old_prefix: LeftRightDot, new_prefix: LeftRightDot) -> LeftRightDot:
    """Rewrite one materialized-path alias from `old_prefix` to `new_prefix`."""
    return new_prefix + alias[len(old_prefix):]


def moved_child_new_prefix(new_node_alias: LeftRightDot, child_alias: LeftRightDot) -> LeftRightDot:
    """The alias-prefix a moved child takes under the new node N (N.alias + child's last word)."""
    return f"{new_node_alias}.{child_alias.rsplit('.', 1)[-1]}"


def subtree_rewrite_map(
    aliases: Iterable[LeftRightDot], old_prefix: LeftRightDot, new_prefix: LeftRightDot
) -> dict[LeftRightDot, LeftRightDot]:
    """Map every alias in the subtree rooted at `old_prefix` to its rewritten alias.

    The pure core of the recursive re-parent rewrite: a subtree is a set of
    materialized-path aliases sharing a prefix, and the rewrite is a prefix swap.
    """
    return {
        a: rewrite_alias(a, old_prefix, new_prefix)
        for a in aliases
        if in_subtree(a, old_prefix)
    }


class AuthoritySource(ABC):
    """The registry's read + mutate surface. Postgres is one implementation."""

    @abstractmethod
    def get_by_id(self, g_node_id: UUID4Str) -> GNodeGt | None: ...

    @abstractmethod
    def get_by_alias(self, alias: LeftRightDot) -> GNodeGt | None: ...

    @abstractmethod
    def assert_active(self, g_node_id: UUID4Str) -> bool:
        """True iff a GNode with this id exists and is Active — FIS's hot-path check."""

    @abstractmethod
    def fetch_edges(self, g_node_id: UUID4Str) -> EdgeView: ...

    @abstractmethod
    def apply_reparent(self, cmd: GNodeReparentCmd) -> GNodeForest: ...


class PostgresAuthority(AuthoritySource):
    """Single-writer Postgres implementation of `AuthoritySource`."""

    def __init__(self, session_factory=SessionLocal) -> None:
        self._session_factory = session_factory

    # ---- reads -------------------------------------------------------------

    def get_by_id(self, g_node_id: UUID4Str) -> GNodeGt | None:
        with self._session_factory() as s:
            row = s.get(GNodeSql, g_node_id)
            return row.to_gt() if row is not None else None

    def get_by_alias(self, alias: LeftRightDot) -> GNodeGt | None:
        with self._session_factory() as s:
            row = s.query(GNodeSql).filter_by(alias=alias).one_or_none()
            return row.to_gt() if row is not None else None

    def assert_active(self, g_node_id: UUID4Str) -> bool:
        with self._session_factory() as s:
            row = s.get(GNodeSql, g_node_id)
            return row is not None and row.status == GNodeStatus.Active

    def fetch_edges(self, g_node_id: UUID4Str) -> EdgeView:
        with self._session_factory() as s:
            active = ConnectivityEdgeSql.status == GNodeStatus.Active
            parents = (
                s.query(ConnectivityEdgeSql)
                .filter(ConnectivityEdgeSql.to_g_node_id == g_node_id, active)
                .all()
            )
            children = (
                s.query(ConnectivityEdgeSql)
                .filter(ConnectivityEdgeSql.from_g_node_id == g_node_id, active)
                .all()
            )
            return EdgeView(
                parents=[e.to_gt() for e in parents],
                children=[e.to_gt() for e in children],
            )

    # ---- the mutation ------------------------------------------------------

    def apply_reparent(self, cmd: GNodeReparentCmd) -> GNodeForest:
        """Introduce node N and re-parent the named children beneath it.

        The whole operation — insert N, recursively rewrite each moved child's
        subtree aliases, retire/create the structural edges, claim every new
        alias, and validate the result — commits in ONE transaction. Returns the
        affected **forest** (rooted at N): its updated GNodes (new aliases) + the
        structural edges created (E→N and N→each moved child).
        """
        n = cmd.new_node
        with self._session_factory() as s:
            if is_forest_root(n.alias):
                raise ReparentError(f"new node {n.alias!r} is a forest root; nothing to re-parent under")
            e_alias = parent_alias(n.alias)
            e = s.query(GNodeSql).filter_by(alias=e_alias).one_or_none()
            if e is None:
                raise ReparentError(f"parent {e_alias!r} of new node {n.alias!r} not found")

            s.add(GNodeSql.from_gt(n))
            claim_alias(s, n.alias, n.g_node_id)
            s.flush()

            updated: dict[str, GNodeSql] = {n.g_node_id: s.get(GNodeSql, n.g_node_id)}
            created_edges: list[ConnectivityEdgeSql] = []
            edge_e_to_n = ConnectivityEdgeSql(
                id=str(uuid.uuid4()), from_g_node_id=e.id,
                to_g_node_id=n.g_node_id, status=GNodeStatus.Active,
            )
            s.add(edge_e_to_n)
            created_edges.append(edge_e_to_n)

            for child_id in cmd.moved_child_g_node_ids:
                child = s.get(GNodeSql, child_id)
                if child is None:
                    raise ReparentError(f"moved child {child_id!r} not found")
                old_prefix = child.alias
                new_prefix = moved_child_new_prefix(n.alias, old_prefix)
                self._rewrite_prefix(s, old_prefix, new_prefix, updated)

                old_edge = (
                    s.query(ConnectivityEdgeSql)
                    .filter_by(from_g_node_id=e.id, to_g_node_id=child_id,
                               status=GNodeStatus.Active)
                    .one_or_none()
                )
                if old_edge is not None:
                    old_edge.status = GNodeStatus.PermanentlyDeactivated  # retire, keep for history
                edge_n_to_child = ConnectivityEdgeSql(
                    id=str(uuid.uuid4()), from_g_node_id=n.g_node_id,
                    to_g_node_id=child_id, status=GNodeStatus.Active,
                )
                s.add(edge_n_to_child)
                created_edges.append(edge_n_to_child)

            violations = validate_registry(s)
            if violations:
                raise ReparentError(f"re-parent would violate invariants: {violations}")

            broadcast = GNodeForest(
                roots=[n.alias],
                nodes=[row.to_gt() for row in updated.values()],
                edges=[edge.to_gt() for edge in created_edges],
            )
            s.commit()
        return broadcast

    @staticmethod
    def _rewrite_prefix(
        session, old_prefix: str, new_prefix: str, updated: dict[str, GNodeSql]
    ) -> None:
        """Recursively rewrite `old_prefix` and every descendant alias to `new_prefix`.

        Aliases are a dotted materialized path, so a subtree rewrite is a prefix
        rewrite: a node at `old_prefix + suffix` moves to `new_prefix + suffix`.
        Each old alias is stashed in `prev_alias` and the new one claimed in the
        ledger (alias-uniqueness-through-time).
        """
        affected = (
            session.query(GNodeSql)
            .filter(
                (GNodeSql.alias == old_prefix)
                | (GNodeSql.alias.like(old_prefix + ".%"))
            )
            .all()
        )
        for node in affected:
            new_alias = rewrite_alias(node.alias, old_prefix, new_prefix)
            node.prev_alias = node.alias
            node.alias = new_alias
            session.flush()  # land the rename before claiming, so the unique index is consistent
            claim_alias(session, new_alias, node.id)
            updated[node.id] = node
