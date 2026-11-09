"""Full local QA against a DB copy. No paid Meta/Claude calls. Mutates only QA copy + QA client."""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

QA_COPY = ROOT / "data" / "maaike_redrock_qa_copy.db"
os.environ["MAAIKE_DATABASE_PATH"] = str(QA_COPY)

from maaike.activity_log import list_activity_events  # noqa: E402
from maaike.ai_status import public_ai_status  # noqa: E402
from maaike.claude_analysis import probe_claude_connection  # noqa: E402
from maaike.data_transfer import (  # noqa: E402
    apply_import,
    export_package,
    export_package_json_bytes,
    export_posts_csv,
    preview_import,
    validate_package,
)
from maaike.db import initialize_database, transaction  # noqa: E402
from maaike.filter_posts import filter_search_payload, sync_totals  # noqa: E402
from maaike.rating import get_rating_settings, rate_post, save_rating_settings  # noqa: E402
from maaike.reports import get_report, inspect_client_report_data, prepare_client_report  # noqa: E402
from maaike.repository import (  # noqa: E402
    add_format,
    add_hook,
    add_pillar,
    list_formats,
    list_hooks,
    list_pillars,
    list_posts,
    update_format,
)

RESULTS: list[dict] = []


def record(part: str, status: str, checked: str, leftover: str = "") -> None:
    RESULTS.append(
        {"onderdeel": part, "status": status, "gecontroleerd": checked, "restant": leftover}
    )
    print(f"[{status}] {part}: {checked}" + (f" | {leftover}" if leftover else ""))


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def ensure_qa_client(conn) -> int:
    row = conn.execute("SELECT id FROM clients WHERE name = 'QA Controle'").fetchone()
    if row:
        return int(row["id"])
    return int(
        conn.execute(
            "INSERT INTO clients (name, created_at, updated_at, meta_status) VALUES ('QA Controle', ?, ?, 'not_connected')",
            (now_iso(), now_iso()),
        ).lastrowid
    )


