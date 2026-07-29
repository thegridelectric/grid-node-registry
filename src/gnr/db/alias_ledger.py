"""Enforcement of the *alias-uniqueness-through-time* invariant.

An alias, once held by a `GNodeId`, is permanently owned by it and MUST NOT ever
bind to a different `GNodeId` — even after the node renames away from it. The
`alias_assignment` ledger (`alias` PRIMARY KEY) holds that permanent binding;
`claim_alias` is the write primitive every create/rename calls, inside the same
transaction as the GNode write.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from gnr.db.models import AliasAssignmentSql
from gnr.sema.property_format import LeftRightDot, UUID4Str


class AliasAlreadyOwned(Exception):
    """Raised when an alias is already owned by a different `GNodeId`.

    The caller's transaction MUST roll back — the binding is permanent and the
    requested owner is not the one that holds it.
    """

    def __init__(self, alias: LeftRightDot, current_owner: UUID4Str, requested_owner: UUID4Str) -> None:
        self.alias = alias
        self.current_owner = current_owner
        self.requested_owner = requested_owner
        super().__init__(
            f"Alias {alias!r} is permanently owned by GNodeId {current_owner!r}; "
            f"it cannot be assigned to {requested_owner!r}."
        )


def claim_alias(session: Session, alias: LeftRightDot, g_node_id: UUID4Str) -> None:
    """Record that `g_node_id` owns `alias`, or assert it already does.

    Three outcomes, race-free (the `alias` unique index serializes concurrent
    inserts, so there is no app-level check-then-insert window):
      - alias unowned        → claimed for `g_node_id`
      - already owned by it   → no-op (re-acquiring a former alias is allowed)
      - owned by a different id → raises `AliasAlreadyOwned` (caller rolls back)

    Call inside the same transaction as the GNode write so the row commits (or
    rolls back) atomically with the rest of the mutation.
    """
    stmt = (
        pg_insert(AliasAssignmentSql)
        .values(
            alias=alias,
            g_node_id=g_node_id,
            first_assigned_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=["alias"])
    )
    session.execute(stmt)

    owner = session.execute(
        select(AliasAssignmentSql.g_node_id).where(AliasAssignmentSql.alias == alias)
    ).scalar_one()

    if owner != g_node_id:
        raise AliasAlreadyOwned(alias, owner, g_node_id)
