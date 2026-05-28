-- Query 1: Canonical nutrition vectors for KNN / training
SELECT
    f.food_id,
    f.canonical_key,
    f.canonical_name_en,
    f.name_vi,
    g.group_code AS food_group_code,
    g.display_name AS food_group_name,
    n.basis_amount,
    n.basis_unit,
    n.energy_kcal,
    n.protein_g,
    n.fat_g,
    n.carbs_g,
    n.vitamin_a_mcg,
    n.beta_carotene_mcg,
    n.vitamin_c_mg,
    n.calcium_mg,
    n.iron_mg,
    n.zinc_mg,
    n.sodium_mg,
    n.cholesterol_mg,
    n.magnesium_mg,
    n.transfat_mg,
    f.source_name,
    f.source_priority,
    f.confidence_score,
    f.is_estimated
FROM foods f
JOIN food_groups g ON g.food_group_id = f.food_group_id
JOIN food_nutrients n ON n.food_id = f.food_id
ORDER BY f.food_id;

-- Query 2: Add binary expert tags for supervised / rule-based features
SELECT
    f.food_id,
    f.canonical_key,
    f.canonical_name_en,
    f.name_vi,
    g.group_code AS food_group_code,
    n.energy_kcal,
    n.protein_g,
    n.fat_g,
    n.carbs_g,
    n.basis_amount,
    n.basis_unit,
    MAX(CASE WHEN t.tag_code = 'is_vegan' THEN 1 ELSE 0 END) AS is_vegan,
    MAX(CASE WHEN t.tag_code = 'is_high_protein' THEN 1 ELSE 0 END) AS is_high_protein,
    MAX(CASE WHEN t.tag_code = 'is_diabetic_friendly' THEN 1 ELSE 0 END) AS is_diabetic_friendly,
    MAX(CASE WHEN t.tag_code = 'is_low_carb' THEN 1 ELSE 0 END) AS is_low_carb
FROM foods f
JOIN food_groups g ON g.food_group_id = f.food_group_id
JOIN food_nutrients n ON n.food_id = f.food_id
LEFT JOIN food_tag_mapping m ON m.food_id = f.food_id
LEFT JOIN food_tags t ON t.tag_id = m.tag_id
GROUP BY
    f.food_id,
    f.canonical_key,
    f.canonical_name_en,
    f.name_vi,
    g.group_code,
    n.energy_kcal,
    n.protein_g,
    n.fat_g,
    n.carbs_g,
    n.basis_amount,
    n.basis_unit
ORDER BY f.food_id;

-- Query 3: User-targeted candidate foods based on weight goal
-- Replace :user_id with the profile id from your application layer.
SELECT
    f.food_id,
    f.canonical_key,
    f.canonical_name_en,
    f.name_vi,
    g.display_name AS food_group_name,
    n.energy_kcal,
    n.protein_g,
    n.fat_g,
    n.carbs_g,
    u.weight_goal
FROM user_profiles u
CROSS JOIN foods f
JOIN food_groups g ON g.food_group_id = f.food_group_id
JOIN food_nutrients n ON n.food_id = f.food_id
WHERE u.user_id = :user_id
  AND (
      (u.weight_goal = 'lose' AND n.energy_kcal BETWEEN 50 AND 450)
      OR (u.weight_goal = 'maintain' AND n.energy_kcal BETWEEN 200 AND 650)
      OR (u.weight_goal = 'gain' AND n.energy_kcal BETWEEN 350 AND 900)
  )
ORDER BY n.protein_g DESC, n.energy_kcal ASC, f.source_priority ASC;

-- Query 4: Exact alias search for user queries
SELECT
    f.food_id,
    f.canonical_key,
    f.canonical_name_en,
    f.name_vi,
    a.alias_text,
    a.alias_type,
    g.display_name AS food_group_name,
    n.energy_kcal,
    n.protein_g,
    n.fat_g,
    n.carbs_g,
    a.is_preferred
FROM food_aliases a
JOIN foods f ON f.food_id = a.food_id
JOIN food_groups g ON g.food_group_id = f.food_group_id
JOIN food_nutrients n ON n.food_id = f.food_id
WHERE LOWER(a.alias_text) = LOWER(:query)
ORDER BY a.is_preferred DESC, f.source_priority ASC, f.food_id ASC;

-- Query 5: Fuzzy alias search using pg_trgm
-- Requires CREATE EXTENSION IF NOT EXISTS pg_trgm;
SELECT
    f.food_id,
    f.canonical_key,
    f.canonical_name_en,
    f.name_vi,
    a.alias_text,
    similarity(a.alias_text, :query) AS match_score,
    g.display_name AS food_group_name,
    n.energy_kcal,
    n.protein_g,
    n.fat_g,
    n.carbs_g
FROM food_aliases a
JOIN foods f ON f.food_id = a.food_id
JOIN food_groups g ON g.food_group_id = f.food_group_id
JOIN food_nutrients n ON n.food_id = f.food_id
WHERE similarity(a.alias_text, :query) >= 0.3
ORDER BY match_score DESC, a.is_preferred DESC, f.source_priority ASC
LIMIT 10;
