CREATE TABLE IF NOT EXISTS dataset_versions (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    image_count INTEGER NOT NULL DEFAULT 0,
    total_size INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    UNIQUE(dataset_id, version)
);
CREATE INDEX IF NOT EXISTS dataset_versions_dataset_idx
    ON dataset_versions(dataset_id, version);

INSERT OR IGNORE INTO dataset_versions
    (id, dataset_id, version, image_count, total_size, created_at)
SELECT
    lower(hex(randomblob(16))),
    id,
    version,
    0,
    0,
    created_at
FROM datasets;
