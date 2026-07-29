"""The transport-agnostic handler core — `AuthoritySource`.

All registry logic lives here, Sema types in / Sema types out. The rabbit
consumer and the FastAPI façade (step 5) are thin adapters that translate a
request into one of these calls and a result back onto their transport; they
hold no logic of their own. Keeping the backing store behind this interface is
also what makes the registry's authority swappable later (a single-writer
Postgres today, a distributed/on-chain record behind the same surface tomorrow).
"""

from __future__ import annotations

import hashlib
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass

from gnr.db.alias_ledger import claim_alias
from gnr.db.models import AliasAssignmentSql, CommandLogSql, ConnectivityEdgeSql, GNodeSql
from gnr.db.session import SessionLocal
from gnr.db.validate import is_forest_root, parent_alias, universe_of, validate_registry
from gnr.ids import command_hash
from gnr.sema.enums import GNodeStatus
from gnr.sema.property_format import LeftRightDot, UUID4Str
from gnr.sema.types import (
    ConnectivityEdgeGt,
    GNodeCreateCmd,
    GNodeForest,
    GNodeGt,
    GNodeReparentCmd,
)


class CreateError(Exception):
    """A create command could not be applied; the whole transaction rolls back."""


class ReparentError(Exception):
    """A re-parent command could not be applied; the whole transaction rolls back."""


@dataclass(frozen=True)
class EdgeView:
    """Active NON-TREE connectivity edges incident on a GNode, by direction.

    Parent-child tree edges are never stored (the tree is the alias structure);
    what an edge row means is a tie/loop/meshed span — see `gnr.db.validate`
    `check_edges_non_tree`.
    """

    parents: list[ConnectivityEdgeGt]
    children: list[ConnectivityEdgeGt]


# ---- pure alias-rewrite logic (no DB — unit-testable) ----------------------

def _send_time_ms() -> int:
    """The registry's clock at forest assembly (SendTimeMs, sender-time
    standard). Always wall-clock: the registry is a notary and is never
    simulated, even when the fleet it describes runs simulated time."""
    return int(time.time() * 1000)


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
    def resolve_alias(self, alias: LeftRightDot) -> GNodeGt | None:
        """Resolve an alias — **current or past** — to the GNode that owns it now.

        A current alias returns its GNode; a past alias (the node has since renamed
        away) returns the **same GNode in its current form** (new alias). None if the
        alias was never assigned. Well-defined because an alias is permanently owned by
        one `GNodeId` (alias-uniqueness-through-time). The caller detects staleness by
        comparing the queried alias to the returned `alias` (a mismatch ⇒ stale)."""

    @abstractmethod
    def get_forest(self, roots: list[LeftRightDot]) -> GNodeForest:
        """The forest under `roots`: the subtree (root + active descendants) of each
        root alias, as `g.node.gt`s + any active non-tree edges among them
        (parent-child edges are derived from the aliases, never carried)."""

    @abstractmethod
    def apply_create(self, cmd: GNodeCreateCmd) -> GNodeForest: ...

    @abstractmethod
    def apply_reparent(self, cmd: GNodeReparentCmd) -> GNodeForest: ...


