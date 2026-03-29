"""HTTP server for precomputed equilibrium lookup + browser UI."""

from __future__ import annotations

import argparse
import json
import sqlite3
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .state_table import (
    THEORETICAL_STATE_SPACE,
    chairs_to_mask,
    derive_round_num,
    load_all_records_to_memory,
    pack_state_key,
)


def _parse_chairs(raw: str) -> list[int]:
    chairs: list[int] = []
    for token in raw.split(","):
        token = token.strip()
        if token:
            chairs.append(int(token))
    return sorted(set(chairs))


class LookupStore:
    def __init__(self, db_path: Path, in_memory: bool):
        self.db_path = db_path
        self.in_memory = in_memory
        self.cache: dict[int, dict] | None = None
        self.conn: sqlite3.Connection | None = None

        if in_memory:
            self.cache = load_all_records_to_memory(db_path)
        else:
            self.conn = sqlite3.connect(db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()

    def size(self) -> int:
        if self.cache is not None:
            return len(self.cache)
        if self.conn is None:
            return 0
        row = self.conn.execute("SELECT COUNT(*) AS c FROM equilibrium_lookup").fetchone()
        return int(row["c"])

    def lookup(self, state_key: int) -> dict | None:
        if self.cache is not None:
            return self.cache.get(state_key)

        if self.conn is None:
            return None

        row = self.conn.execute(
            """
            SELECT state_key, attacker_points, defender_points,
                   attacker_shocks, defender_shocks, chair_mask,
                   state_value, attacker_strategy, defender_strategy, is_terminal
            FROM equilibrium_lookup
            WHERE state_key = ?
            """,
            (state_key,),
        ).fetchone()
        if row is None:
            return None
        return {
            "state_key": int(row["state_key"]),
            "attacker_points": int(row["attacker_points"]),
            "defender_points": int(row["defender_points"]),
            "attacker_shocks": int(row["attacker_shocks"]),
            "defender_shocks": int(row["defender_shocks"]),
            "chair_mask": int(row["chair_mask"]),
            "round_num": derive_round_num(
                int(row["attacker_shocks"]),
                int(row["defender_shocks"]),
                int(row["chair_mask"]),
            ),
            "state_value": float(row["state_value"]),
            "attacker_strategy": json.loads(row["attacker_strategy"]),
            "defender_strategy": json.loads(row["defender_strategy"]),
            "is_terminal": bool(row["is_terminal"]),
        }


class LookupHandler(SimpleHTTPRequestHandler):
    store: LookupStore

    def _send_json(self, payload: dict, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/stats":
            self._send_json(
                {
                    "rows": self.store.size(),
                    "mode": "memory" if self.store.in_memory else "sqlite",
                    "theoretical_state_space": THEORETICAL_STATE_SPACE,
                }
            )
            return

        if parsed.path == "/api/lookup":
            params = parse_qs(parsed.query)
            try:
                attacker_points = int(params.get("attacker_points", ["0"])[0])
                defender_points = int(params.get("defender_points", ["0"])[0])
                attacker_shocks = int(params.get("attacker_shocks", ["0"])[0])
                defender_shocks = int(params.get("defender_shocks", ["0"])[0])
                chairs = _parse_chairs(params.get("chairs", [""])[0])
            except ValueError as exc:
                self._send_json({"error": f"invalid query: {exc}"}, status=HTTPStatus.BAD_REQUEST)
                return

            if not chairs:
                self._send_json({"error": "chairs is required"}, status=HTTPStatus.BAD_REQUEST)
                return

            try:
                state_key = pack_state_key(
                    attacker_points,
                    defender_points,
                    attacker_shocks,
                    defender_shocks,
                    chairs_to_mask(chairs),
                )
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return

            row = self.store.lookup(state_key)
            if row is None:
                self._send_json({"found": False, "state_key": state_key})
                return

            self._send_json({"found": True, "state_key": state_key, "result": row})
            return

        super().do_GET()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve equilibrium lookup UI/API")
    parser.add_argument("--db", default="data/equilibrium_lookup.sqlite3")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--memory-cache", action="store_true")
    args = parser.parse_args()

    web_root = Path(__file__).resolve().parent.parent / "web"
    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}. Build it first with build_lookup_table.py")

    store = LookupStore(db_path=db_path, in_memory=args.memory_cache)

    class _Handler(LookupHandler):
        pass

    _Handler.store = store
    server = ThreadingHTTPServer((args.host, args.port), lambda *a, **kw: _Handler(*a, directory=str(web_root), **kw))

    mode = "memory" if args.memory_cache else "sqlite"
    print(f"lookup server running: http://{args.host}:{args.port}  (mode={mode}, rows={store.size()})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        store.close()
        server.server_close()


if __name__ == "__main__":
    main()
