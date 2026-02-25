from typing import Literal
from typing_extensions import Self

from pydantic import model_validator

from gnr.sema.base import SemaType
from gnr.sema.enums import BaseGNodeClass, GNodeStatus
from gnr.sema.property_format import (
    LeftRightDot,
    UUID4Str,
)


class GNodeGt(SemaType):
    """Sema: https://schemas.electricity.works/types/g.node.gt/004"""

    g_node_id: UUID4Str
    alias: LeftRightDot
    base_class: BaseGNodeClass
    g_node_class: str
    status: GNodeStatus
    prev_alias: LeftRightDot | None = None
    position_point_id: UUID4Str | None = None
    display_name: str | None = None
    type_name: Literal["g.node.gt"] = "g.node.gt"
    version: Literal["004"] = "004"

    @model_validator(mode="after")
    def check_axiom_1(self) -> Self:
        """
        Axiom 1: PhysicalClassAlignment.
        For physical GNodes (BaseClass != Logical),
        GNodeClass SHALL equal the string value of BaseClass.
        """
        if self.base_class != BaseGNodeClass.Logical:
            if self.g_node_class != self.base_class.value:
                raise ValueError(
                    "Axiom 1 violated: Physical GNodes must align "
                    f"GNodeClass with BaseClass. "
                    f"Expected '{self.base_class.value}', "
                    f"got '{self.g_node_class}'."
                )
        return self

    @model_validator(mode="after")
    def check_axiom_2(self) -> Self:
        """
        Axiom 2: PhysicalGNodeLocations.
        If BaseClass != Logical, PositionPointId SHALL NOT be null.
        """
        if self.base_class != BaseGNodeClass.Logical:
            if self.position_point_id is None:
                raise ValueError(
                    "Axiom 2 violated: Physical GNodes must declare "
                    "PositionPointId."
                )
        return self

    @model_validator(mode="after")
    def check_axiom_3(self) -> Self:
        """
        Axiom 3: AliasTransitionConsistency.
        If PrevAlias is not null, it SHALL differ from Alias.
        If PrevAlias is null, no alias transition is represented.
        """
        if self.prev_alias is not None:
            if self.prev_alias == self.alias:
                raise ValueError(
                    "Axiom 3 violated: PrevAlias must differ from Alias "
                    "when present."
                )
        return self