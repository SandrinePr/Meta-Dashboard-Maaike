"""Versioned JSON backup export/import. Never includes API keys or Meta tokens."""

from __future__ import annotations

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
SECRET_TABLES = frozenset({"client_meta_secrets"})
SECRET_CLIENT_FIELDS = frozenset(
    {
        "user_access_token",
        "page_access_token",
        "access_token",
        "api_key",
        "ai_api_key",
        "password",
        "secret",
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
    backup_dir = project_root() / "data" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    dest = backup_dir / f"maaike_redrock-before-import-{stamp}.db"
    shutil.copy2(src, dest)
    return dest


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
            "targets": len(targets),
            "posts": len(posts),
            "hooks_editorial": len(hooks),
            "import_links": len(import_links),
            "assessments": len(assessments),
            "reports": len(reports),
            "report_sources": len(report_sources),
            "activity_events": len(activity),
            "logs_rows": len(logs_rows),
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
        "activity_events": activity,
        "logs_export_rows": logs_rows,
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
    if "client_meta_secrets" in data:
        raise ValueError("client_meta_secrets mag niet in een importpakket zitten.")
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
            "Zonder overwrite=true worden bestaande klanten/formats/posts niet overschreven; "
            "alleen ontbrekende records worden toegevoegd. Relaties lopen via klantnaam en "
            "(platform, external_id)."
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
        "targets_added": 0,
        "reports_added": 0,
        "activity_added": 0,
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
            cols = [
                c
                for c in report.keys()
                if c
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

    return {"ok": True, "stats": stats, "overwrite": overwrite}
