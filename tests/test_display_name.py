"""One display-name rule for the seed and `gnr create`."""

from gnr.dev_universe import build_dev_universe
from gnr.display_name import default_display_name


def test_house_nodes_read_as_the_house():
    assert (
        default_display_name("d1.isone.me.versant.keene.beech.ta", "TerminalAsset")
        == "Beech"
    )
    assert (
        default_display_name("d1.isone.me.versant.keene.beech.scada", "Scada")
        == "Beech Scada"
    )
    assert (
        default_display_name("d1.isone.me.versant.keene.beech", "LeafTransactiveNode")
        == "Beech LTN"
    )


def test_other_nodes_read_as_their_last_segment():
    assert default_display_name("d1.isone", "MarketMaker") == "Isone"
    assert default_display_name("d1.isone.me.versant.keene", "MarketMaker") == "Keene"
    assert (
        default_display_name("d1.isone.me.weather", "WeatherForecastService")
        == "Weather"
    )


def test_seed_uses_the_rule():
    by_alias = {n.alias: n.display_name for n in build_dev_universe()}
    assert by_alias["d1.isone.me.versant.keene.beech.ta"] == "Beech"
    assert by_alias["d1.isone.me.versant.keene.willow.scada"] == "Willow Scada"
    assert by_alias["d1.isone.me.versant.keene.oak"] == "Oak LTN"
    assert all(name != alias for alias, name in by_alias.items())
