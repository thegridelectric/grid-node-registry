from typing import Literal, Self
from pydantic import model_validator
from gnr.sema.base import SemaType
from gnr.sema.types.g_node_gt import GNodeGt


class GNodeCreateCmd(SemaType):
    """Sema: https://schemas.electricity.works/types/g.node.create.cmd/001"""

    new_node: GNodeGt
    proof: str | None = None
    type_name: Literal["g.node.create.cmd"] = "g.node.create.cmd"
    version: Literal["001"] = "001"

    @model_validator(mode="after")
    def check_axiom_1(self) -> Self:
        """
        Axiom 1: LocationlessAtCreation
        NewNode.PositionPointId SHALL be null.
        """
        if self.new_node.position_point_id is not None:
            raise ValueError(
                "Axiom 1 failed: NewNode.PositionPointId must be null — a "
                "location identity is registered after creation, never "
                "carried in the create command."
            )
        return self
