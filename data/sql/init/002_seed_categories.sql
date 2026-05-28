-- Seed default meal slots for meal planning
INSERT INTO categories (category_code, display_name)
VALUES
    ('breakfast', 'Breakfast'),
    ('lunch', 'Lunch'),
    ('dinner', 'Dinner'),
    ('snack', 'Snack')
ON CONFLICT (category_code) DO UPDATE
SET display_name = EXCLUDED.display_name;
