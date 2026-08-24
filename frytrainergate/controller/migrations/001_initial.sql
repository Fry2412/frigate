CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS pairing_tokens (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    verifier TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    consumed_at REAL,
    revoked_at REAL
);

CREATE TABLE IF NOT EXISTS runners (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    credential_hash TEXT NOT NULL,
    credential_version INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    revoked_at REAL,
    created_at REAL NOT NULL,
    last_seen_at REAL,
    last_ip TEXT,
    runner_version TEXT NOT NULL DEFAULT 'unknown',
    protocol_version TEXT NOT NULL DEFAULT '1.0',
    platform TEXT NOT NULL DEFAULT 'unknown',
    hostname TEXT NOT NULL DEFAULT 'unknown',
    capabilities_json TEXT NOT NULL DEFAULT '{}',
    current_job_id TEXT,
    status TEXT NOT NULL DEFAULT 'OFFLINE'
);
CREATE INDEX IF NOT EXISTS runners_last_seen_idx ON runners(last_seen_at);

CREATE TABLE IF NOT EXISTS datasets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    created_at REAL NOT NULL,
    version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS dataset_images (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    storage_name TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    source_camera TEXT,
    captured_at REAL,
    width INTEGER,
    height INTEGER,
    size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    annotations_json TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS dataset_images_dataset_idx ON dataset_images(dataset_id);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    dataset_id TEXT NOT NULL REFERENCES datasets(id),
    assigned_runner_id TEXT REFERENCES runners(id),
    state TEXT NOT NULL,
    backend TEXT NOT NULL,
    config_json TEXT NOT NULL,
    requirements_json TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    current_epoch INTEGER,
    total_epochs INTEGER,
    status_message TEXT,
    failure_reason TEXT,
    metrics_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    started_at REAL,
    completed_at REAL,
    updated_at REAL NOT NULL,
    cancellation_requested INTEGER NOT NULL DEFAULT 0,
    protocol_version TEXT NOT NULL DEFAULT '1.0'
);
CREATE INDEX IF NOT EXISTS jobs_state_idx ON jobs(state);
CREATE INDEX IF NOT EXISTS jobs_runner_idx ON jobs(assigned_runner_id);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    runner_id TEXT NOT NULL REFERENCES runners(id),
    filename TEXT NOT NULL,
    storage_name TEXT NOT NULL,
    model_format TEXT NOT NULL,
    size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    created_at REAL NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS artifacts_job_idx ON artifacts(job_id);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    timestamp REAL NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT,
    action TEXT NOT NULL,
    job_id TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS audit_events_timestamp_idx ON audit_events(timestamp);

