"""Robust Meta Graph API client for retrieval and pagination."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from config import get_settings
from meta.endpoints import (
    COMMENTS_EDGE,
    DEFAULT_LIMIT,
    INSTAGRAM_COMMENT_FIELDS,
    INSTAGRAM_MEDIA_FIELDS,
    ME_ACCOUNTS_EDGE,
    PAGE_INSTAGRAM_ACCOUNT_FIELDS,
    PAGES_FIELDS,
    POSTS_EDGE,
    FACEBOOK_POST_FIELDS,
    FACEBOOK_COMMENT_FIELDS,
    MEDIA_EDGE,
    as_fields_param,
)
from meta.rate_limit import (
    build_rate_limit_info,
    is_rate_limit_error,
    sanitize_request_params,
)


logger = logging.getLogger(__name__)


class MetaClientError(Exception):
    """Base class for Meta API client errors."""


class MetaConfigError(MetaClientError):
    """Raised when required configuration values are missing."""


class MetaRequestError(MetaClientError):
    """Raised when a request to Graph API fails."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: int | None = None,
        error_subcode: int | None = None,
        is_transient: bool = False,
        retry_after_seconds: int | None = None,
        blocked_until: str | None = None,
        usage_headers: dict | None = None,
        fbtrace_id: str | None = None,
        is_rate_limited: bool = False,
        duration_ms: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.error_subcode = error_subcode
        self.is_transient = is_transient
        self.retry_after_seconds = retry_after_seconds
        self.blocked_until = blocked_until
        self.usage_headers = usage_headers or {}
        self.fbtrace_id = fbtrace_id
        self.is_rate_limited = is_rate_limited
        self.duration_ms = duration_ms


TOKEN_EXPIRED_MESSAGE = (
    "Meta token verlopen. Genereer nieuwe User Token en run scripts/refresh_all_tokens.py."
)
RATE_LIMIT_USER_MESSAGE = "Meta-aanvraaglimiet bereikt"


def format_meta_client_error(exc: MetaClientError) -> str:
    """Return a user-facing sync error message for Meta client failures."""
    if isinstance(exc, MetaRequestError) and exc.error_code == 190:
        return TOKEN_EXPIRED_MESSAGE
    if isinstance(exc, MetaRequestError) and exc.is_rate_limited:
        return RATE_LIMIT_USER_MESSAGE
    return str(exc)


def _is_retryable_error(exc: BaseException) -> bool:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, MetaRequestError):
        # Never retry application/rate limits — retries burn the remaining quota.
        if exc.is_rate_limited or is_rate_limit_error(
            error_code=exc.error_code,
            message=str(exc),
            status_code=exc.status_code,
        ):
            return False
        if exc.is_transient:
            return True
        if exc.status_code in {500, 502, 503, 504}:
            return True
    return False


@dataclass(frozen=True, slots=True)
class MetaRequestMeta:
    """Safe timing/usage metadata for one Graph API HTTP response."""

    duration_ms: float
    usage_headers: dict[str, Any]
    status_code: int | None = None


