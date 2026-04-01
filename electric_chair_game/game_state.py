"""Game state model for the Electric Chair Game (電気椅子ゲーム).

Rules summary:
- 12 chairs numbered 1–12 are placed on stage.
- Each round: defender secretly electrifies one chair; attacker picks a chair to sit in.
- Attacker avoids shock → gains points equal to the chair number; that chair is removed.
- Attacker gets shocked → loses ALL accumulated points; chair stays.
- Roles alternate each round (up to 8 rounds total, or until 1 chair remains).

Win conditions (first to satisfy):
- Most points after 8 rounds.
- Reach 40 points first.
- Cause the opponent to be shocked 3 times.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

# ──────────────────────────────────────────────
# Game constants
# ──────────────────────────────────────────────
ALL_CHAIRS: List[int] = list(range(1, 13))  # chairs 1 to 12
MAX_ROUNDS: int = 8
TURNS_PER_ROUND: int = 2
MAX_TURNS: int = MAX_ROUNDS * TURNS_PER_ROUND
WIN_POINTS: int = 40
MAX_SHOCKS: int = 3


# ──────────────────────────────────────────────
# GameState
# ──────────────────────────────────────────────
@dataclass
class GameState:
    """Snapshot of the game at a given point.

    Attributes:
        attacker_points: Current accumulated points of the attacker this round.
        defender_points: Current accumulated points of the defender this round.
        round_num: Current turn number (1-based).
        remaining_chairs: Chair numbers still in play (not yet successfully claimed).
        attacker_shocks: Number of times the attacker has been shocked so far.
        defender_shocks: Number of times the defender (as attacker) has been shocked.
    """

    attacker_points: int = 0
    defender_points: int = 0
    round_num: int = 1
    remaining_chairs: List[int] = field(default_factory=lambda: list(range(1, 13)))
    attacker_shocks: int = 0
    defender_shocks: int = 0

    # ── Derived properties ──────────────────────

    def max_remaining_points(self) -> int:
        """Sum of all remaining chair values (upper bound on future gains)."""
        return sum(self.remaining_chairs)

    def winner(self) -> str | None:
        """Return 'attacker', 'defender', or None if the game is still ongoing."""
        if self.attacker_shocks >= MAX_SHOCKS:
            return "defender"
        if self.defender_shocks >= MAX_SHOCKS:
            return "attacker"
        if self.attacker_points >= WIN_POINTS:
            return "attacker"
        if self.defender_points >= WIN_POINTS:
            return "defender"
        if self.round_num > MAX_TURNS or len(self.remaining_chairs) <= 1:
            if self.attacker_points > self.defender_points:
                return "attacker"
            elif self.defender_points > self.attacker_points:
                return "defender"
            return "tie"
        return None

    def is_game_over(self) -> bool:
        """True when the game has reached a terminal state."""
        return self.winner() is not None
