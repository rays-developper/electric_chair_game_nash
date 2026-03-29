#!/usr/bin/env python3
"""Export equilibrium data to JSON for GitHub Pages static hosting."""

import argparse
import json
import sqlite3
from pathlib import Path


def export_to_json(db_path: str, output_path: str, limit: int | None = None):
    """Export SQLite data to JSON file."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Export all or limited rows, prioritizing common game states
    if limit:
        # Prioritize: low total points, more chairs remaining
        cur.execute(
            """
            SELECT * FROM equilibrium_lookup
            ORDER BY 
                (attacker_points + defender_points) ASC,
                (attacker_shocks + defender_shocks) ASC
            LIMIT ?
            """,
            (limit,),
        )
    else:
        cur.execute("SELECT * FROM equilibrium_lookup")

    rows = cur.fetchall()
    print(f"Exporting {len(rows)} rows...")

    data = {}
    for row in rows:
        key = str(row["state_key"])
        data[key] = {
            "ap": row["attacker_points"],
            "dp": row["defender_points"],
            "as": row["attacker_shocks"],
            "ds": row["defender_shocks"],
            "cm": row["chair_mask"],
            "sv": round(row["state_value"], 6),
            "a": json.loads(row["attacker_strategy"]),
            "d": json.loads(row["defender_strategy"]),
            "t": bool(row["is_terminal"]),
        }

    conn.close()

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))

    size_mb = output.stat().st_size / 1024 / 1024
    print(f"Exported to {output_path} ({size_mb:.2f} MB, {len(data)} entries)")


def main():
    parser = argparse.ArgumentParser(description="Export equilibrium DB to JSON")
    parser.add_argument(
        "--db",
        default="data/equilibrium_lookup.sqlite3",
        help="Path to SQLite database",
    )
    parser.add_argument(
        "--output",
        default="docs/data/equilibrium.json",
        help="Output JSON file path",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of rows (None = all)",
    )
    args = parser.parse_args()

    export_to_json(args.db, args.output, args.limit)


if __name__ == "__main__":
    main()
