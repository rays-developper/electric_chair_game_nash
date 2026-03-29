"""Precomputed state table utilities for O(1)-style equilibrium lookup.

This module provides:
- compact state key packing,
- full-game memoized solver from a root state,
- persistence to SQLite,
- fast lookup helpers for UI/API.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Tuple

import numpy as np

from .game_state import MAX_ROUNDS, MAX_SHOCKS, WIN_POINTS, GameState
from .nash_solver import _solve_attacker_lp, _solve_defender_lp


# 28-bit packed key layout
# [ atk_pts(6) | def_pts(6) | atk_shocks(2) | def_shocks(2) | chair_mask(12) ]

MAX_NON_TERMINAL_POINTS = WIN_POINTS - 1  # 39
THEORETICAL_STATE_SPACE = 40 * 40 * 3 * 3 * (2 ** 12)


@dataclass(frozen=True)
class StateRecord:
    state_key: int
    round_num: int
    attacker_points: int
    defender_points: int
    attacker_shocks: int
    defender_shocks: int
    chair_mask: int
    state_value: float
    attacker_strategy: List[Tuple[int, float]]
    defender_strategy: List[Tuple[int, float]]
    is_terminal: bool


def chairs_to_mask(chairs: Iterable[int]) -> int:
    mask = 0
    for chair in chairs:
        if not 1 <= chair <= 12:
            raise ValueError(f"chair must be in [1,12], got {chair}")
        mask |= 1 << (chair - 1)
    return mask


def mask_to_chairs(mask: int) -> Tuple[int, ...]:
    chairs = []
    for idx in range(12):
        if mask & (1 << idx):
            chairs.append(idx + 1)
    return tuple(chairs)


def derive_round_num(attacker_shocks: int, defender_shocks: int, chair_mask: int) -> int:
    """Derive current round from shocks + removed chairs.

    elapsed_rounds = total_shocks + removed_chair_count
    current_round = elapsed_rounds + 1
    """
    remaining = chair_mask.bit_count()
    removed = 12 - remaining
    elapsed = attacker_shocks + defender_shocks + removed
    return elapsed + 1


def pack_state_key(
    attacker_points: int,
    defender_points: int,
    attacker_shocks: int,
    defender_shocks: int,
    chair_mask: int,
) -> int:
    if not 0 <= attacker_points <= MAX_NON_TERMINAL_POINTS:
        raise ValueError(f"attacker_points must be 0..{MAX_NON_TERMINAL_POINTS}, got {attacker_points}")
    if not 0 <= defender_points <= MAX_NON_TERMINAL_POINTS:
        raise ValueError(f"defender_points must be 0..{MAX_NON_TERMINAL_POINTS}, got {defender_points}")
    if not 0 <= attacker_shocks <= 3:
        raise ValueError(f"attacker_shocks must fit 2 bits (0..3), got {attacker_shocks}")
    if not 0 <= defender_shocks <= 3:
        raise ValueError(f"defender_shocks must fit 2 bits (0..3), got {defender_shocks}")
    if not 0 <= chair_mask <= 0xFFF:
        raise ValueError(f"chair_mask must fit 12 bits (0..4095), got {chair_mask}")

    key = attacker_points
    key = (key << 6) | defender_points
    key = (key << 2) | attacker_shocks
    key = (key << 2) | defender_shocks
    key = (key << 12) | chair_mask
    return key


def unpack_state_key(state_key: int) -> Tuple[int, int, int, int, int]:
    chair_mask = state_key & 0xFFF
    state_key >>= 12
    defender_shocks = state_key & 0x3
    state_key >>= 2
    attacker_shocks = state_key & 0x3
    state_key >>= 2
    defender_points = state_key & 0x3F
    state_key >>= 6
    attacker_points = state_key & 0x3F
    return attacker_points, defender_points, attacker_shocks, defender_shocks, chair_mask


def _terminal_value(
    attacker_points: int,
    defender_points: int,
    attacker_shocks: int,
    defender_shocks: int,
    chairs: Tuple[int, ...],
) -> float | None:
    if attacker_shocks >= MAX_SHOCKS:
        return -1.0
    if defender_shocks >= MAX_SHOCKS:
        return 1.0

    if attacker_points >= WIN_POINTS:
        return 1.0
    if defender_points >= WIN_POINTS:
        return -1.0

    remaining_total = sum(chairs)
    diff = attacker_points - defender_points
    if abs(diff) > remaining_total:
        return 1.0 if diff > 0 else -1.0

    elapsed_rounds = (12 - len(chairs)) + attacker_shocks + defender_shocks
    if elapsed_rounds >= MAX_ROUNDS or len(chairs) <= 1:
        if attacker_points > defender_points:
            return 1.0
        if defender_points > attacker_points:
            return -1.0
        return 0.0

    return None


def _next_state_relative(
    attacker_points: int,
    defender_points: int,
    attacker_shocks: int,
    defender_shocks: int,
    chairs: Tuple[int, ...],
    attacker_chair: int,
    defender_chair: int,
) -> Tuple[int, int, int, int, Tuple[int, ...]]:

    if attacker_chair == defender_chair:
        next_attacker_points = defender_points
        next_defender_points = 0
        next_attacker_shocks = defender_shocks
        next_defender_shocks = attacker_shocks + 1
        return (
            next_attacker_points,
            next_defender_points,
            next_attacker_shocks,
            next_defender_shocks,
            chairs,
        )

    updated_attacker_points = attacker_points + attacker_chair
    chairs_next = tuple(c for c in chairs if c != attacker_chair)
    return (
        defender_points,
        updated_attacker_points,
        defender_shocks,
        attacker_shocks,
        chairs_next,
    )


def solve_state_table_from_root(
    root: GameState,
    progress_callback: Callable[[int], None] | None = None,
    progress_interval: int = 5000,
    initial_cache: Dict[int, StateRecord] | None = None,
    on_new_record: Callable[[StateRecord], None] | None = None,
) -> Dict[int, StateRecord]:
    """Solve all states reachable from ``root`` by memoized recursion.

    Value convention: state_value is from *current attacker* perspective.
    """
    cache: Dict[int, StateRecord] = dict(initial_cache) if initial_cache is not None else {}
    value_memo: Dict[Tuple[int, int, int, int, Tuple[int, ...]], float] = {}

    for rec in cache.values():
        chairs = mask_to_chairs(rec.chair_mask)
        memo_key = (
            rec.attacker_points,
            rec.defender_points,
            rec.attacker_shocks,
            rec.defender_shocks,
            chairs,
        )
        value_memo[memo_key] = rec.state_value

    def _notify_progress() -> None:
        if progress_callback is not None and len(cache) % max(progress_interval, 1) == 0:
            progress_callback(len(cache))

    def solve(
        attacker_points: int,
        defender_points: int,
        attacker_shocks: int,
        defender_shocks: int,
        chairs: Tuple[int, ...],
    ) -> float:
        memo_key = (attacker_points, defender_points, attacker_shocks, defender_shocks, chairs)
        if memo_key in value_memo:
            return value_memo[memo_key]

        terminal = _terminal_value(
            attacker_points,
            defender_points,
            attacker_shocks,
            defender_shocks,
            chairs,
        )
        if terminal is not None:
            value_memo[memo_key] = float(terminal)
            return float(terminal)

        chair_mask = chairs_to_mask(chairs)
        key = pack_state_key(
            attacker_points,
            defender_points,
            attacker_shocks,
            defender_shocks,
            chair_mask,
        )
        if key in cache:
            value_memo[memo_key] = cache[key].state_value
            return cache[key].state_value

        round_num = derive_round_num(attacker_shocks, defender_shocks, chair_mask)

        n = len(chairs)
        matrix = np.empty((n, n), dtype=float)

        for i, attacker_chair in enumerate(chairs):
            for j, defender_chair in enumerate(chairs):
                next_state = _next_state_relative(
                    attacker_points,
                    defender_points,
                    attacker_shocks,
                    defender_shocks,
                    chairs,
                    attacker_chair,
                    defender_chair,
                )
                # next state's value is from next attacker (= current defender),
                # so flip sign to current attacker's perspective.
                matrix[i, j] = -solve(*next_state)

        attacker_probs, state_value = _solve_attacker_lp(matrix)
        defender_probs, _ = _solve_defender_lp(matrix)

        cache[key] = StateRecord(
            state_key=key,
            round_num=round_num,
            attacker_points=attacker_points,
            defender_points=defender_points,
            attacker_shocks=attacker_shocks,
            defender_shocks=defender_shocks,
            chair_mask=chair_mask,
            state_value=float(state_value),
            attacker_strategy=[(chairs[i], float(attacker_probs[i])) for i in range(n)],
            defender_strategy=[(chairs[i], float(defender_probs[i])) for i in range(n)],
            is_terminal=False,
        )
        value_memo[memo_key] = float(state_value)
        if on_new_record is not None:
            on_new_record(cache[key])
        _notify_progress()
        return float(state_value)

    solve(
        root.attacker_points,
        root.defender_points,
        root.attacker_shocks,
        root.defender_shocks,
        tuple(sorted(root.remaining_chairs)),
    )
    return cache


def create_lookup_schema(conn: sqlite3.Connection) -> None:
    existing_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(equilibrium_lookup)").fetchall()
    }
    if "round_num" in existing_columns:
        conn.execute("DROP TABLE IF EXISTS equilibrium_lookup")
        conn.execute("DROP INDEX IF EXISTS idx_equilibrium_lookup_components")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS equilibrium_lookup (
            state_key INTEGER PRIMARY KEY,
            attacker_points INTEGER NOT NULL,
            defender_points INTEGER NOT NULL,
            attacker_shocks INTEGER NOT NULL,
            defender_shocks INTEGER NOT NULL,
            chair_mask INTEGER NOT NULL,
            state_value REAL NOT NULL,
            attacker_strategy TEXT NOT NULL,
            defender_strategy TEXT NOT NULL,
            is_terminal INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_equilibrium_lookup_components
        ON equilibrium_lookup(
            attacker_points,
            defender_points,
            attacker_shocks,
            defender_shocks,
            chair_mask
        )
        """
    )
    conn.commit()


