"""Backward-induction state-DP solver for the full Electric Chair Game.

This module solves the *multi-round* game (up to 8 rounds) by dynamic
programming over game states, rather than only solving a single round.

State definition (fixed-player perspective)
------------------------------------------
- p1_points, p2_points: cumulative points of each fixed player.
- p1_shocks, p2_shocks: number of shocks each player has received.
- round_num: current round index (1-based).
- remaining_chairs: tuple of remaining chair values.

At each state, the current attacker and defender choose simultaneously:
- attacker picks one remaining chair to sit in.
- defender picks one remaining chair to electrify.

Transition applies the official rule:
- safe (different chairs): attacker gains that chair's points; chair is removed.
- shocked (same chair): attacker points reset to 0; shocks +1; chair stays.

Then roles swap for the next round.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Dict, Tuple

import numpy as np

from .game_state import MAX_ROUNDS, MAX_SHOCKS, WIN_POINTS, GameState
from .nash_solver import _solve_attacker_lp, _solve_defender_lp


def _terminal_value(
    round_num: int,
    p1_points: int,
    p2_points: int,
    p1_shocks: int,
    p2_shocks: int,
    chairs: Tuple[int, ...],
) -> float | None:
    """Return terminal value from Player-1 perspective, or None if non-terminal.

    Values:
    - +1.0 : Player-1 win
    - -1.0 : Player-1 loss
    -  0.0 : tie
    """
    if p1_shocks >= MAX_SHOCKS:
        return -1.0
    if p2_shocks >= MAX_SHOCKS:
        return 1.0

    if p1_points >= WIN_POINTS:
        return 1.0
    if p2_points >= WIN_POINTS:
        return -1.0

    remaining_total = sum(chairs)
    diff = p1_points - p2_points
    if abs(diff) > remaining_total:
        return 1.0 if diff > 0 else -1.0

    if round_num > MAX_ROUNDS or len(chairs) <= 1:
        if p1_points > p2_points:
            return 1.0
        if p2_points > p1_points:
            return -1.0
        return 0.0

    return None


def _next_state(
    round_num: int,
    p1_points: int,
    p2_points: int,
    p1_shocks: int,
    p2_shocks: int,
    chairs: Tuple[int, ...],
    attacker_is_p1: bool,
    attacker_chair: int,
    defender_chair: int,
) -> Tuple[int, int, int, int, int, Tuple[int, ...], bool]:
    """Apply one-round transition and return the next state tuple."""
    next_round = round_num + 1

    p1_next = p1_points
    p2_next = p2_points
    s1_next = p1_shocks
    s2_next = p2_shocks
    chairs_next = chairs

    if attacker_is_p1:
        if attacker_chair == defender_chair:
            p1_next = 0
            s1_next += 1
        else:
            p1_next += attacker_chair
            chairs_next = tuple(c for c in chairs if c != attacker_chair)
    else:
        if attacker_chair == defender_chair:
            p2_next = 0
            s2_next += 1
        else:
            p2_next += attacker_chair
            chairs_next = tuple(c for c in chairs if c != attacker_chair)

    return next_round, p1_next, p2_next, s1_next, s2_next, chairs_next, (not attacker_is_p1)


@lru_cache(maxsize=None)
def _solve_state(
    round_num: int,
    p1_points: int,
    p2_points: int,
    p1_shocks: int,
    p2_shocks: int,
    chairs: Tuple[int, ...],
    attacker_is_p1: bool,
) -> Tuple[float, Tuple[float, ...], Tuple[float, ...]]:
    """Solve one state and return (value, attacker_probs, defender_probs).

    Value is always from Player-1 perspective.
    """
    terminal = _terminal_value(round_num, p1_points, p2_points, p1_shocks, p2_shocks, chairs)
    if terminal is not None:
        return terminal, tuple(), tuple()

    n = len(chairs)
    matrix = np.empty((n, n), dtype=float)

    for i, attacker_chair in enumerate(chairs):
        for j, defender_chair in enumerate(chairs):
            next_args = _next_state(
                round_num,
                p1_points,
                p2_points,
                p1_shocks,
                p2_shocks,
                chairs,
                attacker_is_p1,
                attacker_chair,
                defender_chair,
            )
            matrix[i, j] = _solve_state(*next_args)[0]

    if attacker_is_p1:
        attacker_probs, game_value = _solve_attacker_lp(matrix)
        defender_probs, _ = _solve_defender_lp(matrix)
        return float(game_value), tuple(float(x) for x in attacker_probs), tuple(float(x) for x in defender_probs)

    # If attacker is Player-2, they minimize Player-1 value.
    # Convert to standard max-min by solving on -matrix.
    attacker_probs, neg_value = _solve_attacker_lp(-matrix)
    defender_probs, _ = _solve_defender_lp(-matrix)
    return float(-neg_value), tuple(float(x) for x in attacker_probs), tuple(float(x) for x in defender_probs)


def compute_full_game_equilibrium(game_state: GameState) -> Dict:
    """Compute backward-induction mixed strategy for the current round state.

    The provided ``game_state`` is interpreted from current attacker/defender
    viewpoint exactly as used in the existing single-round solver:
    - ``attacker_points`` and ``attacker_shocks`` belong to Player-1 at this state.
    - ``defender_points`` and ``defender_shocks`` belong to Player-2 at this state.
    - ``attacker`` acts now; roles alternate each next round.

    Returns
    -------
    dict with keys:
        ``attacker_strategy``: list[(chair, prob)]
        ``defender_strategy``: list[(chair, prob)]
        ``state_value``: equilibrium value from current attacker perspective
                        (+1 win, 0 tie, -1 loss expectation)
    """
    chairs = tuple(sorted(game_state.remaining_chairs))
    value, attacker_probs, defender_probs = _solve_state(
        game_state.round_num,
        game_state.attacker_points,
        game_state.defender_points,
        game_state.attacker_shocks,
        game_state.defender_shocks,
        chairs,
        True,
    )

    attacker_strategy = [(chairs[i], attacker_probs[i]) for i in range(len(chairs))] if attacker_probs else []
    defender_strategy = [(chairs[i], defender_probs[i]) for i in range(len(chairs))] if defender_probs else []

    return {
        "attacker_strategy": attacker_strategy,
        "defender_strategy": defender_strategy,
        "state_value": float(value),
    }


def clear_full_game_cache() -> None:
    """Clear internal DP cache (useful for repeated benchmarking)."""
    _solve_state.cache_clear()
