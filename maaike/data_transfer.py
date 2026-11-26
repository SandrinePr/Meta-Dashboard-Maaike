"""Versioned JSON backup export/import. Never includes API keys or Meta tokens."""

from __future__ import annotations

import base64
import csv
import io
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from maaike.config import database_path, project_root
from maaike.logs_export import EXPORT_COLUMNS, export_csv_bytes, rows_for_export
from maaike.repository import list_posts

FORMAT_ID = "maaike-dashboard-backup"
FORMAT_VERSION = 1

# Never export these tables/columns
SECRET_TABLES = frozenset(
    {
        "client_meta_secrets",
        "canva_oauth_secrets",
        "canva_oauth_pending",
    }
)
SECRET_CLIENT_FIELDS = frozenset(
    {
        "user_access_token",
        "page_access_token",
        "access_token",
        "refresh_token",
        "api_key",
        "ai_api_key",
        "password",
        "secret",
        "code_verifier",
    }
)


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _table_exists(conn, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        is not None
    )


def create_pre_import_backup() -> Path:
    src = database_path()
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    candidates = [
        project_root() / "data" / "backups",
        Path("/tmp") / "maaike_backups",
        src.parent,
    ]
    last_error: Exception | None = None
    for backup_dir in candidates:
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            dest = backup_dir / f"maaike_redrock-before-import-{stamp}.db"
            if src.is_file():
                shutil.copy2(src, dest)
            else:
                dest.write_bytes(b"")
            return dest
        except OSError as exc:
            last_error = exc
            continue
    raise OSError(f"Could not create pre-import backup: {last_error}")


