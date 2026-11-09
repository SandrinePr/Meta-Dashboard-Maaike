"""Feedback, Logs adopt, uploads and full-duration video frame sampling (no paid AI)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from maaike.ai_trial import apply_mock_ai_result, get_trial, prepare_redrock_trial
from maaike.ai_trial_feedback import adopt_to_logs, logs_adopt_preview, save_feedback
from maaike.ai_trial_media import sample_video_timestamps
from maaike.db import initialize_database, transaction
from maaike.post_media_upload import list_post_media, reorder_post_media, save_uploaded_files


def _seed_trial_posts(conn, client_id: int) -> None:
    now = datetime.now(tz=timezone.utc).isoformat()
    for post_id, kind, media in (
        (31, "image", "https://cdn.example/a.jpg"),
        (16, "carousel_album", "https://cdn.example/1.jpg https://cdn.example/2.jpg"),
        (8, "reel", "https://cdn.example/v.mp4"),
    ):
        conn.execute(
            """
            INSERT OR REPLACE INTO posts (
                id, client_id, platform, external_id, published_at, content_kind,
                permalink, caption, media_urls, views, likes, comments, shares, saves, clicks, reach
            ) VALUES (?, ?, 'instagram', ?, ?, ?, ?, 'caption', ?, 10, 1, 0, 0, 0, 0, 5)
            """,
            (post_id, client_id, f"ext-{post_id}", now, kind, f"https://ig/{post_id}", media),
        )
    conn.execute(
        """
        INSERT OR REPLACE INTO post_assessments (
            id, post_id, source, source_label, rating_text, insight_text, action_text, imported_at
        ) VALUES (9001, 31, 'excel_imported', 'Overgenomen uit Excel', 'Slecht', 'geheim insight', 'actie', ?)
        """,
        (now,),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO content_formats (id, client_id, name, explanation, created_at, updated_at)
        VALUES (501, ?, 'C05', 'BTS carrousel', ?, ?)
        """,
        (client_id, now, now),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO content_pillars (id, client_id, name, explanation, created_at, updated_at)
        VALUES (601, ?, 'BTS', 'Behind the scenes', ?, ?)
        """,
        (client_id, now, now),
    )


def test_sample_timestamps_span_full_duration():
    stamps = sample_video_timestamps(40.0, max_frames=12)
    assert 0.0 in stamps
    assert any(t <= 3.0 for t in stamps)
    assert max(stamps) > 3.0
    assert len(stamps) <= 12


def test_feedback_verdict_adopt_upload_isolation(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "fb.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db))
    initialize_database()
    with transaction() as conn:
        client_id = int(conn.execute("SELECT id FROM clients WHERE name = 'Red Rock'").fetchone()[0])
        other = conn.execute(
            "INSERT INTO clients (name, created_at, updated_at, meta_status) VALUES ('Other', ?, ?, 'not_connected')",
            (datetime.now(tz=timezone.utc).isoformat(), datetime.now(tz=timezone.utc).isoformat()),
        ).lastrowid
        _seed_trial_posts(conn, client_id)
        prepare_redrock_trial(conn, client_id, download_media=False)
        apply_mock_ai_result(
            conn,
            client_id,
            31,
            {
                "observations": [{"evidence_ref": "image", "fact": "mock"}],
                "proposed_format_code": "Geen passend bestaand format",
                "format_rationale": "geen image-code",
                "format_uncertainty": "hoog",
                "proposed_pillar": "Strategie & Expertise",
                "proposed_hook": "mock hook",
                "ai_insight": "mock insight",
                "ai_action": "mock action",
            },
        )
        trial = get_trial(conn, client_id)["trial"]
        post = next(p for p in trial["posts"] if p["post_id"] == 31)
        assert "niet menselijk beoordeeld" in post["joint_verdict"].lower()
        key1 = post["execution_key"]

        # Without human feedback, confirm is rejected.
        try:
            save_feedback(conn, client_id, 31, {"confirm_final_verdict": True, "final_verdict": "x"})
            raised = False
        except ValueError:
            raised = True
        assert raised

        out = save_feedback(
            conn,
            client_id,
            31,
            {
                "usability": "partial",
                "notes": "deels ok",
                "corrected_format": "C05",
                "corrected_pillar": "BTS",
                "corrected_hook": "nieuwe hook",
                "final_verdict": "AI deels bruikbaar; format handmatig C05.",
            },
        )
        post = next(p for p in out["trial"]["posts"] if p["post_id"] == 31)
        assert post["human_feedback_record"]["usability"] == "partial"
        assert post["execution_key"] == key1

        confirmed = save_feedback(
            conn,
            client_id,
            31,
            {
                "usability": "partial",
                "notes": "deels ok",
                "corrected_format": "C05",
                "corrected_pillar": "BTS",
                "corrected_hook": "nieuwe hook",
                "final_verdict": "AI deels bruikbaar; format handmatig C05.",
                "reviewer_name": "QA Controle Tester",
                "confirm_final_verdict": True,
            },
        )
        post = next(p for p in confirmed["trial"]["posts"] if p["post_id"] == 31)
        assert post["human_feedback_record"]["final_verdict_confirmed"] is True
        assert post["human_feedback_record"]["is_approved"] is True
        assert post["human_feedback_record"]["review_status"] == "approved"
        assert post["human_feedback_record"]["reviewer_name"] == "QA Controle Tester"

        preview = logs_adopt_preview(conn, client_id, 31)
        assert preview["excel_unchanged"]["insight_text"] == "geheim insight"
        assert any(f["field"] == "contentformat" and f["proposed"] == "C05" for f in preview["fields"])

        adopted = adopt_to_logs(conn, client_id, 31, {"fields": ["contentformat", "hook"]})
        assert adopted["excel_untouched"] is True
        editorial = conn.execute(
            "SELECT f.name AS format_name, e.hook FROM post_editorial e "
            "JOIN content_formats f ON f.id = e.format_id WHERE e.post_id = 31"
        ).fetchone()
        assert editorial["format_name"] == "C05"
        assert editorial["hook"] == "nieuwe hook"
        excel = conn.execute(
            "SELECT insight_text FROM post_assessments WHERE post_id = 31"
        ).fetchone()
        assert excel["insight_text"] == "geheim insight"
        rev = conn.execute(
            "SELECT COUNT(*) n FROM post_editorial_revisions WHERE post_id = 31"
        ).fetchone()["n"]
        assert rev >= 2

        # Upload without Meta
        tiny = b"\xff\xd8\xff\xd9" + b"0" * 100
        saved = save_uploaded_files(
            conn,
            client_id,
            31,
            [{"filename": "a.jpg", "content": tiny, "content_type": "image/jpeg"}],
        )
        assert len(saved["saved"]) == 1
        assets = list_post_media(conn, client_id, 31)
        assert len(assets) == 1
        # second file + reorder
        save_uploaded_files(
            conn,
            client_id,
            31,
            [{"filename": "b.jpg", "content": tiny, "content_type": "image/jpeg"}],
        )
        assets = list_post_media(conn, client_id, 31)
        ids = [a["id"] for a in assets]
        reordered = reorder_post_media(conn, client_id, 31, list(reversed(ids)))
        assert [a["id"] for a in reordered] == list(reversed(ids))

        # Client isolation
        assert get_trial(conn, other)["trial"] is None
        try:
            save_uploaded_files(
                conn,
                other,
                31,
                [{"filename": "x.jpg", "content": tiny, "content_type": "image/jpeg"}],
            )
            iso = False
        except ValueError:
            iso = True
        assert iso
