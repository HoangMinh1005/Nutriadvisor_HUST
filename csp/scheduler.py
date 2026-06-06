"""Scheduler core utilizing backtracking and automated progressive multi-stage constraint relaxation."""
from __future__ import annotations

import logging
import os
import random
from collections import Counter
from typing import Any, Dict, List, Set

import psycopg
from constraint import Problem

from .constraints import NutrientConstraints
from .objective import score_meal_plan
from .classification import (
    classify_food,
    get_dynamic_tags,
    is_single_bowl_meal,
    is_offal_or_blood,
    is_clean_protein_gym,
    is_gym_blacklisted,
    get_max_serving_g,
    is_high_quality_protein,
    is_standalone_main_dish,
    get_food_role,
    clean_category,
)


class MealScheduler:
    """Ties together constraints and solver logic to produce 7-day personal meal plans using pure Database layers."""

    def __init__(
        self,
        user_profile: Dict[str, Any],
        available_foods: List[Dict[str, Any]] | None = None,
        db_url: str | None = None,
        candidate_food_ids: List[int] | None = None,
    ) -> None:
        self.user = user_profile
        self.db_url = db_url if db_url is not None else os.getenv("DATABASE_URL")
        self.candidate_food_ids = candidate_food_ids
        
        self.is_gym = (
            float(self.user.get("daily_calorie_target") or 0.0) >= 2800.0
            or str(self.user.get("goal") or "").lower() == "gym"
            or "gym" in str(self.user.get("user_message") or "").lower()
        )
        
        self.foods = available_foods or self._load_foods()
        for f in self.foods:
            f["max_serving_g"] = get_max_serving_g(f, self.is_gym)
            
        self.food_by_id = {int(f["food_id"]): f for f in self.foods}

    def _load_foods(self) -> List[Dict[str, Any]]:
        """Strictly load candidate foods from Postgres database without offline file fallbacks."""
        if not self.db_url:
            raise ValueError("DATABASE_URL environment variable is missing or empty. Postgres connection aborted.")

        foods_list: List[Dict[str, Any]] = []
        try:
            query = """
                SELECT 
                    f.food_id, f.canonical_key, f.canonical_name_en, f.name_vi,
                    n.energy_kcal, n.protein_g, n.fat_g, n.carbs_g,
                    COALESCE(f.price_100g_vnd, 15000) AS price_100g,
                    g.group_code AS category,
                    f.source_name, f.source_priority,
                    f.tags, f.meal_role
                FROM foods f
                JOIN food_nutrients n ON f.food_id = n.food_id
                JOIN food_groups g ON f.food_group_id = g.food_group_id
                WHERE f.is_active = TRUE;
            """
            with psycopg.connect(self.db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(query)
                    for row in cur.fetchall():
                        fid, key, name_en, name_vi, cal, prot, fat, carb, price, category, src_name, src_priority, tags_array, meal_role = row
                        row_tags = set(tags_array) if tags_array else set()
                        
                        # Chạy phân loại động tại chỗ để ghi đè dữ liệu thô chưa dọn sạch từ DB
                        assigned_role = classify_food({"name_vi": name_vi, "category": category, "tags": row_tags})
                        
                        # XỬ LÝ LỖI NHẬP SAI SỐ GIÁ TIỀN TRONG POSTGRES
                        actual_price = float(price or 15000)
                        if actual_price > 50000: 
                            actual_price = 22000.0  # Điều chỉnh giá thịt thăn/bắp bò đắt đỏ về mức thực tế bình quân

                        foods_list.append({
                            "food_id": int(fid),
                            "canonical_key": key,
                            "canonical_name_en": name_en,
                            "name_vi": name_vi,
                            "calories": float(cal or 0),
                            "protein": float(prot or 0),
                            "fat": float(fat or 0),
                            "carbs": float(carb or 0),
                            "cost_vnd_100g": actual_price,
                            "category": category,
                            "source_name": src_name,
                            "source_priority": int(src_priority or 1),
                            "tags": row_tags,
                            "meal_role": assigned_role,
                        })
            return foods_list
        except Exception as exc:
            raise ConnectionError(f"CRITICAL: Failed to load food records natively from PostgreSQL: {exc}")

    def solve_with_relaxation(self, max_attempts: int = 4) -> Dict[str, Any]:
        """Solver orchestration wrapping the auto-relaxation loops."""
        constraints = NutrientConstraints(
            daily_calorie_target=float(self.user.get("daily_calorie_target") or 1800.0),
            calorie_tolerance_pct=0.12,
            macro_ratios=self.user.get("macro_ratios"),
            macro_tolerance_pct=0.12,
            allergies=self.user.get("allergies"),
            budget_vnd_max=self.user.get("budget_vnd_max") or 200000.0,
            max_food_occurrences_per_week=3,
        )

        domain_foods = self.foods
        if self.candidate_food_ids is not None:
            domain_foods = [f for f in domain_foods if int(f["food_id"]) in self.candidate_food_ids]
        if constraints.allergies:
            domain_foods = [f for f in domain_foods if constraints.check_allergies([f])]
        if self.is_gym:
            domain_foods = [f for f in domain_foods if not is_gym_blacklisted(f)]

        MAX_DOMAIN_SIZE = 250
        if len(domain_foods) > MAX_DOMAIN_SIZE:
            domain_foods.sort(key=lambda x: int(x.get("source_priority") or 1))
            domain_foods = domain_foods[:MAX_DOMAIN_SIZE]

        attempt = 1
        tolerance_multiplier = 1.0

        while attempt <= max_attempts:
            logging.getLogger(__name__).info(
                "CSP Solve Attempt %s/%s (multiplier=%.2f)", attempt, max_attempts, tolerance_multiplier
            )
            result = self._solve(domain_foods, constraints, tolerance_multiplier)
            if result["feasible"]:
                result["relaxation_attempts"] = attempt
                return result

            # Tăng biên độ nới lỏng dần dần
            tolerance_multiplier += 0.25
            attempt += 1

        return {
            "status": "infeasible",
            "feasible": False,
            "meal_plan": [],
            "relaxation_attempts": max_attempts,
        }

    def _get_meal_plan_for_solution(
        self,
        sol: Dict[str, int],
        constraints: NutrientConstraints,
        tolerance_multiplier: float,
        all_carbs: List[Dict[str, Any]],
        all_proteins: List[Dict[str, Any]],
        all_fibers: List[Dict[str, Any]],
        all_snacks: List[Dict[str, Any]],
        day_excluded_ids: Set[int] | None = None,
    ) -> List[Dict[str, Any]]:
        """Greedily builds sub-components for meals with stage-based relaxation safety nets."""
        def get_complementary(pool, excluded_ids=None):
            if excluded_ids is None: excluded_ids = set()
            candidates = [f for f in pool if int(f["food_id"]) not in excluded_ids and 
                          (not day_excluded_ids or int(f["food_id"]) not in day_excluded_ids)]
            if candidates:
                return random.choice(candidates[:min(12, len(candidates))])
            candidates_fallback = [f for f in pool if int(f["food_id"]) not in excluded_ids]
            if candidates_fallback:
                return random.choice(candidates_fallback[:min(5, len(candidates_fallback))])
            return pool[0] if pool else None

        def build_meal_components(core_food, slot, excluded_ids):
            components = []
            core_role = classify_food(core_food)
            name_check = str(core_food.get("name_vi") or "").lower()
            
            # 1. Nhận diện món truyền thống trọn vẹn
            is_standalone = is_single_bowl_meal(core_food) or any(k in name_check for k in ['bún chả', 'bún nem', 'phở', 'cháo'])
            
            components.append({"slot": slot, "food": core_food, "role": "core"})
            
            # 2. Logic phối hợp cho món trọn vẹn
            if is_standalone:
                # Nếu là người tập Gym -> Bốc thêm 1 món Đạm để đạt mục tiêu 40% Protein
                if self.is_gym and all_proteins:
                    comp_protein = get_complementary(all_proteins, excluded_ids)
                    if comp_protein:
                        components.append({"slot": slot, "food": comp_protein, "role": "protein"})
                        excluded_ids.add(comp_protein["food_id"])
                
                # Bắt buộc bốc kèm Rau xanh (Fiber) để cân bằng
                if all_fibers:
                    comp_fiber = get_complementary(all_fibers, excluded_ids)
                    if comp_fiber:
                        components.append({"slot": slot, "food": comp_fiber, "role": "fiber"})
                        excluded_ids.add(comp_fiber["food_id"])
                return components

            # 3. Logic cho mâm cơm thường (Cơm + Đạm + Rau)
            if core_role != "STAPLE_CARB" and all_carbs:
                comp_carb = get_complementary(all_carbs, excluded_ids)
                if comp_carb:
                    components.append({"slot": slot, "food": comp_carb, "role": "carb"})
                    excluded_ids.add(comp_carb["food_id"])
                    
            if core_role != "MAIN_PROTEIN" and all_proteins:
                comp_protein = get_complementary(all_proteins, excluded_ids)
                if comp_protein:
                    components.append({"slot": slot, "food": comp_protein, "role": "protein"})
                    excluded_ids.add(comp_protein["food_id"])
                    
            if core_role != "FIBER_SIDE" and all_fibers:
                comp_fiber = get_complementary(all_fibers, excluded_ids)
                if comp_fiber:
                    components.append({"slot": slot, "food": comp_fiber, "role": "fiber"})
                    excluded_ids.add(comp_fiber["food_id"])
            return components

        exclude_snacks = self.user.get("exclude_snacks", False)
        b_food = self.food_by_id[sol["breakfast"]]
        l_food = self.food_by_id[sol["lunch"]]
        s_food = None if exclude_snacks else self.food_by_id.get(sol.get("snack"))
        d_food = self.food_by_id[sol["dinner"]]

        components = []
        excluded_ids = set()
        
        components.append({"slot": "breakfast", "food": b_food, "role": "core"})
        if not exclude_snacks and s_food:
            components.append({"slot": "snack", "food": s_food, "role": "snack"})
            
        components.extend(build_meal_components(l_food, "lunch", excluded_ids))
        components.extend(build_meal_components(d_food, "dinner", excluded_ids))

        p_ratio = constraints.macro_ratios.get("protein", 0.4)
        c_ratio = constraints.macro_ratios.get("carbs", 0.3)
        f_ratio = constraints.macro_ratios.get("fat", 0.3)

        w_prot_space = [100.0, 150.0, 200.0, 250.0, 300.0]
        w_crb_space = [60.0, 100.0, 150.0, 200.0]
        w_fix_space = [40.0, 80.0, 120.0, 160.0]

        best_w_protein, best_w_carb, best_w_fixed = 150.0, 100.0, 80.0
        min_error = float("inf")
        
        for w_prot in w_prot_space:
            for w_crb in w_crb_space:
                for w_fix in w_fix_space:
                    skip_combo = False
                    total_cal, total_p, total_f, total_c = 0.0, 0.0, 0.0, 0.0
                    
                    for comp in components:
                        f = comp["food"]
                        slot = comp["slot"]
                        
                        if slot == "snack": w = w_fix
                        else:
                            role = classify_food(f)
                            if is_standalone_main_dish(f) or role == "MAIN_PROTEIN": w = w_prot
                            elif role == "STAPLE_CARB": w = w_crb
                            else: w = w_fix
                        
                        max_w = f.get("max_serving_g") or 300.0
                        if w > max_w:
                            skip_combo = True
                            break
                        
                        factor = w / 100.0
                        total_cal += float(f.get("calories") or 0.0) * factor
                        total_p += float(f.get("protein") or 0.0) * factor
                        total_f += float(f.get("fat") or 0.0) * factor
                        total_c += float(f.get("carbs") or 0.0) * factor
                        
                    if skip_combo: continue
                        
                    cal_error = abs(total_cal - constraints.daily_calorie_target) / constraints.daily_calorie_target
                    total_mass = total_p + total_f + total_c
                    if total_mass > 0:
                        macro_error = (
                            abs((total_p / total_mass) - p_ratio) * 2.0 +  # Trọng số ép chặt Đạm cho Gymer
                            abs((total_f / total_mass) - f_ratio) +
                            abs((total_c / total_mass) - c_ratio)
                        )
                    else: macro_error = 1.0
                        
                    error = cal_error + macro_error
                    if error < min_error:
                        min_error = error
                        best_w_protein, best_w_carb, best_w_fixed = w_prot, w_crb, w_fix

        if min_error == float("inf"):
            raise ValueError("No portion spacing matches criteria.")

        day_meals = []
        slots_to_generate = ["breakfast", "lunch", "dinner"] if exclude_snacks else ["breakfast", "lunch", "snack", "dinner"]
        
        for slot in slots_to_generate:
            slot_comps = [c["food"] for c in components if c["slot"] == slot]
            if not slot_comps: continue
            
            names_vi = []
            meal_cost, meal_cal, meal_p, meal_f, meal_c = 0.0, 0.0, 0.0, 0.0, 0.0
            
            for f in slot_comps:
                if slot == "snack": w = best_w_fixed
                else:
                    role = classify_food(f)
                    if is_standalone_main_dish(f) or role == "MAIN_PROTEIN": w = best_w_protein
                    elif role == "STAPLE_CARB": w = best_w_carb
                    else: w = best_w_fixed
                
                factor = w / 100.0
                meal_cost += float(f.get("cost_vnd_100g") or 15000) * factor
                meal_cal += float(f.get("calories") or 0.0) * factor
                meal_p += float(f.get("protein") or 0.0) * factor
                meal_f += float(f.get("fat") or 0.0) * factor
                meal_c += float(f.get("carbs") or 0.0) * factor
                
                display = f.get("name_vi") or f.get("canonical_name_en") or "Thực phẩm"
                suffix = " (Postgres DB)"
                names_vi.append(f"{display}{suffix} ({int(w)}g)")

            day_meals.append({
                "meal_type": slot,
                "food_id": slot_comps[0]["food_id"],
                "name": " + ".join(names_vi),
                "cost_vnd_100g": meal_cost,
                "calories": meal_cal,
                "protein": meal_p,
                "fat": meal_f,
                "carbs": meal_c,
                "component_food_ids": [f["food_id"] for f in slot_comps],
            })

        return day_meals

    def _solve(self, domain_foods: List[Dict[str, Any]], constraints: NutrientConstraints, tolerance_multiplier: float) -> Dict[str, Any]:
        """Core sequential CSP engine with strict upper bound budget containment and dynamic safety net."""
        all_carbs, all_proteins, all_fibers, all_snacks = [], [], [], []
        
        # Sắp xếp và bọc cách ly hoàn toàn phụ gia/nước sốt khỏi thực đơn mâm cơm chính
        for f in self.foods:
            role = classify_food(f)
            tags = f.get("tags") or set()
            cat_clean = clean_category(f.get("category"))
            
            if role == "ACCESSORY_CONDIMENT":
                if "is_dessert_snack" in tags or cat_clean == "trai_cay":
                    all_snacks.append(f)
                continue
            if role == "STAPLE_CARB": all_carbs.append(f)
            elif role == "MAIN_PROTEIN": all_proteins.append(f)
            elif role == "FIBER_SIDE": all_fibers.append(f)

        # Cơ chế dự phòng mở rộng Domain toàn cục để cứu vãn đói nghiệm
        if tolerance_multiplier >= 1.25 or not all_carbs or not all_proteins or not all_fibers:
            if not all_carbs: all_carbs = [x for x in self.foods if classify_food(x) == "STAPLE_CARB"]
            if not all_proteins: all_proteins = [x for x in self.foods if classify_food(x) == "MAIN_PROTEIN"]
            if not all_fibers: all_fibers = [x for x in self.foods if classify_food(x) == "FIBER_SIDE"]
        if not all_snacks: all_snacks = self.foods

        exclude_snacks = self.user.get("exclude_snacks", False)
        scheduled_plan = []
        used_food_ids = []
        offal_blood_count = 0
        rng = random.Random(42)

        for day in range(7):
            global_counts = Counter(used_food_ids)
            breakfast_foods, lunch_foods, dinner_foods, snack_foods = [], [], [], []
            
            day_domain = domain_foods
            if offal_blood_count >= 1:
                day_domain = [f for f in day_domain if not is_offal_or_blood(f)]
                
            for f in day_domain:
                fid = int(f["food_id"])
                role = classify_food(f)
                tags = f.get("tags") or set()
                name_vi = str(f.get("name_vi") or "").lower()
                
                if role == "ACCESSORY_CONDIMENT": continue
                if global_counts[fid] >= 3 and not ("cơm" in name_vi or "com" in name_vi): continue
                
                if "is_main_dish" in tags or is_single_bowl_meal(f):
                    breakfast_foods.append(fid)
                    lunch_foods.append(fid)
                    dinner_foods.append(fid)
                else:
                    if role == "STAPLE_CARB" or "allergen_egg" in tags: breakfast_foods.append(fid)
                    lunch_foods.append(fid)
                    dinner_foods.append(fid)
                snack_foods.append(fid)

            # Khởi tạo miền giá trị dự phòng an toàn từ database tổng
            if not breakfast_foods: breakfast_foods = [x["food_id"] for x in self.foods if classify_food(x) == "STAPLE_CARB"][:20]
            if not lunch_foods: lunch_foods = [x["food_id"] for x in self.foods if classify_food(x) == "MAIN_PROTEIN"][:20]
            if not dinner_foods: dinner_foods = [x["food_id"] for x in self.foods if classify_food(x) == "MAIN_PROTEIN"][:20]

            MAX_C = 50
            breakfast_candidates = list(set(breakfast_foods))[:MAX_C]
            lunch_candidates = list(set(lunch_foods))[:MAX_C]
            dinner_candidates = list(set(dinner_foods))[:MAX_C]
            
            rng.shuffle(breakfast_candidates)
            rng.shuffle(lunch_candidates)
            rng.shuffle(dinner_candidates)

            prob = Problem()
            prob.addVariable("breakfast", breakfast_candidates)
            prob.addVariable("lunch", lunch_candidates)
            if not exclude_snacks:
                snack_candidates = list(set(snack_foods))[:MAX_C]
                rng.shuffle(snack_candidates)
                prob.addVariable("snack", snack_candidates)
            prob.addVariable("dinner", dinner_candidates)

            # KIỂM TRA NGÂN SÁCH TRẦN KHẮT KHE (INLINE HARD CONSTRAINT)
            def check_inline_budget_and_habits(*args):
                b, l, d = args[0], args[1], args[-1]
                b_f, l_f, d_f = self.food_by_id[b], self.food_by_id[l], self.food_by_id[d]
                if not constraints.check_allergies([b_f, l_f, d_f]): return False
                
                # Tính chi phí ước lượng dựa trên thực tế
                approx_cost = (b_f.get("cost_vnd_100g", 15000) + l_f.get("cost_vnd_100g", 15000) + d_f.get("cost_vnd_100g", 15000)) * 1.2
                
                # ÉP CHẶT NGÂN SÁCH TRẦN: Tuyệt đối không cho phép vượt quá ngân sách trần, kể cả khi giải tiến trình
                if approx_cost > constraints.budget_vnd_max: 
                    return False
                return True

            var_order = ["breakfast", "lunch", "snack", "dinner"] if not exclude_snacks else ["breakfast", "lunch", "dinner"]
            prob.addConstraint(check_inline_budget_and_habits, var_order)

            sols = prob.getSolutionIter()
            valid_scored = []
            checked_count = 0
            MAX_CHECKED = 150

            for sol in sols:
                if checked_count >= MAX_CHECKED: break
                checked_count += 1
                try:
                    day_meals = self._get_meal_plan_for_solution(
                        sol, constraints, tolerance_multiplier,
                        all_carbs, all_proteins, all_fibers, all_snacks,
                        day_excluded_ids=set(used_food_ids)
                    )
                    
                    if not constraints.check_daily_calories(day_meals, tolerance_multiplier): continue
                    if not constraints.check_daily_macros(day_meals, tolerance_multiplier): continue
                    costs = [m["cost_vnd_100g"] for m in day_meals]
                    
                    # Ràng buộc cứng vòng cuối cùng: Bảo vệ túi tiền người dùng
                    if sum(costs) > constraints.budget_vnd_max: continue

                    base_score = score_meal_plan([{"meals": day_meals}], self.user.get("maximize_nutrients"), self.user.get("minimize_nutrients"))
                    penalty = 0.0

                    meal_cals = {m["meal_type"]: m["calories"] for m in day_meals}
                    total_actual_cal = sum(meal_cals.values())
                    if total_actual_cal > 0:
                        b_pct = meal_cals.get("breakfast", 0) / total_actual_cal
                        l_pct = meal_cals.get("lunch", 0) / total_actual_cal
                        d_pct = meal_cals.get("dinner", 0) / total_actual_cal
                        
                        if not (0.15 <= b_pct <= 0.35): penalty += 200.0
                        if not (0.25 <= l_pct <= 0.45): penalty += 200.0
                        if not (0.25 <= d_pct <= 0.45): penalty += 200.0

                    cand_ids = []
                    for m in day_meals: cand_ids.extend(m.get("component_food_ids", [m["food_id"]]))

                    for fid in cand_ids:
                        f = self.food_by_id[fid]
                        name_low = str(f.get("name_vi") or "").lower()
                        if "cơm" in name_low or "com" in name_low: continue

                        count = global_counts[fid]
                        if count == 1: penalty += 40.0
                        elif count >= 2: penalty += 200.0

                        if day >= 1 and fid in [x for m in scheduled_plan[-1]["meals"] for x in m.get("component_food_ids", [m["food_id"]])]:
                            penalty += 200.0

                    b_name = str(self.food_by_id[sol["breakfast"]].get("name_vi") or "").lower()
                    if any(k in b_name for k in ["bún", "miến", "phở", "xôi", "bánh mì", "bánh mỳ"]):
                        penalty -= 80.0

                    valid_scored.append((base_score - penalty, sol, day_meals))
                except Exception:
                    continue

            # KHỐI CỨU VÃN KHẨN CẤP THOÁNG CALO (TUYỆT ĐỐI BẢO VỆ NGÂN SÁCH)
            if not valid_scored:
                sols = prob.getSolutionIter()
                for sol in sols:
                    try:
                        day_meals = self._get_meal_plan_for_solution(sol, constraints, tolerance_multiplier, all_carbs, all_proteins, all_fibers, all_snacks, day_excluded_ids=None)
                        costs = [m["cost_vnd_100g"] for m in day_meals]
                        
                        # Cứu vãn calo lệch một chút nhưng ngân sách vượt trần là ĐÁNH TRƯỢT NGAY
                        if sum(costs) <= constraints.budget_vnd_max and constraints.check_daily_calories(day_meals, tolerance_multiplier * 1.3):
                            valid_scored.append((0, sol, day_meals))
                            break
                    except Exception: continue

            if not valid_scored:
                return {"feasible": False, "meal_plan": []}

            valid_scored.sort(key=lambda x: x[0], reverse=True)
            best_day = valid_scored[0]
            scheduled_plan.append({"day": day + 1, "meals": best_day[2]})
            
            for m in best_day[2]:
                c_ids = m.get("component_food_ids", [m["food_id"]])
                used_food_ids.extend(c_ids)
                for fid in c_ids:
                    if is_offal_or_blood(self.food_by_id[fid]): offal_blood_count += 1

        final_score = score_meal_plan(scheduled_plan, self.user.get("maximize_nutrients"), self.user.get("minimize_nutrients"))
        return {
            "status": "success",
            "feasible": True,
            "meal_plan": scheduled_plan,
            "score": round(final_score, 2),
        }