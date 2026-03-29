"""Tests for the Nash equilibrium solver."""

import pytest
import numpy as np

from electric_chair_game.game_state import GameState
from electric_chair_game.nash_solver import (
    build_payoff_matrix,
    compute_nash_equilibrium,
    _solve_attacker_lp,
    _solve_defender_lp,
)


# ──────────────────────────────────────────────
# Payoff matrix
# ──────────────────────────────────────────────

class TestBuildPayoffMatrix:
    def test_shape(self):
        A = build_payoff_matrix(10, [1, 2, 3])
        assert A.shape == (3, 3)

    def test_diagonal_equals_negative_attacker_points(self):
        chairs = [2, 5, 9]
        A = build_payoff_matrix(15, chairs)
        np.testing.assert_array_equal(np.diag(A), [-15, -15, -15])

    def test_off_diagonal_equals_chair_value(self):
        chairs = [3, 7]
        A = build_payoff_matrix(5, chairs)
        # A[0,1]: attacker picks chairs[0]=3, defender picks chairs[1]=7 → gain 3
        assert A[0, 1] == 3.0
        # A[1,0]: attacker picks chairs[1]=7, defender picks chairs[0]=3 → gain 7
        assert A[1, 0] == 7.0

    def test_zero_attacker_points_diagonal(self):
        A = build_payoff_matrix(0, [4, 8])
        # With 0 points, shock costs nothing
        np.testing.assert_array_equal(np.diag(A), [0.0, 0.0])

    def test_full_12_chair_game(self):
        chairs = list(range(1, 13))
        A = build_payoff_matrix(20, chairs)
        assert A.shape == (12, 12)
        assert all(A[i, i] == -20 for i in range(12))
        # Spot-check off-diagonal
        assert A[0, 5] == 1.0   # chair 1
        assert A[11, 0] == 12.0  # chair 12


# ──────────────────────────────────────────────
# LP solvers
# ──────────────────────────────────────────────

class TestAttackerLP:
    def test_probabilities_sum_to_one(self):
        A = build_payoff_matrix(10, [1, 2, 3, 4, 5])
        probs, _ = _solve_attacker_lp(A)
        assert abs(probs.sum() - 1.0) < 1e-6

    def test_probabilities_non_negative(self):
        A = build_payoff_matrix(10, [1, 2, 3, 4, 5])
        probs, _ = _solve_attacker_lp(A)
        assert all(p >= -1e-9 for p in probs)

    def test_returns_correct_length(self):
        chairs = list(range(1, 8))
        A = build_payoff_matrix(5, chairs)
        probs, _ = _solve_attacker_lp(A)
        assert len(probs) == 7

    def test_two_chair_analytic(self):
        """For 2 chairs v1,v2 with P=0: attacker optimal prob for chair-0 = v2/(v1+v2)."""
        v1, v2 = 3.0, 7.0
        A = build_payoff_matrix(0, [v1, v2])
        probs, _ = _solve_attacker_lp(A)
        expected_p0 = v2 / (v1 + v2)
        assert abs(probs[0] - expected_p0) < 1e-4


class TestDefenderLP:
    def test_probabilities_sum_to_one(self):
        A = build_payoff_matrix(10, [1, 2, 3, 4, 5])
        probs, _ = _solve_defender_lp(A)
        assert abs(probs.sum() - 1.0) < 1e-6

    def test_probabilities_non_negative(self):
        A = build_payoff_matrix(10, [1, 2, 3, 4, 5])
        probs, _ = _solve_defender_lp(A)
        assert all(p >= -1e-9 for p in probs)

    def test_two_chair_analytic(self):
        """For 2 chairs v1,v2 with P=0: defender optimal prob for chair-0 = v1/(v1+v2)."""
        v1, v2 = 3.0, 7.0
        A = build_payoff_matrix(0, [v1, v2])
        probs, _ = _solve_defender_lp(A)
        expected_q0 = v1 / (v1 + v2)
        assert abs(probs[0] - expected_q0) < 1e-4

    def test_game_values_agree(self):
        """Attacker LP value and defender LP value should match (minimax theorem)."""
        A = build_payoff_matrix(12, [2, 5, 8, 11])
        _, v_atk = _solve_attacker_lp(A)
        _, v_def = _solve_defender_lp(A)
        assert abs(v_atk - v_def) < 1e-4