class PostgresAuthority(AuthoritySource):
    """Single-writer Postgres implementation of `AuthoritySource`.

    `universe` is REQUIRED (no default): a registry instance is scoped to exactly
    one universe, and every write is checked against it. Normally sourced from
    `Settings.universe`.
    """

    def __init__(
        self,
        session_factory=SessionLocal,
        *,
        universe: str,
        write_proof_sha256: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._universe = universe
        self._write_proof_sha256 = write_proof_sha256

    def _check_proof(self, proof: str | None, err: type[Exception]) -> None:
        """Stop-gap write authorization (retired by mTLS+FIS, OPS-420): when
        the deploy configures a proof hash, every write command must carry the
        matching opaque Proof. Checked before anything else — including the
        idempotent-replay short-circuit — so an unproven command never touches
        state or learns whether its hash was ever applied."""
        if self._write_proof_sha256 is None:
            return
        if (
            proof is None
            or hashlib.sha256(proof.encode()).hexdigest() != self._write_proof_sha256
        ):
            raise err("write command refused: missing or invalid Proof")

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

    def resolve_alias(self, alias: LeftRightDot) -> GNodeGt | None:
        with self._session_factory() as s:
            row = s.query(GNodeSql).filter_by(alias=alias).one_or_none()
            if row is not None:
                return row.to_gt()  # a current alias
            claim = s.get(AliasAssignmentSql, alias)  # was it ever assigned?
            if claim is None:
                return None
            owner = s.get(GNodeSql, claim.g_node_id)  # the permanent owner, current form
            return owner.to_gt() if owner is not None else None

    def get_forest(self, roots: list[LeftRightDot]) -> GNodeForest:
        with self._session_factory() as s:
            nodes: list[GNodeSql] = []
            seen: set[str] = set()
            for root in roots:
                # the subtree = the root alias and every descendant (materialized
                # path), ordered by alias: forest serialization must be
                # DETERMINISTIC (executor *Durability* — replay/rebroadcast
                # compare byte-identically), and row order is not.
                for row in (
                    s.query(GNodeSql)
                    .filter((GNodeSql.alias == root) | (GNodeSql.alias.like(root + ".%")))
                    .order_by(GNodeSql.alias)
                    .all()
                ):
                    if row.id not in seen:
                        seen.add(row.id)
                        nodes.append(row)
            edges: list[ConnectivityEdgeSql] = []
            if seen:
                edges = (
                    s.query(ConnectivityEdgeSql)
                    .filter(
                        ConnectivityEdgeSql.status == GNodeStatus.Active,
                        ConnectivityEdgeSql.from_g_node_id.in_(seen),
                        ConnectivityEdgeSql.to_g_node_id.in_(seen),
                    )
                    .order_by(ConnectivityEdgeSql.id)  # deterministic, like nodes
                    .all()
                )
            return GNodeForest(
                roots=list(roots),
                nodes=[row.to_gt() for row in nodes],
                edges=[edge.to_gt() for edge in edges],
                send_time_ms=_send_time_ms(),
            )

    # ---- the mutations -----------------------------------------------------

    def apply_create(self, cmd: GNodeCreateCmd) -> GNodeForest:
        """Create a single GNode — the registrar-facing write of the populate path.

        One node per command, parents first: unless the node is a forest root,
        its alias-parent must already exist and be Active. Claims the alias in
        the through-time ledger and appends the command to the log — one
        transaction. No edge rows: the parent-child structure is the alias
        prefix itself. Returns the (single-node) forest rooted at the new node.
        """
        self._check_proof(cmd.proof, CreateError)
        node = cmd.new_node
        payload = cmd.to_bytes()
        chash = command_hash(payload)
        with self._session_factory() as s:
            # Replay-safety, idempotent — same contract as apply_reparent.
            if s.get(CommandLogSql, chash) is not None:
                return self.get_forest([node.alias])
            if universe_of(node.alias) != self._universe:
                raise CreateError(
                    f"{node.alias!r} is in universe {universe_of(node.alias)!r}; "
                    f"this registry serves {self._universe!r}"
                )
            if s.get(GNodeSql, node.g_node_id) is not None:
                raise CreateError(f"GNodeId {node.g_node_id!r} already exists")
            claim = s.get(AliasAssignmentSql, node.alias)
            if claim is not None and claim.g_node_id != node.g_node_id:
                raise CreateError(
                    f"alias {node.alias!r} is permanently owned by a different "
                    f"GNodeId ({claim.g_node_id}) — aliases are never recycled"
                )
            if not is_forest_root(node.alias):
                parent = (
                    s.query(GNodeSql)
                    .filter_by(alias=parent_alias(node.alias))
                    .one_or_none()
                )
                if parent is None:
                    raise CreateError(
                        f"parent {parent_alias(node.alias)!r} of {node.alias!r} "
                        "not found — create parents first"
                    )
                # A Pending parent is legal: fleet bootstrap enters everything
                # Pending, parents-first, and activation comes later with the
                # TaValidator work. An ACTIVE child under a Pending parent is
                # still rejected — validate_registry's parent-closed-active
                # check catches it below.
                if parent.status not in (GNodeStatus.Pending, GNodeStatus.Active):
                    raise CreateError(
                        f"parent {parent_alias(node.alias)!r} is "
                        f"{parent.status.value}; a parent must be Pending or Active"
                    )
            s.add(GNodeSql.from_gt(node))
            claim_alias(s, node.alias, node.g_node_id)
            s.flush()
            violations = validate_registry(s, self._universe)
            if violations:
                raise CreateError(f"create would violate invariants: {violations}")
            s.add(CommandLogSql(
                command_hash=chash, type_name=cmd.type_name, payload=payload.decode()
            ))
            broadcast = GNodeForest(
                roots=[node.alias],
                nodes=[s.get(GNodeSql, node.g_node_id).to_gt()],
                edges=[],
                send_time_ms=_send_time_ms(),
            )
            s.commit()
        return broadcast

    def apply_reparent(self, cmd: GNodeReparentCmd) -> GNodeForest:
        """Introduce node N and re-parent the named children beneath it.

        The whole operation — insert N, recursively rewrite each moved child's
        subtree aliases, claim every new alias, and validate the result —
        commits in ONE transaction. Edge rows are untouched: the parent-child
        structure is the alias prefix itself. Returns the affected **forest**
        (rooted at N): its updated GNodes (new aliases) + any active non-tree
        edges among them.
        """
        self._check_proof(cmd.proof, ReparentError)
        n = cmd.new_node
        payload = cmd.to_bytes()
        chash = command_hash(payload)
        with self._session_factory() as s:
            # Replay-safety, idempotent: a command already in the log was already
            # applied — its effects ARE the current state. An at-least-once
            # retrier gets the affected subtree back (success), not an error it
            # cannot distinguish from a rejection.
            if s.get(CommandLogSql, chash) is not None:
                return self.get_forest([n.alias])
            if universe_of(n.alias) != self._universe:
                raise ReparentError(
                    f"{n.alias!r} is in universe {universe_of(n.alias)!r}; "
                    f"this registry serves {self._universe!r}"
                )
            if is_forest_root(n.alias):
                raise ReparentError(f"new node {n.alias!r} is a forest root; nothing to re-parent under")
            e_alias = parent_alias(n.alias)
            e = s.query(GNodeSql).filter_by(alias=e_alias).one_or_none()
            if e is None:
                raise ReparentError(f"parent {e_alias!r} of new node {n.alias!r} not found")

            # Alias-collision PRE-CHECK: the rewrite generates new aliases; if any
            # is permanently owned by a DIFFERENT GNodeId (uniqueness-through-time),
            # fail up front with an explicit error naming the collisions — not a
            # raw ledger abort mid-rewrite (which stays as defense-in-depth).
            intended: dict[str, str] = {n.alias: n.g_node_id}
            for child_id in cmd.moved_child_g_node_ids:
                child = s.get(GNodeSql, child_id)
                if child is None:
                    raise ReparentError(f"moved child {child_id!r} not found")
                new_prefix = moved_child_new_prefix(n.alias, child.alias)
                for row in (
                    s.query(GNodeSql)
                    .filter((GNodeSql.alias == child.alias)
                            | (GNodeSql.alias.like(child.alias + ".%")))
                    .all()
                ):
                    intended[rewrite_alias(row.alias, child.alias, new_prefix)] = row.id
            collisions = [
                f"{claim.alias!r} (owned by {claim.g_node_id})"
                for claim in s.query(AliasAssignmentSql)
                .filter(AliasAssignmentSql.alias.in_(intended.keys()))
                .all()
                if claim.g_node_id != intended[claim.alias]
            ]
            if collisions:
                raise ReparentError(
                    "alias collision — target alias(es) permanently owned by a "
                    f"different GNodeId: {', '.join(collisions)}"
                )

            s.add(GNodeSql.from_gt(n))
            claim_alias(s, n.alias, n.g_node_id)
            s.flush()

            updated: dict[str, GNodeSql] = {n.g_node_id: s.get(GNodeSql, n.g_node_id)}
            for child_id in cmd.moved_child_g_node_ids:
                child = s.get(GNodeSql, child_id)
                if child is None:
                    raise ReparentError(f"moved child {child_id!r} not found")
                old_prefix = child.alias
                new_prefix = moved_child_new_prefix(n.alias, old_prefix)
                self._rewrite_prefix(s, old_prefix, new_prefix, updated)

            violations = validate_registry(s, self._universe)
            if violations:
                raise ReparentError(f"re-parent would violate invariants: {violations}")

            # Any active non-tree edges among the affected nodes ride along; a
            # radial fleet has none, so this is usually empty. (A re-parent never
            # creates or retires edges — the tree is the alias structure.)
            affected_ids = set(updated.keys())
            nontree_edges = (
                s.query(ConnectivityEdgeSql)
                .filter(
                    ConnectivityEdgeSql.status == GNodeStatus.Active,
                    ConnectivityEdgeSql.from_g_node_id.in_(affected_ids),
                    ConnectivityEdgeSql.to_g_node_id.in_(affected_ids),
                )
                .all()
            )
            broadcast = GNodeForest(
                roots=[n.alias],
                nodes=[row.to_gt() for row in updated.values()],
                edges=[edge.to_gt() for edge in nontree_edges],
                send_time_ms=_send_time_ms(),
            )
            # Append the applied command to the log (the primitive; state is a
            # projection). Same transaction as the state change.
            s.add(CommandLogSql(command_hash=chash, type_name=cmd.type_name, payload=payload.decode()))
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
