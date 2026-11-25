"""The committed `dev-universe/` folder is the seed, byte for byte.

Other repos copy d1 GNode identity from that folder at a pinned registry
commit, so a seed change cannot merge without its export: `gnr export-dev
dev-universe` regenerates it.
"""

from __future__ import annotations

import filecmp
from pathlib import Path

from gnr.dev_universe import (
    KEENE,
    NEWHAVEN,
    build_dev_universe,
    export_dev_universe,
    export_filename,
)
from gnr.sema.types import GNodeGt

ROOT = Path(__file__).resolve().parents[1]
COMMITTED = ROOT / "dev-universe"


def test_committed_export_matches_the_seed(tmp_path: Path):
    fresh = export_dev_universe(tmp_path)
    assert sorted(p.name for p in fresh) == sorted(
        p.name for p in COMMITTED.glob("*.json")
    ), "run `uv run gnr export-dev dev-universe` and commit the result"
    _, mismatch, errors = filecmp.cmpfiles(
        tmp_path, COMMITTED, [p.name for p in fresh], shallow=False
    )
    assert mismatch == [] and errors == [], (
        "run `uv run gnr export-dev dev-universe` and commit the result"
    )


def test_every_gnode_has_one_file_that_decodes_to_it():
    for g in build_dev_universe():
        path = COMMITTED / export_filename(g)
        assert GNodeGt.from_bytes(path.read_bytes()) == g


def test_export_removes_a_stale_file(tmp_path: Path):
    stale = tmp_path / "d1.gone-g.node.gt-006.json"
    stale.write_text("{}")
    export_dev_universe(tmp_path)
    assert not stale.exists()


def test_seed_has_the_simulated_fleet():
    by_alias = {g.alias: g for g in build_dev_universe()}
    for home in (f"{KEENE}.beech1", f"{KEENE}.beech2", f"{NEWHAVEN}.orange1"):
        assert by_alias[f"{home}.ta"].g_node_class == "TerminalAsset"
        assert by_alias[f"{home}.scada"].g_node_class == "Scada"
    assert by_alias["d1.weather"].g_node_class == "WeatherForecastService"
    assert by_alias["d1.price"].g_node_class == "PriceForecastService"
    assert "d1.isone.me.weather" not in by_alias