def save_state_table_to_sqlite(records: Dict[int, StateRecord], db_path: str | Path) -> int:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        create_lookup_schema(conn)

        rows = [
            (
                rec.state_key,
                rec.attacker_points,
                rec.defender_points,
                rec.attacker_shocks,
                rec.defender_shocks,
                rec.chair_mask,
                rec.state_value,
                json.dumps(rec.attacker_strategy, ensure_ascii=False),
                json.dumps(rec.defender_strategy, ensure_ascii=False),
                int(rec.is_terminal),
            )
            for rec in records.values()
        ]

        conn.executemany(
            """
            INSERT OR REPLACE INTO equilibrium_lookup(
                state_key,
                attacker_points,
                defender_points,
                attacker_shocks,
                defender_shocks,
                chair_mask,
                state_value,
                attacker_strategy,
                defender_strategy,
                is_terminal
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def load_all_records_to_memory(db_path: str | Path) -> Dict[int, dict]:
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM equilibrium_lookup").fetchall()
    finally:
        conn.close()

    cache: Dict[int, dict] = {}
    for row in rows:
        cache[int(row["state_key"])] = {
            "state_key": int(row["state_key"]),
            "attacker_points": int(row["attacker_points"]),
            "defender_points": int(row["defender_points"]),
            "attacker_shocks": int(row["attacker_shocks"]),
            "defender_shocks": int(row["defender_shocks"]),
            "chair_mask": int(row["chair_mask"]),
            "chairs": list(mask_to_chairs(int(row["chair_mask"]))),
            "round_num": derive_round_num(
                int(row["attacker_shocks"]),
                int(row["defender_shocks"]),
                int(row["chair_mask"]),
            ),
            "state_value": float(row["state_value"]),
            "attacker_strategy": json.loads(row["attacker_strategy"]),
            "defender_strategy": json.loads(row["defender_strategy"]),
            "is_terminal": bool(row["is_terminal"]),
        }
    return cache


def load_state_records_from_sqlite(db_path: str | Path) -> Dict[int, StateRecord]:
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT state_key, attacker_points, defender_points,
                   attacker_shocks, defender_shocks, chair_mask,
                   state_value, attacker_strategy, defender_strategy, is_terminal
            FROM equilibrium_lookup
            """
        ).fetchall()
    finally:
        conn.close()

    records: Dict[int, StateRecord] = {}
    for row in rows:
        chair_mask = int(row["chair_mask"])
        records[int(row["state_key"])] = StateRecord(
            state_key=int(row["state_key"]),
            round_num=derive_round_num(
                int(row["attacker_shocks"]),
                int(row["defender_shocks"]),
                chair_mask,
            ),
            attacker_points=int(row["attacker_points"]),
            defender_points=int(row["defender_points"]),
            attacker_shocks=int(row["attacker_shocks"]),
            defender_shocks=int(row["defender_shocks"]),
            chair_mask=chair_mask,
            state_value=float(row["state_value"]),
            attacker_strategy=[(int(c), float(p)) for c, p in json.loads(row["attacker_strategy"])],
            defender_strategy=[(int(c), float(p)) for c, p in json.loads(row["defender_strategy"])],
            is_terminal=bool(row["is_terminal"]),
        )
    return records


