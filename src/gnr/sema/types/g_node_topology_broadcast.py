from typing import Literal
from gnr.sema.base import SemaType
from gnr.sema.types.g_node_gt import GNodeGt


class GNodeTopologyBroadcast(SemaType):
    """Sema: https://schemas.electricity.works/types/g.node.topology.broadcast/000"""

    updated_nodes: list[GNodeGt]
    type_name: Literal["g.node.topology.broadcast"] = "g.node.topology.broadcast"
    version: Literal["000"] = "000"
