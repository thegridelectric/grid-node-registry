from typing import Literal
from typing_extensions import Self

from pydantic import model_validator

from gnr.sema.base import SemaType
from gnr.sema.enums import GNodeStatus
from gnr.sema.property_format import UUID4Str, LeftRightDot


class ConnectivityEdgeGt(SemaType):
    """Sema: https://schemas.electricity.works/types/connectivity.edge.gt/000"""

    id: UUID4Str
    from_g_node_id: UUID4Str
    to_g_node_id: UUID4Str
    from_g_node_alias: LeftRightDot
    to_g_node_alias: LeftRightDot
    status: GNodeStatus
    type_name: Literal["connectivity.edge.gt"] = "connectivity.edge.gt"
    version: Literal["000"] = "000"


    @model_validator(mode="after")
    def check_axiom_1(self) -> Self:
        """
        Axiom 1: A ConnectivityEdge cannot connect a GNode to itself.
        """
        if self.from_g_node_id == self.to_g_node_id:
            raise ValueError(
                "Axiom 1 violated! A ConnectivityEdge cannot connect a GNode "
                f"to itself (got {self.from_g_node_id})."
            )
        return self