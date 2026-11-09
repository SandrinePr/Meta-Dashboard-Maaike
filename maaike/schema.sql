-- Maaike's client database. Do not apply this file to social_search.db.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    meta_status TEXT NOT NULL DEFAULT 'not_connected',
    meta_status_detail TEXT,
    meta_page_id TEXT,
    meta_page_name TEXT,
    meta_ig_user_id TEXT,
    meta_ig_username TEXT,
    meta_connected_at TEXT,
    meta_token_expires_at TEXT,
    meta_last_checked_at TEXT,
    last_fetch_status TEXT,
    last_fetch_detail TEXT,
    last_fetch_at TEXT,
    last_fetch_from TEXT,
    last_fetch_until TEXT,
    last_fetch_instagram INTEGER,
    last_fetch_facebook INTEGER,
    UNIQUE(name COLLATE NOCASE)
);

-- Tokens stay in this table. Screens never select these columns.
CREATE TABLE IF NOT EXISTS client_meta_secrets (
    client_id INTEGER PRIMARY KEY,
    user_access_token TEXT,
    page_access_token TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(client_id) REFERENCES clients(id)
);

CREATE TABLE IF NOT EXISTS content_formats (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL,
    name TEXT NOT NULL COLLATE NOCASE,
    explanation TEXT NOT NULL DEFAULT '',
    example_url TEXT,
    status TEXT,
    usage_count INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(client_id, name COLLATE NOCASE),
    FOREIGN KEY(client_id) REFERENCES clients(id)
);

CREATE TABLE IF NOT EXISTS content_pillars (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL,
    name TEXT NOT NULL COLLATE NOCASE,
    explanation TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(client_id, name COLLATE NOCASE),
    FOREIGN KEY(client_id) REFERENCES clients(id)
);

CREATE TABLE IF NOT EXISTS content_hooks (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL,
    name TEXT NOT NULL COLLATE NOCASE,
    explanation TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(client_id, name COLLATE NOCASE),
    FOREIGN KEY(client_id) REFERENCES clients(id)
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    external_id TEXT NOT NULL,
    published_at TEXT NOT NULL,
    content_kind TEXT,
    permalink TEXT,
    views INTEGER,
    likes INTEGER,
    comments INTEGER,
    shares INTEGER,
    saves INTEGER,
    clicks INTEGER,
    reach INTEGER,
    account_name TEXT,
    caption TEXT,
    media_urls TEXT,
    last_synced_at TEXT,
    UNIQUE(client_id, platform, external_id),
    FOREIGN KEY(client_id) REFERENCES clients(id)
);

CREATE TABLE IF NOT EXISTS post_editorial (
    post_id INTEGER PRIMARY KEY,
    format_id INTEGER,
    pillar_id INTEGER,
    hook TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    FOREIGN KEY(post_id) REFERENCES posts(id),
    FOREIGN KEY(format_id) REFERENCES content_formats(id),
    FOREIGN KEY(pillar_id) REFERENCES content_pillars(id)
);

-- One row per post and metric. A failed later fetch keeps the last measured value.
CREATE TABLE IF NOT EXISTS post_metrics (
    post_id INTEGER NOT NULL,
    metric_name TEXT NOT NULL,
    value INTEGER,
    availability TEXT NOT NULL,
    source_name TEXT NOT NULL DEFAULT '',
    measured_at TEXT,
    PRIMARY KEY (post_id, metric_name),
    FOREIGN KEY(post_id) REFERENCES posts(id)
);

-- Comment bodies for Filter posts (Original). Counts on posts stay separate metrics.
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL,
    post_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    external_id TEXT NOT NULL,
    text TEXT,
    permalink TEXT,
    published_at TEXT,
    author_name TEXT,
    UNIQUE(client_id, platform, external_id),
    FOREIGN KEY(client_id) REFERENCES clients(id),
    FOREIGN KEY(post_id) REFERENCES posts(id)
);

CREATE TABLE IF NOT EXISTS client_comparison_preferences (
    client_id INTEGER PRIMARY KEY,
    competitors_json TEXT NOT NULL DEFAULT '[]',
    period_key TEXT NOT NULL DEFAULT '3m',
    custom_start TEXT,
    custom_end TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(client_id) REFERENCES clients(id)
);

