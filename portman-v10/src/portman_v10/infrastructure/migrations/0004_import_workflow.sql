CREATE TABLE import_jobs (
    job_id TEXT PRIMARY KEY,
    import_id TEXT NOT NULL UNIQUE REFERENCES imports(import_id) ON DELETE RESTRICT,
    state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'needs_review', 'completed', 'failed', 'cancelled')),
    progress INTEGER NOT NULL CHECK (progress BETWEEN 0 AND 100),
    revision INTEGER NOT NULL CHECK (revision >= 1),
    document_count INTEGER NOT NULL CHECK (document_count >= 1),
    completed_documents INTEGER NOT NULL CHECK (completed_documents BETWEEN 0 AND document_count),
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
    error_code TEXT,
    account_hint TEXT,
    updated_at TEXT NOT NULL
) STRICT;

CREATE TABLE import_job_documents (
    job_id TEXT NOT NULL REFERENCES import_jobs(job_id) ON DELETE RESTRICT,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    status TEXT NOT NULL CHECK (status IN ('queued', 'parsed', 'needs_review', 'information', 'unsupported', 'failed', 'cancelled', 'duplicate_file')),
    document_type TEXT,
    plugin_id TEXT,
    plugin_version TEXT,
    parser_package_version TEXT,
    parser_api_version TEXT,
    handler_id TEXT,
    parser_schema_version TEXT,
    extraction_preparation_version TEXT,
    warning_messages_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(warning_messages_json)),
    error_code TEXT,
    PRIMARY KEY(job_id, document_id),
    UNIQUE(job_id, ordinal)
) STRICT;

CREATE TABLE import_previews (
    import_id TEXT PRIMARY KEY REFERENCES imports(import_id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    data_revision INTEGER NOT NULL CHECK (data_revision >= 1),
    normalized_preview_json TEXT NOT NULL CHECK (json_valid(normalized_preview_json)),
    updated_at TEXT NOT NULL
) STRICT;

CREATE TABLE import_review_decisions (
    import_id TEXT NOT NULL REFERENCES imports(import_id) ON DELETE RESTRICT,
    candidate_id TEXT NOT NULL,
    candidate_revision INTEGER NOT NULL CHECK (candidate_revision >= 1),
    preview_revision INTEGER NOT NULL CHECK (preview_revision >= 1),
    decision_json TEXT NOT NULL CHECK (json_valid(decision_json)),
    created_at TEXT NOT NULL,
    PRIMARY KEY(import_id, candidate_id, preview_revision)
) STRICT;

CREATE INDEX import_jobs_state ON import_jobs(state, updated_at);
ALTER TABLE imports ADD COLUMN parser_api_version TEXT;
PRAGMA user_version = 4;
