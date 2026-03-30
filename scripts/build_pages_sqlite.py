#!/usr/bin/env python3
"""Build compact sharded SQLite files for GitHub Pages range-based lookup.

Design:
- Quantize state value to fixed-point integer (sv_i / sv_scale)
- Encode strategy arrays to compact bytes (chair:uint8, prob:uint8)
- Split into multiple SQLite shard files so each file can stay <100MB
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from pathlib import Path


def _size_mb(path: Path) -> float:
    return path.stat().st_size / 1024 / 1024


def _encode_strategy(raw: str) -> bytes:
    pairs = json.loads(raw)
    encoded = bytearray()
    for chair, prob in pairs:
        chair_i = int(chair)
        q = int(round(float(prob) * 255.0))
        if q <= 0:
            continue
        if chair_i < 0 or chair_i > 255:
            raise ValueError(f"chair out of range: {chair_i}")
        if q > 255:
            q = 255
        encoded.append(chair_i)
        encoded.append(q)
    return bytes(encoded)


def _open_shard(path: Path, page_size: int) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute(f"PRAGMA page_size={page_size}")
    conn.execute(
        """
        CREATE TABLE lookup (
            state_key INTEGER PRIMARY KEY,
            sv_i INTEGER NOT NULL,
            a BLOB NOT NULL,
            d BLOB NOT NULL,
            t INTEGER NOT NULL
        ) WITHOUT ROWID
        """
    )
    return conn


def build_pages_sqlite_shards(
    src_db: Path,
    dst_dir: Path,
    manifest_path: Path,
    shards: int = 32,
    page_size: int = 4096,
    sv_scale: int = 1000,
    batch_size: int = 5000,
) -> dict:
    if not src_db.exists():
        raise SystemExit(f"Source DB not found: {src_db}")
    if shards <= 0:
        raise SystemExit("--shards must be >= 1")
    if sv_scale <= 0:
        raise SystemExit("--sv-scale must be >= 1")

    dst_dir.mkdir(parents=True, exist_ok=True)
    for stale in dst_dir.glob("equilibrium_shard_*.sqlite3"):
        stale.unlink(missing_ok=True)

    width = math.ceil((1 << 28) / shards)

    shard_conns: list[sqlite3.Connection] = []
    shard_paths: list[Path] = []
    shard_rows = [0 for _ in range(shards)]
    min_keys: list[int | None] = [None for _ in range(shards)]
    max_keys: list[int | None] = [None for _ in range(shards)]
    pending: list[list[tuple[int, int, bytes, bytes, int]]] = [[] for _ in range(shards)]

    for sid in range(shards):
        path = dst_dir / f"equilibrium_shard_{sid:03d}.sqlite3"
        shard_paths.append(path)
        shard_conns.append(_open_shard(path, page_size=page_size))

    src = sqlite3.connect(src_db)
    src.row_factory = sqlite3.Row
    try:
        cur = src.execute(
            """
            SELECT state_key, state_value, attacker_strategy, defender_strategy, is_terminal
            FROM equilibrium_lookup
            ORDER BY state_key
            """
        )
        total = 0
        for row in cur:
            state_key = int(row["state_key"])
            sid = min(state_key // width, shards - 1)
            sv_i = int(round(float(row["state_value"]) * sv_scale))
            a = _encode_strategy(str(row["attacker_strategy"]))
            d = _encode_strategy(str(row["defender_strategy"]))
            t = int(row["is_terminal"])

            pending[sid].append((state_key, sv_i, a, d, t))
            total += 1

            if min_keys[sid] is None or state_key < min_keys[sid]:
                min_keys[sid] = state_key
            if max_keys[sid] is None or state_key > max_keys[sid]:
                max_keys[sid] = state_key

            if len(pending[sid]) >= batch_size:
                shard_conns[sid].executemany(
                    "INSERT OR REPLACE INTO lookup(state_key, sv_i, a, d, t) VALUES (?, ?, ?, ?, ?)",
                    pending[sid],
                )
                shard_conns[sid].commit()
                shard_rows[sid] += len(pending[sid])
                pending[sid].clear()

            if total % 500000 == 0:
                print(f"processed={total}", flush=True)

        for sid in range(shards):
            if pending[sid]:
                shard_conns[sid].executemany(
                    "INSERT OR REPLACE INTO lookup(state_key, sv_i, a, d, t) VALUES (?, ?, ?, ?, ?)",
                    pending[sid],
                )
                shard_conns[sid].commit()
                shard_rows[sid] += len(pending[sid])
                pending[sid].clear()
    finally:
        src.close()

    for conn in shard_conns:
        conn.execute("ANALYZE")
        conn.execute("VACUUM")
        conn.close()

    ranges = []
    total_rows = 0
    total_bytes = 0
    max_file_mb = 0.0
    for sid, path in enumerate(shard_paths):
        rows = shard_rows[sid]
        if rows == 0:
            path.unlink(missing_ok=True)
            continue
        size_bytes = path.stat().st_size
        total_rows += rows
        total_bytes += size_bytes
        size_mb = _size_mb(path)
        max_file_mb = max(max_file_mb, size_mb)
        ranges.append(
            {
                "file": path.name,
                "min_key": int(min_keys[sid]),
                "max_key": int(max_keys[sid]),
                "rows": rows,
                "size_bytes": size_bytes,
            }
        )

    ranges.sort(key=lambda x: x["min_key"])
    manifest = {
        "format": "pages-sqlite-shards-v1",
        "source": str(src_db),
        "sv_scale": sv_scale,
        "prob_scale": 255,
        "rows": total_rows,
        "shards": len(ranges),
        "total_size_bytes": total_bytes,
        "ranges": ranges,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return {
        "rows": total_rows,
        "shards": len(ranges),
        "total_mb": total_bytes / 1024 / 1024,
        "max_file_mb": max_file_mb,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build compact sharded SQLite for GitHub Pages")
    parser.add_argument("--src", default="data/equilibrium_lookup.sqlite3", help="Source DB path")
    parser.add_argument("--dst-dir", default="docs/data", help="Output directory for shard DB files")
    parser.add_argument("--manifest", default="docs/data/sqlite_manifest.json", help="Manifest JSON path")
    parser.add_argument("--shards", type=int, default=32, help="Number of output shard sqlite files")
    parser.add_argument("--page-size", type=int, default=4096, help="SQLite page_size for output DBs")
    parser.add_argument("--sv-scale", type=int, default=1000, help="Scale for quantized state_value")
    parser.add_argument("--batch-size", type=int, default=5000, help="Per-shard insert batch size")
    args = parser.parse_args()

    src = Path(args.src)
    dst_dir = Path(args.dst_dir)
    manifest = Path(args.manifest)

    stats = build_pages_sqlite_shards(
        src_db=src,
        dst_dir=dst_dir,
        manifest_path=manifest,
        shards=args.shards,
        page_size=args.page_size,
        sv_scale=args.sv_scale,
        batch_size=args.batch_size,
    )

    src_mb = _size_mb(src)
    ratio = (stats["total_mb"] / src_mb * 100.0) if src_mb > 0 else 0.0
    print(f"source: {src} ({src_mb:.2f} MB)")
    print(f"output total: {stats['total_mb']:.2f} MB in {stats['shards']} shards")
    print(f"largest shard: {stats['max_file_mb']:.2f} MB")
    print(f"ratio: {ratio:.2f}%")
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
