"""Lifecycle state machines — the legal `GNodeStatus` and `base_class` transitions.

The write handlers (step 5) call these before applying a status or class change;
an illegal transition raises and the whole mutation is rejected. Pure functions
over the enums — no DB access — so they are cheap to call on every write and
trivial to unit-test.

Grounded in legacy `g-node-factory`:
  - status SM = Update Axiom 3;
  - `base_class` SM = a CopperNode switching between its two forms, both
    directions — ConnectivityNode ⇄ MarketMaker (a constraint emerges → a market
    is needed; a constraint is relieved → it isn't). `g_node_class` moves in
    lockstep with `base_class` (per-row Sema axiom 1), so the GT codec keeps the
    two consistent; this SM governs only which `base_class` change is allowed.
"""

from __future__ import annotations

from gnr.sema.enums import BaseGNodeClass, GNodeStatus


class IllegalStatusTransition(Exception):
    """Raised when a `GNodeStatus` change is not a legal move."""


class IllegalBaseClassTransition(Exception):
    """Raised when a `base_class` change is not a sanctioned transition."""


# Update Axiom 3. A status may always stay itself (a no-op); these are the *moves*.
ALLOWED_STATUS_TRANSITIONS: dict[GNodeStatus, frozenset[GNodeStatus]] = {
    GNodeStatus.Pending: frozenset({GNodeStatus.Active}),
    GNodeStatus.Active: frozenset(
        {GNodeStatus.Suspended, GNodeStatus.PermanentlyDeactivated}
    ),
    GNodeStatus.Suspended: frozenset(
        {GNodeStatus.Active, GNodeStatus.PermanentlyDeactivated}
    ),
    GNodeStatus.PermanentlyDeactivated: frozenset(),  # terminal
}

# A CopperNode may change between its two forms, both directions:
#   ConnectivityNode -> MarketMaker  (a copper constraint emerges; the node must run a local market)
#   MarketMaker -> ConnectivityNode  (the constraint is relieved on the grid; no market maker needed)
# No other base_class change is sanctioned.
ALLOWED_BASE_CLASS_TRANSITIONS: dict[BaseGNodeClass, frozenset[BaseGNodeClass]] = {
    BaseGNodeClass.ConnectivityNode: frozenset({BaseGNodeClass.MarketMaker}),
    BaseGNodeClass.MarketMaker: frozenset({BaseGNodeClass.ConnectivityNode}),
}


def check_status_transition(old: GNodeStatus, new: GNodeStatus) -> None:
    """Assert `old -> new` is a legal `GNodeStatus` move (identity is a no-op)."""
    if new == old:
        return
    if new not in ALLOWED_STATUS_TRANSITIONS[old]:
        allowed = ", ".join(sorted(s.value for s in ALLOWED_STATUS_TRANSITIONS[old]))
        raise IllegalStatusTransition(
            f"GNodeStatus {old.value} cannot change to {new.value}; "
            f"allowed: {allowed or '(terminal — no change)'}."
        )


def check_base_class_transition(old: BaseGNodeClass, new: BaseGNodeClass) -> None:
    """Assert `old -> new` is a sanctioned `base_class` change (identity is a no-op)."""
    if new == old:
        return
    if new not in ALLOWED_BASE_CLASS_TRANSITIONS.get(old, frozenset()):
        allowed = ", ".join(
            sorted(
                c.value for c in ALLOWED_BASE_CLASS_TRANSITIONS.get(old, frozenset())
            )
        )
        raise IllegalBaseClassTransition(
            f"base_class {old.value} cannot change to {new.value}; "
            f"allowed: {allowed or '(none — fixed)'}."
        )