@dataclass(slots=True)
class MetaClient:
    """Graph API client with retries, paging, and typed helper methods."""

    base_url: str
    timeout_seconds: int
    user_access_token: str
    page_access_token: str
    default_page_id: str | None = None
    default_instagram_business_account_id: str | None = None
    session: requests.Session | None = None

    @classmethod
    def from_settings(cls) -> "MetaClient":
        """Build client from environment-backed settings."""
        settings = get_settings()
        return cls(
            base_url=f"https://graph.facebook.com/{settings.meta_graph_api_version}",
            timeout_seconds=settings.request_timeout_seconds,
            user_access_token=settings.meta_user_access_token,
            page_access_token=settings.meta_page_access_token,
            default_page_id=settings.meta_page_id or None,
            default_instagram_business_account_id=(
                settings.meta_instagram_business_account_id or None
            ),
        )

    @property
    def http(self) -> requests.Session:
        if self.session is None:
            self.session = requests.Session()
        return self.session

    def _validate_token(self, access_token: str | None, context: str) -> str:
        token = (access_token or "").strip()
        if not token:
            raise MetaConfigError(f"Missing access token for {context}.")
        return token

    @retry(
        retry=retry_if_exception(_is_retryable_error),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _request_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], MetaRequestMeta]:
        """Execute one GET request and return JSON plus safe request metadata."""
        safe_params = sanitize_request_params(params)
        # Never log the full URL: paging.next includes access_token.
        logger.debug("Meta request start endpoint_params=%s", safe_params)
        started = time.perf_counter()
        try:
            response = self.http.get(url, params=params, timeout=self.timeout_seconds)
        except (requests.Timeout, requests.ConnectionError) as exc:
            logger.warning("Meta network error params=%s error=%s", safe_params, exc)
            raise

        duration_ms = (time.perf_counter() - started) * 1000.0

        if response.ok:
            try:
                payload: dict[str, Any] = response.json()
            except ValueError as exc:
                raise MetaRequestError(
                    "Meta API returned non-JSON response.",
                    status_code=response.status_code,
                ) from exc
            usage = build_rate_limit_info(
                error_code=None,
                message="ok",
                headers=response.headers,
            ).usage_headers
            if usage:
                logger.debug("Meta usage headers=%s", usage)
            logger.debug("Meta request success duration_ms=%.1f", duration_ms)
            return payload, MetaRequestMeta(
                duration_ms=duration_ms,
                usage_headers=usage,
                status_code=response.status_code,
            )

        error_payload: dict[str, Any] = {}
        try:
            parsed_error = response.json().get("error", {})
            if isinstance(parsed_error, dict):
                error_payload = parsed_error
        except ValueError:
            pass

        message = error_payload.get("message") or response.text or "Unknown Meta API error"
        error_code = error_payload.get("code")
        rate_info = build_rate_limit_info(
            error_code=error_code if isinstance(error_code, int) else None,
            message=str(message),
            headers=response.headers,
            error_payload=error_payload,
            fbtrace_id=str(error_payload["fbtrace_id"])
            if error_payload.get("fbtrace_id")
            else None,
        )
        rate_limited = is_rate_limit_error(
            error_code=rate_info.error_code,
            message=str(message),
            status_code=response.status_code,
        )
        meta_error = MetaRequestError(
            RATE_LIMIT_USER_MESSAGE if rate_limited else message,
            status_code=response.status_code,
            error_code=error_code if isinstance(error_code, int) else None,
            error_subcode=error_payload.get("error_subcode"),
            is_transient=bool(error_payload.get("is_transient", False)),
            retry_after_seconds=rate_info.retry_after_seconds,
            blocked_until=rate_info.blocked_until,
            usage_headers=rate_info.usage_headers,
            fbtrace_id=rate_info.fbtrace_id,
            is_rate_limited=rate_limited,
            duration_ms=duration_ms,
        )
        logger.warning(
            "Meta request failed status=%s code=%s rate_limited=%s "
            "retry_after=%s usage=%s duration_ms=%.1f message=%s",
            meta_error.status_code,
            meta_error.error_code,
            meta_error.is_rate_limited,
            meta_error.retry_after_seconds,
            meta_error.usage_headers,
            duration_ms,
            str(meta_error),
        )
        raise meta_error

    def get_json(
        self,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        access_token: str | None = None,
        use_page_token: bool = True,
    ) -> dict[str, Any]:
        """Perform a GET against `base_url/<endpoint>` and return JSON."""
        payload, _meta = self.get_json_with_meta(
            endpoint,
            params=params,
            access_token=access_token,
            use_page_token=use_page_token,
        )
        return payload

    def get_json_with_meta(
        self,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        access_token: str | None = None,
        use_page_token: bool = True,
    ) -> tuple[dict[str, Any], MetaRequestMeta]:
        """GET JSON and return safe per-request timing/usage metadata."""
        token_source = access_token
        if token_source is None:
            token_source = self.page_access_token if use_page_token else self.user_access_token
        token = self._validate_token(token_source, f"endpoint {endpoint}")

        merged_params = dict(params or {})
        merged_params["access_token"] = token
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        return self._request_json(url, params=merged_params)

    def get_paginated(
        self,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        access_token: str | None = None,
        use_page_token: bool = True,
        max_items: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all pages using `paging.next` and return flattened `data`."""
        token_source = access_token
        if token_source is None:
            token_source = self.page_access_token if use_page_token else self.user_access_token
        token = self._validate_token(token_source, f"pagination endpoint {endpoint}")

        page_params = dict(params or {})
        page_params.setdefault("limit", DEFAULT_LIMIT)
        page_params["access_token"] = token

        next_url: str | None = f"{self.base_url}/{endpoint.lstrip('/')}"
        current_params: dict[str, Any] | None = page_params
        records: list[dict[str, Any]] = []

        while next_url:
            payload, _meta = self._request_json(next_url, params=current_params)
            data = payload.get("data", [])
            if not isinstance(data, list):
                raise MetaRequestError("Expected list payload in Graph API data field.")

            records.extend(data)
            logger.debug("Meta pagination page_fetched count=%s total=%s", len(data), len(records))

            if max_items is not None and len(records) >= max_items:
                return records[:max_items]

            paging = payload.get("paging", {})
            next_url = paging.get("next") if isinstance(paging, dict) else None
            # `paging.next` already includes all query params.
            current_params = None

        return records

    def get_pages(self) -> list[dict[str, Any]]:
        """Return Facebook Pages the authenticated user can access."""
        return self.get_paginated(
            ME_ACCOUNTS_EDGE,
            params={"fields": as_fields_param(PAGES_FIELDS)},
            use_page_token=False,
        )

    def get_instagram_business_account_id(self, page_id: str | None = None) -> str | None:
        """Resolve linked Instagram Business account ID for a Facebook Page."""
        resolved_page_id = (page_id or self.default_page_id or "").strip()
        if not resolved_page_id:
            raise MetaConfigError("Missing page_id for Instagram account discovery.")

        payload = self.get_json(
            resolved_page_id,
            params={"fields": as_fields_param(PAGE_INSTAGRAM_ACCOUNT_FIELDS)},
            use_page_token=True,
        )
        ig_account = payload.get("instagram_business_account")
        if isinstance(ig_account, dict):
            ig_id = ig_account.get("id")
            return str(ig_id) if ig_id else None
        return None

    def get_instagram_media(
        self,
        instagram_business_account_id: str | None = None,
        *,
        since: int | None = None,
        until: int | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch Instagram media for the provided IG business account."""
        ig_id = (
            instagram_business_account_id
            or self.default_instagram_business_account_id
            or ""
        ).strip()
        if not ig_id:
            raise MetaConfigError("Missing instagram_business_account_id for media fetch.")

        params: dict[str, Any] = {"fields": as_fields_param(INSTAGRAM_MEDIA_FIELDS)}
        if since is not None:
            params["since"] = since
        if until is not None:
            params["until"] = until
        if limit is not None:
            params["limit"] = limit

        return self.get_paginated(f"{ig_id}/{MEDIA_EDGE}", params=params, use_page_token=True)

    def get_instagram_media_insights(
        self,
        media_id: str,
        *,
        metrics: str = "views,reach,saved,total_views",
    ) -> dict[str, Any]:
        """Fetch lifetime insights for one Instagram media object (post/reel/carousel)."""
        if not media_id.strip():
            raise MetaConfigError("media_id is required for Instagram insights fetch.")

        try:
            return self.get_json(
                f"{media_id.strip()}/insights",
                params={"metric": metrics},
                use_page_token=True,
            )
        except MetaRequestError as primary_exc:
            # total_views is Facebook-Login-only; retry without it, then try impressions
            # for older feed posts created before the impressions deprecation window.
            fallbacks = (
                "views,reach,saved",
                "impressions,reach,saved",
            )
            last_exc: MetaRequestError = primary_exc
            for fallback in fallbacks:
                if fallback == metrics:
                    continue
                try:
                    return self.get_json(
                        f"{media_id.strip()}/insights",
                        params={"metric": fallback},
                        use_page_token=True,
                    )
                except MetaRequestError as exc:
                    last_exc = exc
            raise last_exc

    def get_facebook_post_insights(
        self,
        post_id: str,
        *,
        metrics: str = "post_media_view,post_total_media_view_unique",
    ) -> dict[str, Any]:
        """Fetch insights for one Facebook Page post."""
        if not post_id.strip():
            raise MetaConfigError("post_id is required for Facebook insights fetch.")

        params = {"metric": metrics, "period": "lifetime"}
        try:
            return self.get_json(
                f"{post_id.strip()}/insights",
                params=params,
                use_page_token=True,
            )
        except MetaRequestError as primary_exc:
            fallbacks = (
                "post_media_view",
                "post_impressions,post_impressions_unique",
            )
            last_exc: MetaRequestError = primary_exc
            for fallback in fallbacks:
                if fallback == metrics:
                    continue
                try:
                    return self.get_json(
                        f"{post_id.strip()}/insights",
                        params={"metric": fallback, "period": "lifetime"},
                        use_page_token=True,
                    )
                except MetaRequestError as exc:
                    last_exc = exc
            raise last_exc

    def get_instagram_comments(
        self,
        media_id: str,
        *,
        since: int | None = None,
        until: int | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch comments for one Instagram media object."""
        if not media_id.strip():
            raise MetaConfigError("media_id is required for Instagram comments fetch.")

        params: dict[str, Any] = {"fields": as_fields_param(INSTAGRAM_COMMENT_FIELDS)}
        if since is not None:
            params["since"] = since
        if until is not None:
            params["until"] = until
        if limit is not None:
            params["limit"] = limit

        return self.get_paginated(
            f"{media_id.strip()}/{COMMENTS_EDGE}",
            params=params,
            use_page_token=True,
        )

    def get_instagram_comment_replies(
        self,
        comment_id: str,
        *,
        limit: int | None = 50,
    ) -> list[dict[str, Any]]:
        """Fetch replies under one Instagram comment. Does not invent missing replies."""
        if not comment_id.strip():
            raise MetaConfigError("comment_id is required for Instagram reply fetch.")
        params: dict[str, Any] = {"fields": "id,text,timestamp,username"}
        if limit is not None:
            params["limit"] = limit
        return self.get_paginated(
            f"{comment_id.strip()}/replies",
            params=params,
            use_page_token=True,
        )

    def get_instagram_media_children(self, media_id: str) -> list[dict[str, Any]]:
        """Fetch carousel children in API order, following next pages."""
        if not media_id.strip():
            raise MetaConfigError("media_id is required for Instagram children fetch.")
        return self.get_paginated(
            f"{media_id.strip()}/children",
            params={"fields": "id,media_type,media_url,thumbnail_url"},
            use_page_token=True,
        )

    def get_instagram_media_content(self, media_id: str) -> dict[str, Any]:
        """Fetch caption and media URLs for one own Instagram post."""
        if not media_id.strip():
            raise MetaConfigError("media_id is required for Instagram content fetch.")
        from meta.content_media import OWN_CONTENT_FIELDS, as_content_fields

        return self.get_json(
            media_id.strip(),
            params={"fields": as_content_fields(OWN_CONTENT_FIELDS)},
            use_page_token=True,
        )

    def get_facebook_page_posts(
        self,
        page_id: str | None = None,
        *,
        since: int | None = None,
        until: int | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch Facebook posts created by the configured Page."""
        resolved_page_id = (page_id or self.default_page_id or "").strip()
        if not resolved_page_id:
            raise MetaConfigError("Missing page_id for Facebook posts fetch.")

        params: dict[str, Any] = {"fields": as_fields_param(FACEBOOK_POST_FIELDS)}
        if since is not None:
            params["since"] = since
        if until is not None:
            params["until"] = until
        if limit is not None:
            params["limit"] = limit

        return self.get_paginated(
            f"{resolved_page_id}/{POSTS_EDGE}",
            params=params,
            use_page_token=True,
        )

    def get_facebook_comments(
        self,
        post_id: str,
        *,
        since: int | None = None,
        until: int | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch comments for one Facebook post."""
        if not post_id.strip():
            raise MetaConfigError("post_id is required for Facebook comments fetch.")

        params: dict[str, Any] = {"fields": as_fields_param(FACEBOOK_COMMENT_FIELDS)}
        if since is not None:
            params["since"] = since
        if until is not None:
            params["until"] = until
        if limit is not None:
            params["limit"] = limit

        return self.get_paginated(
            f"{post_id.strip()}/{COMMENTS_EDGE}",
            params=params,
            use_page_token=True,
        )
