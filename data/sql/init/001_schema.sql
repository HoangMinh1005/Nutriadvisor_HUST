-- Nutri-Advisor PostgreSQL schema
-- Canonical-food model:
-- 1) foods = one canonical record per food
-- 2) food_nutrients = normalized nutrient vector
-- 3) food_aliases = multilingual search aliases
-- 4) dataset_versions = snapshot metadata for reproducibility

BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Table: meal slots (used by meal planning only)
CREATE TABLE IF NOT EXISTS categories (
    category_id SMALLSERIAL PRIMARY KEY,
    category_code VARCHAR(20) NOT NULL UNIQUE
        CHECK (category_code IN ('breakfast', 'lunch', 'dinner', 'snack')),
    display_name VARCHAR(50) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Table: food_groups
-- Purpose: semantic food group for nutrition/search/training (different from meal slots)
CREATE TABLE IF NOT EXISTS food_groups (
    food_group_id SMALLSERIAL PRIMARY KEY,
    group_code VARCHAR(40) NOT NULL UNIQUE
        CHECK (group_code IN (
            'gia_cam',
            'thit_do',
            'hai_san',
            'rau_cu',
            'tinh_bot',
            'hat',
            'trai_cay',
            'sua_che_pham',
            'trung',
            'khac'
        )),
    display_name VARCHAR(80) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Table: dataset_versions
-- Purpose: frozen snapshots of each generated dataset version
CREATE TABLE IF NOT EXISTS dataset_versions (
    dataset_version_id BIGSERIAL PRIMARY KEY,
    version_tag VARCHAR(40) NOT NULL UNIQUE,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
    notes TEXT,
    source_hash VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Table: foods
-- Purpose: canonical food records, independent of nutrient vector
CREATE TABLE IF NOT EXISTS foods (
    food_id BIGSERIAL PRIMARY KEY,
    canonical_key VARCHAR(255) NOT NULL UNIQUE,
    canonical_name_en VARCHAR(255) NOT NULL,
    name_vi VARCHAR(255),
    food_group_id SMALLINT NOT NULL REFERENCES food_groups(food_group_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    source_name VARCHAR(40) NOT NULL DEFAULT 'NIN',
    source_priority SMALLINT NOT NULL DEFAULT 1
        CHECK (source_priority BETWEEN 1 AND 10),
    source_food_id VARCHAR(120),
    dataset_version_id BIGINT REFERENCES dataset_versions(dataset_version_id)
        ON UPDATE CASCADE
        ON DELETE SET NULL,
    confidence_score NUMERIC(4,3) NOT NULL DEFAULT 1.000
        CHECK (confidence_score >= 0 AND confidence_score <= 1),
    is_estimated BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Table: food_nutrients
-- Purpose: 1:1 nutrient vector for each canonical food
CREATE TABLE IF NOT EXISTS food_nutrients (
    food_id BIGINT PRIMARY KEY REFERENCES foods(food_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    basis_amount NUMERIC(8,2) NOT NULL DEFAULT 100.00
        CHECK (basis_amount > 0),
    basis_unit VARCHAR(20) NOT NULL DEFAULT 'g',
    energy_kcal NUMERIC(8,2) CHECK (energy_kcal >= 0),
    protein_g NUMERIC(8,2) CHECK (protein_g >= 0),
    fat_g NUMERIC(8,2) CHECK (fat_g >= 0),
    carbs_g NUMERIC(8,2) CHECK (carbs_g >= 0),
    vitamin_a_mcg NUMERIC(10,2) CHECK (vitamin_a_mcg >= 0),
    beta_carotene_mcg NUMERIC(10,2) CHECK (beta_carotene_mcg >= 0),
    vitamin_c_mg NUMERIC(8,2) CHECK (vitamin_c_mg >= 0),
    calcium_mg NUMERIC(8,2) CHECK (calcium_mg >= 0),
    iron_mg NUMERIC(8,2) CHECK (iron_mg >= 0),
    zinc_mg NUMERIC(8,2) CHECK (zinc_mg >= 0),
    sodium_mg NUMERIC(10,2) CHECK (sodium_mg >= 0),
    cholesterol_mg NUMERIC(8,2) CHECK (cholesterol_mg >= 0),
    magnesium_mg NUMERIC(8,2) CHECK (magnesium_mg >= 0),
    transfat_mg NUMERIC(8,2) CHECK (transfat_mg >= 0),
    nutrient_source VARCHAR(40) NOT NULL DEFAULT 'NIN',
    nutrient_confidence NUMERIC(4,3) NOT NULL DEFAULT 1.000
        CHECK (nutrient_confidence >= 0 AND nutrient_confidence <= 1),
    dataset_version_id BIGINT REFERENCES dataset_versions(dataset_version_id)
        ON UPDATE CASCADE
        ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Table: food_aliases
-- Purpose: multilingual search aliases and display variants
CREATE TABLE IF NOT EXISTS food_aliases (
    alias_id BIGSERIAL PRIMARY KEY,
    food_id BIGINT NOT NULL REFERENCES foods(food_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    alias_text VARCHAR(255) NOT NULL,
    alias_lang VARCHAR(10) NOT NULL DEFAULT 'vi',
    alias_type VARCHAR(30) NOT NULL
        CHECK (alias_type IN ('display', 'non_diacritic', 'synonym', 'regional', 'misspelling', 'short_name', 'brand_variant')),
    is_preferred BOOLEAN NOT NULL DEFAULT FALSE,
    source_name VARCHAR(40) NOT NULL,
    source_priority SMALLINT NOT NULL DEFAULT 1
        CHECK (source_priority BETWEEN 1 AND 10),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_food_alias UNIQUE (food_id, alias_lang, alias_text)
);

-- Table: food_tags
-- Purpose: expert-system labels used by rule logic and filtering
CREATE TABLE IF NOT EXISTS food_tags (
    tag_id SERIAL PRIMARY KEY,
    tag_code VARCHAR(60) NOT NULL UNIQUE,
    tag_name VARCHAR(100) NOT NULL,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (tag_code ~ '^[a-z0-9_]+$')
);

-- Table: food_tag_mapping
-- Purpose: many-to-many relation between foods and expert tags
CREATE TABLE IF NOT EXISTS food_tag_mapping (
    food_id BIGINT NOT NULL REFERENCES foods(food_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES food_tags(tag_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    confidence NUMERIC(4,3) NOT NULL DEFAULT 1.000
        CHECK (confidence >= 0 AND confidence <= 1),
    assigned_by VARCHAR(30) NOT NULL DEFAULT 'rule_engine',
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (food_id, tag_id)
);

-- Table: food_search_logs
-- Purpose: capture search misses / fuzzy hits for iterative alias expansion and training feedback
CREATE TABLE IF NOT EXISTS food_search_logs (
    search_log_id BIGSERIAL PRIMARY KEY,
    query_text VARCHAR(255) NOT NULL,
    normalized_query VARCHAR(255) NOT NULL,
    matched_food_id BIGINT REFERENCES foods(food_id)
        ON UPDATE CASCADE
        ON DELETE SET NULL,
    match_tier VARCHAR(20) NOT NULL
        CHECK (match_tier IN ('exact', 'fuzzy', 'fallback', 'none')),
    confidence_score NUMERIC(4,3) NOT NULL DEFAULT 0.000
        CHECK (confidence_score >= 0 AND confidence_score <= 1),
    user_locale VARCHAR(10) NOT NULL DEFAULT 'vi',
    user_action VARCHAR(20) NOT NULL DEFAULT 'search'
        CHECK (user_action IN ('search', 'select', 'dismiss', 'estimate')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Table: user_profiles
-- Purpose: user anthropometric data, allergies, and nutrition goal
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id BIGSERIAL PRIMARY KEY,
    full_name VARCHAR(120) NOT NULL,
    email VARCHAR(255) UNIQUE,
    gender VARCHAR(20) NOT NULL DEFAULT 'unknown'
        CHECK (gender IN ('male', 'female', 'other', 'unknown')),
    birth_year INTEGER CHECK (
        birth_year IS NULL
        OR (birth_year BETWEEN 1900 AND EXTRACT(YEAR FROM NOW())::INT)
    ),
    height_cm NUMERIC(5,2) CHECK (height_cm IS NULL OR height_cm > 0),
    weight_kg NUMERIC(5,2) CHECK (weight_kg IS NULL OR weight_kg > 0),
    bmi NUMERIC(5,2)
        GENERATED ALWAYS AS (
            CASE
                WHEN height_cm IS NULL OR weight_kg IS NULL OR height_cm = 0 THEN NULL
                ELSE weight_kg / POWER(height_cm / 100.0, 2)
            END
        ) STORED,
    allergies TEXT[] NOT NULL DEFAULT '{}',
    weight_goal VARCHAR(20) NOT NULL
        CHECK (weight_goal IN ('lose', 'maintain', 'gain')),
    daily_calorie_target INTEGER CHECK (
        daily_calorie_target IS NULL OR daily_calorie_target > 0
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Table: meal_plans
-- Purpose: 7-day meal schedule generated mainly by CSP planner
CREATE TABLE IF NOT EXISTS meal_plans (
    meal_plan_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES user_profiles(user_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    food_id BIGINT NOT NULL REFERENCES foods(food_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    plan_date DATE NOT NULL,
    meal_slot_code VARCHAR(20) NOT NULL REFERENCES categories(category_code)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    portion_multiplier NUMERIC(4,2) NOT NULL DEFAULT 1.00
        CHECK (portion_multiplier > 0),
    generated_by VARCHAR(20) NOT NULL DEFAULT 'csp'
        CHECK (generated_by IN ('csp', 'logic', 'knn', 'manual')),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_meal_plan_per_slot UNIQUE (user_id, plan_date, meal_slot_code)
);

-- Helpful indexes for training, search, and joins
CREATE INDEX IF NOT EXISTS idx_foods_food_group_id ON foods(food_group_id);
CREATE INDEX IF NOT EXISTS idx_foods_source_priority ON foods(source_priority);
CREATE INDEX IF NOT EXISTS idx_foods_canonical_name_en ON foods(canonical_name_en);
CREATE INDEX IF NOT EXISTS idx_foods_canonical_key ON foods(canonical_key);

CREATE INDEX IF NOT EXISTS idx_food_nutrients_energy_kcal ON food_nutrients(energy_kcal);
CREATE INDEX IF NOT EXISTS idx_food_nutrients_protein_g ON food_nutrients(protein_g);

CREATE INDEX IF NOT EXISTS idx_food_aliases_food_id ON food_aliases(food_id);
CREATE INDEX IF NOT EXISTS idx_food_aliases_alias_lang ON food_aliases(alias_lang);
CREATE INDEX IF NOT EXISTS idx_food_aliases_alias_text_trgm ON food_aliases USING GIN (alias_text gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_food_tag_mapping_tag_id ON food_tag_mapping(tag_id);

CREATE INDEX IF NOT EXISTS idx_food_search_logs_created_at ON food_search_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_food_search_logs_normalized_query ON food_search_logs(normalized_query);

CREATE INDEX IF NOT EXISTS idx_user_profiles_weight_goal ON user_profiles(weight_goal);
CREATE INDEX IF NOT EXISTS idx_user_profiles_allergies_gin ON user_profiles USING GIN (allergies);

CREATE INDEX IF NOT EXISTS idx_meal_plans_user_date ON meal_plans(user_id, plan_date);
CREATE INDEX IF NOT EXISTS idx_meal_plans_food_id ON meal_plans(food_id);
CREATE INDEX IF NOT EXISTS idx_meal_plans_meal_slot_code ON meal_plans(meal_slot_code);

COMMIT;
