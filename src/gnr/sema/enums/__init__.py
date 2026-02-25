"""
Sema enum definitions for Grid Node Registry

Enums define versioned controlled vocabularies used at system boundaries.
They evolve additively (values may be added but not removed or reordered)
to preserve backward compatibility across distributed systems.

All enums correspond to published Sema schemas under:
https://schemas.electricity.works/enums/
"""

from gnr.sema.enums.base_g_node_class import BaseGNodeClass
from gnr.sema.enums.g_node_class import GNodeClass
from gnr.sema.enums.g_node_status import GNodeStatus


__all__ = [
    "BaseGNodeClass",
    "GNodeClass",
    "GNodeStatus",
]
