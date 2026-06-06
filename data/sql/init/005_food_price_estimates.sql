-- Add canonical food price estimates table.

BEGIN;

CREATE TABLE IF NOT EXISTS food_price_estimates (
    food_id BIGINT PRIMARY KEY REFERENCES foods(food_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    price_100g_vnd INTEGER NOT NULL
        CHECK (price_100g_vnd > 0),
    price_category VARCHAR(80) NOT NULL,
    price_source VARCHAR(40) NOT NULL DEFAULT 'gemini',
    model_name VARCHAR(80),
    estimate_version VARCHAR(40),
    confidence_score NUMERIC(4,3) NOT NULL DEFAULT 0.700
        CHECK (confidence_score >= 0 AND confidence_score <= 1),
    source_key VARCHAR(255),
    source_name_vi VARCHAR(255),
    dataset_version_id BIGINT REFERENCES dataset_versions(dataset_version_id)
        ON UPDATE CASCADE
        ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_food_price_estimates_price_100g_vnd ON food_price_estimates(price_100g_vnd);
CREATE INDEX IF NOT EXISTS idx_food_price_estimates_price_category ON food_price_estimates(price_category);
CREATE INDEX IF NOT EXISTS idx_food_price_estimates_price_source ON food_price_estimates(price_source);

COMMIT;
