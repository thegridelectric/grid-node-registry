"""The recursive re-parent alias rewrite — pure logic, no DB.

The re-parent is a materialized-path prefix swap over a subtree; these test that
pure core (`gnr.db.authority`), independent of Postgres.
"""

from gnr.db.authority import (
    in_subtree,
    moved_child_new_prefix,
    rewrite_alias,
    subtree_rewrite_map,
)


def test_in_subtree_respects_segment_boundary():
    assert in_subtree("e.c", "e.c")  # the node itself
    assert in_subtree("e.c.x", "e.c")  # a descendant
    assert in_subtree("e.c.x.y", "e.c")  # a deeper descendant
    assert not in_subtree("e", "e.c")  # an ancestor
    assert not in_subtree("e.cd", "e.c")  # shares a string prefix, NOT a path prefix
    assert not in_subtree("e.d", "e.c")  # a sibling


def test_rewrite_alias_swaps_prefix():
    assert rewrite_alias("e.c", "e.c", "e.n.c") == "e.n.c"
    assert rewrite_alias("e.c.x.y", "e.c", "e.n.c") == "e.n.c.x.y"


def test_moved_child_new_prefix_keeps_last_word():
    assert moved_child_new_prefix("e.n", "e.c") == "e.n.c"
    assert moved_child_new_prefix("rauth.mm.sub", "rauth.mm.ctn") == "rauth.mm.sub.ctn"


def test_subtree_rewrite_map_moves_only_the_subtree():
    aliases = ["e", "e.c", "e.c.x", "e.c.x.y", "e.d"]
    old = "e.c"
    new = moved_child_new_prefix("e.n", "e.c")  # "e.n.c"
    m = subtree_rewrite_map(aliases, old, new)
    assert m == {
        "e.c": "e.n.c",
        "e.c.x": "e.n.c.x",
        "e.c.x.y": "e.n.c.x.y",
    }
    # the ancestor and the sibling are untouched
    assert "e" not in m and "e.d" not in m
