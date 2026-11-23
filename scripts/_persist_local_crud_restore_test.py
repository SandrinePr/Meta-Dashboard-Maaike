"""Local durable-persist CRUD + empty-DB restore test (HTTP file store).

Does not touch live GitHub hamster-persist. Uses the safeguarded live export
(Red Rock + BBQube) as the base, never the old Red-Rock-only snapshot.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EXPORT = ROOT / "data" / "backups" / "maaike-live-all-clients-20261123-144028.json"
TEMP_NAME = "TEMP Persist CRUD Klant"
TEMP_RENAME = "TEMP Persist CRUD Hernoemd"
MARKER = "DURABLE_PERSIST_LOCAL_TEST_20261123"


class _Store:
    def __init__(self) -> None:
        self.body: bytes | None = None
        self.lock = threading.Lock()


def _serve(store: _Store) -> tuple[HTTPServer, str]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            with store.lock:
                body = store.body
            if body is None:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"missing")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_PUT(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length)
            with store.lock:
                store.body = raw
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

    server = HTTPServer(("127.0.0.1", 0), Handler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://{host}:{port}/backup.json"


def main() -> int:
    from maaike.comparison_service import (
        add_competitor as comparison_add_competitor,
        ensure_tables as ensure_comparison_tables,
        _prefs as get_preferences,
    )
    from maaike.data_transfer import apply_import, validate_package
    from maaike.db import initialize_database, transaction
    from maaike.figma_planning import save_figma_connection
    from maaike.hamster_seed import restore_hamster_seed_if_empty
    from maaike.persist_remote import (
        durable_persist_result,
        push_if_changed,
        restore_from_remote_if_needed,
        should_run_hamster_seed,
    )
    from maaike.repository import add_client, delete_client, rename_client
    from maaike.strategy import save_strategy, upsert_target

    if not EXPORT.is_file():
        print("MISSING_EXPORT", EXPORT)
        return 1

    package = json.loads(EXPORT.read_text(encoding="utf-8"))
    validate_package(package)
    names = {c["name"] for c in package.get("clients") or []}
    if "Red Rock" not in names or "BBQube" not in names:
        print("EXPORT_CLIENTS_UNEXPECTED", sorted(names))
        return 2
    # Older export without competitors must remain importable
    package.pop("client_comparison_preferences", None)

    store = _Store()
    server, url = _serve(store)
    os.environ["MAAIKE_PERSIST_ENABLED"] = "1"
    os.environ["MAAIKE_PERSIST_BACKUP_URL"] = url
    os.environ["MAAIKE_PERSIST_PROVIDER"] = "http"
    os.environ.pop("MAAIKE_PERSIST_TOKEN", None)
    os.environ.pop("MAAIKE_PERSIST_RESTORE_ALWAYS", None)

    work = Path(tempfile.mkdtemp(prefix="hamster-persist-local-"))
    db1 = work / "crud.db"
    os.environ["MAAIKE_DATABASE_PATH"] = str(db1)
    initialize_database(db1)

    with transaction(db1) as conn:
        apply_import(conn, package, overwrite=True)
        ensure_comparison_tables(conn)
        temp_id = add_client(conn, TEMP_NAME)
        rename_client(conn, temp_id, TEMP_RENAME)
        save_strategy(
            conn,
            temp_id,
            account_info={},
            start_answers={"website": "https://example.test/persist", "tone_of_voice": MARKER},
            strategy_fields={"canva_strategy_url": "https://www.canva.com/design/persist-test"},
            source_notes=[],
            mark_complete=False,
        )
        save_figma_connection(
            conn,
            temp_id,
            file_key="PersistTestFigmaKey123",
            file_name="Persist Test",
            source_url="https://www.figma.com/file/PersistTestFigmaKey123",
        )
        upsert_target(
            conn,
            temp_id,
            {
                "metric_name": "followers",
                "target_value": 42,
                "unit": "count",
                "notes": MARKER,
            },
        )
        comparison_add_competitor(conn, temp_id, "temp_competitor_ig")
        doomed = add_client(conn, "TEMP Te Verwijderen")
        delete_client(conn, doomed)
        push = durable_persist_result(push_if_changed(conn))
        clients_after = [
            dict(r)
            for r in conn.execute("SELECT id, name FROM clients ORDER BY id").fetchall()
        ]
        prefs = get_preferences(conn, temp_id)

    print(
        "CRUD_PUSH",
        json.dumps(
            {
                "durable": push.get("durable"),
                "pushed": push.get("pushed"),
                "reason": push.get("reason"),
                "bytes": push.get("bytes"),
                "clients": clients_after,
                "temp_id": temp_id,
                "competitors": prefs.get("competitors") if isinstance(prefs, dict) else prefs,
            },
            ensure_ascii=False,
            default=str,
        ),
    )
    if not push.get("durable"):
        server.shutdown()
        return 3
    with store.lock:
        remote = json.loads(store.body.decode("utf-8"))
    remote_names = {c["name"] for c in remote.get("clients") or []}
    if TEMP_RENAME not in remote_names or "TEMP Te Verwijderen" in remote_names:
        print("REMOTE_CLIENTS_BAD", sorted(remote_names))
        server.shutdown()
        return 4
    if "Red Rock" not in remote_names or "BBQube" not in remote_names:
        print("REMOTE_MISSING_LIVE", sorted(remote_names))
        server.shutdown()
        return 5

    # Empty DB restore (Render Free wipe simulation)
    db2 = work / "empty_restore.db"
    os.environ["MAAIKE_DATABASE_PATH"] = str(db2)
    initialize_database(db2)
    with transaction(db2) as conn:
        restore = restore_from_remote_if_needed(conn)
        seed_allowed = should_run_hamster_seed(restore)
        seed = {"reason": "skipped_by_gate"}
        if seed_allowed:
            seed = restore_hamster_seed_if_empty(conn)
        restored_clients = [
            dict(r)
            for r in conn.execute("SELECT id, name FROM clients ORDER BY name").fetchall()
        ]
        names = {c["name"] for c in restored_clients}
        temp_row = conn.execute(
            "SELECT id FROM clients WHERE name = ?", (TEMP_RENAME,)
        ).fetchone()
        strategy_ok = False
        figma_ok = False
        target_ok = False
        competitor_ok = False
        if temp_row:
            tid = int(temp_row[0])
            strat = conn.execute(
                "SELECT start_answers_json, strategy_fields_json FROM client_strategy WHERE client_id = ?",
                (tid,),
            ).fetchone()
            if strat:
                answers = json.loads(strat[0] or "{}")
                fields = json.loads(strat[1] or "{}")
                strategy_ok = answers.get("tone_of_voice") == MARKER and "canva.com" in str(
                    fields.get("canva_strategy_url") or ""
                )
            fig = conn.execute(
                "SELECT file_key FROM client_figma_files WHERE client_id = ?", (tid,)
            ).fetchone()
            figma_ok = bool(fig and fig[0] == "PersistTestFigmaKey123")
            tgt = conn.execute(
                "SELECT notes FROM client_targets WHERE client_id = ?", (tid,)
            ).fetchone()
            target_ok = bool(tgt and MARKER in str(tgt[0] or ""))
            prefs = get_preferences(conn, tid)
            comps = (prefs or {}).get("competitors") if isinstance(prefs, dict) else []
            competitor_ok = any(str(c) == "temp_competitor_ig" for c in (comps or []))

    server.shutdown()
    summary = {
        "restored": restore.get("restored"),
        "reason": restore.get("reason"),
        "seed_allowed": seed_allowed,
        "seed_reason": seed.get("reason"),
        "names": sorted(names),
        "has_red_rock": "Red Rock" in names,
        "has_bbqube": "BBQube" in names,
        "has_temp": TEMP_RENAME in names,
        "deleted_absent": "TEMP Te Verwijderen" not in names,
        "strategy_ok": strategy_ok,
        "figma_ok": figma_ok,
        "target_ok": target_ok,
        "competitor_ok": competitor_ok,
    }
    print("RESTORE", json.dumps(summary, ensure_ascii=False))
    ok = (
        restore.get("restored")
        and not seed_allowed
        and summary["has_red_rock"]
        and summary["has_bbqube"]
        and summary["has_temp"]
        and summary["deleted_absent"]
        and strategy_ok
        and figma_ok
        and target_ok
        and competitor_ok
    )
    print("LOCAL_PERSIST_TEST_OK" if ok else "LOCAL_PERSIST_TEST_FAIL")
    return 0 if ok else 6


if __name__ == "__main__":
    raise SystemExit(main())
