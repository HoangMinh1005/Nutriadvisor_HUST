-- Add raw source row staging table for full lineage preservation.

BEGIN;

CREATE TABLE IF NOT EXISTS food_source_rows (
    source_row_id BIGSERIAL PRIMARY KEY,
    dataset_version_id BIGINT NOT NULL REFERENCES dataset_versions(dataset_version_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    source_name VARCHAR(40) NOT NULL,
    source_file VARCHAR(255) NOT NULL,
    source_row_number INTEGER NOT NULL,
    canonical_key VARCHAR(255),
    raw_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_food_source_row UNIQUE (dataset_version_id, source_name, source_file, source_row_number)
);

CREATE INDEX IF NOT EXISTS idx_food_source_rows_dataset_version_id ON food_source_rows(dataset_version_id);
CREATE INDEX IF NOT EXISTS idx_food_source_rows_canonical_key ON food_source_rows(canonical_key);

COMMIT;