def export_package(conn, *, client_id: int | None = None) -> dict[str, Any]:
    """Build a portable backup package without secrets."""
    clients_q = "SELECT * FROM clients"
    params: list[Any] = []
    if client_id is not None:
        clients_q += " WHERE id = ?"
        params.append(client_id)
    clients_q += " ORDER BY id"
    clients_out = []
    for row in conn.execute(clients_q, params).fetchall():
        d = {k: row[k] for k in row.keys() if k.lower() not in SECRET_CLIENT_FIELDS}
        # Never include token-ish values by accident
        clients_out.append(d)

    client_ids = [int(c["id"]) for c in clients_out]
    if not client_ids:
        client_ids = [-1]

    def _in_clause(ids: list[int]) -> tuple[str, list[int]]:
        return ",".join("?" * len(ids)), ids

    placeholders, ids = _in_clause(client_ids)

    formats = [
        dict(r)
        for r in conn.execute(
            f"SELECT * FROM content_formats WHERE client_id IN ({placeholders}) ORDER BY client_id, id",
            ids,
        ).fetchall()
    ]
    pillars = [
        dict(r)
        for r in conn.execute(
            f"SELECT * FROM content_pillars WHERE client_id IN ({placeholders}) ORDER BY client_id, id",
            ids,
        ).fetchall()
    ]
    hooks_legend = []
    if _table_exists(conn, "content_hooks"):
        hooks_legend = [
            dict(r)
            for r in conn.execute(
                f"SELECT * FROM content_hooks WHERE client_id IN ({placeholders}) ORDER BY client_id, id",
                ids,
            ).fetchall()
        ]

    strategies = []
    if _table_exists(conn, "client_strategy"):
        strategies = [
            dict(r)
            for r in conn.execute(
                f"SELECT * FROM client_strategy WHERE client_id IN ({placeholders})",
                ids,
            ).fetchall()
        ]

    strategy_files = []
    if _table_exists(conn, "client_strategy_files"):
        for r in conn.execute(
            f"""
            SELECT client_id, file_ref, filename, mime_type, byte_size, sha256,
                   status, content, created_at, updated_at
            FROM client_strategy_files
            WHERE client_id IN ({placeholders})
            ORDER BY client_id, id
            """,
            ids,
        ).fetchall():
            raw_content = r["content"] or b""
            if not raw_content:
                continue
            strategy_files.append(
                {
                    "client_id": int(r["client_id"]),
                    "file_ref": str(r["file_ref"] or ""),
                    "filename": str(r["filename"] or "strategie.pdf"),
                    "mime_type": str(r["mime_type"] or "application/pdf"),
                    "byte_size": int(r["byte_size"] or len(raw_content)),
                    "sha256": str(r["sha256"] or ""),
                    "status": str(r["status"] or "active"),
                    "content_b64": base64.b64encode(bytes(raw_content)).decode("ascii"),
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                }
            )

    targets = []
    if _table_exists(conn, "client_targets"):
        targets = [
            dict(r)
            for r in conn.execute(
                f"SELECT * FROM client_targets WHERE client_id IN ({placeholders}) ORDER BY id",
                ids,
            ).fetchall()
        ]

    posts = [
        dict(r)
        for r in conn.execute(
            f"SELECT * FROM posts WHERE client_id IN ({placeholders}) ORDER BY id",
            ids,
        ).fetchall()
    ]
    post_ids = [int(p["id"]) for p in posts] or [-1]
    pp, pids = _in_clause(post_ids)

    editorial = [
        dict(r)
        for r in conn.execute(
            f"SELECT * FROM post_editorial WHERE post_id IN ({pp})",
            pids,
        ).fetchall()
    ]
    hooks = [
        {
            "post_id": e["post_id"],
            "hook": e.get("hook") or "",
            "format_id": e.get("format_id"),
            "pillar_id": e.get("pillar_id"),
        }
        for e in editorial
    ]

    import_links = []
    if _table_exists(conn, "post_import_links"):
        import_links = [
            dict(r)
            for r in conn.execute(
                f"SELECT * FROM post_import_links WHERE post_id IN ({pp})",
                pids,
            ).fetchall()
        ]

    assessments = []
    if _table_exists(conn, "post_assessments"):
        assessments = [
            dict(r)
            for r in conn.execute(
                f"SELECT * FROM post_assessments WHERE post_id IN ({pp})",
                pids,
            ).fetchall()
        ]

    reports = []
    report_sources = []
    report_reviews = []
    monthly_trend_runs = []
    if _table_exists(conn, "client_reports"):
        reports = [
            dict(r)
            for r in conn.execute(
                f"SELECT * FROM client_reports WHERE client_id IN ({placeholders}) ORDER BY id",
                ids,
            ).fetchall()
        ]
        rids = [int(r["id"]) for r in reports] or [-1]
        rp, rparams = _in_clause(rids)
        if _table_exists(conn, "client_report_sources"):
            report_sources = [
                dict(r)
                for r in conn.execute(
                    f"SELECT * FROM client_report_sources WHERE report_id IN ({rp})",
                    rparams,
                ).fetchall()
            ]
        if _table_exists(conn, "client_report_reviews"):
            report_reviews = [
                dict(r)
                for r in conn.execute(
                    f"SELECT * FROM client_report_reviews WHERE report_id IN ({rp})",
                    rparams,
                ).fetchall()
            ]
    monthly_trend_settings = None
    if _table_exists(conn, "monthly_trend_schedule_runs"):
        monthly_trend_runs = [
            dict(r)
            for r in conn.execute("SELECT * FROM monthly_trend_schedule_runs ORDER BY id").fetchall()
        ]
    if _table_exists(conn, "monthly_trend_planner_settings"):
        s_row = conn.execute("SELECT * FROM monthly_trend_planner_settings WHERE id = 1").fetchone()
        if s_row is not None:
            monthly_trend_settings = dict(s_row)

    activity = []
    if _table_exists(conn, "dashboard_activity_events"):
        aq = f"SELECT * FROM dashboard_activity_events WHERE client_id IN ({placeholders}) OR client_id IS NULL"
        activity = [dict(r) for r in conn.execute(aq, ids).fetchall()]
    # Also snapshot synthesized activity (sync/AI/reports) so full backups keep the Logs view
    from maaike.activity_log import list_activity_events

    for cid in [int(c["id"]) for c in clients_out]:
        snap = list_activity_events(conn, client_id=cid, limit=200)
        for ev in snap.get("events") or []:
            activity.append(
                {
                    "client_id": ev.get("client_id"),
                    "occurred_at": ev.get("occurred_at"),
                    "activity_type": ev.get("activity_type"),
                    "status": ev.get("status"),
                    "title": ev.get("title"),
                    "details": ev.get("details"),
                    "source_ref": ev.get("source") or "",
                    "is_error": 1 if ev.get("is_error") else 0,
                }
            )

    # Content-log rows for convenience (same as Logs CSV columns)
    logs_rows = []
    for cid in [int(c["id"]) for c in clients_out]:
        stored = list_posts(conn, cid)
        for row in rows_for_export(stored):
            row["_client_id"] = cid
            logs_rows.append(row)

    prompt_settings = []
    if _table_exists(conn, "maaike_prompt_settings"):
        prompt_settings = [dict(r) for r in conn.execute("SELECT * FROM maaike_prompt_settings ORDER BY prompt_key").fetchall()]

    figma_files = []
    figma_items = []
    if _table_exists(conn, "client_figma_files"):
        figma_files = [
            dict(r)
            for r in conn.execute(
                f"SELECT * FROM client_figma_files WHERE client_id IN ({placeholders}) ORDER BY client_id",
                ids,
            ).fetchall()
        ]
    if _table_exists(conn, "figma_planning_items"):
        figma_items = [
            dict(r)
            for r in conn.execute(
                f"SELECT * FROM figma_planning_items WHERE client_id IN ({placeholders}) ORDER BY id",
                ids,
            ).fetchall()
        ]

    post_ai_analyses = []
    if _table_exists(conn, "post_ai_analyses"):
        post_ai_analyses = [
            dict(r)
            for r in conn.execute(
                f"SELECT * FROM post_ai_analyses WHERE client_id IN ({placeholders}) ORDER BY id",
                ids,
            ).fetchall()
        ]

    comparison_preferences = []
    if _table_exists(conn, "client_comparison_preferences"):
        comparison_preferences = [
            dict(r)
            for r in conn.execute(
                f"SELECT * FROM client_comparison_preferences WHERE client_id IN ({placeholders}) ORDER BY client_id",
                ids,
            ).fetchall()
        ]

    crawl_accounts = []
    if _table_exists(conn, "client_crawl_accounts"):
        crawl_accounts = [
            dict(r)
            for r in conn.execute(
                f"SELECT * FROM client_crawl_accounts WHERE client_id IN ({placeholders}) ORDER BY client_id, id",
                ids,
            ).fetchall()
        ]

    logs_weekly_preferences = []
    if _table_exists(conn, "client_logs_weekly_preferences"):
        logs_weekly_preferences = [
            dict(r)
            for r in conn.execute(
                f"SELECT * FROM client_logs_weekly_preferences WHERE client_id IN ({placeholders}) ORDER BY client_id",
                ids,
            ).fetchall()
        ]

    return {
        "format": FORMAT_ID,
        "version": FORMAT_VERSION,
        "exported_at": _now(),
        "secrets_excluded": True,
        "secret_tables_omitted": sorted(SECRET_TABLES),
        "scope": {"client_id": client_id, "all_clients": client_id is None},
        "counts": {
            "clients": len(clients_out),
            "formats": len(formats),
            "pillars": len(pillars),
            "hooks_legend": len(hooks_legend),
            "strategies": len(strategies),
            "strategy_files": len(strategy_files),
            "targets": len(targets),
            "posts": len(posts),
            "hooks_editorial": len(hooks),
            "import_links": len(import_links),
            "assessments": len(assessments),
            "reports": len(reports),
            "report_sources": len(report_sources),
            "activity_events": len(activity),
            "logs_rows": len(logs_rows),
            "prompt_settings": len(prompt_settings),
            "figma_files": len(figma_files),
            "figma_items": len(figma_items),
            "post_ai_analyses": len(post_ai_analyses),
            "comparison_preferences": len(comparison_preferences),
            "crawl_accounts": len(crawl_accounts),
        },
        "clients": clients_out,
        "content_formats": formats,
        "content_pillars": pillars,
        "content_hooks": hooks_legend,
        "strategies": strategies,
        "targets": targets,
        "posts": posts,
        "post_editorial": editorial,
        "hooks": hooks,
        "post_import_links": import_links,
        "post_assessments": assessments,
        "client_reports": reports,
        "client_report_sources": report_sources,
        "client_report_reviews": report_reviews,
        "monthly_trend_schedule_runs": monthly_trend_runs,
        "monthly_trend_planner_settings": monthly_trend_settings,
        "activity_events": activity,
        "logs_export_rows": logs_rows,
        "prompt_settings": prompt_settings,
        "client_figma_files": figma_files,
        "figma_planning_items": figma_items,
        "post_ai_analyses": post_ai_analyses,
        # Optional for older packages that omit this key — import must stay compatible.
        "client_comparison_preferences": comparison_preferences,
        "client_crawl_accounts": crawl_accounts,
        "client_logs_weekly_preferences": logs_weekly_preferences,
        "client_strategy_files": strategy_files,
    }


def export_posts_csv(conn, client_id: int) -> bytes:
    posts = list_posts(conn, client_id)
    return export_csv_bytes(posts)


