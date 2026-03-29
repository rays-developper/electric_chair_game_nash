"""Nash equilibrium solver for the Electric Chair Game (電気椅子ゲーム).

Single-round model
------------------
Within each round the interaction between attacker and defender is modelled as
a finite, simultaneous, two-player zero-sum game:

  - Attacker's pure strategies : sit in one of the N remaining chairs.
  - Defender's pure strategies : electrify one of the N remaining chairs.

Payoff matrix A  (N × N, row = attacker choice, column = defender choice)
  A[i][j] = chairs[i]          if i ≠ j   (attacker gains chair value)
  A[i][j] = -attacker_points   if i == j  (attacker loses all accumulated pts)

The Nash equilibrium of this zero-sum game is found by solving two dual linear
programmes (minimax / maximin formulations).

The output is the optimal *mixed* strategy:
  - Attacker : probability distribution over chairs to sit in.
  - Defender : probability distribution over chairs to electrify.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
from scipy.optimize import linprog

from .game_state import GameState


# ──────────────────────────────────────────────
# Payoff matrix
# ──────────────────────────────────────────────

def build_payoff_matrix(attacker_points: int, chairs: List[int]) -> np.ndarray:
    """Build the N×N payoff matrix for the current round.

    Parameters
    ----------
    attacker_points:
        Attacker's accumulated points at the start of this round.
        If shocked they lose this amount.
    chairs:
        Ordered list of chair values still in play.

    Returns
    -------
    np.ndarray of shape (N, N) where N = len(chairs).
    """
    n = len(chairs)
    A = np.empty((n, n), dtype=float)
    for i in range(n):
        for j in range(n):
            A[i, j] = -attacker_points if i == j else float(chairs[i])
    return A


# ──────────────────────────────────────────────
# LP solvers
# ──────────────────────────────────────────────

def _solve_attacker_lp(A: np.ndarray) -> Tuple[np.ndarray, float]:
    """Find the attacker's Nash equilibrium mixed strategy.

    Solves:
        max  v
        s.t. Σ_i p_i * A[i,j] ≥ v   for all j
             Σ_i p_i = 1
             p_i ≥ 0

    Equivalent LP (minimisation):
        min  -v
        s.t. -Σ_i p_i * A[i,j] + v ≤ 0   for all j
             Σ_i p_i = 1
             p_i ≥ 0,  v free

    Variables: x = [p_0, …, p_{n-1}, v]
    """
    n = A.shape[0]

    # Objective: minimise -v
    c = np.zeros(n + 1)
    c[n] = -1.0

    # Inequality constraints: -A[:,j]^T p + v ≤ 0
    A_ub = np.zeros((n, n + 1))
    A_ub[:, :n] = -A.T          # column j → row j constraint
    A_ub[:, n] = 1.0
    b_ub = np.zeros(n)

    # Equality: Σ p_i = 1
    A_eq = np.zeros((1, n + 1))
    A_eq[0, :n] = 1.0
    b_eq = np.array([1.0])

    bounds = [(0.0, None)] * n + [(None, None)]

    result = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                     bounds=bounds, method="highs")

    if result.success:
        p = np.maximum(result.x[:n], 0.0)
        total = p.sum()
        if total > 0:
            p /= total
        else:
            p = np.ones(n) / n
        return p, float(result.x[n])

    # Fallback: uniform (should not happen for well-formed games)
    return np.ones(n) / n, 0.0


def _solve_defender_lp(A: np.ndarray) -> Tuple[np.ndarray, float]:
    """Find the defender's Nash equilibrium mixed strategy.

    Solves:
        min  v
        s.t. Σ_j q_j * A[i,j] ≤ v   for all i
             Σ_j q_j = 1
             q_j ≥ 0

    Variables: x = [q_0, …, q_{n-1}, v]
    """
    n = A.shape[0]

    # Objective: minimise v
    c = np.zeros(n + 1)
    c[n] = 1.0

    # Inequality: A[i,:] q - v ≤ 0
    A_ub = np.zeros((n, n + 1))
    A_ub[:, :n] = A               # row i → row i constraint
    A_ub[:, n] = -1.0
    b_ub = np.zeros(n)

    # Equality: Σ q_j = 1
    A_eq = np.zeros((1, n + 1))
    A_eq[0, :n] = 1.0
    b_eq = np.array([1.0])

    bounds = [(0.0, None)] * n + [(None, None)]

    result = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                     bounds=bounds, method="highs")

    if result.success:
        q = np.maximum(result.x[:n], 0.0)
        total = q.sum()
        if total > 0:
            q /= total
        else:
            q = np.ones(n) / n
        return q, float(result.x[n])

    return np.ones(n) / n, 0.0


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def compute_nash_equilibrium(game_state: GameState) -> Dict:
    """Compute the Nash equilibrium mixed strategies for the current round.

    Parameters
    ----------
    game_state:
        Current snapshot of the game.

    Returns
    -------
    dict with keys:
        ``attacker_strategy`` : list of (chair_value, probability) tuples
        ``defender_strategy``  : list of (chair_value, probability) tuples
        ``game_value``         : expected per-round payoff to attacker at equilibrium
        ``payoff_matrix``      : the N×N payoff matrix used for the calculation
    """
    chairs = sorted(game_state.remaining_chairs)
    A = build_payoff_matrix(game_state.attacker_points, chairs)

    attacker_probs, game_value = _solve_attacker_lp(A)
    defender_probs, _ = _solve_defender_lp(A)

    attacker_strategy = [(chairs[i], float(attacker_probs[i])) for i in range(len(chairs))]
    defender_strategy = [(chairs[i], float(defender_probs[i])) for i in range(len(chairs))]

    return {
        "attacker_strategy": attacker_strategy,
        "defender_strategy": defender_strategy,
        "game_value": float(game_value),
        "payoff_matrix": A,
    }
