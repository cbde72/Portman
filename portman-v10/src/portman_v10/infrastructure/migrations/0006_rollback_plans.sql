CREATE TABLE rollback_plans (
    plan_id TEXT PRIMARY KEY,
    data_revision INTEGER NOT NULL CHECK (data_revision >= 1),
    import_ids_json TEXT NOT NULL CHECK (json_valid(import_ids_json)),
    created_at TEXT NOT NULL
) STRICT;

PRAGMA user_version = 6;