def export_package_json_bytes(conn, *, client_id: int | None = None) -> bytes:
    package = export_package(conn, client_id=client_id)
    return json.dumps(package, ensure_ascii=False, indent=2).encode("utf-8")


def validate_package(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("Importbestand moet een JSON-object zijn.")
    if data.get("format") != FORMAT_ID:
        raise ValueError(f"Onbekend formaat (verwacht {FORMAT_ID}).")
    try:
        ver = int(data.get("version") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Ongeldige package-versie.") from exc
    if ver < 1 or ver > FORMAT_VERSION:
        raise ValueError(f"Niet-ondersteunde package-versie: {ver}.")
    if data.get("secrets_excluded") is False:
        raise ValueError("Pakket claimt geheimen te bevatten; import geweigerd.")
    # Reject accidental secret payload keys (not metadata like meta_token_expires_at).
    blocked_substrings = ("access_token", "api_key", "password", "client_secret", "refresh_token")
    for client in data.get("clients") or []:
        if not isinstance(client, dict):
            continue
        for key in list(client.keys()):
            kl = key.lower()
            if kl in SECRET_CLIENT_FIELDS or any(part in kl for part in blocked_substrings):
                raise ValueError(f"Geheime velden in import geweigerd: {key}")
    for secret_table in SECRET_TABLES:
        if secret_table in data:
            raise ValueError(f"{secret_table} mag niet in een importpakket zitten.")
    return {
        "ok": True,
        "version": ver,
        "exported_at": data.get("exported_at"),
        "counts": data.get("counts") or {},
        "scope": data.get("scope") or {},
    }


def preview_import(conn, data: dict[str, Any]) -> dict[str, Any]:
    meta = validate_package(data)
    name_to_id = {
        str(r["name"]).casefold(): int(r["id"])
        for r in conn.execute("SELECT id, name FROM clients").fetchall()
    }
    actions = {"add": [], "update": [], "skip": [], "link": []}

    for client in data.get("clients") or []:
        name = str(client.get("name") or "").strip()
        if not name:
            actions["skip"].append({"kind": "client", "reason": "lege naam", "row": client.get("id")})
            continue
        if name.casefold() in name_to_id:
            actions["update"].append(
                {"kind": "client", "name": name, "existing_id": name_to_id[name.casefold()]}
            )
        else:
            actions["add"].append({"kind": "client", "name": name})

    # Formats / pillars counted per name within client
    for kind, key in (("format", "content_formats"), ("pillar", "content_pillars")):
        for item in data.get(key) or []:
            actions["add" if True else "skip"].append(
                {
                    "kind": kind,
                    "name": item.get("name"),
                    "client_id_in_package": item.get("client_id"),
                    "note": "wordt gematcht op klantnaam + itemnaam; bestaande naam → update bij overwrite",
                }
            )

    for report in data.get("client_reports") or []:
        actions["add"].append(
            {
                "kind": "report",
                "title": report.get("title"),
                "period": f"{report.get('period_year')}-{report.get('period_month')}",
                "version": report.get("version"),
            }
        )

    for link in data.get("post_import_links") or []:
        actions["link"].append(
            {
                "kind": "import_link",
                "post_id_in_package": link.get("post_id"),
                "source_file": link.get("source_file"),
                "source_row": link.get("source_row"),
            }
        )

    return {
        "validation": meta,
        "summary": {
            "clients_add": sum(1 for a in actions["add"] if a["kind"] == "client"),
            "clients_update": sum(1 for a in actions["update"] if a["kind"] == "client"),
            "formats_pillars": sum(1 for a in actions["add"] if a["kind"] in {"format", "pillar"}),
            "reports": sum(1 for a in actions["add"] if a["kind"] == "report"),
            "posts_in_package": len(data.get("posts") or []),
            "hooks": len(data.get("hooks") or data.get("post_editorial") or []),
            "import_links": len(data.get("post_import_links") or []),
            "activity_events": len(data.get("activity_events") or []),
            "skipped": len(actions["skip"]),
        },
        "sample_actions": {
            "add": actions["add"][:40],
            "update": actions["update"][:40],
            "skip": actions["skip"][:40],
            "link": actions["link"][:20],
        },
        "overwrite_required_for_updates": True,
        "note": (
            "Zonder overschrijven blijven bestaande klanten en posts staan. "
            "Alleen wat nog ontbreekt wordt toegevoegd. "
            + (
                "Dit bestand bevat een klantnaam die hier nog niet staat. Importeren maakt dan een extra klant. "
                "Gebruik dezelfde naam als de bestaande klant als je geen tweede klant wilt."
                if sum(1 for a in actions["add"] if a["kind"] == "client")
                else ""
            )
        ),
    }


def apply_import(
    conn,
    data: dict[str, Any],
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Apply import inside caller's transaction. Backup must be made by caller first."""
    validate_package(data)
    stats = {
        "clients_added": 0,
        "clients_updated": 0,
        "formats_added": 0,
        "formats_updated": 0,
        "pillars_added": 0,
        "pillars_updated": 0,
        "posts_added": 0,
        "posts_updated": 0,
        "posts_skipped": 0,
        "editorial_upserted": 0,
        "import_links_added": 0,
        "strategies_upserted": 0,
        "strategy_files_upserted": 0,
        "targets_added": 0,
        "reports_added": 0,
        "activity_added": 0,
        "prompt_settings_upserted": 0,
        "figma_files_upserted": 0,
        "figma_items_upserted": 0,
        "post_ai_analyses_added": 0,
        "comparison_preferences_upserted": 0,
        "skipped": 0,
    }

    # Map package client id -> live client id
    pkg_client_to_live: dict[int, int] = {}
    now = _now()

    for client in data.get("clients") or []:
        name = str(client.get("name") or "").strip()
        if not name:
            stats["skipped"] += 1
            continue
        pkg_id = int(client["id"])
        existing = conn.execute(
            "SELECT id FROM clients WHERE name = ? COLLATE NOCASE",
            (name,),
        ).fetchone()
        if existing is None:
            cur = conn.execute(
                """
                INSERT INTO clients (
                    name, created_at, updated_at, meta_status, meta_status_detail,
                    meta_page_id, meta_page_name, meta_ig_user_id, meta_ig_username,
                    meta_connected_at, meta_token_expires_at, meta_last_checked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    client.get("created_at") or now,
                    now,
                    client.get("meta_status") or "not_connected",
                    client.get("meta_status_detail"),
                    client.get("meta_page_id"),
                    client.get("meta_page_name"),
                    client.get("meta_ig_user_id"),
                    client.get("meta_ig_username"),
                    client.get("meta_connected_at"),
                    client.get("meta_token_expires_at"),
                    client.get("meta_last_checked_at"),
                ),
            )
            live_id = int(cur.lastrowid)
            stats["clients_added"] += 1
        else:
            live_id = int(existing["id"])
            if overwrite:
                conn.execute(
                    """
                    UPDATE clients SET
                        updated_at = ?, meta_status = ?, meta_status_detail = ?,
                        meta_page_name = ?, meta_ig_username = ?
                    WHERE id = ?
                    """,
                    (
                        now,
                        client.get("meta_status") or "not_connected",
                        client.get("meta_status_detail"),
                        client.get("meta_page_name"),
                        client.get("meta_ig_username"),
                        live_id,
                    ),
                )
                stats["clients_updated"] += 1
            else:
                stats["skipped"] += 1
        pkg_client_to_live[pkg_id] = live_id

    # Formats
    pkg_format_to_live: dict[int, int] = {}
    for item in data.get("content_formats") or []:
        live_client = pkg_client_to_live.get(int(item["client_id"]))
        if live_client is None:
            stats["skipped"] += 1
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            stats["skipped"] += 1
            continue
        existing = conn.execute(
            "SELECT id FROM content_formats WHERE client_id = ? AND name = ? COLLATE NOCASE",
            (live_client, name),
        ).fetchone()
        if existing is None:
            cur = conn.execute(
                """
                INSERT INTO content_formats (client_id, name, explanation, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    live_client,
                    name,
                    item.get("explanation") or "",
                    item.get("created_at") or now,
                    now,
                ),
            )
            pkg_format_to_live[int(item["id"])] = int(cur.lastrowid)
            stats["formats_added"] += 1
        else:
            live_fid = int(existing["id"])
            pkg_format_to_live[int(item["id"])] = live_fid
            if overwrite:
                conn.execute(
                    "UPDATE content_formats SET explanation = ?, updated_at = ? WHERE id = ?",
                    (item.get("explanation") or "", now, live_fid),
                )
                stats["formats_updated"] += 1

    pkg_pillar_to_live: dict[int, int] = {}
    for item in data.get("content_pillars") or []:
        live_client = pkg_client_to_live.get(int(item["client_id"]))
        if live_client is None:
            stats["skipped"] += 1
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            stats["skipped"] += 1
            continue
        existing = conn.execute(
            "SELECT id FROM content_pillars WHERE client_id = ? AND name = ? COLLATE NOCASE",
            (live_client, name),
        ).fetchone()
        if existing is None:
            cur = conn.execute(
                """
                INSERT INTO content_pillars (client_id, name, explanation, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    live_client,
                    name,
                    item.get("explanation") or "",
                    item.get("created_at") or now,
                    now,
                ),
            )
            pkg_pillar_to_live[int(item["id"])] = int(cur.lastrowid)
            stats["pillars_added"] += 1
        else:
            live_pid = int(existing["id"])
            pkg_pillar_to_live[int(item["id"])] = live_pid
            if overwrite:
                conn.execute(
                    "UPDATE content_pillars SET explanation = ?, updated_at = ? WHERE id = ?",
                    (item.get("explanation") or "", now, live_pid),
                )
                stats["pillars_updated"] += 1

    if _table_exists(conn, "content_hooks"):
        for item in data.get("content_hooks") or []:
            live_client = pkg_client_to_live.get(int(item["client_id"]))
            if live_client is None:
                stats["skipped"] += 1
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                stats["skipped"] += 1
                continue
            existing = conn.execute(
                "SELECT id FROM content_hooks WHERE client_id = ? AND name = ? COLLATE NOCASE",
                (live_client, name),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO content_hooks (client_id, name, explanation, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        live_client,
                        name,
                        item.get("explanation") or "",
                        item.get("created_at") or now,
                        now,
                    ),
                )
                stats["hooks_added"] = stats.get("hooks_added", 0) + 1
            elif overwrite:
                conn.execute(
                    "UPDATE content_hooks SET explanation = ?, updated_at = ? WHERE id = ?",
                    (item.get("explanation") or "", now, int(existing["id"])),
                )
                stats["hooks_updated"] = stats.get("hooks_updated", 0) + 1

    # Strategy
    if _table_exists(conn, "client_strategy"):
        for strat in data.get("strategies") or []:
            live_client = pkg_client_to_live.get(int(strat["client_id"]))
            if live_client is None:
                continue
            existing = conn.execute(
                "SELECT client_id FROM client_strategy WHERE client_id = ?",
                (live_client,),
            ).fetchone()
            values = (
                live_client,
                strat.get("account_info_json") or "{}",
                strat.get("start_answers_json") or "{}",
                strat.get("strategy_fields_json") or "{}",
                strat.get("source_notes_json") or "[]",
                strat.get("completed_at"),
                now,
            )
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO client_strategy (
                        client_id, account_info_json, start_answers_json, strategy_fields_json,
                        source_notes_json, completed_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                stats["strategies_upserted"] += 1
            elif overwrite:
                conn.execute(
                    """
                    UPDATE client_strategy SET
                        account_info_json = ?, start_answers_json = ?, strategy_fields_json = ?,
                        source_notes_json = ?, completed_at = ?, updated_at = ?
                    WHERE client_id = ?
                    """,
                    (*values[1:], live_client),
                )
                stats["strategies_upserted"] += 1

    # Private strategy PDF binaries (optional in older packages)
    if data.get("client_strategy_files"):
        from maaike.strategy_files import ensure_strategy_file_table

        ensure_strategy_file_table(conn)
        for item in data.get("client_strategy_files") or []:
            live_client = pkg_client_to_live.get(int(item["client_id"]))
            if live_client is None:
                continue
            file_ref = str(item.get("file_ref") or "").strip()
            encoded = str(item.get("content_b64") or "").strip()
            if not file_ref or not encoded:
                continue
            try:
                raw_pdf = base64.b64decode(encoded)
            except (ValueError, TypeError):
                continue
            if not raw_pdf:
                continue
            existing_file = conn.execute(
                "SELECT id FROM client_strategy_files WHERE client_id = ? AND file_ref = ?",
                (live_client, file_ref),
            ).fetchone()
            if existing_file is not None and not overwrite:
                continue
            conn.execute(
                """
                INSERT INTO client_strategy_files (
                    client_id, file_ref, filename, mime_type, byte_size,
                    sha256, status, content, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(client_id, file_ref) DO UPDATE SET
                    filename = excluded.filename,
                    mime_type = excluded.mime_type,
                    byte_size = excluded.byte_size,
                    sha256 = excluded.sha256,
                    status = excluded.status,
                    content = excluded.content,
                    updated_at = excluded.updated_at
                """,
                (
                    live_client,
                    file_ref,
                    str(item.get("filename") or "strategie.pdf"),
                    str(item.get("mime_type") or "application/pdf"),
                    int(item.get("byte_size") or len(raw_pdf)),
                    str(item.get("sha256") or ""),
                    str(item.get("status") or "active"),
                    bytes(raw_pdf),
                    str(item.get("created_at") or now),
                    str(item.get("updated_at") or now),
                ),
            )
            stats["strategy_files_upserted"] += 1

    if _table_exists(conn, "client_targets"):
        for target in data.get("targets") or []:
            live_client = pkg_client_to_live.get(int(target["client_id"]))
            if live_client is None:
                continue
            dup = conn.execute(
                """
                SELECT id FROM client_targets
                WHERE client_id = ? AND metric_name = ? AND IFNULL(period_year, -1) = IFNULL(?, -1)
                  AND IFNULL(period_quarter, -1) = IFNULL(?, -1) AND account_key = ?
                """,
                (
                    live_client,
                    target.get("metric_name"),
                    target.get("period_year"),
                    target.get("period_quarter"),
                    target.get("account_key") or "",
                ),
            ).fetchone()
            if dup is not None and not overwrite:
                stats["skipped"] += 1
                continue
            if dup is not None and overwrite:
                conn.execute(
                    """
                    UPDATE client_targets SET
                        platform = ?, target_kind = ?, baseline_value = ?, target_value = ?,
                        unit = ?, notes = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        target.get("platform") or "",
                        target.get("target_kind") or "absolute",
                        target.get("baseline_value"),
                        target.get("target_value"),
                        target.get("unit") or "",
                        target.get("notes") or "",
                        now,
                        int(dup["id"]),
                    ),
                )
                stats["targets_added"] += 1
                continue
            conn.execute(
                """
                INSERT INTO client_targets (
                    client_id, account_key, platform, metric_name, target_kind,
                    baseline_value, target_value, unit, period_year, period_quarter,
                    notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    live_client,
                    target.get("account_key") or "",
                    target.get("platform") or "",
                    target.get("metric_name") or "",
                    target.get("target_kind") or "absolute",
                    target.get("baseline_value"),
                    target.get("target_value"),
                    target.get("unit") or "",
                    target.get("period_year"),
                    target.get("period_quarter"),
                    target.get("notes") or "",
                    target.get("created_at") or now,
                    now,
                ),
            )
            stats["targets_added"] += 1

    # Posts
    pkg_post_to_live: dict[int, int] = {}
    for post in data.get("posts") or []:
        live_client = pkg_client_to_live.get(int(post["client_id"]))
        if live_client is None:
            stats["posts_skipped"] += 1
            continue
        platform = post.get("platform") or ""
        external_id = post.get("external_id") or ""
        existing = conn.execute(
            """
            SELECT id FROM posts
            WHERE client_id = ? AND platform = ? AND external_id = ?
            """,
            (live_client, platform, external_id),
        ).fetchone()
        if existing is None:
            cols = [
                "client_id",
                "platform",
                "external_id",
                "published_at",
                "content_kind",
                "permalink",
                "views",
                "likes",
                "comments",
                "shares",
                "saves",
                "clicks",
                "reach",
                "account_name",
                "caption",
                "media_urls",
                "last_synced_at",
            ]
            optional = []
            values = [
                live_client,
                platform,
                external_id,
                post.get("published_at") or now,
                post.get("content_kind"),
                post.get("permalink"),
                post.get("views"),
                post.get("likes"),
                post.get("comments"),
                post.get("shares"),
                post.get("saves"),
                post.get("clicks"),
                post.get("reach"),
                post.get("account_name"),
                post.get("caption"),
                post.get("media_urls"),
                post.get("last_synced_at"),
            ]
            # platform_label / source_origin if present in schema
            from maaike.migrate import _has_column

            for extra in ("platform_label", "source_origin"):
                if _has_column(conn, "posts", extra):
                    optional.append(extra)
                    values.append(post.get(extra))
            all_cols = cols + optional
            cur = conn.execute(
                f"""
                INSERT INTO posts ({", ".join(all_cols)})
                VALUES ({", ".join("?" for _ in all_cols)})
                """,
                values,
            )
            pkg_post_to_live[int(post["id"])] = int(cur.lastrowid)
            stats["posts_added"] += 1
        else:
            live_post = int(existing["id"])
            pkg_post_to_live[int(post["id"])] = live_post
            if overwrite:
                conn.execute(
                    """
                    UPDATE posts SET
                        published_at = ?, content_kind = ?, permalink = ?,
                        account_name = ?, caption = ?, media_urls = ?, last_synced_at = ?
                    WHERE id = ?
                    """,
                    (
                        post.get("published_at"),
                        post.get("content_kind"),
                        post.get("permalink"),
                        post.get("account_name"),
                        post.get("caption"),
                        post.get("media_urls"),
                        post.get("last_synced_at"),
                        live_post,
                    ),
                )
                stats["posts_updated"] += 1
            else:
                stats["posts_skipped"] += 1

    # Editorial / hooks
    for ed in data.get("post_editorial") or []:
        live_post = pkg_post_to_live.get(int(ed["post_id"]))
        if live_post is None:
            continue
        fmt = ed.get("format_id")
        pil = ed.get("pillar_id")
        live_fmt = pkg_format_to_live.get(int(fmt)) if fmt is not None else None
        live_pil = pkg_pillar_to_live.get(int(pil)) if pil is not None else None
        conn.execute(
            """
            INSERT INTO post_editorial (post_id, format_id, pillar_id, hook, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(post_id) DO UPDATE SET
                format_id = excluded.format_id,
                pillar_id = excluded.pillar_id,
                hook = excluded.hook,
                updated_at = excluded.updated_at
            """,
            (live_post, live_fmt, live_pil, ed.get("hook") or "", now),
        )
        stats["editorial_upserted"] += 1

    # Import links
    if _table_exists(conn, "post_import_links"):
        for link in data.get("post_import_links") or []:
            live_post = pkg_post_to_live.get(int(link["post_id"]))
            if live_post is None:
                continue
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO post_import_links (
                        post_id, source_file, source_sheet, source_row, imported_at,
                        platform_label_original, excel_published_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        live_post,
                        link.get("source_file") or "",
                        link.get("source_sheet") or "",
                        link.get("source_row") or 0,
                        link.get("imported_at") or now,
                        link.get("platform_label_original"),
                        link.get("excel_published_at"),
                    ),
                )
                if conn.execute("SELECT changes()").fetchone()[0]:
                    stats["import_links_added"] += 1
            except Exception:
                stats["skipped"] += 1

    # Reports (append new versions; preserve relations via mapped trend ids when possible)
    pkg_report_to_live: dict[int, int] = {}
    if _table_exists(conn, "client_reports"):
        try:
            from maaike.report_planning import ensure_tables as ensure_report_planning_tables

            ensure_report_planning_tables(conn)
        except Exception:
            pass
        for report in data.get("client_reports") or []:
            live_client = pkg_client_to_live.get(int(report["client_id"]))
            if live_client is None:
                continue
            # Skip exact duplicate version for same period/type unless overwrite creates new version always append
            existing = conn.execute(
                """
                SELECT id FROM client_reports
                WHERE client_id = ? AND report_type = ? AND period_year = ? AND period_month = ? AND version = ?
                """,
                (
                    live_client,
                    report.get("report_type"),
                    report.get("period_year"),
                    report.get("period_month"),
                    report.get("version"),
                ),
            ).fetchone()
            if existing is not None and not overwrite:
                pkg_report_to_live[int(report["id"])] = int(existing["id"])
                stats["skipped"] += 1
                continue
            table_cols = {
                str(r[1]) for r in conn.execute("PRAGMA table_info(client_reports)").fetchall()
            }
            cols = [
                c
                for c in report.keys()
                if c in table_cols
                and c
                not in {
                    "id",
                    "client_id",
                    "supersedes_id",
                    "linked_trend_report_id",
                }
            ]
            cur = conn.execute(
                f"""
                INSERT INTO client_reports (client_id, {", ".join(cols)})
                VALUES (?, {", ".join("?" for _ in cols)})
                """,
                (live_client, *[report[c] for c in cols]),
            )
            pkg_report_to_live[int(report["id"])] = int(cur.lastrowid)
            stats["reports_added"] += 1

        # Second pass: restore linked_trend_report_id and supersedes_id across imported reports
        for report in data.get("client_reports") or []:
            live_id = pkg_report_to_live.get(int(report["id"]))
            if live_id is None:
                continue
            raw_linked = report.get("linked_trend_report_id")
            raw_super = report.get("supersedes_id")
            mapped_linked = pkg_report_to_live.get(int(raw_linked)) if raw_linked is not None else None
            mapped_super = pkg_report_to_live.get(int(raw_super)) if raw_super is not None else None
            if mapped_linked is not None or mapped_super is not None:
                conn.execute(
                    """
                    UPDATE client_reports
                    SET linked_trend_report_id = COALESCE(?, linked_trend_report_id),
                        supersedes_id = COALESCE(?, supersedes_id)
                    WHERE id = ?
                    """,
                    (mapped_linked, mapped_super, live_id),
                )

        if _table_exists(conn, "client_report_sources"):
            for src in data.get("client_report_sources") or []:
                live_report = pkg_report_to_live.get(int(src["report_id"]))
                if live_report is None:
                    continue
                conn.execute(
                    """
                    INSERT INTO client_report_sources (
                        report_id, title, url, published_at, consulted_at, excerpt, source_kind, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        live_report,
                        src.get("title") or "",
                        src.get("url") or "",
                        src.get("published_at"),
                        src.get("consulted_at") or now[:10],
                        src.get("excerpt") or "",
                        src.get("source_kind") or "imported",
                        src.get("created_at") or now,
                    ),
                )

        if data.get("client_report_reviews"):
            try:
                from maaike.report_review import ensure_report_review_tables

                ensure_report_review_tables(conn)
                for rev in data.get("client_report_reviews") or []:
                    live_report = pkg_report_to_live.get(int(rev["report_id"]))
                    live_client = pkg_client_to_live.get(int(rev["client_id"]))
                    if live_report is None or live_client is None:
                        continue
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO client_report_reviews (
                            client_id, report_id, execution_key, ai_original_json,
                            item_feedback_json, final_version_text, reviewer_name,
                            review_status, reviewed_at, approved_at, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            live_client,
                            live_report,
                            rev.get("execution_key") or "",
                            rev.get("ai_original_json") or "{}",
                            rev.get("item_feedback_json") or "[]",
                            rev.get("final_version_text") or "",
                            rev.get("reviewer_name") or "",
                            rev.get("review_status") or "",
                            rev.get("reviewed_at"),
                            rev.get("approved_at"),
                            rev.get("created_at") or now,
                            rev.get("updated_at") or now,
                        ),
                    )
            except Exception:
                pass

        if data.get("monthly_trend_schedule_runs") or data.get("monthly_trend_planner_settings"):
            try:
                from maaike.monthly_trend_scheduler import ensure_monthly_trend_tables

                ensure_monthly_trend_tables(conn)
                for mrun in data.get("monthly_trend_schedule_runs") or []:
                    raw_rid = mrun.get("report_id")
                    live_rid = pkg_report_to_live.get(int(raw_rid)) if raw_rid is not None else None
                    scope = mrun.get("run_scope") or (
                        "production" if int(mrun.get("paid_ai_called") or 0) == 1 else "simulation"
                    )
                    # Never restore a stale 'in_progress' claim from an older snapshot
                    restored_status = mrun.get("status") or "completed"
                    if restored_status == "in_progress":
                        restored_status = "retry_needed"
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO monthly_trend_schedule_runs (
                            period_year, period_month, run_scope, timezone, scheduled_for, report_id,
                            mode, paid_ai_called, caught_up, trigger_source, attempt_count,
                            status, claim_token, claim_expires_at, detail, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', ?, ?, ?)
                        """,
                        (
                            int(mrun["period_year"]),
                            int(mrun["period_month"]),
                            scope,
                            mrun.get("timezone") or "Europe/Amsterdam",
                            mrun.get("scheduled_for") or f"{int(mrun['period_year']):04d}-{int(mrun['period_month']):02d}-01",
                            live_rid,
                            mrun.get("mode") or "simulation_no_paid_ai",
                            int(mrun.get("paid_ai_called") or 0),
                            int(mrun.get("caught_up") or 0),
                            mrun.get("trigger_source") or "",
                            int(mrun.get("attempt_count") or 1),
                            restored_status,
                            mrun.get("detail") or "",
                            mrun.get("created_at") or now,
                            mrun.get("updated_at") or now,
                        ),
                    )
                ms = data.get("monthly_trend_planner_settings")
                if isinstance(ms, dict):
                    conn.execute(
                        """
                        UPDATE monthly_trend_planner_settings
                        SET production_enabled = ?,
                            catchup_enabled = ?,
                            active_from = COALESCE(?, active_from),
                            last_external_trigger_at = ?,
                            last_external_trigger_mode = ?,
                            last_external_trigger_source = ?,
                            last_external_trigger_result = ?,
                            updated_at = ?
                        WHERE id = 1
                        """,
                        (
                            1 if ms.get("production_enabled", 1) else 0,
                            1 if ms.get("catchup_enabled", 1) else 0,
                            ms.get("active_from"),
                            ms.get("last_external_trigger_at"),
                            ms.get("last_external_trigger_mode"),
                            ms.get("last_external_trigger_source"),
                            ms.get("last_external_trigger_result"),
                            ms.get("updated_at") or now,
                        ),
                    )
            except Exception:
                pass

    # Activity events (create table if needed so full backups keep logs)
    from maaike.activity_log import ensure_activity_table, record_activity

    ensure_activity_table(conn)
    if data.get("activity_events"):
        for ev in data.get("activity_events") or []:
            live_client = None
            if ev.get("client_id") is not None:
                live_client = pkg_client_to_live.get(int(ev["client_id"]))
            record_activity(
                conn,
                client_id=live_client,
                activity_type=str(ev.get("activity_type") or "imported"),
                status=str(ev.get("status") or "info"),
                title=str(ev.get("title") or "Geïmporteerde gebeurtenis"),
                details=str(ev.get("details") or ""),
                source_ref="import",
                is_error=bool(ev.get("is_error")),
                occurred_at=ev.get("occurred_at"),
            )
            stats["activity_added"] += 1

    # Editable dashboard prompts (survive Render Free restarts via remote persist)
    if data.get("prompt_settings"):
        from maaike.prompt_settings import ensure_prompt_settings_table

        ensure_prompt_settings_table(conn)
        for row in data.get("prompt_settings") or []:
            key = str(row.get("prompt_key") or "").strip()
            body = str(row.get("body_text") or "").strip()
            if not key or not body:
                continue
            conn.execute(
                """
                INSERT INTO maaike_prompt_settings (prompt_key, label, body_text, version_tag, updated_at, updated_by)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(prompt_key) DO UPDATE SET
                    label = excluded.label,
                    body_text = excluded.body_text,
                    version_tag = excluded.version_tag,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by
                """,
                (
                    key,
                    str(row.get("label") or ""),
                    body,
                    str(row.get("version_tag") or ""),
                    str(row.get("updated_at") or now),
                    str(row.get("updated_by") or "import"),
                ),
            )
            stats["prompt_settings_upserted"] += 1

    # Figma file links + planning items
    if data.get("client_figma_files"):
        from maaike.figma_planning import ensure_figma_tables

        ensure_figma_tables(conn)
        for row in data.get("client_figma_files") or []:
            live_client = pkg_client_to_live.get(int(row["client_id"]))
            if live_client is None:
                continue
            conn.execute(
                """
                INSERT INTO client_figma_files (
                    client_id, file_key, file_name, source_url, last_synced_at, last_sync_note, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(client_id) DO UPDATE SET
                    file_key = excluded.file_key,
                    file_name = excluded.file_name,
                    source_url = excluded.source_url,
                    last_synced_at = excluded.last_synced_at,
                    last_sync_note = excluded.last_sync_note,
                    updated_at = excluded.updated_at
                """,
                (
                    live_client,
                    str(row.get("file_key") or ""),
                    str(row.get("file_name") or ""),
                    str(row.get("source_url") or ""),
                    row.get("last_synced_at"),
                    str(row.get("last_sync_note") or ""),
                    str(row.get("updated_at") or now),
                ),
            )
            stats["figma_files_upserted"] += 1

        for item in data.get("figma_planning_items") or []:
            live_client = pkg_client_to_live.get(int(item["client_id"]))
            if live_client is None:
                continue
            linked = item.get("linked_post_id")
            live_linked = pkg_post_to_live.get(int(linked)) if linked is not None else None
            conn.execute(
                """
                INSERT INTO figma_planning_items (
                    client_id, node_id, source_url, page_name, page_node_id,
                    period_year, period_month, code, content_kind, platform_hint,
                    format_raw, format_usable, pillar_raw, pillar_usable,
                    hook_raw, hook_usable, brief_excerpt, linked_post_id, link_status,
                    raw_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(client_id, node_id) DO UPDATE SET
                    source_url = excluded.source_url,
                    page_name = excluded.page_name,
                    page_node_id = excluded.page_node_id,
                    period_year = excluded.period_year,
                    period_month = excluded.period_month,
                    code = excluded.code,
                    content_kind = excluded.content_kind,
                    platform_hint = excluded.platform_hint,
                    format_raw = excluded.format_raw,
                    format_usable = excluded.format_usable,
                    pillar_raw = excluded.pillar_raw,
                    pillar_usable = excluded.pillar_usable,
                    hook_raw = excluded.hook_raw,
                    hook_usable = excluded.hook_usable,
                    brief_excerpt = excluded.brief_excerpt,
                    linked_post_id = COALESCE(excluded.linked_post_id, figma_planning_items.linked_post_id),
                    link_status = excluded.link_status,
                    raw_json = excluded.raw_json,
                    updated_at = excluded.updated_at
                """,
                (
                    live_client,
                    str(item.get("node_id") or ""),
                    str(item.get("source_url") or ""),
                    str(item.get("page_name") or ""),
                    str(item.get("page_node_id") or ""),
                    item.get("period_year"),
                    item.get("period_month"),
                    str(item.get("code") or ""),
                    str(item.get("content_kind") or ""),
                    str(item.get("platform_hint") or ""),
                    str(item.get("format_raw") or ""),
                    1 if item.get("format_usable") else 0,
                    str(item.get("pillar_raw") or ""),
                    1 if item.get("pillar_usable") else 0,
                    str(item.get("hook_raw") or ""),
                    1 if item.get("hook_usable") else 0,
                    str(item.get("brief_excerpt") or "")[:2000],
                    live_linked,
                    str(item.get("link_status") or "unlinked"),
                    str(item.get("raw_json") or "{}")[:20000],
                    str(item.get("updated_at") or now),
                ),
            )
            stats["figma_items_upserted"] += 1

    # Comparison / competitors (optional in older packages)
    if data.get("client_comparison_preferences"):
        from maaike.comparison_service import ensure_tables as ensure_comparison_tables

        ensure_comparison_tables(conn)
        for row in data.get("client_comparison_preferences") or []:
            live_client = pkg_client_to_live.get(int(row["client_id"]))
            if live_client is None:
                continue
            conn.execute(
                """
                INSERT INTO client_comparison_preferences (
                    client_id, competitors_json, period_key, custom_start, custom_end, updated_at,
                    weekly_enabled, weekly_weekday, weekly_time, weekly_note, weekly_responsible
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(client_id) DO UPDATE SET
                    competitors_json = excluded.competitors_json,
                    period_key = excluded.period_key,
                    custom_start = excluded.custom_start,
                    custom_end = excluded.custom_end,
                    updated_at = excluded.updated_at,
                    weekly_enabled = excluded.weekly_enabled,
                    weekly_weekday = excluded.weekly_weekday,
                    weekly_time = excluded.weekly_time,
                    weekly_note = excluded.weekly_note,
                    weekly_responsible = excluded.weekly_responsible
                """,
                (
                    live_client,
                    str(row.get("competitors_json") or "[]"),
                    str(row.get("period_key") or "3m"),
                    row.get("custom_start"),
                    row.get("custom_end"),
                    str(row.get("updated_at") or now),
                    int(row.get("weekly_enabled") or 0),
                    int(row.get("weekly_weekday") or 0),
                    str(row.get("weekly_time") or "09:00"),
                    str(row.get("weekly_note") or ""),
                    str(row.get("weekly_responsible") or ""),
                ),
            )
            stats["comparison_preferences_upserted"] += 1

    # Competitor crawl status metadata (optional in older packages)
    if data.get("client_crawl_accounts"):
        from maaike.account_crawl import ensure_crawl_tables

        ensure_crawl_tables(conn)
        stats["crawl_accounts_upserted"] = 0
        for row in data.get("client_crawl_accounts") or []:
            live_client = pkg_client_to_live.get(int(row["client_id"]))
            if live_client is None:
                continue
            uname = str(row.get("username") or "").strip().lower()
            if not uname:
                continue
            conn.execute(
                """
                INSERT INTO client_crawl_accounts (
                    client_id, username, ig_account_id, display_name, followers_count,
                    linked_at, last_crawled_at, last_success_at, last_crawl_status,
                    last_crawl_detail, last_crawl_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(client_id, username) DO UPDATE SET
                    ig_account_id = excluded.ig_account_id,
                    display_name = excluded.display_name,
                    followers_count = excluded.followers_count,
                    linked_at = excluded.linked_at,
                    last_crawled_at = excluded.last_crawled_at,
                    last_success_at = excluded.last_success_at,
                    last_crawl_status = excluded.last_crawl_status,
                    last_crawl_detail = excluded.last_crawl_detail,
                    last_crawl_json = excluded.last_crawl_json
                """,
                (
                    live_client,
                    uname,
                    row.get("ig_account_id"),
                    row.get("display_name"),
                    row.get("followers_count"),
                    str(row.get("linked_at") or now),
                    row.get("last_crawled_at"),
                    row.get("last_success_at"),
                    row.get("last_crawl_status"),
                    row.get("last_crawl_detail"),
                    str(row.get("last_crawl_json") or "{}"),
                ),
            )
            stats["crawl_accounts_upserted"] += 1

    # Weekly Logs check preferences & completion state (optional in older packages)
    if data.get("client_logs_weekly_preferences"):
        from maaike.logs_weekly import ensure_logs_weekly_table

        ensure_logs_weekly_table(conn)
        stats["logs_weekly_preferences_upserted"] = 0
        for row in data.get("client_logs_weekly_preferences") or []:
            live_client = pkg_client_to_live.get(int(row["client_id"]))
            if live_client is None:
                continue
            conn.execute(
                """
                INSERT INTO client_logs_weekly_preferences (
                    client_id, weekly_enabled, weekly_weekday, weekly_time, weekly_note,
                    responsible_name, last_completed_at, last_completed_by,
                    last_completed_window_from, last_completed_window_to, last_completed_count,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(client_id) DO UPDATE SET
                    weekly_enabled = excluded.weekly_enabled,
                    weekly_weekday = excluded.weekly_weekday,
                    weekly_time = excluded.weekly_time,
                    weekly_note = excluded.weekly_note,
                    responsible_name = excluded.responsible_name,
                    last_completed_at = excluded.last_completed_at,
                    last_completed_by = excluded.last_completed_by,
                    last_completed_window_from = excluded.last_completed_window_from,
                    last_completed_window_to = excluded.last_completed_window_to,
                    last_completed_count = excluded.last_completed_count,
                    updated_at = excluded.updated_at
                """,
                (
                    live_client,
                    int(row.get("weekly_enabled") or 0),
                    int(row.get("weekly_weekday") or 0),
                    str(row.get("weekly_time") or "09:00"),
                    str(row.get("weekly_note") or ""),
                    str(row.get("responsible_name") or ""),
                    row.get("last_completed_at"),
                    str(row.get("last_completed_by") or ""),
                    str(row.get("last_completed_window_from") or ""),
                    str(row.get("last_completed_window_to") or ""),
                    int(row["last_completed_count"]) if row.get("last_completed_count") is not None else None,
                    str(row.get("updated_at") or now),
                ),
            )
            stats["logs_weekly_preferences_upserted"] += 1

    # Stored post analyses / Claude feedback (no secrets)
    if data.get("post_ai_analyses"):
        from maaike.claude_analysis import ensure_analysis_tables

        ensure_analysis_tables(conn)
        for row in data.get("post_ai_analyses") or []:
            live_client = pkg_client_to_live.get(int(row["client_id"]))
            live_post = pkg_post_to_live.get(int(row["post_id"])) if row.get("post_id") is not None else None
            if live_client is None or live_post is None:
                continue
            conn.execute(
                """
                INSERT INTO post_ai_analyses (
                    client_id, post_id, provider, model, prompt_version, status,
                    started_at, finished_at, insight_text, action_text, rating_text,
                    raw_response_json, usage_json, input_snapshot_json, error_text,
                    actual_cost_usd, cost_known
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    live_client,
                    live_post,
                    str(row.get("provider") or ""),
                    str(row.get("model") or ""),
                    str(row.get("prompt_version") or ""),
                    str(row.get("status") or ""),
                    str(row.get("started_at") or now),
                    row.get("finished_at"),
                    str(row.get("insight_text") or ""),
                    str(row.get("action_text") or ""),
                    str(row.get("rating_text") or ""),
                    str(row.get("raw_response_json") or "{}"),
                    str(row.get("usage_json") or "{}"),
                    str(row.get("input_snapshot_json") or "{}"),
                    str(row.get("error_text") or ""),
                    row.get("actual_cost_usd"),
                    1 if row.get("cost_known") else 0,
                ),
            )
            stats["post_ai_analyses_added"] += 1

    return {"ok": True, "stats": stats, "overwrite": overwrite}
