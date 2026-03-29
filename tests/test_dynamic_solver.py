"""Tests for full-game backward DP solver."""

from electric_chair_game.dynamic_solver import clear_full_game_cache, compute_full_game_equilibrium
from electric_chair_game.game_state import GameState


class TestDynamicSolver:
    def setup_method(self):
        clear_full_game_cache()

    def test_terminal_state_returns_no_strategy(self):
        gs = GameState(
            attacker_points=40,
            defender_points=0,
            round_num=2,
            remaining_chairs=[1, 2, 3],
            attacker_shocks=0,
            defender_shocks=0,
        )
        result = compute_full_game_equilibrium(gs)
        assert result["state_value"] == 1.0
        assert result["attacker_strategy"] == []
        assert result["defender_strategy"] == []

    def test_single_chair_is_terminal(self):
        gs = GameState(
            attacker_points=10,
            defender_points=5,
            round_num=4,
            remaining_chairs=[12],
            attacker_shocks=0,
            defender_shocks=0,
        )
        result = compute_full_game_equilibrium(gs)
        assert result["state_value"] == 1.0
        assert result["attacker_strategy"] == []
        assert result["defender_strategy"] == []

    def test_non_terminal_probabilities_sum_to_one(self):
        gs = GameState(
            attacker_points=0,
            defender_points=0,
            round_num=8,
            remaining_chairs=[1, 2],
            attacker_shocks=0,
            defender_shocks=0,
        )
        result = compute_full_game_equilibrium(gs)

        atk_total = sum(p for _, p in result["attacker_strategy"])
        dfn_total = sum(p for _, p in result["defender_strategy"])
        assert abs(atk_total - 1.0) < 1e-6
        assert abs(dfn_total - 1.0) < 1e-6

    def test_state_value_within_bounds(self):
        gs = GameState(
            attacker_points=0,
            defender_points=0,
            round_num=7,
            remaining_chairs=[1, 2, 3],
            attacker_shocks=0,
            defender_shocks=0,
        )
        result = compute_full_game_equilibrium(gs)
        assert -1.0 <= result["state_value"] <= 1.0
