CREATE TABLE restore_quarantine (
    id TEXT PRIMARY KEY,
    backup_origin TEXT NOT NULL,
    backup_sha256 TEXT NOT NULL CHECK(length(backup_sha256)=64),
    restored_at TEXT NOT NULL,
    released_at TEXT
);