def main() -> int:
    if not QA_COPY.exists():
        print("QA copy missing", QA_COPY)
        return 1
    initialize_database(QA_COPY)

    with transaction() as conn:
        rr_posts = conn.execute("SELECT COUNT(*) n FROM posts WHERE client_id=1").fetchone()["n"]
        links = conn.execute("SELECT COUNT(*) n FROM post_import_links").fetchone()["n"]
        reports = conn.execute("SELECT COUNT(*) n FROM client_reports WHERE client_id=1").fetchone()["n"]
        record(
            "Back-up/baseline",
            "geslaagd",
            f"QA-copy; Red Rock posts={rr_posts}, import_links={links}, reports={reports}",
        )
        record(
            "Excel-importkoppelingen",
            "geslaagd" if links == 91 else "geblokkeerd",
            f"{links} post_import_links op QA-copy (live backup bewaard apart)",
        )

        qa_id = ensure_qa_client(conn)
        other = 2

        # Isolation
        try:
            insp_rr = inspect_client_report_data(conn, 1, period_year=2026, period_month=9)
            rr_fmt = {f.name for f in list_formats(conn, 1)}
            add_format(conn, qa_id, f"QA-ISO-{datetime.now().strftime('%H%M%S')}", "isolatie")
            assert {f.name for f in list_formats(conn, 1)} == rr_fmt
            if reports:
                rid = conn.execute(
                    "SELECT id FROM client_reports WHERE client_id=1 ORDER BY id DESC LIMIT 1"
                ).fetchone()["id"]
                try:
                    get_report(conn, other, rid)
                    raise AssertionError("cross-client get_report had moeten falen")
                except ValueError:
                    pass
            record(
                "Klantisolatie",
                "geslaagd",
                f"QA-legenda raakt Red Rock niet; report-isolatie ok; RR inspect posts={insp_rr['metrics']['post_count']}",
            )
        except Exception as exc:
            record("Klantisolatie", "geblokkeerd", "Isolatietest mislukt", str(exc))
            traceback.print_exc()

        # Feeds
        try:
            feed = filter_search_payload(
                conn,
                1,
                query="",
                platforms={"instagram", "facebook"},
                match_types={"caption"},
                date_from=date(2026, 9, 1),
                date_to=date(2026, 9, 30),
            )
            assert feed["total"] == 13
            platforms = {r.get("platform") for r in feed["results"]}
            assert platforms <= {"instagram", "facebook"}
            totals = sync_totals(conn, 1)
            assert totals["instagram_posts"] >= 1
            record(
                "My Social Feeds (API)",
                "geslaagd",
                f"Sep2026 total={feed['total']} alleen IG/FB; sync_totals ig={totals['instagram_posts']} fb={totals['facebook_posts']}",
            )
        except Exception as exc:
            record("My Social Feeds (API)", "geblokkeerd", "Filter mislukt", str(exc))
            traceback.print_exc()

        # Legend CRUD + couple
        try:
            stamp = datetime.now().strftime("%H%M%S")
            fid = add_format(conn, qa_id, f"QA-CRUD-F-{stamp}", "voor")
            update_format(conn, qa_id, fid, f"QA-CRUD-F-{stamp}", "na-update")
            assert next(f.explanation for f in list_formats(conn, qa_id) if f.item_id == fid) == "na-update"
            add_pillar(conn, qa_id, f"QA-CRUD-P-{stamp}", "p")
            add_hook(conn, qa_id, f"QA-CRUD-H-{stamp}", "h")
            qa_post = conn.execute("SELECT id FROM posts WHERE client_id=? LIMIT 1", (qa_id,)).fetchone()
            if qa_post is None:
                conn.execute(
                    """
                    INSERT INTO posts (
                        client_id, platform, external_id, published_at, content_kind,
                        permalink, caption, media_urls, views, likes, comments, shares, saves, clicks, reach
                    ) VALUES (?, 'instagram', ?, '2026-09-10T12:00:00+00:00', 'image',
                              'https://example.com/qa', 'QA caption', '', 10, 1, 0, 0, 0, 0, 5)
                    """,
                    (qa_id, f"qa-temp-{stamp}"),
                )
                qa_post_id = int(
                    conn.execute(
                        "SELECT id FROM posts WHERE client_id=? AND external_id=?",
                        (qa_id, f"qa-temp-{stamp}"),
                    ).fetchone()["id"]
                )
            else:
                qa_post_id = int(qa_post["id"])
            fmt = next(f for f in list_formats(conn, qa_id) if f.item_id == fid)
            pil = next(p for p in list_pillars(conn, qa_id) if p.name.startswith("QA-CRUD-P-"))
            existing = conn.execute(
                "SELECT post_id FROM post_editorial WHERE post_id=?", (qa_post_id,)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE post_editorial SET format_id=?, pillar_id=?, hook=?, updated_at=? WHERE post_id=?",
                    (fmt.item_id, pil.item_id, f"QA-CRUD-H-{stamp}", now_iso(), qa_post_id),
                )
            else:
                conn.execute(
                    "INSERT INTO post_editorial (post_id, format_id, pillar_id, hook, updated_at) VALUES (?,?,?,?,?)",
                    (qa_post_id, fmt.item_id, pil.item_id, f"QA-CRUD-H-{stamp}", now_iso()),
                )
            ed = dict(
                conn.execute(
                    "SELECT format_id, pillar_id, hook FROM post_editorial WHERE post_id=?",
                    (qa_post_id,),
                ).fetchone()
            )
            assert ed["format_id"] == fmt.item_id
            record(
                "Legenda + koppeling",
                "geslaagd",
                f"CRUD+update+koppeling post {qa_post_id} op QA-client {qa_id}",
            )
        except Exception as exc:
            record("Legenda + koppeling", "geblokkeerd", "Legend CRUD mislukt", str(exc))
            traceback.print_exc()

        # Rating
        try:
            save_rating_settings(
                conn,
                qa_id,
                {
                    "active": False,
                    "profile_name": "Voorlopig — QA test",
                    "is_provisional": True,
                    "formula_key": "voorlopig_engagement_per_bereik",
                    "weights": {"likes": 1.0, "comments": 2.0, "shares": 2.0, "saves": 3.0},
                    "denominator_metric": "reach",
                    "good_min": 5.0,
                    "average_min": 2.0,
                },
            )
            assert not get_rating_settings(conn, qa_id)["active"]
            save_rating_settings(
                conn,
                qa_id,
                {
                    "active": True,
                    "profile_name": "Voorlopig — QA test",
                    "is_provisional": True,
                    "formula_key": "voorlopig_engagement_per_bereik",
                    "weights": {"likes": 1.0, "comments": 2.0, "shares": 2.0, "saves": 3.0},
                    "denominator_metric": "reach",
                    "good_min": 5.0,
                    "average_min": 2.0,
                },
            )
            on = get_rating_settings(conn, qa_id)
            assert on["active"]
            posts = list_posts(conn, qa_id)
            if posts:
                rated = rate_post(posts[0], on)
                assert "label" in rated or "rating" in rated or "status" in rated or "reason" in rated
            save_rating_settings(conn, qa_id, {"active": False})
            rr = get_rating_settings(conn, 1)
            record(
                "Beoordeling",
                "geslaagd",
                f"QA uit→aan→rate→uit; Red Rock active={bool(rr.get('active'))}",
            )
        except Exception as exc:
            record("Beoordeling", "geblokkeerd", "Rating mislukt", str(exc))
            traceback.print_exc()

        # Reports + snapshot immutability
        try:
            insp = inspect_client_report_data(conn, 1, period_year=2026, period_month=9)
            assert insp["metrics"]["post_count"] == 14
            assert insp["period"]["previous_start"] == "2026-08-02"
            assert insp["ai_analysis_executed"] is False
            prepared = prepare_client_report(
                conn,
                1,
                period_year=2026,
                period_month=9,
                allow_partial_without_trend=True,
                max_budget_usd=0.01,
            )
            rid = prepared["report"]["id"]
            snap1 = json.dumps(prepared["report"]["input_snapshot"], sort_keys=True)
            conn.execute(
                """
                UPDATE post_editorial SET format_id=NULL
                WHERE post_id = (
                  SELECT e.post_id FROM post_editorial e
                  JOIN posts p ON p.id=e.post_id
                  WHERE p.client_id=1 AND p.published_at LIKE '2026-09%' AND e.format_id IS NOT NULL
                  LIMIT 1
                )
                """
            )
            again = get_report(conn, 1, rid)
            assert json.dumps(again["report"]["input_snapshot"], sort_keys=True) == snap1
            record(
                "Reports",
                "geslaagd",
                f"14 posts; vergelijk 2–31 aug; prepare id={rid}; snapshot stabiel na mutatie; geen AI",
            )
        except Exception as exc:
            record("Reports", "geblokkeerd", "Reports mislukt", str(exc))
            traceback.print_exc()

        # Export/import
        try:
            pkg = export_package(conn, client_id=1)
            raw = export_package_json_bytes(conn, client_id=1).decode("utf-8", errors="replace")
            validate_package(pkg)
            for secret_key in ("META_ACCESS_TOKEN", "CLAUDE_API_KEY", "AI_API_KEY", "ANTHROPIC_API_KEY"):
                val = os.getenv(secret_key) or ""
                if len(val) > 8:
                    assert val not in raw
            assert pkg.get("secrets_excluded") is not False
            csv_bytes = export_posts_csv(conn, 1)
            assert len(csv_bytes) > 10
            try:
                validate_package({"format": "nope"})
                invalid_ok = False
            except ValueError:
                invalid_ok = True
            preview = preview_import(conn, pkg)
            assert "summary" in preview
            # duplicate import without overwrite on same package into copy
            stats1 = apply_import(conn, pkg, overwrite=False)
            stats2 = apply_import(conn, pkg, overwrite=False)
            links_after = conn.execute("SELECT COUNT(*) n FROM post_import_links").fetchone()["n"]
            record(
                "Export/Import",
                "geslaagd",
                f"JSON secrets_excluded; CSV ok; invalid geweigerd={invalid_ok}; "
                f"import1={stats1.get('posts_added')}/{stats1.get('posts_updated')} "
                f"import2={stats2.get('posts_added')}/{stats2.get('posts_updated')}; links={links_after}",
            )
        except Exception as exc:
            record("Export/Import", "geblokkeerd", "Data transfer mislukt", str(exc))
            traceback.print_exc()

        # Logs/activity
        try:
            act = list_activity_events(conn, client_id=1, limit=50)
            assert "events" in act or isinstance(act, dict)
            n = len(act.get("events") or act.get("items") or [])
            record("Logs/activity (API)", "geslaagd", f"Activity events geladen n≈{n}")
        except Exception as exc:
            record("Logs/activity (API)", "geblokkeerd", "Activity mislukt", str(exc))
            traceback.print_exc()

        # Medewerkercontrole route on QA Controle (mock AI only)
        try:
            from maaike.report_review import save_report_review
            from maaike.reports import apply_mock_report, prepare_client_report

            prep = prepare_client_report(
                conn,
                qa_id,
                period_year=2026,
                period_month=9,
                allow_partial_without_trend=True,
                max_budget_usd=0.01,
            )
            rid = prep["report"]["id"]
            assert prep["review"]["can_review"] is False
            blocked = False
            try:
                save_report_review(
                    conn,
                    qa_id,
                    rid,
                    {"approve": True, "reviewer_name": "QA", "final_version_text": "x"},
                )
            except ValueError:
                blocked = True
            assert blocked
            mocked = apply_mock_report(conn, qa_id, rid)
            key1 = mocked["review"]["execution_key"]
            items = mocked["review"]["item_feedback"]
            for item in items:
                if item["key"] == "six_answers.beter":
                    item["decision"] = "accept"
                elif item["key"] == "addition.staff":
                    item["decision"] = "add"
                    item["human_text"] = "QA Controle TEST — aanvulling zonder Claude."
            draft = save_report_review(
                conn,
                qa_id,
                rid,
                {
                    "reviewer_name": "QA Controle Medewerker",
                    "item_feedback": items,
                    "compose_final_from_items": True,
                },
            )
            approved = save_report_review(
                conn,
                qa_id,
                rid,
                {
                    "reviewer_name": "QA Controle Medewerker",
                    "item_feedback": items,
                    "final_version_text": draft["review"]["final_version_text"],
                    "approve": True,
                },
            )
            assert approved["review"]["is_approved"] is True
            reloaded = get_report(conn, qa_id, rid)
            assert reloaded["review"]["execution_key"] == key1
            assert "QA Controle TEST" in reloaded["review"]["final_version_text"]
            # New version must re-review
            prep2 = prepare_client_report(
                conn,
                qa_id,
                period_year=2026,
                period_month=9,
                allow_partial_without_trend=True,
                max_budget_usd=0.01,
            )
            mocked2 = apply_mock_report(conn, qa_id, prep2["report"]["id"])
            assert mocked2["review"]["is_approved"] is False
            assert mocked2["review"]["execution_key"] != key1
            record(
                "Medewerkercontrole (QA Controle)",
                "geslaagd",
                f"prepare geblokkeerd→mock→eindversie→Goedgekeurd; reload ok; nieuwe versie opnieuw te controleren; key={key1[:48]}…",
                "Geen betaalde AI; gemarkeerde QA Controle-testinhoud",
            )
        except Exception as exc:
            record("Medewerkercontrole (QA Controle)", "geblokkeerd", "Controle-route mislukt", str(exc))
            traceback.print_exc()

        # Meta/Claude status only
        try:
            ai = public_ai_status()
            claude = probe_claude_connection()
            client = conn.execute(
                "SELECT meta_status, meta_status_detail FROM clients WHERE id=1"
            ).fetchone()
            record(
                "Meta/Claude status (geen betaalde call)",
                "geslaagd",
                f"meta={client['meta_status']}; ai_configured={ai.get('configured')}; "
                f"claude_ok={claude.get('ok')}; detail={(str(claude.get('detail') or claude.get('reason') or claude.get('error') or ''))[:140]}",
                "Geen echte crawl of Claude-analyse uitgevoerd",
            )
        except Exception as exc:
            record("Meta/Claude status", "geblokkeerd", "Probe mislukt", str(exc))
            traceback.print_exc()

        links_end = conn.execute("SELECT COUNT(*) n FROM post_import_links").fetchone()["n"]
        record(
            "Behoud importkoppelingen (QA-copy)",
            "geslaagd" if links_end >= links else "geblokkeerd",
            f"Voor={links} na={links_end}",
        )

    out = ROOT / "data" / "backups" / f"qa_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", out)
    return 1 if any(r["status"] == "geblokkeerd" for r in RESULTS) else 0


if __name__ == "__main__":
    raise SystemExit(main())
