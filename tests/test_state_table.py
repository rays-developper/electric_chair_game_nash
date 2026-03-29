"""Tests for precomputed state table utilities."""

from pathlib import Path

from electric_chair_game.game_state import GameState
from electric_chair_game.state_table import (
    chairs_to_mask,
    lookup_record_sqlite,
    pack_state_key,
    save_state_table_to_sqlite,
    solve_state_table_from_root,
    unpack_state_key,
)


def test_pack_unpack_roundtrip():
    key = pack_state_key(17, 23, 1, 2, chairs_to_mask([1, 4, 9, 12]))
    restored = unpack_state_key(key)
    assert restored == (17, 23, 1, 2, chairs_to_mask([1, 4, 9, 12]))


def test_save_and_lookup_sqlite(tmp_path: Path):
    root = GameState(
        attacker_points=0,
        defender_points=0,
        round_num=1,
        remaining_chairs=[1, 2, 3, 4, 5],
        attacker_shocks=0,
        defender_shocks=0,
    )
    table = solve_state_table_from_root(root)
    db_path = tmp_path / "lookup.sqlite3"
    saved = save_state_table_to_sqlite(table, db_path)
    assert saved > 0

    key = pack_state_key(0, 0, 0, 0, chairs_to_mask([1, 2, 3, 4, 5]))
    record = lookup_record_sqlite(db_path, key)
    assert record is not None
    assert record["state_key"] == key
    assert "state_value" in record
    assert "attacker_strategy" in record
    assert "defender_strategy" in record