# ──────────────────────────────────────────────
# compute_nash_equilibrium
# ──────────────────────────────────────────────

class TestComputeNashEquilibrium:
    def _make_gs(self, attacker_points=10, chairs=None):
        if chairs is None:
            chairs = list(range(1, 7))
        return GameState(attacker_points=attacker_points, remaining_chairs=chairs)

    def test_output_keys(self):
        result = compute_nash_equilibrium(self._make_gs())
        assert "attacker_strategy" in result
        assert "defender_strategy" in result
        assert "game_value" in result
        assert "payoff_matrix" in result

    def test_attacker_strategy_length(self):
        chairs = [1, 3, 5, 7]
        result = compute_nash_equilibrium(self._make_gs(chairs=chairs))
        assert len(result["attacker_strategy"]) == 4

    def test_defender_strategy_length(self):
        chairs = [1, 3, 5, 7]
        result = compute_nash_equilibrium(self._make_gs(chairs=chairs))
        assert len(result["defender_strategy"]) == 4

    def test_attacker_probabilities_sum_to_one(self):
        result = compute_nash_equilibrium(self._make_gs())
        total = sum(p for _, p in result["attacker_strategy"])
        assert abs(total - 1.0) < 1e-6

    def test_defender_probabilities_sum_to_one(self):
        result = compute_nash_equilibrium(self._make_gs())
        total = sum(p for _, p in result["defender_strategy"])
        assert abs(total - 1.0) < 1e-6

    def test_chairs_in_strategy_match_remaining(self):
        chairs = [2, 5, 9, 11]
        result = compute_nash_equilibrium(self._make_gs(chairs=chairs))
        atk_chairs = sorted(c for c, _ in result["attacker_strategy"])
        def_chairs = sorted(c for c, _ in result["defender_strategy"])
        assert atk_chairs == sorted(chairs)
        assert def_chairs == sorted(chairs)

    def test_zero_points_valid_strategy(self):
        """Game still resolves when attacker has 0 points (no penalty for shock)."""
        gs = GameState(attacker_points=0, remaining_chairs=[1, 2, 3, 4])
        result = compute_nash_equilibrium(gs)
        total = sum(p for _, p in result["attacker_strategy"])
        assert abs(total - 1.0) < 1e-6

    def test_single_chair_degenerate(self):
        """With one chair, probability must be 1.0 for that chair."""
        gs = GameState(attacker_points=5, remaining_chairs=[7])
        result = compute_nash_equilibrium(gs)
        assert result["attacker_strategy"] == [(7, 1.0)]
        assert result["defender_strategy"] == [(7, 1.0)]

    def test_high_points_affect_game_value(self):
        """Higher attacker points → larger downside → different game value."""
        chairs = [3, 6, 9]
        gs_low = GameState(attacker_points=0, remaining_chairs=chairs)
        gs_high = GameState(attacker_points=30, remaining_chairs=chairs)
        v_low = compute_nash_equilibrium(gs_low)["game_value"]
        v_high = compute_nash_equilibrium(gs_high)["game_value"]
        # With more at stake, the equilibrium value should be lower for high-points
        assert v_high < v_low

    def test_full_game_12_chairs(self):
        """Smoke test with all 12 chairs and mid-game points."""
        gs = GameState(attacker_points=15, remaining_chairs=list(range(1, 13)))
        result = compute_nash_equilibrium(gs)
        total_atk = sum(p for _, p in result["attacker_strategy"])
        total_def = sum(p for _, p in result["defender_strategy"])
        assert abs(total_atk - 1.0) < 1e-6
        assert abs(total_def - 1.0) < 1e-6
