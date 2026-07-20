from typing import Literal
from gnr.sema.base import SemaType
from gnr.sema.property_format import UUID4Str
from gnr.sema.types.g_node_gt import GNodeGt


class GNodeReparentCmd(SemaType):
    """Sema: https://schemas.electricity.works/types/g.node.reparent.cmd/000"""

    new_node: GNodeGt
    moved_child_g_node_ids: list[UUID4Str]
    type_name: Literal["g.node.reparent.cmd"] = "g.node.reparent.cmd"
    version: Literal["000"] = "000"
