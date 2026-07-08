"""Whole-registry structural invariants Sema can't express per-row.

These are the invariants from `executor/primary.md` "Intended invariants" that
span *rows* — universe scoping, parent-closure, and the non-tree edge rules.
`validate_registry` scans the committed registry and returns every violation
(the audit pass); the write handlers run it at write time. Topology is derived
from the dotted alias: a node's parent is its alias with the last word dropped
(`parent_alias`), so the parent relation is self-evident from the alias and
there is no separate parent pointer to keep consistent. The alias hierarchy is
a **spanning tree** of the grid graph; `connectivity_edges` holds only the
copper the tree cannot express (ties, loops, meshed feeds) — parent-child
edges are never stored.

The role/class **hierarchy** parent rule (what `BaseGNodeClass` may parent what)
is the new-class form of legacy `g-node-factory` Creation Axiom 5 (ROLE), with
the legacy→new mapping `ConductorTopologyNode → ConnectivityNode`,
`AtomicTNode`/`AtomicMeteringNode → LeafTransactiveNode`, `Scada`/`Other →
Logical` (confirmed by the `base.g.node.class` value-descriptions). Because the
physical classes only ever parent physical classes (a TerminalAsset sits behind
an atomic-metered LeafTransactiveNode, which sits under a ConnectivityNode/
MarketMaker, up to a copper forest root), enforcing the hierarchy also gives "the
active physical subtree is parent-closed" as a consequence.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from gnr.sema.enums import BaseGNodeClass, GNodeStatus
from gnr.sema.property_format import LeftRightDot, UUID4Str
from gnr.db.models import ConnectivityEdgeSql, GNodeSql


# A **CopperNode** is the copper-topology backbone class — a ConnectivityNode or a
# MarketMaker (a MarketMaker is a ConnectivityNode that also runs a local market).
# The backbone is parent-closed: a CopperNode's parent is another CopperNode, unless
# it is a forest root (its alias-parent is the bare universe token, not a GNode).
COPPER_CLASSES = frozenset({BaseGNodeClass.ConnectivityNode, BaseGNodeClass.MarketMaker})


@dataclass(frozen=True)
class Violation:
    invariant: str
    g_node_id: UUID4Str
    alias: LeftRightDot
    detail: str


def universe_of(alias: LeftRightDot) -> str:
    """The universe an alias lives in: its first dotted segment (executor *Universes*)."""
    return alias.split(".", 1)[0]


def parent_alias(alias: LeftRightDot) -> LeftRightDot:
    """The alias-parent: `alias` with its last dotted word dropped.

    Every GNodeAlias has ≥2 words, so this is always defined — a forest root's
    parent is the bare **universe token** (a namespace, not a GNode).
    """
    return alias.rsplit(".", 1)[0]


def is_forest_root(alias: LeftRightDot) -> bool:
    """True if the alias-parent is the bare universe token — a two-word alias like
    `d1.isone`. The universe segment is a namespace, not a GNode, so a forest root
    has no GNode parent (see executor *Universes*)."""
    return alias.count(".") == 1


def check_parent_closed_active(nodes_by_alias: dict[str, GNodeSql]) -> list[Violation]:
    """Active non-forest-root nodes have an existing, Active alias-parent.

    The active GNode forest is parent-closed: no active node dangles under a
    missing, suspended, or deactivated parent. Forest roots (alias-parent is the
    bare universe token) are the tops and are skipped.
    """
    violations: list[Violation] = []
    for node in nodes_by_alias.values():
        if node.status != GNodeStatus.Active or is_forest_root(node.alias):
            continue
        p_alias = parent_alias(node.alias)
        parent = nodes_by_alias.get(p_alias)
        if parent is None:
            violations.append(Violation(
                "parent_closed_active", node.id, node.alias,
                f"active non-root node has no parent at alias {p_alias!r}",
            ))
        elif parent.status != GNodeStatus.Active:
            violations.append(Violation(
                "parent_closed_active", node.id, node.alias,
                f"parent {p_alias!r} is {parent.status.value}, not Active",
            ))
    return violations


def check_universe_scope(
    nodes_by_alias: dict[str, GNodeSql], universe: str
) -> list[Violation]:
    """Every alias in the registry carries the instance's universe as segment 0.

    A registry instance is scoped to exactly one universe (executor *Universes*);
    a row from another universe is a deployment error, never valid data.
    """
    return [
        Violation(
            "universe_scope", node.id, node.alias,
            f"alias is in universe {universe_of(node.alias)!r}; "
            f"this registry serves {universe!r}",
        )
        for node in nodes_by_alias.values()
        if universe_of(node.alias) != universe
    ]


def check_edges_non_tree(
    nodes_by_alias: dict[str, GNodeSql], active_edges: list[ConnectivityEdgeSql]
) -> list[Violation]:
    """Edges are non-tree copper only: real endpoints, and never a tree mirror.

    The alias hierarchy is the spanning tree; `connectivity_edges` exists for the
    copper the tree cannot express (a tie between feeders, a loop, a meshed
    section). So for every active edge:
      - both endpoints exist and are Active;
      - the edge does not duplicate a parent-child pair in either direction
        (a stored tree edge is always a modeling error — the tree is derived
        from aliases, never stored).
    This is how a loop enters the registry: the loop's closing span is an edge
    row between two nodes neither of which is the other's alias-parent.
    """
    nodes_by_id = {n.id: n for n in nodes_by_alias.values()}
    violations: list[Violation] = []
    for edge in active_edges:
        frm = nodes_by_id.get(edge.from_g_node_id)
        to = nodes_by_id.get(edge.to_g_node_id)
        if frm is None or to is None:
            missing = edge.from_g_node_id if frm is None else edge.to_g_node_id
            violations.append(Violation(
                "edge_non_tree", edge.id, "",
                f"active edge endpoint {missing!r} does not exist",
            ))
            continue
        for node in (frm, to):
            if node.status != GNodeStatus.Active:
                violations.append(Violation(
                    "edge_non_tree", edge.id, node.alias,
                    f"active edge endpoint {node.alias!r} is "
                    f"{node.status.value}, not Active",
                ))
        if (
            parent_alias(to.alias) == frm.alias
            or parent_alias(frm.alias) == to.alias
        ):
            violations.append(Violation(
                "edge_non_tree", edge.id, to.alias,
                f"edge {frm.alias!r} ↔ {to.alias!r} mirrors a parent-child tree "
                "edge; the tree is the alias structure and is never stored",
            ))
    return violations


def check_class_hierarchy(nodes_by_alias: dict[str, GNodeSql]) -> list[Violation]:
    """Each non-root node's parent class is legal for its own class.

    The new-class form of legacy Creation Axiom 5 (ROLE):
      - a **forest root** (alias-parent is the bare universe token) → only a
        CopperNode or a non-Scada Logical node may sit at a forest top;
      - ConnectivityNode / MarketMaker → parent is a ConnectivityNode / MarketMaker
        (or it is a forest root, handled above);
      - LeafTransactiveNode → parent is a ConnectivityNode / MarketMaker;
      - TerminalAsset → parent is a LeafTransactiveNode (it sits behind an
        atomic-metered point);
      - Scada (`g_node_class == "Scada"`, Logical base_class) → parent is a
        LeafTransactiveNode (it represents that metered unit's controller);
      - other Logical → unconstrained (a non-physical node carries no topology rule).

    (The alias suffixes `.ta`/`.scada` are enforced per-row by `g.node.gt` Sema
    axiom 5, not here.)

    Structural (class-only) — independent of status; existence of the parent is
    `check_parent_closed_active`'s job, so a missing parent is skipped here.
    """
    violations: list[Violation] = []
    for node in nodes_by_alias.values():
        if is_forest_root(node.alias):
            # No GNode parent — only a CopperNode or a non-Scada Logical node may
            # sit at a forest top (LTN/TA/Scada each require a specific parent).
            ok = node.base_class in COPPER_CLASSES or (
                node.base_class == BaseGNodeClass.Logical and node.g_node_class != "Scada"
            )
            if not ok:
                violations.append(Violation(
                    "class_hierarchy", node.id, node.alias,
                    f"a {node.g_node_class} cannot be a forest root; it requires a parent",
                ))
            continue
        parent = nodes_by_alias.get(parent_alias(node.alias))
        if parent is None:
            continue
        bc, pbc = node.base_class, parent.base_class
        kind = bc.value
        if bc in COPPER_CLASSES:
            ok = pbc in COPPER_CLASSES
            allowed = "a CopperNode (ConnectivityNode/MarketMaker)"
        elif bc == BaseGNodeClass.LeafTransactiveNode:
            ok = pbc in COPPER_CLASSES
            allowed = "a CopperNode (ConnectivityNode/MarketMaker)"
        elif bc == BaseGNodeClass.TerminalAsset:
            ok = pbc == BaseGNodeClass.LeafTransactiveNode
            allowed = "a LeafTransactiveNode"
        elif node.g_node_class == "Scada":  # Logical base_class, but anchored to its home LTN
            kind = "Scada"
            ok = pbc == BaseGNodeClass.LeafTransactiveNode
            allowed = "a LeafTransactiveNode"
        else:  # other Logical — unconstrained
            continue
        if not ok:
            violations.append(Violation(
                "class_hierarchy", node.id, node.alias,
                f"a {kind} must have a parent that is {allowed}; "
                f"parent {parent.alias!r} is a {pbc.value}",
            ))
    return violations


def validate_registry(session: Session, universe: str) -> list[Violation]:
    """Run every whole-registry invariant; return all violations (empty = clean).

    `universe` is the universe this registry instance serves (required — the
    caller declares it, normally from `Settings.universe`).
    """
    nodes_by_alias = {n.alias: n for n in session.query(GNodeSql).all()}
    active_edges = (
        session.query(ConnectivityEdgeSql)
        .filter(ConnectivityEdgeSql.status == GNodeStatus.Active)
        .all()
    )
    return [
        *check_universe_scope(nodes_by_alias, universe),
        *check_parent_closed_active(nodes_by_alias),
        *check_edges_non_tree(nodes_by_alias, active_edges),
        *check_class_hierarchy(nodes_by_alias),
    ]
