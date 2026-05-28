-- Seed food groups used for canonical food classification
INSERT INTO food_groups (group_code, display_name)
VALUES
    ('gia_cam', 'Gia cầm'),
    ('thit_do', 'Thịt đỏ'),
    ('hai_san', 'Hải sản'),
    ('rau_cu', 'Rau củ'),
    ('tinh_bot', 'Tinh bột'),
    ('hat', 'Hạt'),
    ('trai_cay', 'Trái cây'),
    ('sua_che_pham', 'Sữa và chế phẩm'),
    ('trung', 'Trứng'),
    ('khac', 'Khác')
ON CONFLICT (group_code) DO UPDATE
SET display_name = EXCLUDED.display_name;