CREATE INDEX IF NOT EXISTS idx_maaike_posts_client_published
    ON posts(client_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_maaike_formats_client
    ON content_formats(client_id, name);
CREATE INDEX IF NOT EXISTS idx_maaike_pillars_client
    ON content_pillars(client_id, name);
CREATE INDEX IF NOT EXISTS idx_maaike_hooks_client
    ON content_hooks(client_id, name);
CREATE INDEX IF NOT EXISTS idx_maaike_comments_client_platform
    ON comments(client_id, platform);

-- Excel/strategy extensions (Red Rock Logs import). Meta posts stay untouched by default.
CREATE TABLE IF NOT EXISTS post_assessments (
    id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    source_label TEXT NOT NULL,
    rating_text TEXT,
    rating_fill TEXT,
    score_value REAL,
    rating_origin TEXT,
    score_origin TEXT,
    rating_missing_reason TEXT,
    score_missing_reason TEXT,
    insight_text TEXT,
    action_text TEXT,
    source_file TEXT,
    source_sheet TEXT,
    source_row INTEGER,
    imported_at TEXT NOT NULL,
    FOREIGN KEY(post_id) REFERENCES posts(id)
);

CREATE TABLE IF NOT EXISTS client_rating_settings (
    client_id INTEGER PRIMARY KEY,
    active INTEGER NOT NULL DEFAULT 0,
    profile_name TEXT NOT NULL DEFAULT '',
    is_provisional INTEGER NOT NULL DEFAULT 1,
    formula_key TEXT NOT NULL DEFAULT '',
    settings_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    FOREIGN KEY(client_id) REFERENCES clients(id)
);

CREATE TABLE IF NOT EXISTS post_metric_readings (
    id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL,
    metric_name TEXT NOT NULL,
    value INTEGER,
    availability TEXT NOT NULL,
    source_name TEXT NOT NULL,
    measured_at TEXT,
    imported_at TEXT NOT NULL,
    source_file TEXT,
    source_sheet TEXT,
    source_row INTEGER,
    FOREIGN KEY(post_id) REFERENCES posts(id)
);

CREATE TABLE IF NOT EXISTS post_import_links (
    post_id INTEGER NOT NULL,
    source_file TEXT NOT NULL,
    source_sheet TEXT NOT NULL,
    source_row INTEGER NOT NULL,
    imported_at TEXT NOT NULL,
    platform_label_original TEXT,
    excel_published_at TEXT,
    PRIMARY KEY (post_id, source_file, source_sheet, source_row),
    FOREIGN KEY(post_id) REFERENCES posts(id)
);

CREATE TABLE IF NOT EXISTS excel_import_runs (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL,
    file_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    summary_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(client_id) REFERENCES clients(id)
);

CREATE TABLE IF NOT EXISTS excel_import_rows (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL,
    excel_row INTEGER NOT NULL,
    status TEXT NOT NULL,
    post_id INTEGER,
    detail_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(run_id) REFERENCES excel_import_runs(id),
    FOREIGN KEY(post_id) REFERENCES posts(id)
);

CREATE TABLE IF NOT EXISTS client_strategy (
    client_id INTEGER PRIMARY KEY,
    account_info_json TEXT NOT NULL DEFAULT '{}',
    start_answers_json TEXT NOT NULL DEFAULT '{}',
    strategy_fields_json TEXT NOT NULL DEFAULT '{}',
    source_notes_json TEXT NOT NULL DEFAULT '[]',
    completed_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(client_id) REFERENCES clients(id)
);

CREATE TABLE IF NOT EXISTS client_targets (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL,
    account_key TEXT NOT NULL DEFAULT '',
    platform TEXT NOT NULL DEFAULT '',
    metric_name TEXT NOT NULL,
    target_kind TEXT NOT NULL DEFAULT 'absolute',
    baseline_value REAL,
    target_value REAL,
    unit TEXT NOT NULL DEFAULT '',
    period_year INTEGER,
    period_quarter INTEGER,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(client_id) REFERENCES clients(id)
);

CREATE TABLE IF NOT EXISTS client_target_measurements (
    id INTEGER PRIMARY KEY,
    target_id INTEGER NOT NULL,
    measured_at TEXT NOT NULL,
    value REAL NOT NULL,
    source_name TEXT NOT NULL DEFAULT 'manual',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY(target_id) REFERENCES client_targets(id)
);

CREATE INDEX IF NOT EXISTS idx_maaike_assessments_post
    ON post_assessments(post_id, source);
CREATE INDEX IF NOT EXISTS idx_maaike_metric_readings_post
    ON post_metric_readings(post_id, metric_name);

-- AI trial prep + cost registration (no paid calls required to create these rows).
CREATE TABLE IF NOT EXISTS ai_prompt_catalog (
    id INTEGER PRIMARY KEY,
    purpose TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_label TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    body_text TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'catalogued',
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    UNIQUE(purpose, source_path, prompt_version)
);

CREATE TABLE IF NOT EXISTS ai_cost_rates (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    currency TEXT NOT NULL,
    input_per_1m REAL,
    output_per_1m REAL,
    rate_date TEXT NOT NULL,
    source_url TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    UNIQUE(provider, model, rate_date)
);

CREATE TABLE IF NOT EXISTS ai_trial_runs (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL,
    trial_key TEXT NOT NULL,
    status TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT '',
    prepared_at TEXT NOT NULL,
    executed_at TEXT,
    capability_json TEXT NOT NULL DEFAULT '{}',
    estimate_json TEXT NOT NULL DEFAULT '{}',
    notes_json TEXT NOT NULL DEFAULT '[]',
    UNIQUE(client_id, trial_key),
    FOREIGN KEY(client_id) REFERENCES clients(id)
);

CREATE TABLE IF NOT EXISTS ai_trial_posts (
    id INTEGER PRIMARY KEY,
    trial_run_id INTEGER NOT NULL,
    post_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    selection_reason TEXT NOT NULL DEFAULT '',
    request_payload_json TEXT NOT NULL DEFAULT '{}',
    media_access_json TEXT NOT NULL DEFAULT '{}',
    ai_observations_json TEXT NOT NULL DEFAULT '[]',
    ai_format_code TEXT NOT NULL DEFAULT '',
    ai_format_rationale TEXT NOT NULL DEFAULT '',
    ai_format_uncertainty TEXT NOT NULL DEFAULT '',
    ai_pillar TEXT NOT NULL DEFAULT '',
    ai_hook TEXT NOT NULL DEFAULT '',
    ai_insight TEXT NOT NULL DEFAULT '',
    ai_action TEXT NOT NULL DEFAULT '',
    human_feedback TEXT NOT NULL DEFAULT '',
    joint_verdict TEXT NOT NULL DEFAULT '',
    excel_assessment_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'prepared',
    UNIQUE(trial_run_id, post_id),
    FOREIGN KEY(trial_run_id) REFERENCES ai_trial_runs(id),
    FOREIGN KEY(post_id) REFERENCES posts(id)
);

CREATE TABLE IF NOT EXISTS ai_usage_events (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL,
    post_id INTEGER,
    trial_run_id INTEGER,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    extra_tool_cost REAL,
    extra_media_cost REAL,
    currency TEXT,
    estimated_cost REAL,
    actual_cost REAL,
    cost_known INTEGER NOT NULL DEFAULT 0,
    rate_date TEXT,
    notes TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(client_id) REFERENCES clients(id),
    FOREIGN KEY(post_id) REFERENCES posts(id),
    FOREIGN KEY(trial_run_id) REFERENCES ai_trial_runs(id)
);

-- Human feedback bound to a specific AI execution (survives re-prepare of other runs).
CREATE TABLE IF NOT EXISTS ai_analysis_feedback (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL,
    post_id INTEGER NOT NULL,
    trial_run_id INTEGER,
    execution_key TEXT NOT NULL,
    usability TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    corrected_format TEXT NOT NULL DEFAULT '',
    corrected_pillar TEXT NOT NULL DEFAULT '',
    corrected_hook TEXT NOT NULL DEFAULT '',
    final_verdict TEXT NOT NULL DEFAULT '',
    final_verdict_confirmed INTEGER NOT NULL DEFAULT 0,
    final_verdict_confirmed_at TEXT,
    reviewer_name TEXT NOT NULL DEFAULT '',
    item_decisions_json TEXT NOT NULL DEFAULT '[]',
    final_version_text TEXT NOT NULL DEFAULT '',
    review_status TEXT NOT NULL DEFAULT '',
    ai_original_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(client_id, post_id, execution_key),
    FOREIGN KEY(client_id) REFERENCES clients(id),
    FOREIGN KEY(post_id) REFERENCES posts(id)
);

CREATE TABLE IF NOT EXISTS post_editorial_revisions (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL,
    post_id INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    old_value TEXT NOT NULL DEFAULT '',
    new_value TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL,
    source_detail TEXT NOT NULL DEFAULT '',
    trial_run_id INTEGER,
    feedback_id INTEGER,
    adopted_at TEXT NOT NULL,
    FOREIGN KEY(client_id) REFERENCES clients(id),
    FOREIGN KEY(post_id) REFERENCES posts(id)
);

-- Local uploads (Meta not required).
CREATE TABLE IF NOT EXISTS post_media_assets (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL,
    post_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    kind TEXT NOT NULL,
    original_name TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    mime_type TEXT NOT NULL DEFAULT '',
    byte_size INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'upload',
    created_at TEXT NOT NULL,
    UNIQUE(client_id, post_id, position),
    FOREIGN KEY(client_id) REFERENCES clients(id),
    FOREIGN KEY(post_id) REFERENCES posts(id)
);

-- Trend- and client reports (versions kept; open/reload never starts AI).
CREATE TABLE IF NOT EXISTS client_reports (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL,
    report_type TEXT NOT NULL,
    period_year INTEGER NOT NULL,
    period_month INTEGER NOT NULL,
    planning_year INTEGER,
    planning_month INTEGER,
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    supersedes_id INTEGER,
    prompt_version TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    prepared_at TEXT,
    executed_at TEXT,
    input_snapshot_json TEXT NOT NULL DEFAULT '{}',
    sources_json TEXT NOT NULL DEFAULT '[]',
    body_json TEXT NOT NULL DEFAULT '{}',
    estimate_json TEXT NOT NULL DEFAULT '{}',
    usage_json TEXT NOT NULL DEFAULT '{}',
    linked_trend_report_id INTEGER,
    error_text TEXT NOT NULL DEFAULT '',
    is_mock INTEGER NOT NULL DEFAULT 0,
    notes_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(client_id) REFERENCES clients(id),
    FOREIGN KEY(supersedes_id) REFERENCES client_reports(id),
    FOREIGN KEY(linked_trend_report_id) REFERENCES client_reports(id)
);

CREATE TABLE IF NOT EXISTS client_report_sources (
    id INTEGER PRIMARY KEY,
    report_id INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    consulted_at TEXT NOT NULL,
    excerpt TEXT NOT NULL DEFAULT '',
    source_kind TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL,
    FOREIGN KEY(report_id) REFERENCES client_reports(id)
);

-- Medewerkercontrole per rapport-uitvoering (AI-origineel / feedback / eindversie gescheiden).
CREATE TABLE IF NOT EXISTS client_report_reviews (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL,
    report_id INTEGER NOT NULL,
    execution_key TEXT NOT NULL,
    ai_original_json TEXT NOT NULL DEFAULT '{}',
    item_feedback_json TEXT NOT NULL DEFAULT '[]',
    final_version_text TEXT NOT NULL DEFAULT '',
    reviewer_name TEXT NOT NULL DEFAULT '',
    review_status TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT,
    approved_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(client_id, report_id, execution_key),
    FOREIGN KEY(client_id) REFERENCES clients(id),
    FOREIGN KEY(report_id) REFERENCES client_reports(id)
);

CREATE INDEX IF NOT EXISTS idx_report_reviews_report
    ON client_report_reviews(client_id, report_id, execution_key);
