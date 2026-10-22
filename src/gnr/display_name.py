"""The default display name of a GNode, from its alias and class.

One rule for every path that names a node without an operator typing a
name: the dev universe seed and the `gnr create` default. A physical
node at a house reads as the house (`...keene.beech.ta` is "Beech"); the
house's other nodes append their class ("Beech Scada", "Beech LTN");
anything else is its last alias segment, title-cased ("Keene", "Weather").
"""

from __future__ import annotations

from gnr.sema.property_format import LeftRightDot

HOUSE_SUFFIXES: dict[str, str | None] = {
    "TerminalAsset": None,
    "Scada": "Scada",
    "LeafTransactiveNode": "LTN",
}
"""GNodeClass → what follows the house name, None for the house name alone."""


def default_display_name(alias: LeftRightDot, g_node_class: str) -> str:
    segments = alias.split(".")
    if g_node_class == "TerminalAsset" or g_node_class == "Scada":
        house = segments[-2] if len(segments) > 1 else segments[-1]
    else:
        house = segments[-1]
    name = house.title()
    suffix = HOUSE_SUFFIXES.get(g_node_class)
    return f"{name} {suffix}" if suffix else name
