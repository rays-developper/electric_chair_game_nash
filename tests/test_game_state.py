"""Tests for GameState."""

import pytest
from electric_chair_game.game_state import (
    GameState,
    MAX_ROUNDS,
    MAX_TURNS,
    WIN_POINTS,
    MAX_SHOCKS,
)


class TestGameStateDefaults:
    def test_default_chairs(self):
        gs = GameState()
        assert gs.remaining_chairs == list(range(1, 13))

    def test_default_points(self):
        gs = GameState()
        assert gs.attacker_points == 0
        assert gs.defender_points == 0

    def test_default_round(self):
        gs = GameState()
        assert gs.round_num == 1

    def test_default_shocks(self):
        gs = GameState()
        assert gs.attacker_shocks == 0
        assert gs.defender_shocks == 0


class TestMaxRemainingPoints:
    def test_full_set(self):
        gs = GameState()
        assert gs.max_remaining_points() == sum(range(1, 13))  # 78

    def test_partial_set(self):
        gs = GameState(remaining_chairs=[3, 5, 7])
        assert gs.max_remaining_points() == 15

    def test_single_chair(self):
        gs = GameState(remaining_chairs=[12])
        assert gs.max_remaining_points() == 12

    def test_empty(self):
        gs = GameState(remaining_chairs=[])
        assert gs.max_remaining_points() == 0


class TestIsGameOver:
    def test_not_over_initial(self):
        gs = GameState()
        assert not gs.is_game_over()

    def test_over_max_rounds(self):
        gs = GameState(round_num=MAX_TURNS + 1, attacker_points=10,
                       defender_points=5, remaining_chairs=[1, 2, 3])
        assert gs.is_game_over()

    def test_over_attacker_win_points(self):
        gs = GameState(attacker_points=WIN_POINTS)
        assert gs.is_game_over()

    def test_over_defender_win_points(self):
        gs = GameState(defender_points=WIN_POINTS)
        assert gs.is_game_over()

    def test_over_attacker_max_shocks(self):
        gs = GameState(attacker_shocks=MAX_SHOCKS)
        assert gs.is_game_over()

    def test_over_defender_max_shocks(self):
        gs = GameState(defender_shocks=MAX_SHOCKS)
        assert gs.is_game_over()

    def test_over_one_chair_remains(self):
        gs = GameState(remaining_chairs=[5], attacker_points=10, defender_points=5)
        assert gs.is_game_over()


class TestWinner:
    def test_attacker_win_by_shocks(self):
        gs = GameState(defender_shocks=MAX_SHOCKS)
        assert gs.winner() == "attacker"

    def test_defender_win_by_shocks(self):
        gs = GameState(attacker_shocks=MAX_SHOCKS)
        assert gs.winner() == "defender"

    def test_attacker_win_by_points(self):
        gs = GameState(attacker_points=WIN_POINTS)
        assert gs.winner() == "attacker"

    def test_defender_win_by_points(self):
        gs = GameState(defender_points=WIN_POINTS)
        assert gs.winner() == "defender"

    def test_tie_after_max_rounds(self):
        gs = GameState(round_num=MAX_TURNS + 1, attacker_points=5, defender_points=5,
                       remaining_chairs=[1, 2])
        assert gs.winner() == "tie"

    def test_no_winner_mid_game(self):
        gs = GameState(round_num=3, attacker_points=10, defender_points=5)
        assert gs.winner() is None
