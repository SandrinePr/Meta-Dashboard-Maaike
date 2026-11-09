"""JSON API for Maaike's dashboard.

Start from the project root:

    .venv\\Scripts\\python.exe -m uvicorn maaike_web.app:app --host 127.0.0.1 --port 8000 --no-access-log

The access log stays off so an OAuth code in the callback URL is not written to the log.
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from urllib.parse import quote

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict

from maaike.ai_status import public_ai_status
from maaike.config import MaaikeConfigError, database_path
from maaike.db import initialize_database, transaction
from maaike.comparison_service import (
    add_competitor as comparison_add_competitor,
    comparison_state,
    remove_competitor as comparison_remove_competitor,
    save_period as comparison_save_period,
)
from maaike.filter_posts import filter_search_payload, sync_totals
from maaike.feed import (
    FEED_PAGE_SIZE,
    feed_payload,
    overview_payload,
    post_detail,
)
from maaike.original_performance import performance_month_payload
from maaike.meta_connect import (
    LOGIN_SCOPES,
    MetaConnectError,
    build_login_url,
    collect_pages,
    confirm_selected_page,
    readiness,
    recheck_stored_link,
    record_failed_attempt,
)
from maaike.post_fetch import fetch_client_posts
from maaike.presentation import (
    COLUMN_LABELS,
    OVERVIEW_COLUMNS,
    RATING_PENDING,
    format_sync_moment,
    overview_record,
)
from maaike.repository import (
    UNSET_LABEL,
    Client,
    ClientInputError,
    LegendInputError,
    add_client,
    add_format,
    add_hook,
    add_pillar,
    connection_label,
    disconnect_meta_link,
    get_client,
    is_verified_link,
    latest_sync_at,
    list_clients,
    list_formats,
    list_hooks,
    list_pillars,
    list_posts,
    rename_client,
    save_editorial,
    update_format,
    update_hook,
    update_pillar,
)
from maaike_web.session import (
    COOKIE_NAME,
    arm_login,
    clear_pending,
    cookie_value,
    ensure_session,
    pages_public,
    pending_for,
    popup_for_state,
    read_session_id,
    selectable_page,
    store_pending,
    take_callback,
    take_popup_flag,
)
from maaike_web.settings import WebSettings, load_settings

_COOKIE_MAX_AGE = 8 * 60 * 60


class NameBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str


class LegendBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    explanation: str = ""


class EditorialBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    format_id: int | None = None
    pillar_id: int | None = None
    hook: str = ""


class ConfirmBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    page_index: int


class StartMetaBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    popup: bool = False


def create_app() -> FastAPI:
    settings = load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            initialize_database()
        except MaaikeConfigError as exc:
            raise RuntimeError(str(exc)) from exc
        try:
            from maaike.competitor_scheduler import start_competitor_scheduler

            start_competitor_scheduler()
        except Exception:
            # Dashboard must still boot if the scheduler fails to start.
            pass
        yield

    app = FastAPI(title="Maaike", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        if isinstance(exc, HTTPException):
            detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
            return JSONResponse(status_code=exc.status_code, content={"detail": detail})
        return JSONResponse(status_code=500, content={"detail": "Something went wrong."})

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/ai-status")
    def ai_status() -> dict:
        return public_ai_status()

    @app.get("/api/clients/{client_id}/ai-trial")
    def read_ai_trial(client_id: int) -> dict:
        from maaike.ai_trial import get_trial

        with transaction() as conn:
            _require_client(conn, client_id)
            return get_trial(conn, client_id)

    @app.post("/api/clients/{client_id}/ai-trial/prepare")
    def prepare_ai_trial(client_id: int) -> dict:
        from maaike.ai_trial import prepare_redrock_trial

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return prepare_redrock_trial(conn, client_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/clients/{client_id}/ai-trial/posts/{post_id}/feedback")
    def ai_trial_feedback(client_id: int, post_id: int, body: dict) -> dict:
        from maaike.ai_trial_feedback import save_feedback

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return save_feedback(conn, client_id, post_id, body or {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/clients/{client_id}/ai-trial/posts/{post_id}/logs-preview")
    def ai_trial_logs_preview(client_id: int, post_id: int) -> dict:
        from maaike.ai_trial_feedback import logs_adopt_preview

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return logs_adopt_preview(conn, client_id, post_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/clients/{client_id}/ai-trial/posts/{post_id}/adopt-logs")
    def ai_trial_adopt_logs(client_id: int, post_id: int, body: dict) -> dict:
        from maaike.ai_trial_feedback import adopt_to_logs

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return adopt_to_logs(conn, client_id, post_id, body or {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/clients/{client_id}/posts/{post_id}/media")
    def list_post_media_assets(client_id: int, post_id: int) -> dict:
        from maaike.post_media_upload import list_post_media

        with transaction() as conn:
            _require_client(conn, client_id)
            owned = conn.execute(
                "SELECT id FROM posts WHERE id = ? AND client_id = ?",
                (post_id, client_id),
            ).fetchone()
            if owned is None:
                raise HTTPException(status_code=404, detail="Post not found for this client.")
            return {"post_id": post_id, "assets": list_post_media(conn, client_id, post_id)}

    @app.post("/api/clients/{client_id}/posts/{post_id}/media")
    async def upload_post_media(
        client_id: int,
        post_id: int,
        files: list[UploadFile] = File(default=[]),
        replace: str = "",
    ) -> dict:
        from maaike.post_media_upload import save_uploaded_files

        files_out: list[dict] = []
        for upload in files or []:
            filename = upload.filename or ""
            if not filename:
                continue
            content = await upload.read()
            files_out.append(
                {
                    "filename": filename,
                    "content": content,
                    "content_type": upload.content_type or "",
                }
            )
        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return save_uploaded_files(
                    conn,
                    client_id,
                    post_id,
                    files_out,
                    replace=str(replace or "").lower() in {"1", "true", "yes"},
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/clients/{client_id}/posts/{post_id}/media/reorder")
    def reorder_post_media_assets(client_id: int, post_id: int, body: dict) -> dict:
        from maaike.post_media_upload import reorder_post_media

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                ordered = [int(x) for x in (body or {}).get("ordered_ids") or []]
                assets = reorder_post_media(conn, client_id, post_id, ordered)
                return {"post_id": post_id, "assets": assets}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/clients/{client_id}/ai-trial/posts/{post_id}/accept")
    def ai_trial_accept(client_id: int, post_id: int, body: dict) -> dict:
        from maaike.ai_trial import accept_ai_proposal

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return accept_ai_proposal(conn, client_id, post_id, body or {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/clients/{client_id}/ai-trial/guard-start")
    def ai_trial_guard_start(client_id: int) -> dict:
        """Mark trial running to block duplicate starts. Does not call a paid API."""
        from maaike.ai_trial import begin_paid_execution_guard

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return begin_paid_execution_guard(conn, client_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/clients/{client_id}/ai-trial/execute")
    def ai_trial_execute(client_id: int) -> dict:
        """Run the prepared trial (max 3 paid calls, USD 0.10). Not triggered by page load."""
        from maaike.ai_trial_execute import execute_prepared_trial

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return execute_prepared_trial(conn, client_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/clients/{client_id}/ai-trial/posts/{post_id}/mock")
    def ai_trial_mock(client_id: int, post_id: int, body: dict | None = None) -> dict:
        """Store a mock AI result for flow tests. Never calls a paid provider."""
        from maaike.ai_trial import apply_mock_ai_result

        payload = body or {}
        result = payload.get("result") or {
            "observations": [
                {
                    "evidence_ref": "caption/media",
                    "fact": "Mock observation — no real model output.",
                }
            ],
            "proposed_format_code": payload.get("proposed_format_code")
            or "Geen passend bestaand format",
            "format_rationale": payload.get("format_rationale")
            or "Mock: no paid analysis was run.",
            "format_uncertainty": "hoog",
            "proposed_pillar": payload.get("proposed_pillar") or "Niet vast te stellen",
            "proposed_hook": payload.get("proposed_hook") or "Niet vast te stellen",
            "ai_insight": payload.get("ai_insight")
            or "Mock insight: storage and UI test only.",
            "ai_action": payload.get("ai_action") or "Mock action: not production advice.",
            "hypotheses": [],
            "unassessable": ["No real model analysis in this mock."],
        }
        usage = payload.get("usage") or {
            "status": "mock_completed",
            "cost_known": False,
            "notes": "Mock; tokens unknown (not stored as 0).",
        }
        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return apply_mock_ai_result(conn, client_id, post_id, result, usage=usage)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/clients/{client_id}/reports")
    def list_client_reports(client_id: int, report_type: str | None = None) -> dict:
        from maaike.reports import list_reports

        with transaction() as conn:
            _require_client(conn, client_id)
            return list_reports(conn, client_id, report_type=report_type or None)

    @app.get("/api/clients/{client_id}/reports/{report_id}")
    def read_client_report(client_id: int, report_id: int) -> dict:
        from maaike.reports import get_report

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return get_report(conn, client_id, report_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/clients/{client_id}/reports/{report_id}/pdf")
    def download_client_report_pdf(client_id: int, report_id: int) -> Response:
        """Export saved client report as PDF. No AI call / no credits."""
        from maaike.client_report_pdf import render_client_report_pdf

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                pdf_bytes, presentation = render_client_report_pdf(conn, client_id, report_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        client_slug = re.sub(
            r"[^a-zA-Z0-9_-]+",
            "-",
            str(presentation.get("client_name") or f"client-{client_id}"),
        ).strip("-")[:40] or f"client-{client_id}"
        period = re.sub(r"[^0-9A-Za-z_-]+", "-", str(presentation.get("period_label") or "period"))[:32]
        filename = f"client-report-{client_slug}-{period}-v{presentation.get('version') or report_id}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Report-Id": str(report_id),
                "X-PDF-No-AI": "1",
            },
        )

    @app.post("/api/clients/{client_id}/reports/trend/prepare")
    def prepare_trend(client_id: int, body: dict | None = None) -> dict:
        from maaike.reports import prepare_trend_report

        payload = body or {}
        try:
            budget_raw = payload.get("max_budget_usd")
            budget = float(budget_raw) if budget_raw not in (None, "") else None
            with transaction() as conn:
                _require_client(conn, client_id)
                return prepare_trend_report(
                    conn,
                    client_id,
                    run_year=int(payload.get("run_year")),
                    run_month=int(payload.get("run_month")),
                    sources=payload.get("sources") or [],
                    research_mode=str(payload.get("research_mode") or "manual"),
                    max_budget_usd=budget,
                    title=payload.get("title"),
                )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/clients/{client_id}/reports/{report_id}/sources")
    def add_report_sources(client_id: int, report_id: int, body: dict | None = None) -> dict:
        from maaike.reports import add_trend_sources

        payload = body or {}
        fetch_raw = payload.get("fetch_content", True)
        if isinstance(fetch_raw, str):
            fetch_raw = fetch_raw.lower() not in {"0", "false", "no"}
        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return add_trend_sources(
                    conn,
                    client_id,
                    report_id,
                    payload.get("sources") or [],
                    fetch_content=bool(fetch_raw),
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/clients/{client_id}/reports/client/inspect")
    def inspect_client_report(
        client_id: int,
        period_year: int | None = None,
        period_month: int | None = None,
        start: str | None = None,
        end: str | None = None,
        compare_start: str | None = None,
        compare_end: str | None = None,
        linked_trend_report_id: int | None = None,
    ) -> dict:
        """Inspect client-report figures + prompt input. No AI, nothing persisted."""
        from maaike.reports import inspect_client_report_data

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return inspect_client_report_data(
                    conn,
                    client_id,
                    period_year=period_year,
                    period_month=period_month,
                    start=start,
                    end=end,
                    compare_start=compare_start,
                    compare_end=compare_end,
                    linked_trend_report_id=linked_trend_report_id,
                )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/clients/{client_id}/reports/client/prepare")
    def prepare_client(client_id: int, body: dict | None = None) -> dict:
        from maaike.reports import prepare_client_report

        payload = body or {}
        try:
            budget_raw = payload.get("max_budget_usd")
            budget = float(budget_raw) if budget_raw not in (None, "") else None
            with transaction() as conn:
                _require_client(conn, client_id)
                trend_id = payload.get("linked_trend_report_id")
                return prepare_client_report(
                    conn,
                    client_id,
                    period_year=int(payload.get("period_year")),
                    period_month=int(payload.get("period_month")),
                    linked_trend_report_id=int(trend_id) if trend_id not in (None, "") else None,
                    allow_partial_without_trend=bool(payload.get("allow_partial_without_trend")),
                    max_budget_usd=budget,
                    start=payload.get("start") or None,
                    end=payload.get("end") or None,
                    compare_start=payload.get("compare_start") or None,
                    compare_end=payload.get("compare_end") or None,
                    title=payload.get("title"),
                )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/clients/{client_id}/reports/{report_id}/title")
    def patch_report_title(client_id: int, report_id: int, body: dict | None = None) -> dict:
        from maaike.reports import update_report_title

        payload = body or {}
        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return update_report_title(
                    conn, client_id, report_id, str(payload.get("title") or "")
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/clients/{client_id}/reports/{report_id}/mock")
    def mock_client_report(client_id: int, report_id: int, body: dict | None = None) -> dict:
        """Mock generate only — never a paid AI/search call."""
        from maaike.report_execute import apply_execution_mock
        from maaike.reports import apply_mock_report

        payload = body or {}
        scenario = str(payload.get("scenario") or "").strip()
        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                if scenario:
                    return apply_execution_mock(
                        conn, client_id, report_id, scenario=scenario
                    )
                return apply_mock_report(conn, client_id, report_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/clients/{client_id}/reports/{report_id}/execution-preview")
    def report_execution_preview(client_id: int, report_id: int, max_budget_usd: float | None = None) -> dict:
        """Preview provider/model/budget/context — no paid call."""
        from maaike.report_execute import execution_preview

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return execution_preview(
                    conn, client_id, report_id, max_budget_usd=max_budget_usd
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/clients/{client_id}/reports/{report_id}/model-input-preview")
    def report_model_input_preview(client_id: int, report_id: int) -> dict:
        """Exact execute model input + per-section presence checklist. No AI call."""
        from maaike.report_execute import (
            build_execute_model_input,
            model_input_presence_checklist,
        )
        from maaike.reports import get_report

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                payload = get_report(conn, client_id, report_id)
                report = payload["report"]
                snap = report["input_snapshot"]
                model_input = build_execute_model_input(report, snap)
                return {
                    "report_id": report_id,
                    "client_id": client_id,
                    "paid_call": False,
                    "model_input": model_input,
                    "checklist": model_input_presence_checklist(model_input)
                    if report["report_type"] == "client"
                    else [],
                    "note": (
                        "Identiek aan de JSON die execute als gebruikersbericht meestuurt. "
                        "Geen betaalde AI-aanroep."
                    ),
                }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/clients/{client_id}/reports/{report_id}/execute")
    def execute_client_report(client_id: int, report_id: int, body: dict | None = None) -> dict:
        """Execute report. Default dry_run_paid=true blocks real paid calls in this step."""
        from maaike.report_execute import execute_report

        payload = body or {}
        dry_run = payload.get("dry_run_paid", True)
        if isinstance(dry_run, str):
            dry_run = dry_run.lower() not in {"0", "false", "no"}
        budget_raw = payload.get("max_budget_usd")
        try:
            budget = float(budget_raw) if budget_raw not in (None, "") else None
            with transaction() as conn:
                _require_client(conn, client_id)
                return execute_report(
                    conn,
                    client_id,
                    report_id,
                    max_budget_usd=budget,
                    dry_run_paid=bool(dry_run),
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/clients/{client_id}/reports/{report_id}/guard-start")
    def report_guard_start(client_id: int, report_id: int) -> dict:
        from maaike.reports import begin_report_execution_guard

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return begin_report_execution_guard(conn, client_id, report_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/clients/{client_id}/reports/{report_id}/review")
    def save_client_report_review(client_id: int, report_id: int, body: dict | None = None) -> dict:
        """Save human review / final version / explicit approval for one report execution."""
        from maaike.report_review import save_report_review

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return save_report_review(conn, client_id, report_id, body or {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/clients")
    def read_clients() -> dict:
        with transaction() as conn:
            clients = list_clients(conn)
        return {
            "database_name": database_path().name,
            "clients": [_client_out(client) for client in clients],
        }

    @app.post("/api/clients", status_code=201)
    def create_client(body: NameBody) -> dict:
        try:
            with transaction() as conn:
                client_id = add_client(conn, body.name)
                client = get_client(conn, client_id)
        except ClientInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if client is None:
            raise HTTPException(status_code=400, detail="The client could not be added.")
        return _client_out(client)

    @app.patch("/api/clients/{client_id}")
    def update_client(client_id: int, body: NameBody) -> dict:
        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                rename_client(conn, client_id, body.name)
                client = get_client(conn, client_id)
        except ClientInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if client is None:
            raise HTTPException(status_code=404, detail="This client is not in the list.")
        return _client_out(client)

    @app.get("/api/clients/{client_id}/legend")
    def read_legend(client_id: int) -> dict:
        with transaction() as conn:
            _require_client(conn, client_id)
            return _legend_out(conn, client_id)

    @app.post("/api/clients/{client_id}/formats", status_code=201)
    def create_format(client_id: int, body: LegendBody) -> dict:
        return _add_legend(client_id, "format", body)

    @app.patch("/api/clients/{client_id}/formats/{item_id}")
    def patch_format(client_id: int, item_id: int, body: LegendBody) -> dict:
        return _update_legend(client_id, "format", item_id, body)

    @app.post("/api/clients/{client_id}/pillars", status_code=201)
    def create_pillar(client_id: int, body: LegendBody) -> dict:
        return _add_legend(client_id, "pillar", body)

    @app.patch("/api/clients/{client_id}/pillars/{item_id}")
    def patch_pillar(client_id: int, item_id: int, body: LegendBody) -> dict:
        return _update_legend(client_id, "pillar", item_id, body)

    @app.post("/api/clients/{client_id}/hooks", status_code=201)
    def create_hook(client_id: int, body: LegendBody) -> dict:
        return _add_legend(client_id, "hook", body)

    @app.patch("/api/clients/{client_id}/hooks/{item_id}")
    def patch_hook(client_id: int, item_id: int, body: LegendBody) -> dict:
        return _update_legend(client_id, "hook", item_id, body)

    @app.get("/api/clients/{client_id}/overview")
    def read_overview(client_id: int) -> dict:
        with transaction() as conn:
            _require_client(conn, client_id)
            try:
                return overview_payload(conn, client_id)
            except ValueError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/clients/{client_id}/feed")
    def read_feed(
        client_id: int,
        q: str = "",
        platform: str = "",
        kind: str = "",
        date_from: str = "",
        date_to: str = "",
        sort: str = "published_desc",
        offset: int = 0,
        limit: int = FEED_PAGE_SIZE,
    ) -> dict:
        platforms = [part for part in platform.split(",") if part.strip()]
        kinds = [part for part in kind.split(",") if part.strip()]
        with transaction() as conn:
            _require_client(conn, client_id)
            try:
                return feed_payload(
                    conn,
                    client_id,
                    query=q,
                    platforms=platforms,
                    kinds=kinds,
                    date_from=date_from or None,
                    date_to=date_to or None,
                    sort=sort,
                    offset=offset,
                    limit=limit,
                )
            except ValueError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/clients/{client_id}/filter-posts")
    def read_filter_posts(
        client_id: int,
        q: str = "",
        platforms: str = "instagram,facebook",
        types: str = "comment,tag,hashtag,caption",
        date_from: str = "",
        date_to: str = "",
        offset: int = 0,
        limit: int = FEED_PAGE_SIZE,
    ) -> dict:
        from datetime import date as date_cls

        platform_set = {part.strip() for part in platforms.split(",") if part.strip()}
        type_set = {part.strip() for part in types.split(",") if part.strip()}
        start = date_cls.fromisoformat(date_from) if date_from else None
        end = date_cls.fromisoformat(date_to) if date_to else None
        with transaction() as conn:
            _require_client(conn, client_id)
            try:
                return filter_search_payload(
                    conn,
                    client_id,
                    query=q,
                    platforms=platform_set,
                    match_types=type_set,
                    date_from=start,
                    date_to=end,
                    offset=offset,
                    limit=limit,
                )
            except ValueError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/clients/{client_id}/sync-totals")
    def read_sync_totals(client_id: int) -> dict:
        with transaction() as conn:
            _require_client(conn, client_id)
            try:
                return sync_totals(conn, client_id)
            except ValueError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/clients/{client_id}/posts")
    def read_posts(client_id: int) -> dict:
        return _posts_payload(client_id)

    @app.get("/api/clients/{client_id}/posts/{post_id}")
    def read_post_detail(client_id: int, post_id: int) -> dict:
        with transaction() as conn:
            _require_client(conn, client_id)
            item = post_detail(conn, client_id, post_id)
        if item is None:
            raise HTTPException(status_code=404, detail="This post does not belong to the selected client.")
        return item

    @app.get("/api/clients/{client_id}/posts/{post_id}/analysis-panel")
    def read_post_analysis_panel(client_id: int, post_id: int) -> dict:
        from maaike.post_analysis_workflow import analysis_panel

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return analysis_panel(conn, client_id, post_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/clients/{client_id}/posts/{post_id}/analysis/prepare")
    def prepare_post_analysis_route(client_id: int, post_id: int) -> dict:
        """Prepare media + prompt inventory for one post. Does not call a paid model."""
        from maaike.post_analysis_workflow import prepare_post_analysis

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return prepare_post_analysis(conn, client_id, post_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/clients/{client_id}/posts/{post_id}/analysis/insight")
    def save_post_analysis_insight(client_id: int, post_id: int, body: dict) -> dict:
        from maaike.post_analysis_workflow import save_reviewed_insight

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return save_reviewed_insight(conn, client_id, post_id, body or {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/clients/{client_id}/posts/{post_id}/analysis/execute")
    def execute_post_analysis_route(client_id: int, post_id: int, body: dict | None = None) -> dict:
        """Paid single-post analysis. Requires confirm=true; not started by prepare/open."""
        from maaike.post_analysis_workflow import execute_prepared_post_analysis

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return execute_prepared_post_analysis(conn, client_id, post_id, body or {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/clients/{client_id}/performance")
    def read_performance(
        client_id: int,
        year: int | None = None,
        month: int | None = None,
        platforms: str = "instagram,facebook",
    ) -> dict:
        platform_set = {part.strip() for part in platforms.split(",") if part.strip()}
        with transaction() as conn:
            _require_client(conn, client_id)
            try:
                return performance_month_payload(
                    conn,
                    client_id,
                    year=year,
                    month=month,
                    platforms=platform_set or {"instagram", "facebook"},
                )
            except ValueError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/clients/{client_id}/comparison")
    def read_comparison(
        client_id: int,
        period: str = "",
        start: str = "",
        end: str = "",
    ) -> dict:
        from datetime import date as date_cls

        custom_start = date_cls.fromisoformat(start) if start else None
        custom_end = date_cls.fromisoformat(end) if end else None
        with transaction() as conn:
            _require_client(conn, client_id)
            try:
                return comparison_state(
                    conn,
                    client_id,
                    period_key=period or None,
                    custom_start=custom_start,
                    custom_end=custom_end,
                )
            except ValueError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/clients/{client_id}/crawl-accounts")
    def read_crawl_accounts(client_id: int) -> dict:
        from maaike.account_crawl import list_crawl_accounts

        with transaction() as conn:
            _require_client(conn, client_id)
            return {"accounts": list_crawl_accounts(conn, client_id)}

    @app.post("/api/clients/{client_id}/crawl-accounts")
    def post_crawl_account(client_id: int, body: NameBody) -> dict:
        from maaike.account_crawl import link_crawl_account, list_crawl_accounts

        with transaction() as conn:
            _require_client(conn, client_id)
            try:
                linked = link_crawl_account(conn, client_id, body.name)
                return {"account": linked, "accounts": list_crawl_accounts(conn, client_id)}
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/clients/{client_id}/crawl-accounts/{username}/run")
    def run_crawl_account(client_id: int, username: str, body: dict | None = None) -> dict:
        from maaike.account_crawl import crawl_account

        payload = body or {}
        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return crawl_account(
                    conn,
                    client_id,
                    username,
                    max_pages=int(payload.get("max_pages") or 2),
                    page_limit=int(payload.get("page_limit") or 25),
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/clients/{client_id}/ai-analyses")
    def list_ai_analyses(client_id: int, post_id: int | None = None) -> dict:
        from maaike.claude_analysis import list_analyses

        with transaction() as conn:
            _require_client(conn, client_id)
            return list_analyses(conn, client_id, post_id=post_id)

    @app.get("/api/clients/{client_id}/ai-analyses/{analysis_id}")
    def read_ai_analysis(client_id: int, analysis_id: int) -> dict:
        from maaike.claude_analysis import get_analysis

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return get_analysis(conn, client_id, analysis_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/clients/{client_id}/posts/{post_id}/claude-analyze")
    def claude_analyze_post(client_id: int, post_id: int) -> dict:
        from maaike.claude_analysis import run_claude_post_analysis

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return run_claude_post_analysis(conn, client_id, post_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/clients/{client_id}/comparison/competitors")
    def post_competitor(client_id: int, body: NameBody) -> dict:
        with transaction() as conn:
            _require_client(conn, client_id)
            try:
                return comparison_add_competitor(conn, client_id, body.name)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/clients/{client_id}/comparison/competitors/{username}")
    def delete_competitor(client_id: int, username: str) -> dict:
        with transaction() as conn:
            _require_client(conn, client_id)
            try:
                return comparison_remove_competitor(conn, client_id, username)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/clients/{client_id}/comparison/schedule")
    def comparison_schedule(client_id: int) -> dict:
        from maaike.competitor_scheduler import ensure_competitors_linked, schedule_status

        with transaction() as conn:
            _require_client(conn, client_id)
            linked = ensure_competitors_linked(conn, client_id)
        return {"client_id": client_id, "linked": linked, "schedule": schedule_status()}

    @app.post("/api/clients/{client_id}/comparison/competitors/refresh")
    def refresh_competitors(client_id: int, body: dict | None = None) -> dict:
        """Manual competitor crawl (Business Discovery). Prefer automatic off-hours ticks."""
        from maaike.competitor_scheduler import refresh_client_competitors

        payload = body or {}
        try:
            max_accounts = int(payload.get("max_accounts") or 3)
        except (TypeError, ValueError):
            max_accounts = 3
        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return refresh_client_competitors(
                    conn, client_id, max_accounts=max(1, min(max_accounts, 10))
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/clients/{client_id}/comparison/period")
    def post_comparison_period(client_id: int, body: dict) -> dict:
        from datetime import date as date_cls

        period_key = str((body or {}).get("period_key") or "3m")
        start_raw = (body or {}).get("custom_start")
        end_raw = (body or {}).get("custom_end")
        custom_start = date_cls.fromisoformat(str(start_raw)) if start_raw else None
        custom_end = date_cls.fromisoformat(str(end_raw)) if end_raw else None
        with transaction() as conn:
            _require_client(conn, client_id)
            try:
                return comparison_save_period(
                    conn,
                    client_id,
                    period_key,
                    custom_start=custom_start,
                    custom_end=custom_end,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/clients/{client_id}/posts/fetch")
    def fetch_posts(client_id: int) -> dict:
        try:
            fetch_client_posts(client_id)
        except MetaConnectError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _posts_payload(client_id)

    @app.patch("/api/clients/{client_id}/posts/{post_id}")
    def patch_post(client_id: int, post_id: int, body: EditorialBody) -> dict:
        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                save_editorial(
                    conn,
                    client_id,
                    post_id=post_id,
                    format_id=body.format_id,
                    pillar_id=body.pillar_id,
                    hook=body.hook,
                )
        except LegendInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"saved": True}

    @app.post("/api/clients/{client_id}/posts/manual", status_code=201)
    def create_manual_post(client_id: int, body: dict) -> dict:
        from maaike.excel_import import extract_external_id, normalize_post_url
        from datetime import datetime, timezone

        platform_label = str((body or {}).get("platform_label") or (body or {}).get("platform") or "").strip()
        platform_key = str((body or {}).get("platform_key") or platform_label).strip().lower().replace(" ", "_")
        permalink = str((body or {}).get("permalink") or "").strip() or None
        external_id = str((body or {}).get("external_id") or "").strip() or extract_external_id(
            platform_key, permalink
        )
        if not external_id:
            raise HTTPException(status_code=400, detail="Provide a post URL or external ID.")
        published_at = str((body or {}).get("published_at") or datetime.now(tz=timezone.utc).date().isoformat())
        now = datetime.now(tz=timezone.utc).isoformat()
        with transaction() as conn:
            _require_client(conn, client_id)
            cursor = conn.execute(
                """
                INSERT INTO posts (
                    client_id, platform, external_id, published_at, content_kind, permalink,
                    platform_label, source_origin
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'manual')
                """,
                (
                    client_id,
                    platform_key,
                    external_id,
                    published_at,
                    (body or {}).get("content_kind"),
                    permalink or normalize_post_url(permalink),
                    platform_label or None,
                ),
            )
            post_id = int(cursor.lastrowid)
            hook = str((body or {}).get("hook") or "")
            conn.execute(
                """
                INSERT INTO post_editorial (post_id, format_id, pillar_id, hook, updated_at)
                VALUES (?, NULL, NULL, ?, ?)
                """,
                (post_id, hook, now),
            )
        return {"id": post_id}

    @app.post("/api/clients/{client_id}/excel/preview")
    async def excel_preview(client_id: int, file: UploadFile | None = File(None)) -> dict:
        from maaike.excel_import import build_preview, parse_workbook

        path = await _resolve_excel_upload(client_id, file)
        try:
            parsed = parse_workbook(path)
            with transaction() as conn:
                _require_client(conn, client_id)
                return build_preview(conn, client_id, parsed)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/clients/{client_id}/excel/import")
    async def excel_import_run(
        client_id: int,
        file: UploadFile | None = File(None),
        update_assessments: bool = False,
    ) -> dict:
        from maaike.excel_import import execute_import, parse_workbook

        path = await _resolve_excel_upload(client_id, file)
        try:
            parsed = parse_workbook(path)
            with transaction() as conn:
                _require_client(conn, client_id)
                result = execute_import(
                    conn,
                    client_id,
                    path=path,
                    parsed=parsed,
                    update_assessments=bool(update_assessments),
                )
            return result
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/clients/{client_id}/activity")
    def read_activity(
        client_id: int,
        activity_type: str = "",
        status: str = "",
        errors_only: bool = False,
        limit: int = 200,
    ) -> dict:
        from maaike.activity_log import list_activity_events

        with transaction() as conn:
            _require_client(conn, client_id)
            return list_activity_events(
                conn,
                client_id=client_id,
                activity_type=activity_type or None,
                status=status or None,
                errors_only=errors_only,
                limit=min(max(limit, 1), 500),
            )

    @app.get("/api/clients/{client_id}/activity/export.csv")
    def export_activity_csv(
        client_id: int,
        activity_type: str = "",
        status: str = "",
        errors_only: bool = False,
    ) -> Response:
        from maaike.activity_log import activity_events_csv_bytes, list_activity_events

        with transaction() as conn:
            _require_client(conn, client_id)
            payload = list_activity_events(
                conn,
                client_id=client_id,
                activity_type=activity_type or None,
                status=status or None,
                errors_only=errors_only,
                limit=500,
            )
        data = activity_events_csv_bytes(payload["events"])
        return Response(
            content=data,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="activity-export.csv"'},
        )

    @app.get("/api/export/package.json")
    def export_full_package(client_id: int | None = None) -> Response:
        from maaike.data_transfer import export_package_json_bytes

        with transaction() as conn:
            if client_id is not None:
                _require_client(conn, client_id)
            data = export_package_json_bytes(conn, client_id=client_id)
        stamp = __import__("datetime").datetime.now().strftime("%Y%m%d-%H%M")
        name = f"maaike-backup-{stamp}.json"
        return Response(
            content=data,
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @app.get("/api/clients/{client_id}/export/posts.csv")
    def export_client_posts_csv(client_id: int) -> Response:
        from maaike.data_transfer import export_posts_csv
        from maaike.logs_export import export_filename

        with transaction() as conn:
            _require_client(conn, client_id)
            data = export_posts_csv(conn, client_id)
        return Response(
            content=data,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{export_filename("csv")}"'},
        )

    @app.post("/api/import/preview")
    async def import_preview(file: UploadFile = File(...)) -> dict:
        import json as json_mod

        from maaike.data_transfer import preview_import

        raw = await file.read()
        try:
            payload = json_mod.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json_mod.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON file.") from exc
        try:
            with transaction() as conn:
                return preview_import(conn, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/import/apply")
    async def import_apply(file: UploadFile = File(...), overwrite: bool = False) -> dict:
        import json as json_mod

        from maaike.activity_log import record_activity
        from maaike.data_transfer import apply_import, create_pre_import_backup, preview_import

        raw = await file.read()
        try:
            payload = json_mod.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json_mod.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON file.") from exc
        try:
            backup_path = create_pre_import_backup()
            with transaction() as conn:
                preview = preview_import(conn, payload)
                result = apply_import(conn, payload, overwrite=overwrite)
                record_activity(
                    conn,
                    client_id=None,
                    activity_type="data_import",
                    status="completed",
                    title="JSON-import uitgevoerd",
                    details=f"backup={backup_path.name}; overwrite={overwrite}; stats={result.get('stats')}",
                    source_ref=backup_path.name,
                    is_error=False,
                )
            return {
                "backup": str(backup_path),
                "preview_summary": preview.get("summary"),
                "result": result,
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/clients/{client_id}/logs/export.csv")
    def export_logs_csv(
        client_id: int,
        platform: str = "",
        content_soort: str = "",
        format: str = "",
        pillar: str = "",
        date_from: str = "",
        date_to: str = "",
        missing: str = "",
    ) -> Response:
        from maaike.logs_export import export_csv_bytes, export_filename, filtered_export_posts

        with transaction() as conn:
            _require_client(conn, client_id)
            posts = filtered_export_posts(
                conn,
                client_id,
                {
                    "platform": platform,
                    "content_soort": content_soort,
                    "format": format,
                    "pillar": pillar,
                    "date_from": date_from,
                    "date_to": date_to,
                    "missing": missing,
                },
            )
        data = export_csv_bytes(posts)
        return Response(
            content=data,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{export_filename("csv")}"'},
        )

    @app.get("/api/clients/{client_id}/logs/export.xlsx")
    def export_logs_xlsx(
        client_id: int,
        platform: str = "",
        content_soort: str = "",
        format: str = "",
        pillar: str = "",
        date_from: str = "",
        date_to: str = "",
        missing: str = "",
    ) -> Response:
        from maaike.logs_export import export_filename, export_xlsx_bytes, filtered_export_posts

        with transaction() as conn:
            _require_client(conn, client_id)
            posts = filtered_export_posts(
                conn,
                client_id,
                {
                    "platform": platform,
                    "content_soort": content_soort,
                    "format": format,
                    "pillar": pillar,
                    "date_from": date_from,
                    "date_to": date_to,
                    "missing": missing,
                },
            )
        data = export_xlsx_bytes(posts)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{export_filename("xlsx")}"'},
        )

    @app.get("/api/clients/{client_id}/strategy")
    def read_strategy(client_id: int) -> dict:
        from maaike.strategy import get_strategy

        with transaction() as conn:
            _require_client(conn, client_id)
            return get_strategy(conn, client_id)

    @app.get("/api/clients/{client_id}/figma-planning")
    def read_figma_planning(client_id: int) -> dict:
        from maaike.figma_planning import planning_overview

        with transaction() as conn:
            _require_client(conn, client_id)
            return planning_overview(conn, client_id)

    @app.put("/api/clients/{client_id}/figma-planning/connection")
    def put_figma_connection(client_id: int, body: dict) -> dict:
        from maaike.figma_planning import save_figma_connection

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return {
                    "connection": save_figma_connection(
                        conn,
                        client_id,
                        file_key=str((body or {}).get("file_key") or ""),
                        file_name=str((body or {}).get("file_name") or ""),
                        source_url=str((body or {}).get("source_url") or ""),
                    )
                }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/clients/{client_id}/figma-planning/sync")
    def sync_figma_planning(client_id: int, body: dict | None = None) -> dict:
        """Sync planning items from Figma API when FIGMA_ACCESS_TOKEN is set."""
        from maaike.figma_planning import sync_from_figma_api

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return sync_from_figma_api(conn, client_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/clients/{client_id}/figma-planning/import-snapshot")
    def import_figma_snapshot(client_id: int, body: dict) -> dict:
        """Import items from metadata snapshots (MCP/XML) without writing to Figma."""
        from maaike.figma_planning import sync_from_metadata_files

        payload = body or {}
        pages = payload.get("pages") or []
        if not isinstance(pages, list) or not pages:
            raise HTTPException(status_code=400, detail="Provide pages=[{page_name,page_node_id,xml}].")
        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return sync_from_metadata_files(
                    conn,
                    client_id,
                    pages,
                    file_key=str(payload.get("file_key") or ""),
                    note=str(payload.get("note") or "Snapshot import"),
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/clients/{client_id}/figma-planning/items/{item_id}/suggestions")
    def figma_item_suggestions(client_id: int, item_id: int) -> dict:
        from maaike.figma_planning import suggest_post_matches

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return {"suggestions": suggest_post_matches(conn, client_id, item_id)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/clients/{client_id}/figma-planning/items/{item_id}/preview-link")
    def figma_preview_link(client_id: int, item_id: int, body: dict) -> dict:
        from maaike.figma_planning import preview_link_to_post

        post_id = (body or {}).get("post_id")
        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return preview_link_to_post(conn, client_id, item_id, int(post_id))
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/clients/{client_id}/figma-planning/items/{item_id}/link")
    def figma_apply_link(client_id: int, item_id: int, body: dict) -> dict:
        from maaike.figma_planning import apply_link_to_post

        payload = body or {}
        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return apply_link_to_post(
                    conn,
                    client_id,
                    item_id,
                    int(payload.get("post_id")),
                    confirm=bool(payload.get("confirm")),
                    accept_content_kind_mismatch=bool(
                        payload.get("accept_content_kind_mismatch")
                    ),
                )
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/clients/{client_id}/rating-settings")
    def read_rating_settings(client_id: int) -> dict:
        from maaike.rating import get_rating_settings

        with transaction() as conn:
            _require_client(conn, client_id)
            return get_rating_settings(conn, client_id)

    @app.put("/api/clients/{client_id}/rating-settings")
    def put_rating_settings(client_id: int, body: dict) -> dict:
        from maaike.rating import save_rating_settings

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return save_rating_settings(conn, client_id, body or {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/clients/{client_id}/strategy")
    def put_strategy(client_id: int, body: dict) -> dict:
        from maaike.strategy import save_strategy

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return save_strategy(
                    conn,
                    client_id,
                    account_info=(body or {}).get("account_info"),
                    start_answers=(body or {}).get("start_answers"),
                    strategy_fields=(body or {}).get("strategy_fields"),
                    source_notes=(body or {}).get("source_notes"),
                    mark_complete=bool((body or {}).get("mark_complete")),
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/clients/{client_id}/strategy/prefill-redrock")
    def prefill_strategy(client_id: int) -> dict:
        from maaike.strategy import prefill_red_rock_from_sources

        imports_dir = Path(__file__).resolve().parents[1] / "data" / "imports" / "redrock"
        with transaction() as conn:
            _require_client(conn, client_id)
            return prefill_red_rock_from_sources(conn, client_id, imports_dir)

    @app.get("/api/clients/{client_id}/targets")
    def read_targets(client_id: int) -> dict:
        from maaike.strategy import list_targets

        with transaction() as conn:
            _require_client(conn, client_id)
            return {"targets": list_targets(conn, client_id)}

    @app.post("/api/clients/{client_id}/targets")
    def post_target(client_id: int, body: dict) -> dict:
        from maaike.strategy import upsert_target

        with transaction() as conn:
            _require_client(conn, client_id)
            return upsert_target(conn, client_id, body or {})

    @app.post("/api/clients/{client_id}/targets/{target_id}/measurements")
    def post_target_measurement(client_id: int, target_id: int, body: dict) -> dict:
        from maaike.strategy import add_target_measurement

        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                return add_target_measurement(conn, client_id, target_id, body or {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=400, detail="Metric value is missing.") from exc

    @app.get("/api/clients/{client_id}/meta")
    def read_meta(client_id: int, request: Request) -> dict:
        session_id, cookie = _session(request)
        with transaction() as conn:
            client = _require_client(conn, client_id)
        pending = pending_for(session_id, client_id)
        payload = _meta_out(client, settings)
        payload["pages"] = pages_public(pending) if pending is not None else None
        response = JSONResponse(payload)
        if cookie:
            _set_cookie(response, cookie, settings)
        return response

    @app.post("/api/clients/{client_id}/meta/start")
    def start_meta(client_id: int, request: Request, body: StartMetaBody = StartMetaBody()) -> JSONResponse:
        session_id, cookie = _session(request)
        popup = bool(body.popup)
        with transaction() as conn:
            client = _require_client(conn, client_id)
        info = readiness(settings.oauth_redirect_uri)
        if not info.ready or not info.redirect_uri:
            raise HTTPException(
                status_code=400,
                detail="Meta login is not configured yet. Ask an admin to check the configuration.",
            )
        state = arm_login(session_id, client.client_id, info.redirect_uri, popup=popup)
        try:
            login_url = build_login_url(redirect_uri=info.redirect_uri, state=state)
        except MetaConnectError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        response = JSONResponse(
            {
                "login_url": login_url,
                "popup": popup,
                "message": (
                    "Sign in to Meta in the window that opens. "
                    "Status becomes Connected only after you pick a page and the check succeeds."
                ),
            }
        )
        if cookie:
            _set_cookie(response, cookie, settings)
        return response

    @app.post("/api/clients/{client_id}/meta/confirm")
    def confirm_meta(client_id: int, body: ConfirmBody, request: Request) -> JSONResponse:
        session_id, cookie = _session(request)
        pending = pending_for(session_id, client_id)
        if pending is None:
            raise HTTPException(
                status_code=400,
                detail="This Meta login does not belong to this session. Start connecting again.",
            )
        option = selectable_page(pending, body.page_index)
        if option is None:
            raise HTTPException(status_code=400, detail="Choose a Facebook page with a professional Instagram account.")
        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                page_name = confirm_selected_page(conn, client_id, pending, option)
        except MetaConnectError as exc:
            clear_pending(session_id)
            _remember_failure(client_id, exc, replace_verified=False)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ClientInputError as exc:
            clear_pending(session_id)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        clear_pending(session_id)
        response = JSONResponse(
            {"message": f"Connected to {page_name}.", "connected": True}
        )
        if cookie:
            _set_cookie(response, cookie, settings)
        return response

    @app.post("/api/clients/{client_id}/meta/cancel")
    def cancel_meta(client_id: int, request: Request) -> dict:
        session_id, _cookie = _session(request)
        if pending_for(session_id, client_id) is not None:
            clear_pending(session_id)
        return {"cancelled": True}

    @app.post("/api/clients/{client_id}/meta/disconnect")
    def disconnect_meta(client_id: int, request: Request) -> dict:
        """Remove Meta access for this client. Does not delete the client or its content."""
        session_id, _cookie = _session(request)
        if pending_for(session_id, client_id) is not None:
            clear_pending(session_id)
        try:
            with transaction() as conn:
                client = _require_client(conn, client_id)
                before = disconnect_meta_link(conn, client_id)
        except ClientInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        account = before.get("page_name") or "Facebook/Instagram"
        if before.get("ig_username"):
            account = f"{account} (@{before['ig_username']})"
        return {
            "disconnected": True,
            "message": (
                f"Disconnected Meta for this client only ({account}). "
                "Saved posts, strategy, legends and reports were kept."
            ),
            "client_id": client_id,
            "client_name": client.name,
        }

    @app.post("/api/clients/{client_id}/meta/recheck")
    def recheck_meta(client_id: int) -> dict:
        try:
            with transaction() as conn:
                _require_client(conn, client_id)
                page_name = recheck_stored_link(conn, client_id)
        except MetaConnectError as exc:
            _remember_failure(client_id, exc, replace_verified=True)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"message": f"Koppeling gecontroleerd voor {page_name}."}

    @app.get("/api/meta/callback")
    def meta_callback(request: Request):
        settings_now: WebSettings = request.app.state.settings
        # Do not mint a new session here: a fresh empty id would break state lookup.
        cookie_sid = read_session_id(request.cookies.get(COOKIE_NAME), settings_now.session_secret)
        error = request.query_params.get("error") or ""
        state = request.query_params.get("state") or ""
        if error:
            popup = take_popup_flag(cookie_sid) or popup_for_state(state)
            return _front_redirect(
                settings_now,
                None,
                "Meta login was cancelled or denied.",
                popup=popup,
            )
        code = request.query_params.get("code") or ""
        try:
            client_id, redirect_uri, popup, bind_sid = take_callback(cookie_sid, state)
        except MetaConnectError as exc:
            popup = take_popup_flag(cookie_sid) or popup_for_state(state)
            return _front_redirect(settings_now, None, str(exc), popup=popup)
        try:
            pending = collect_pages(code=code, redirect_uri=redirect_uri)
        except MetaConnectError as exc:
            _remember_failure(client_id, exc, replace_verified=False)
            response = _front_redirect(settings_now, client_id, str(exc), popup=popup)
            _set_cookie(response, cookie_value(bind_sid, settings_now.session_secret), settings_now)
            return response
        store_pending(bind_sid, client_id, pending)
        response = _front_redirect(settings_now, client_id, None, popup=popup)
        # Re-attach the armed session so confirm works even when Meta omitted the cookie.
        _set_cookie(response, cookie_value(bind_sid, settings_now.session_secret), settings_now)
        return response

    return app


async def _resolve_excel_upload(client_id: int, file: UploadFile | None) -> Path:
    imports_dir = Path(__file__).resolve().parents[1] / "data" / "imports" / "redrock"
    imports_dir.mkdir(parents=True, exist_ok=True)
    default = imports_dir / "RRO_Social_strategie_overzicht_2026.xlsx"
    if file is None or not file.filename:
        if not default.exists() or default.stat().st_size < 1000:
            raise HTTPException(
                status_code=400,
                detail="No Excel upload and no local RRO_Social_strategie_overzicht_2026.xlsx found.",
            )
        return default
    dest = imports_dir / f"upload-client-{client_id}-{file.filename}"
    dest.write_bytes(await file.read())
    return dest


def _posts_payload(client_id: int) -> dict:
    from maaike.rating import get_rating_settings, rate_post

    with transaction() as conn:
        client = _require_client(conn, client_id)
        posts = list_posts(conn, client_id)
        moment = latest_sync_at(conn, client_id)
        legend = _legend_out(conn, client_id)
        rating_settings = get_rating_settings(conn, client_id)
    connected = _is_connected(client)
    if client.last_fetch_detail:
        fetch_message = client.last_fetch_detail
    elif connected:
        fetch_message = "Connection verified. Fetch posts only loads posts for this client."
    else:
        fetch_message = "Fetch posts stays closed until this client is connected and verified."
    rated_posts = []
    for post in posts:
        formula = rate_post(post, rating_settings)
        cells = overview_record(post)
        # Prefer live formula label in overview when active; keep Excel text in formula payload.
        if rating_settings.get("active"):
            cells = dict(cells)
            cells["Beoordeling"] = formula["label"]
            if formula.get("score_known") and formula.get("score") is not None:
                cells["Beoordeling"] = f"{formula['label']} ({formula['score']})"
        rated_posts.append(
            {
                "id": post.post_id,
                "format_id": post.format_id,
                "pillar_id": post.pillar_id,
                "hook": post.hook,
                "missing_classification": {
                    "format": post.format_id is None,
                    "pillar": post.pillar_id is None,
                    "hook": not bool((post.hook or "").strip()),
                    "any": post.format_id is None
                    or post.pillar_id is None
                    or not bool((post.hook or "").strip()),
                },
                "formula_rating": formula,
                "cells": cells,
            }
        )
    return {
        "synced_at": format_sync_moment(moment),
        "columns": list(OVERVIEW_COLUMNS),
        "column_labels": dict(COLUMN_LABELS),
        "unset_label": UNSET_LABEL,
        "rating_pending": RATING_PENDING,
        "fetch_available": connected,
        "fetch_status": client.last_fetch_status,
        "fetch_message": fetch_message,
        "empty_message": (
            f"No posts yet for {client.name}. "
            "No sample posts were added. "
            "Fetch posts is available only after the Meta connection for this client is verified."
        ),
        "rating_settings": {
            "active": rating_settings.get("active"),
            "profile_name": rating_settings.get("profile_name"),
            "is_provisional": rating_settings.get("is_provisional"),
            "ready_to_activate": rating_settings.get("ready_to_activate"),
            "activation_blockers": rating_settings.get("activation_blockers"),
            "comparison_disclaimer": rating_settings.get("comparison_disclaimer"),
        },
        "formats": legend["formats"],
        "pillars": legend["pillars"],
        "hooks": legend["hooks"],
        "posts": rated_posts,
    }


def _session(request: Request) -> tuple[str, str | None]:
    settings: WebSettings = request.app.state.settings
    cookie = request.cookies.get(COOKIE_NAME)
    return ensure_session(cookie, settings.session_secret)


def _set_cookie(response: Response, value: str, settings: WebSettings) -> None:
    response.set_cookie(
        COOKIE_NAME,
        value,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=settings.backend_url.startswith("https://"),
        path="/",
    )


def _front_redirect(
    settings: WebSettings,
    client_id: int | None,
    error: str | None,
    *,
    popup: bool = False,
) -> RedirectResponse:
    query = "page=clients"
    if client_id is not None:
        query += f"&client={client_id}"
    if error:
        query += f"&meta_error={quote(error)}"
    else:
        query += "&meta=choose"
    if popup:
        query += "&popup=1"
    return RedirectResponse(url=f"{settings.frontend_url}/?{query}", status_code=302)


def _remember_failure(client_id: int, exc: MetaConnectError, *, replace_verified: bool) -> None:
    try:
        with transaction() as conn:
            record_failed_attempt(conn, client_id, exc, replace_verified=replace_verified)
    except ClientInputError:
        return


def _require_client(conn, client_id: int) -> Client:
    client = get_client(conn, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="This client is not in the list.")
    return client


def _add_legend(client_id: int, kind: str, body: LegendBody) -> dict:
    try:
        with transaction() as conn:
            _require_client(conn, client_id)
            if kind == "format":
                add_format(conn, client_id, body.name, body.explanation)
            elif kind == "pillar":
                add_pillar(conn, client_id, body.name, body.explanation)
            elif kind == "hook":
                add_hook(conn, client_id, body.name, body.explanation)
            else:
                raise HTTPException(status_code=400, detail="Unknown legend type.")
            payload = _legend_out(conn, client_id)
    except (LegendInputError, ClientInputError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return payload


def _update_legend(client_id: int, kind: str, item_id: int, body: LegendBody) -> dict:
    try:
        with transaction() as conn:
            _require_client(conn, client_id)
            if kind == "format":
                update_format(conn, client_id, item_id, body.name, body.explanation)
            elif kind == "pillar":
                update_pillar(conn, client_id, item_id, body.name, body.explanation)
            elif kind == "hook":
                update_hook(conn, client_id, item_id, body.name, body.explanation)
            else:
                raise HTTPException(status_code=400, detail="Unknown legend type.")
            payload = _legend_out(conn, client_id)
    except (LegendInputError, ClientInputError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return payload


def _legend_out(conn, client_id: int) -> dict:
    return {
        "formats": [_legend_item(item) for item in list_formats(conn, client_id)],
        "pillars": [_legend_item(item) for item in list_pillars(conn, client_id)],
        "hooks": [_legend_item(item) for item in list_hooks(conn, client_id)],
    }


def _legend_item(item) -> dict:
    return {"id": item.item_id, "name": item.name, "explanation": item.explanation}


def _is_connected(client: Client) -> bool:
    return is_verified_link(client)


def _client_out(client: Client) -> dict:
    connected = _is_connected(client)
    detail = None if connected else client.meta_status_detail
    expires = format_sync_moment(client.meta_token_expires_at) if connected and client.meta_token_expires_at else None
    return {
        "id": client.client_id,
        "name": client.name,
        "status_label": connection_label(client),
        "connected": connected,
        "status_detail": detail,
        "expires_label": expires,
        "meta_status": client.meta_status,
        "page_name": client.meta_page_name,
        "ig_username": client.meta_ig_username,
    }


def _meta_out(client: Client, settings: WebSettings) -> dict:
    info = readiness(settings.oauth_redirect_uri)
    connected = is_verified_link(client)
    user_notes: list[str] = []
    if not info.ready:
        user_notes.append(
            "Meta login is not ready yet. Ask an admin to check the app configuration."
        )
    elif connected:
        user_notes.append("You can recheck the connection or reconnect.")
    else:
        user_notes.append(
            "Log in to Meta and choose the Facebook page with the professional Instagram account for this client."
        )
        if client.meta_status in {"revoked", "expired", "error"} and (
            client.meta_page_name or client.meta_ig_username
        ):
            last = client.meta_page_name or ""
            if client.meta_ig_username:
                last = f"{last} (@{client.meta_ig_username})".strip() if last else f"@{client.meta_ig_username}"
            user_notes.insert(
                0,
                f"Last linked account: {last}. Access is no longer valid — reconnect.",
            )
    admin_notes = [
        "Tokens stay server-side in the local database and are not shown.",
        "That database is not encrypted. Do not host this dashboard on the current TAOL service.",
    ]
    if info.ready and info.uses_configuration:
        admin_notes.insert(0, "Login uses the configured Meta login configuration.")
    elif info.ready:
        scopes = ", ".join(LOGIN_SCOPES)
        admin_notes.insert(
            0,
            "MAAIKE_META_LOGIN_CONFIG_ID is not set. The button requests these permissions directly: "
            f"{scopes}.",
        )
    base = _client_out(client)
    base.update(
        {
            "ready": info.ready,
            "missing": [
                "Meta login is not configured yet. Ask an admin for help."
            ]
            if info.missing
            else [],
            "notes": user_notes,
            "reconnect_label": "Reconnect" if connected else "Connect Facebook and Instagram",
            "page_name": client.meta_page_name,
            "ig_username": client.meta_ig_username,
            "admin": {
                "redirect_uri": info.redirect_uri,
                "notes": admin_notes,
                "missing_raw": list(info.missing),
            },
        }
    )
    return base


app = create_app()
