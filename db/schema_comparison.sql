-- Comparison / Business Discovery extensions (idempotent).

CREATE TABLE IF NOT EXISTS comparison_fetch_runs (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    trigger_source TEXT NOT NULL,
    measured_at TEXT NOT NULL,
    period_start TEXT,
    period_end TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS account_measurements (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL,
    fetch_run_id INTEGER NOT NULL,
    measured_at TEXT NOT NULL,
    followers_count INTEGER,
    media_count INTEGER,
    UNIQUE(fetch_run_id, account_id),
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(fetch_run_id) REFERENCES comparison_fetch_runs(id)
);

CREATE TABLE IF NOT EXISTS post_measurements (
    id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL,
    fetch_run_id INTEGER NOT NULL,
    measured_at TEXT NOT NULL,
    like_count INTEGER,
    comments_count INTEGER,
    UNIQUE(fetch_run_id, post_id),
    FOREIGN KEY(post_id) REFERENCES posts(id),
    FOREIGN KEY(fetch_run_id) REFERENCES comparison_fetch_runs(id)
);

CREATE TABLE IF NOT EXISTS comparison_fetch_account_results (
    id INTEGER PRIMARY KEY,
    fetch_run_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    posts_fetched INTEGER NOT NULL DEFAULT 0,
    period_start TEXT,
    period_end TEXT,
    is_complete INTEGER NOT NULL DEFAULT 0,
    oldest_post_at TEXT,
    newest_post_at TEXT,
    error_message TEXT,
    UNIQUE(fetch_run_id, account_id),
    FOREIGN KEY(fetch_run_id) REFERENCES comparison_fetch_runs(id),
    FOREIGN KEY(account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS comparison_preferences (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    own_account_id INTEGER,
    competitor_usernames_json TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(own_account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS comparison_rate_limits (
    route TEXT PRIMARY KEY,
    hit_at TEXT NOT NULL,
    error_code INTEGER,
    message TEXT,
    retry_after_seconds INTEGER,
    blocked_until TEXT,
    usage_json TEXT,
    last_success_measured_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS comparison_discovery_checkpoints (
    account_id INTEGER PRIMARY KEY,
    username TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    cursor_after TEXT,
    pages_fetched INTEGER NOT NULL DEFAULT 0,
    posts_fetched INTEGER NOT NULL DEFAULT 0,
    is_complete INTEGER NOT NULL DEFAULT 0,
    last_fetch_run_id INTEGER,
    account_external_id TEXT,
    account_payload_json TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(last_fetch_run_id) REFERENCES comparison_fetch_runs(id)
);

CREATE TABLE IF NOT EXISTS comparison_discovery_request_log (
    id INTEGER PRIMARY KEY,
    fetch_run_id INTEGER,
    account_id INTEGER,
    username TEXT NOT NULL,
    page_index INTEGER NOT NULL,
    page_size INTEGER NOT NULL,
    posts_received INTEGER NOT NULL DEFAULT 0,
    duration_ms REAL,
    usage_json TEXT,
    cursor_before TEXT,
    cursor_after TEXT,
    status TEXT NOT NULL,
    error_message TEXT,
    measured_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(fetch_run_id) REFERENCES comparison_fetch_runs(id),
    FOREIGN KEY(account_id) REFERENCES accounts(id)
);

CREATE INDEX IF NOT EXISTS idx_account_measurements_account_measured
    ON account_measurements(account_id, measured_at DESC);
CREATE INDEX IF NOT EXISTS idx_post_measurements_post_measured
    ON post_measurements(post_id, measured_at DESC);
CREATE INDEX IF NOT EXISTS idx_comparison_fetch_runs_started
    ON comparison_fetch_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_posts_account_published
    ON posts(account_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_accounts_comparison_role
    ON accounts(comparison_role);
CREATE INDEX IF NOT EXISTS idx_discovery_request_log_run
    ON comparison_discovery_request_log(fetch_run_id, page_index);
CREATE INDEX IF NOT EXISTS idx_discovery_checkpoints_updated
    ON comparison_discovery_checkpoints(updated_at DESC);

-- Frozen weekly reports. Opening one reads this row and does not call Meta or AI.
CREATE TABLE IF NOT EXISTS weekly_reports (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    own_account_id INTEGER,
    account_label TEXT,
    snapshot_json TEXT NOT NULL,
    ai_status TEXT NOT NULL,
    ai_summary TEXT,
    ai_advice_json TEXT,
    ai_model TEXT,
    ai_generated_at TEXT,
    FOREIGN KEY(own_account_id) REFERENCES accounts(id)
);

CREATE INDEX IF NOT EXISTS idx_weekly_reports_created
    ON weekly_reports(created_at DESC);

-- Editable instruction texts only. API keys stay in the environment, never here.
CREATE TABLE IF NOT EXISTS ai_prompt_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    system_prompt TEXT NOT NULL,
    user_prompt TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Ordered media parts for one post. A URL here is not proof that a model saw the file.
CREATE TABLE IF NOT EXISTS post_media_items (
    id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    role TEXT NOT NULL,
    external_id TEXT,
    media_type TEXT,
    source_url TEXT,
    local_path TEXT,
    available INTEGER NOT NULL DEFAULT 0,
    unavailable_reason TEXT,
    fetched_at TEXT NOT NULL,
    UNIQUE(post_id, position, role),
    FOREIGN KEY(post_id) REFERENCES posts(id)
);

CREATE INDEX IF NOT EXISTS idx_post_media_items_post
    ON post_media_items(post_id, position);

-- One stored content description per post. Unchanged content is not sent again.
CREATE TABLE IF NOT EXISTS content_descriptions (
    post_id INTEGER PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    coverage TEXT NOT NULL,
    coverage_note TEXT,
    description_json TEXT,
    files_processed_json TEXT,
    model TEXT,
    prompt_version TEXT,
    analyzed_at TEXT,
    FOREIGN KEY(post_id) REFERENCES posts(id)
);
