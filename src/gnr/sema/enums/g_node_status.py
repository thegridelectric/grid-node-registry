from typing import List
from gnr.sema.enums.gw_str_enum import GwStrEnum


class GNodeStatus(GwStrEnum):
    """Sema: https://schemas.electricity.works/enums/g.node.status/000"""

    Pending = "Pending"
    Active = "Active"
    Suspended = "Suspended"
    PermanentlyDeactivated = "PermanentlyDeactivated"

    @classmethod
    def default(cls) -> "GNodeStatus":
        return cls.Pending

    @classmethod
    def values(cls) -> List[str]:
        return [elt.value for elt in cls]

    @classmethod
    def enum_name(cls) -> str:
        return "g.node.status"

    @classmethod
    def enum_version(cls) -> str:
        return "000"