"""CLI to precompute and persist equilibrium lookup table to SQLite."""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import sqlite3
import time
from pathlib import Path
from typing import TextIO

from .game_state import GameState
from .state_table import (
    StateRecord,
    THEORETICAL_STATE_SPACE,
    create_lookup_schema,
    load_state_records_from_sqlite,
    save_state_table_to_sqlite,
    solve_state_table_from_root,
)


def _parse_chairs(raw: str) -> list[int]:
    chairs = []
    for token in raw.split(","):
        token = token.strip()
        if token:
            chairs.append(int(token))
    return sorted(set(chairs))


def _next_subroots(root: GameState) -> list[GameState]:
    chairs = sorted(root.remaining_chairs)
    subroots: list[GameState] = []

    shock_state = GameState(
        attacker_points=root.defender_points,
        defender_points=0,
        round_num=1,
        remaining_chairs=chairs,
        attacker_shocks=root.defender_shocks,
        defender_shocks=root.attacker_shocks + 1,
    )
    subroots.append(shock_state)

    for chair in chairs:
        remaining = [c for c in chairs if c != chair]
        success_state = GameState(
            attacker_points=root.defender_points,
            defender_points=root.attacker_points + chair,
            round_num=1,
            remaining_chairs=remaining,
            attacker_shocks=root.defender_shocks,
            defender_shocks=root.attacker_shocks,
        )
        subroots.append(success_state)
    return subroots


def _worker_build_subtree(payload: tuple[GameState, str, int, int]) -> tuple[str, int]:
    state, shard_db_path, save_interval, progress_interval = payload

    conn = sqlite3.connect(shard_db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    create_lookup_schema(conn)

    pending_rows: list[tuple] = []

    def flush_pending() -> int:
        if not pending_rows:
            return 0
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
            pending_rows,
        )
        conn.commit()
        flushed = len(pending_rows)
        pending_rows.clear()
        return flushed

    def on_new_record(rec: StateRecord) -> None:
        pending_rows.append(
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
        )
        if len(pending_rows) >= max(save_interval, 1):
            flush_pending()

    solve_state_table_from_root(
        state,
        progress_interval=max(progress_interval, 1),
        progress_callback=lambda _count: flush_pending(),
        on_new_record=on_new_record,
    )
    flush_pending()
    count = int(conn.execute("SELECT COUNT(*) FROM equilibrium_lookup").fetchone()[0])
    conn.close()
    return shard_db_path, count


def _merge_shards_into_db(main_db: Path, shard_paths: list[Path]) -> None:
    for shard in shard_paths:
        _merge_one_shard_into_db(main_db, shard)


def _merge_one_shard_into_db(main_db: Path, shard: Path, alias: str = "s") -> None:
    conn = sqlite3.connect(main_db)
    src = sqlite3.connect(shard)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        create_lookup_schema(conn)

        cursor = src.execute(
            """
            SELECT
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
            FROM equilibrium_lookup
            """
        )
        while True:
            batch = cursor.fetchmany(5000)
            if not batch:
                break
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
                batch,
            )
            conn.commit()
    finally:
        src.close()
        conn.close()


