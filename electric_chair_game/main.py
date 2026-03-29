"""Command-line interface for the Electric Chair Game Nash Equilibrium Analyzer.

Usage:
    python -m electric_chair_game

Follow the prompts to enter the current game state.  The tool will print the
optimal mixed strategy (Nash equilibrium) for both attacker and defender.
"""

from __future__ import annotations

import sys
from typing import List

from .game_state import GameState, MAX_ROUNDS, MAX_SHOCKS
from electric_chair_game.dynamic_solver import compute_full_game_equilibrium
from .nash_solver import compute_nash_equilibrium


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _parse_chairs(raw: str) -> List[int]:
    """Parse a comma-separated string of chair numbers."""
    chairs = []
    for token in raw.split(","):
        token = token.strip()
        if token:
            chairs.append(int(token))
    return sorted(set(chairs))


def _bar(prob: float, width: int = 30) -> str:
    filled = round(prob * width)
    return "█" * filled + "░" * (width - filled)


def _print_strategy(strategy: List[tuple], title: str) -> None:
    print(f"\n{'─'*52}")
    print(f"  {title}")
    print(f"{'─'*52}")
    print(f"  {'椅子':>4}  {'確率':>7}  分布")
    print(f"  {'----':>4}  {'-------':>7}  " + "─" * 30)
    for chair, prob in strategy:
        if prob >= 0.001:
            print(f"  {chair:4d}  {prob:6.1%}  {_bar(prob)}")
    print()


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main() -> None:
    print("=" * 52)
    print("  電気椅子ゲーム  Nash均衡戦略アナライザー")
    print("=" * 52)

    # ── Mode ───────────────────────────────────
    mode = input("\n解析モード [single / full] (default: single): ").strip().lower()
    if not mode:
        mode = "single"
    if mode not in ("single", "full"):
        print("エラー: 'single' または 'full' を入力してください。")
        sys.exit(1)

    # ── Role ───────────────────────────────────
    role = input("\nあなたの役割 [attacker / defender]: ").strip().lower()
    if role not in ("attacker", "defender"):
        print("エラー: 'attacker' または 'defender' を入力してください。")
        sys.exit(1)

    # ── Game state inputs ──────────────────────
    try:
        my_points = int(input("あなたの現在ポイント: "))
        opp_points = int(input("相手の現在ポイント: "))
        round_num = int(input(f"現在の回戦 (1-{MAX_ROUNDS}): "))
        my_shocks = int(input(f"あなたが受けた電撃回数 (0-{MAX_SHOCKS - 1}): "))
        opp_shocks = int(input(f"相手が受けた電撃回数 (0-{MAX_SHOCKS - 1}): "))
        chairs_raw = input(
            "残りの椅子 (カンマ区切り, 例: 1,2,3,4,5,6,7,8,9,10,11,12): "
        )
        remaining = _parse_chairs(chairs_raw)
    except (ValueError, EOFError) as exc:
        print(f"入力エラー: {exc}")
        sys.exit(1)

    if not remaining:
        print("エラー: 椅子が1脚も指定されていません。")
        sys.exit(1)

    # ── Map to attacker / defender perspective ─
    if role == "attacker":
        attacker_points, defender_points = my_points, opp_points
        attacker_shocks, defender_shocks = my_shocks, opp_shocks
    else:
        attacker_points, defender_points = opp_points, my_points
        attacker_shocks, defender_shocks = opp_shocks, my_shocks

    gs = GameState(
        attacker_points=attacker_points,
        defender_points=defender_points,
        round_num=round_num,
        remaining_chairs=remaining,
        attacker_shocks=attacker_shocks,
        defender_shocks=defender_shocks,
    )

    # ── State summary ──────────────────────────
    print(f"\n{'='*52}")
    print("  現在のゲーム状態")
    print(f"{'='*52}")
    print(f"  回戦         : {round_num} / {MAX_ROUNDS}")
    print(f"  攻撃側ポイント: {attacker_points}")
    print(f"  守備側ポイント: {defender_points}")
    print(f"  残り椅子     : {remaining}")
    print(f"  残りポイント合計: {gs.max_remaining_points()}")
    print(f"  攻撃側電撃回数: {attacker_shocks} / {MAX_SHOCKS}")
    print(f"  守備側電撃回数: {defender_shocks} / {MAX_SHOCKS}")
    if gs.is_game_over():
        print(f"\n  ※ ゲーム終了条件が成立しています (勝者: {gs.winner()})")

    # ── Nash equilibrium ───────────────────────
    if mode == "single":
        result = compute_nash_equilibrium(gs)

        if role == "attacker":
            _print_strategy(result["attacker_strategy"], "攻撃側の最適混合戦略 (あなた)")
            _print_strategy(result["defender_strategy"], "守備側の最適混合戦略 (相手の推定)")
        else:
            _print_strategy(result["defender_strategy"], "守備側の最適混合戦略 (あなた)")
            _print_strategy(result["attacker_strategy"], "攻撃側の最適混合戦略 (相手の推定)")

        print(f"  Nash均衡における期待獲得ポイント (攻撃側): {result['game_value']:.3f}")
        print()
        return

    result = compute_full_game_equilibrium(gs)

    if role == "attacker":
        _print_strategy(result["attacker_strategy"], "攻撃側の最適混合戦略 (あなた)")
        _print_strategy(result["defender_strategy"], "守備側の最適混合戦略 (相手の推定)")
    else:
        _print_strategy(result["defender_strategy"], "守備側の最適混合戦略 (あなた)")
        _print_strategy(result["attacker_strategy"], "攻撃側の最適混合戦略 (相手の推定)")

    print("  8回戦全体DPにおける状態価値 (あなた視点):")
    print(f"    {result['state_value']:.6f}  (1=勝ち確率優位, 0=五分, -1=不利)")
    print()


if __name__ == "__main__":
    main()