def lookup_record_sqlite(db_path: str | Path, state_key: int) -> dict | None:
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM equilibrium_lookup WHERE state_key = ?",
            (state_key,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    return {
        "state_key": int(row["state_key"]),
        "attacker_points": int(row["attacker_points"]),
        "defender_points": int(row["defender_points"]),
        "attacker_shocks": int(row["attacker_shocks"]),
        "defender_shocks": int(row["defender_shocks"]),
        "chair_mask": int(row["chair_mask"]),
        "chairs": list(mask_to_chairs(int(row["chair_mask"]))),
        "round_num": derive_round_num(
            int(row["attacker_shocks"]),
            int(row["defender_shocks"]),
            int(row["chair_mask"]),
        ),
        "state_value": float(row["state_value"]),
        "attacker_strategy": json.loads(row["attacker_strategy"]),
        "defender_strategy": json.loads(row["defender_strategy"]),
        "is_terminal": bool(row["is_terminal"]),
    }


def build_lookup_table_from_initial_state(db_path: str | Path) -> int:
    root = GameState(
        attacker_points=0,
        defender_points=0,
        round_num=1,
        remaining_chairs=list(range(1, 13)),
        attacker_shocks=0,
        defender_shocks=0,
    )
    records = solve_state_table_from_root(root)
    return save_state_table_to_sqlite(records, db_path)