def _count_rows(db_path: Path) -> int:
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(db_path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM equilibrium_lookup").fetchone()[0])
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build equilibrium lookup table into SQLite")
    parser.add_argument("--db", default="data/equilibrium_lookup.sqlite3", help="Output SQLite file path")
    parser.add_argument("--attacker-points", type=int, default=0)
    parser.add_argument("--defender-points", type=int, default=0)
    parser.add_argument("--attacker-shocks", type=int, default=0)
    parser.add_argument("--defender-shocks", type=int, default=0)
    parser.add_argument("--chairs", default="1,2,3,4,5,6,7,8,9,10,11,12")
    parser.add_argument("--progress-interval", type=int, default=5000)
    parser.add_argument("--save-interval", type=int, default=5000)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--log-file", default="data/build_progress.log")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    chairs = _parse_chairs(args.chairs)
    root = GameState(
        attacker_points=args.attacker_points,
        defender_points=args.defender_points,
        round_num=1,
        remaining_chairs=chairs,
        attacker_shocks=args.attacker_shocks,
        defender_shocks=args.defender_shocks,
    )

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = Path(args.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fp: TextIO | None = log_path.open("a", encoding="utf-8")

    def emit(message: str) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {message}"
        print(line, flush=True)
        if log_fp is not None:
            log_fp.write(line + "\n")
            log_fp.flush()

    def pct(rows: int) -> float:
        return 100.0 * rows / THEORETICAL_STATE_SPACE

    start = time.perf_counter()

    if args.workers > 1:
        shard_dir = db_path.parent / "_shards"
        shard_dir.mkdir(parents=True, exist_ok=True)
        if not args.resume:
            for stale in shard_dir.glob("subroot_*.sqlite3*"):
                stale.unlink(missing_ok=True)

        subroots = _next_subroots(root)
        base_rows = _count_rows(db_path)
        emit(
            f"parallel_start workers={args.workers} subroots={len(subroots)} "
            f"base_rows={base_rows} base_goal_pct={pct(base_rows):.3f}%"
        )

        payloads: list[tuple[GameState, str, int, int]] = []
        shard_paths: list[Path] = []
        reused_rows = 0
        for idx, subroot in enumerate(subroots):
            shard = shard_dir / f"subroot_{idx}.sqlite3"
            shard_paths.append(shard)
            existing_rows = _count_rows(shard)
            if args.resume and existing_rows > 0:
                reused_rows += existing_rows
                continue
            payloads.append((subroot, str(shard), args.save_interval, args.progress_interval))

        if args.resume:
            emit(f"parallel_resume_reused shard_rows={reused_rows} skipped_subroots={len(subroots)-len(payloads)}")

        done = 0
        done_rows = 0
        with cf.ProcessPoolExecutor(max_workers=args.workers) as ex:
            pending = {ex.submit(_worker_build_subtree, p) for p in payloads}
            while pending:
                finished, pending = cf.wait(pending, timeout=30, return_when=cf.FIRST_COMPLETED)
                if not finished:
                    elapsed = max(time.perf_counter() - start, 1e-9)
                    persisted_rows = sum(_count_rows(path) for path in shard_paths)
                    est_rows = base_rows + persisted_rows
                    emit(
                        f"parallel_heartbeat done={done}/{len(payloads)} persisted_rows={persisted_rows} "
                        f"est_total_rows={est_rows} goal_pct={pct(est_rows):.3f}% elapsed={elapsed:.1f}s"
                    )
                    continue

                for fut in finished:
                    shard_path, states = fut.result()
                    done += 1
                    done_rows += states
                    _merge_one_shard_into_db(db_path, Path(shard_path), alias=f"m{done}")
                    merged_rows = _count_rows(db_path)
                    elapsed = max(time.perf_counter() - start, 1e-9)
                    est_rows = base_rows + done_rows
                    emit(
                        f"parallel_subroot_done {done}/{len(payloads)} shard={Path(shard_path).name} "
                        f"states={states} rows={done_rows} est_total_rows={est_rows} merged_rows={merged_rows} "
                        f"goal_pct={pct(est_rows):.3f}% elapsed={elapsed:.1f}s"
                    )

        if args.resume:
            _merge_shards_into_db(db_path, shard_paths)
            if not payloads:
                emit("parallel_resume_merge_only reason=no_new_subroots")

        merged_seed = load_state_records_from_sqlite(db_path)

        pending_rows: list[tuple] = []

        def flush_pending_parallel() -> int:
            if not pending_rows:
                return 0
            conn = sqlite3.connect(db_path)
            try:
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
                    pending_rows,
                )
                conn.commit()
            finally:
                conn.close()
            flushed = len(pending_rows)
            pending_rows.clear()
            return flushed

        def on_new_record_parallel(rec: StateRecord) -> None:
            pending_rows.append(
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
            )

        solve_state_table_from_root(
            root,
            initial_cache=merged_seed,
            on_new_record=on_new_record_parallel,
            progress_interval=max(args.progress_interval, 1),
            progress_callback=lambda c: emit(f"finalize_root states={c}"),
        )
        final_flush = flush_pending_parallel()
        conn = sqlite3.connect(db_path)
        try:
            row_count = conn.execute("SELECT COUNT(*) FROM equilibrium_lookup").fetchone()[0]
        finally:
            conn.close()

        elapsed = time.perf_counter() - start
        emit(f"saved_rows={row_count}")
        emit(f"goal_pct={pct(row_count):.3f}%")
        emit("resumed_rows=0")
        emit(f"new_rows={row_count}")
        emit(f"final_flush_rows={final_flush}")
        emit(f"solve_elapsed_sec={elapsed:.3f}")
        emit(f"db_path={args.db}")
        emit("完了")
        if log_fp is not None:
            log_fp.close()
        return
    seed_cache: dict[int, StateRecord] = {}
    if args.resume and db_path.exists():
        try:
            seed_cache = load_state_records_from_sqlite(db_path)
        except sqlite3.Error:
            seed_cache = {}
    resumed_rows = len(seed_cache)
    emit(
        f"start db={db_path} resume={args.resume} resumed_rows={resumed_rows} "
        f"progress_interval={args.progress_interval} save_interval={args.save_interval} "
        f"goal_rows={THEORETICAL_STATE_SPACE} goal_pct={pct(resumed_rows):.3f}%"
    )

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    create_lookup_schema(conn)

    pending_rows: list[tuple] = []

    def flush_pending() -> int:
        if not pending_rows:
            return 0
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
            pending_rows,
        )
        conn.commit()
        flushed = len(pending_rows)
        pending_rows.clear()
        return flushed

    def on_progress(count: int) -> None:
        elapsed = max(time.perf_counter() - start, 1e-9)
        rate = count / elapsed
        current_rows = count
        emit(
            f"progress states={count} rows={current_rows} new={max(0, current_rows-resumed_rows)} "
            f"goal_pct={pct(current_rows):.3f}% elapsed={elapsed:.1f}s rate={rate:.1f}/s",
        )

    def on_new_record(rec: StateRecord) -> None:
        pending_rows.append(
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
        )
        if len(pending_rows) >= max(args.save_interval, 1):
            flushed = flush_pending()
            elapsed = max(time.perf_counter() - start, 1e-9)
            emit(f"checkpoint flushed={flushed} elapsed={elapsed:.1f}s")

    solve_state_table_from_root(
        root,
        progress_callback=on_progress,
        progress_interval=args.progress_interval,
        initial_cache=seed_cache,
        on_new_record=on_new_record,
    )
    elapsed_solve = time.perf_counter() - start
    final_flushed = flush_pending()
    row_count = conn.execute("SELECT COUNT(*) FROM equilibrium_lookup").fetchone()[0]
    conn.close()

    count = row_count
    emit(f"saved_rows={count}")
    emit(f"goal_pct={pct(count):.3f}%")
    emit(f"resumed_rows={resumed_rows}")
    emit(f"new_rows={max(0, count - resumed_rows)}")
    emit(f"final_flush_rows={final_flushed}")
    emit(f"solve_elapsed_sec={elapsed_solve:.3f}")
    emit(f"db_path={args.db}")
    emit("完了")
    if log_fp is not None:
        log_fp.close()


if __name__ == "__main__":
    main()
