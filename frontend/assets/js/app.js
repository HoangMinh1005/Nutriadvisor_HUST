// Application State
let userEmail = "";
let userProfile = null;
let activeDay = 1; // 1 to 7
let mealPlan = [];
let knnInlineActive = false;
let weightForecastChart = null;
let featureImportanceChart = null;

// DOM Elements
const screenLogin = document.getElementById("screen-login");
const screenOnboarding = document.getElementById("screen-onboarding");
const screenDashboard = document.getElementById("screen-dashboard");
const mainHeader = document.getElementById("main-header");
const modalProfile = document.getElementById("modal-profile");

const loginForm = document.getElementById("login-form");
const onboardingForm = document.getElementById("onboarding-form");
const profileEditForm = document.getElementById("profile-edit-form");
const chatInputForm = document.getElementById("chat-input-form");

const sleepSlider = document.getElementById("ob-sleep");
const stressSlider = document.getElementById("ob-stress");
const valSleep = document.getElementById("val-sleep");
const valStress = document.getElementById("val-stress");

const editSleepSlider = document.getElementById("edit-sleep");
const editStressSlider = document.getElementById("edit-stress");
const valEditSleep = document.getElementById("val-edit-sleep");
const valEditStress = document.getElementById("val-edit-stress");

// Setup Range Sliders display values
if (sleepSlider) {
    sleepSlider.addEventListener("input", (e) => {
        valSleep.textContent = `${e.target.value} trên 5`;
    });
}
if (stressSlider) {
    stressSlider.addEventListener("input", (e) => {
        valStress.textContent = `${e.target.value} trên 5`;
    });
}
if (editSleepSlider) {
    editSleepSlider.addEventListener("input", (e) => {
        valEditSleep.textContent = `${e.target.value} trên 5`;
    });
}
if (editStressSlider) {
    editStressSlider.addEventListener("input", (e) => {
        valEditStress.textContent = `${e.target.value} trên 5`;
    });
}

// 1. LOGIN HANDLER
loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = document.getElementById("login-email").value.trim();
    const isFirstTime = document.getElementById("login-first-time").checked;
    
    if (isFirstTime) {
        // Switch to onboarding screen
        userEmail = email;
        document.getElementById("ob-fullname").value = "Vũ Hoàng Minh";
        document.getElementById("ob-age").value = 21;
        document.getElementById("ob-height").value = 175;
        document.getElementById("ob-weight").value = 72.5;
        document.getElementById("ob-calories").value = 2200;
        document.getElementById("ob-budget").value = 200000;
        
        switchScreen("onboarding");
    } else {
        // Query profile and load dashboard
        showLoading(true);
        try {
            const res = await fetch("/api/v1/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email })
            });
            const data = await res.json();
            
            if (data.status === "new_user") {
                userEmail = email;
                switchScreen("onboarding");
            } else if (data.status === "success") {
                userEmail = email;
                userProfile = data.profile;
                mealPlan = data.meal_plan;
                
                // Load Dashboard
                loadDashboardData(data);
                switchScreen("dashboard");
            }
        } catch (err) {
            alert("Đăng nhập thất bại: " + err.message);
        } finally {
            showLoading(false);
        }
    }
});

// 2. ONBOARDING HANDLER
onboardingForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const profilePayload = {
        full_name: document.getElementById("ob-fullname").value.trim(),
        email: userEmail,
        gender: document.getElementById("ob-gender").value,
        age: parseInt(document.getElementById("ob-age").value),
        height_cm: parseFloat(document.getElementById("ob-height").value),
        weight_kg: parseFloat(document.getElementById("ob-weight").value),
        daily_calorie_target: parseInt(document.getElementById("ob-calories").value),
        budget_vnd_max: parseInt(document.getElementById("ob-budget").value),
        physical_activity_level: document.getElementById("ob-activity").value,
        sleep_quality: mapSliderToSleep(parseInt(sleepSlider.value)),
        stress_level: parseInt(stressSlider.value) * 2, // Map scale 1-5 to 1-10
        allergies: [],
        weight_goal: "maintain"
    };
    
    showLoading(true);
    try {
        const res = await fetch("/api/v1/profile", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(profilePayload)
        });
        const data = await res.json();
        
        if (data.status === "success") {
            userProfile = data.profile;
            mealPlan = data.meal_plan;
            loadDashboardData(data);
            switchScreen("dashboard");
        }
    } catch (err) {
        alert("Khởi tạo chỉ số sinh lý thất bại: " + err.message);
    } finally {
        showLoading(false);
    }
});

// Helper functions for screen routing
function switchScreen(screenName) {
    screenLogin.classList.add("hidden");
    screenOnboarding.classList.add("hidden");
    screenDashboard.classList.add("hidden");
    mainHeader.classList.add("hidden");
    
    if (screenName === "login") {
        screenLogin.classList.remove("hidden");
    } else if (screenName === "onboarding") {
        screenOnboarding.classList.remove("hidden");
    } else if (screenName === "dashboard") {
        screenDashboard.classList.remove("hidden");
        mainHeader.classList.remove("hidden");
        
        // Update user badge in header
        document.getElementById("user-display-name").textContent = userProfile.full_name;
        document.getElementById("user-avatar-initials").textContent = getInitials(userProfile.full_name);
    }
}

function getInitials(name) {
    if (!name) return "US";
    const parts = name.trim().split(" ");
    if (parts.length === 1) return parts[0].substring(0, 2).toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function mapSliderToSleep(val) {
    if (val <= 1) return "Poor";
    if (val <= 3) return "Fair";
    if (val === 4) return "Good";
    return "Excellent";
}

function mapSleepToSlider(val) {
    if (val === "Poor") return 1;
    if (val === "Fair") return 3;
    if (val === "Good") return 4;
    if (val === "Excellent") return 5;
    return 4;
}

// 3. LOAD DASHBOARD DATA
function loadDashboardData(data) {
    // 3.1 Load profile cards
    document.getElementById("lbl-weight").textContent = userProfile.weight_kg;
    document.getElementById("lbl-height").textContent = userProfile.height_cm;
    document.getElementById("lbl-calories").textContent = userProfile.daily_calorie_target;
    document.getElementById("lbl-budget").textContent = formatBudget(userProfile.budget_vnd_max);
    
    // Calculate and display BMI
    const heightM = userProfile.height_cm / 100.0;
    const bmiVal = (userProfile.weight_kg / (heightM * heightM)).toFixed(1);
    document.getElementById("lbl-bmi").textContent = bmiVal;
    
    const bmiStatus = document.getElementById("lbl-bmi-status");
    bmiStatus.className = "badge";
    if (bmiVal < 18.5) {
        bmiStatus.textContent = "THẤP";
        bmiStatus.classList.add("badge-warning");
    } else if (bmiVal < 25.0) {
        bmiStatus.textContent = "THƯỜNG";
        bmiStatus.classList.add("badge-success");
    } else {
        bmiStatus.textContent = "CAO";
        bmiStatus.classList.add("badge-danger");
    }
    
    // 3.2 Render weekly schedule
    renderWeeklySchedule();
    
    // 3.3 Render Forecast Charts
    if (data.forecast) {
        renderForecastChart(data.forecast);
        renderFeatureImportance(data.forecast.feature_importance);
    }
}

function formatBudget(val) {
    if (val >= 1000) {
        return Math.round(val / 1000) + "k";
    }
    return val;
}

// 4. RENDER WEEKLY SCHEDULE
function renderWeeklySchedule() {
    const mealsContainer = document.getElementById("meals-container");
    mealsContainer.innerHTML = "";
    
    // Find active day data
    const dayData = mealPlan.find(d => d.day === activeDay);
    if (!dayData || !dayData.meals || dayData.meals.length === 0) {
        mealsContainer.innerHTML = `<div class="empty-schedule-state">Không có thực đơn được tạo cho ngày này. Hãy điều chỉnh chỉ số để lập lịch lại.</div>`;
        return;
    }
    
    const slotLabels = {
        "breakfast": "SÁNG",
        "lunch": "TRƯA",
        "dinner": "TỐI",
        "snack": "PHỤ"
    };
    
    dayData.meals.forEach(m => {
        const componentsToRender = (m.components && m.components.length > 0) ? m.components : [{
            food_id: m.food_id,
            name: m.name,
            calories: m.calories,
            protein: m.protein,
            fat: m.fat,
            carbs: m.carbs,
            weight: null
        }];

        componentsToRender.forEach(comp => {
            const wrapper = document.createElement("div");
            wrapper.className = "meal-row-wrapper";
            wrapper.dataset.mealType = m.meal_type;
            wrapper.dataset.foodId = comp.food_id;
            
            const mainRow = document.createElement("div");
            mainRow.className = "meal-main-row";
            
            const slotCodeClass = `slot-${m.meal_type}`;
            const slotLabel = slotLabels[m.meal_type] || m.meal_type.toUpperCase();
            const displayName = comp.weight ? `${comp.name} (${Math.round(comp.weight)}g)` : comp.name;
            
            mainRow.innerHTML = `
                <div class="meal-meta">
                    <span class="meal-slot-label ${slotCodeClass}">${slotLabel}</span>
                    <span class="meal-name">${displayName}</span>
                </div>
                <div class="meal-stats">
                    <span class="meal-macros">P: ${Math.round(comp.protein)}g C: ${Math.round(comp.carbs)}g F: ${Math.round(comp.fat)}g</span>
                    <span class="meal-calories">${Math.round(comp.calories)} kcal</span>
                    <i class="fa-solid fa-chevron-down meal-expand-arrow"></i>
                </div>
            `;
            
            wrapper.appendChild(mainRow);
            
            // KNN Inline panel container with unique ID per component
            const carouselId = `knn-carousel-${m.meal_type}-${comp.food_id}`;
            const knnPanel = document.createElement("div");
            knnPanel.className = "knn-inline-panel";
            knnPanel.innerHTML = `
                <div class="knn-panel-header">
                    <h4>Món Thay Thế KNN Đề Xuất</h4>
                    <span>K-Nearest Neighbors Algorithm</span>
                </div>
                <div class="knn-cards-carousel" id="${carouselId}">
                    <div class="loading-state-inline"><i class="fa-solid fa-spinner fa-spin"></i> Đang tính toán độ tương đồng dinh dưỡng...</div>
                </div>
            `;
            wrapper.appendChild(knnPanel);
            
            // Handle click event on the row to expand/collapse and load KNN
            mainRow.addEventListener("click", () => {
                const isCurrentlyExpanded = wrapper.classList.contains("expanded");
                
                // Collapse all rows first
                document.querySelectorAll(".meal-row-wrapper").forEach(w => w.classList.remove("expanded"));
                
                if (!isCurrentlyExpanded) {
                    wrapper.classList.add("expanded");
                    // Fetch and populate KNN cards
                    loadKnnAlternatives(comp.food_id, m.meal_type, dayData.date, comp.name, slotLabel, carouselId);
                }
            });
            
            mealsContainer.appendChild(wrapper);
        });
    });
}

// Day tabs click handlers
document.querySelectorAll(".tab-item").forEach(tab => {
    tab.addEventListener("click", (e) => {
        document.querySelectorAll(".tab-item").forEach(t => t.classList.remove("active"));
        tab.classList.add("active");
        activeDay = parseInt(tab.dataset.day);
        renderWeeklySchedule();
    });
});

// KNN Toggle Switches in header
const btnDefault = document.getElementById("btn-toggle-default");
const btnKnn = document.getElementById("btn-toggle-knn");

btnDefault.addEventListener("click", () => {
    btnDefault.classList.add("active");
    btnKnn.classList.remove("active");
    knnInlineActive = false;
    document.querySelectorAll(".meal-row-wrapper").forEach(w => w.classList.remove("expanded"));
});

btnKnn.addEventListener("click", () => {
    btnKnn.classList.add("active");
    btnDefault.classList.remove("active");
    knnInlineActive = true;
    
    // Automatically expand the first meal row
    const firstRow = document.querySelector(".meal-row-wrapper");
    if (firstRow) {
        firstRow.click();
    }
});

// 5. LOAD KNN ALTERNATIVES INLINE
async function loadKnnAlternatives(foodId, mealType, planDate, origName, slotLabelVi, carouselId) {
    const carousel = document.getElementById(carouselId);
    if (!carousel) return;
    
    try {
        const res = await fetch(`/api/v1/food/${foodId}/alternatives?limit=5`);
        const alternatives = await res.json();
        
        carousel.innerHTML = "";
        
        if (alternatives.length === 0) {
            carousel.innerHTML = `<div class="empty-state-inline">Không tìm thấy món thay thế phù hợp.</div>`;
            return;
        }
        
        alternatives.forEach(alt => {
            const card = document.createElement("div");
            card.className = "knn-card";
            
            const matchPct = Math.round(alt.match_score * 100) + "% Khớp";
            
            card.innerHTML = `
                <div class="knn-match-pct">${matchPct}</div>
                <div class="knn-food-name">${alt.name_vi}</div>
                <div class="knn-food-meta">
                    <span>${Math.round(alt.calories || 120)} cal</span>
                    <span>Đạm: ${Math.round(alt.protein || 8)}g</span>
                </div>
                <button class="knn-btn-swap" data-alt-id="${alt.food_id}">Hoán đổi</button>
            `;
            
            card.querySelector(".knn-btn-swap").addEventListener("click", async (e) => {
                e.stopPropagation();
                showLoading(true);
                try {
                    const swapRes = await fetch("/api/v1/meal-plan/swap", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            email: userProfile.email,
                            plan_date: planDate,
                            meal_slot_code: mealType,
                            original_food_id: foodId,
                            replacement_food_id: alt.food_id
                        })
                    });
                    const swapData = await swapRes.json();
                    if (swapData.status === "success") {
                        const profileRes = await fetch("/api/v1/login", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ email: userProfile.email })
                        });
                        const data = await profileRes.json();
                        mealPlan = data.meal_plan;
                        
                        renderWeeklySchedule();
                        
                        addBotMessage(`Đã hoán đổi thành công món **"${origName}"** thành **"${alt.name_vi}"** vào thực đơn **${slotLabelVi}** ngày **Thứ ${activeDay === 7 ? 'Nhật' : activeDay + 1}**.`);
                    }
                } catch (err) {
                    alert("Hoán đổi thất bại: " + err.message);
                } finally {
                    showLoading(false);
                }
            });
            
            carousel.appendChild(card);
        });
        
        const dayNames = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"];
        const curDayName = dayNames[activeDay - 1];
        addBotMessage(`Bạn đang xem danh sách món ăn thay thế bằng thuật toán KNN cho món **"${origName}"** của bữa **${slotLabelVi}** ngày **${curDayName}** trực tiếp trên bảng thực đơn.`);
        
    } catch (err) {
        carousel.innerHTML = `<div class="error-state-inline">Lỗi tải dữ liệu.</div>`;
    }
}

// 6. RENDER CHARTS
function renderForecastChart(forecast) {
    const ctx = document.getElementById("weightForecastChart").getContext("2d");
    
    const labels = ["Hiện tại", "Tuần 1", "Tuần 2", "Tuần 3", "Tuần 4"];
    
    // Parse weight and BMI trajectory array format
    const weightData = [];
    const bmiData = [];
    
    if (forecast.forecast_chart_data && Array.isArray(forecast.forecast_chart_data)) {
        forecast.forecast_chart_data.forEach(item => {
            weightData.push(parseFloat(item.predicted_weight));
            bmiData.push(parseFloat(item.predicted_bmi));
        });
    } else {
        weightData.push(parseFloat(userProfile.weight_kg), 0, 0, 0, 0);
        bmiData.push(22, 0, 0, 0, 0);
    }
    
    if (weightForecastChart) {
        weightForecastChart.destroy();
    }
    
    weightForecastChart = new Chart(ctx, {
        type: "line",
        data: {
            labels: labels,
            datasets: [
                {
                    label: "Cân nặng (kg)",
                    data: weightData,
                    borderColor: "#14b8a6",
                    backgroundColor: "rgba(20, 184, 166, 0.05)",
                    borderWidth: 3,
                    tension: 0.35,
                    fill: true,
                    yAxisID: "y-weight"
                },
                {
                    label: "BMI",
                    data: bmiData,
                    borderColor: "#10b981",
                    backgroundColor: "transparent",
                    borderWidth: 2,
                    borderDash: [5, 5],
                    tension: 0.35,
                    yAxisID: "y-bmi"
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: "top",
                    labels: { color: "hsl(218, 12%, 75%)", font: { family: "Inter", size: 11 } }
                },
                tooltip: {
                    backgroundColor: "rgba(13, 18, 29, 0.95)",
                    borderColor: "rgba(255,255,255,0.08)",
                    borderWidth: 1,
                    titleColor: "#ffffff",
                    bodyColor: "#ffffff",
                    bodyFont: { family: "Inter" }
                }
            },
            scales: {
                x: {
                    grid: { color: "rgba(255, 255, 255, 0.04)" },
                    ticks: { color: "hsl(218, 12%, 65%)", font: { size: 10 } }
                },
                "y-weight": {
                    type: "linear",
                    position: "left",
                    grid: { color: "rgba(255, 255, 255, 0.04)" },
                    ticks: { color: "#14b8a6", font: { size: 10 } },
                    title: { display: true, text: "Cân nặng (kg)", color: "#14b8a6", font: { size: 10, weight: 600 } }
                },
                "y-bmi": {
                    type: "linear",
                    position: "right",
                    grid: { drawOnChartArea: false },
                    ticks: { color: "#10b981", font: { size: 10 } },
                    title: { display: true, text: "BMI", color: "#10b981", font: { size: 10, weight: 600 } }
                }
            }
        }
    });
}

function renderFeatureImportance(importanceMap) {
    const ctx = document.getElementById("featureImportanceChart").getContext("2d");
    
    const factorsMapping = {
        "daily_calories_consumed": "Thặng dư hoặc Dư thừa Calo",
        "stress_level": "Mức độ Căng thẳng",
        "sleep_quality": "Chất lượng Giấc ngủ",
        "physical_activity_level": "Cường độ Vận động"
    };
    
    // Fallback if importanceMap uses standard titles
    const importanceMapNormalized = {};
    if (importanceMap) {
        Object.keys(importanceMap).forEach(k => {
            if (k.toLowerCase().includes("surplus") || k.toLowerCase().includes("calor")) {
                importanceMapNormalized["daily_calories_consumed"] = importanceMap[k];
            } else if (k.toLowerCase().includes("stress")) {
                importanceMapNormalized["stress_level"] = importanceMap[k];
            } else if (k.toLowerCase().includes("sleep")) {
                importanceMapNormalized["sleep_quality"] = importanceMap[k];
            } else if (k.toLowerCase().includes("activ")) {
                importanceMapNormalized["physical_activity_level"] = importanceMap[k];
            }
        });
    }
    
    const labels = [];
    const values = [];
    const colors = ["#14b8a6", "#f97316", "#10b981", "#6366f1"];
    
    Object.keys(factorsMapping).forEach(key => {
        labels.push(factorsMapping[key]);
        let val = (importanceMapNormalized[key] || importanceMap[key] || 0.1) * 100;
        values.push(val);
    });
    
    if (featureImportanceChart) {
        featureImportanceChart.destroy();
    }
    
    featureImportanceChart = new Chart(ctx, {
        type: "bar",
        data: {
            labels: labels,
            datasets: [{
                data: values,
                backgroundColor: colors,
                borderWidth: 0,
                borderRadius: 5,
                barThickness: 12
            }]
        },
        options: {
            indexAxis: "y",
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: "rgba(13, 18, 29, 0.95)",
                    callbacks: {
                        label: function(context) { return context.raw.toFixed(1) + "% tác động"; }
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: "rgba(255, 255, 255, 0.04)" },
                    ticks: { color: "hsl(218, 12%, 60%)", font: { size: 9 } }
                },
                y: {
                    grid: { display: false },
                    ticks: { color: "#ffffff", font: { family: "Outfit", size: 11, weight: 500 } }
                }
            }
        }
    });
}

// 7. AI CHATBOT INTEGRATION
function addBotMessage(text, details = null, rejected = false) {
    const history = document.getElementById("chat-history");
    const bubble = document.createElement("div");
    bubble.className = "chat-bubble bot-message";
    if (rejected) bubble.classList.add("rejected");
    
    let htmlContent = `<div class="bubble-content">${text}</div>`;
    
    if (details) {
        if (details.intent === "SUGGEST_MEAL" && details.meals) {
            htmlContent += `<div class="chat-meal-cards">`;
            const slotLabels = { "breakfast": "SÁNG", "lunch": "TRƯA", "dinner": "TỐI" };
            details.meals.forEach(m => {
                const label = slotLabels[m.meal_type] || m.meal_type.toUpperCase();
                htmlContent += `
                    <div class="chat-meal-card">
                        <div class="chat-meal-card-info">
                            <span class="chat-meal-label slot-${m.meal_type}">${label}</span>
                            <span class="chat-meal-name">${m.name}</span>
                        </div>
                        <span class="chat-meal-cals">${Math.round(m.calories)} cal</span>
                    </div>
                `;
            });
            htmlContent += `</div>`;
        } else if (details.intent === "FIND_ALTERNATIVE" && details.replacements) {
            htmlContent += `<div class="chat-meal-cards">`;
            details.replacements.forEach(r => {
                const pct = Math.round(r.match_score * 100) + "% Tương đồng";
                htmlContent += `
                    <div class="chat-meal-card">
                        <div class="chat-meal-card-info">
                            <span class="chat-meal-label slot-breakfast">${pct}</span>
                            <span class="chat-meal-name">${r.name_vi}</span>
                        </div>
                    </div>
                `;
            });
            htmlContent += `</div>`;
        } else if (details.intent === "QUERY_NUTRITION" && details.foods) {
            htmlContent += `<div class="chat-meal-cards">`;
            details.foods.forEach(f => {
                let microList = [];
                if (f.vitamin_a_mcg > 0) microList.push(`Vit A: ${f.vitamin_a_mcg.toFixed(1)}mcg`);
                if (f.beta_carotene_mcg > 0) microList.push(`Beta-carotene: ${f.beta_carotene_mcg.toFixed(1)}mcg`);
                if (f.vitamin_c_mg > 0) microList.push(`Vit C: ${f.vitamin_c_mg.toFixed(1)}mg`);
                if (f.calcium_mg > 0) microList.push(`Canxi: ${f.calcium_mg.toFixed(1)}mg`);
                if (f.iron_mg > 0) microList.push(`Sắt: ${f.iron_mg.toFixed(1)}mg`);
                if (f.zinc_mg > 0) microList.push(`Kẽm: ${f.zinc_mg.toFixed(1)}mg`);
                if (f.sodium_mg > 0) microList.push(`Natri: ${f.sodium_mg.toFixed(1)}mg`);
                if (f.cholesterol_mg > 0) microList.push(`Cholesterol: ${f.cholesterol_mg.toFixed(1)}mg`);
                if (f.magnesium_mg > 0) microList.push(`Magie: ${f.magnesium_mg.toFixed(1)}mg`);
                if (f.transfat_mg > 0) microList.push(`Trans Fat: ${f.transfat_mg.toFixed(1)}mg`);
                
                let microStr = microList.length > 0 ? `<div class="chat-meal-micros" style="font-size: 10px; color: hsl(218, 12%, 55%); margin-top: 2px;">${microList.join(" | ")}</div>` : "";

                htmlContent += `
                    <div class="chat-meal-card" style="flex-direction: column; align-items: flex-start; gap: 4px; padding: 10px;">
                        <div class="chat-meal-card-info" style="width: 100%; justify-content: space-between; display: flex; align-items: center;">
                            <span class="chat-meal-name" style="font-weight: 600;">${f.name_vi} (100g)</span>
                            <span class="chat-meal-cals" style="font-weight: 700; color: #14b8a6;">${Math.round(f.calories)} kcal</span>
                        </div>
                        <div class="chat-meal-macros" style="font-size: 11px; color: hsl(218, 12%, 75%); font-weight: 500;">
                            Đạm: ${f.protein.toFixed(1)}g | Tinh bột: ${f.carbs.toFixed(1)}g | Béo: ${f.fat.toFixed(1)}g
                        </div>
                        ${microStr}
                    </div>
                `;
            });
            htmlContent += `</div>`;
        }
    }
    
    bubble.innerHTML = htmlContent;
    history.appendChild(bubble);
    history.scrollTop = history.scrollHeight;
}

function addUserMessage(text) {
    const history = document.getElementById("chat-history");
    const bubble = document.createElement("div");
    bubble.className = "chat-bubble user-message";
    bubble.innerHTML = `<div class="bubble-content">${text}</div>`;
    history.appendChild(bubble);
    history.scrollTop = history.scrollHeight;
}

chatInputForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const inputField = document.getElementById("chat-text-input");
    const query = inputField.value.trim();
    if (!query) return;
    
    addUserMessage(query);
    inputField.value = "";
    
    const history = document.getElementById("chat-history");
    const loader = document.createElement("div");
    loader.className = "chat-bubble bot-message temp-loader";
    loader.innerHTML = `<div class="bubble-content"><i class="fa-solid fa-circle-notch fa-spin"></i> Trợ lý đang phân tích...</div>`;
    history.appendChild(loader);
    history.scrollTop = history.scrollHeight;
    
    try {
        const res = await fetch("/api/v1/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                message: query,
                user_profile: {
                    gender: userProfile.gender === "male" ? "M" : "F",
                    daily_calorie_target: userProfile.daily_calorie_target,
                    budget_vnd_max: userProfile.budget_vnd_max,
                    exclude_snacks: true
                }
            })
        });
        
        const data = await res.json();
        
        const temp = document.querySelector(".temp-loader");
        if (temp) temp.remove();
        
        if (data.status === "rejected") {
            addBotMessage(data.reply, null, true);
        } else {
            addBotMessage(data.reply, data);
        }
    } catch (err) {
        const temp = document.querySelector(".temp-loader");
        if (temp) temp.remove();
        addBotMessage("Lỗi kết nối máy chủ chat.", null, true);
    }
});

document.querySelectorAll(".qp-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        const query = btn.dataset.query;
        const inputField = document.getElementById("chat-text-input");
        inputField.value = query;
        chatInputForm.dispatchEvent(new Event("submit"));
    });
});

document.getElementById("btn-clear-chat").addEventListener("click", () => {
    const history = document.getElementById("chat-history");
    history.innerHTML = `
        <div class="chat-bubble bot-message">
            <div class="bubble-content">
                Lịch sử trò chuyện đã được xóa. Tôi có thể giúp gì thêm cho bạn về thực đơn hoặc tra cứu dinh dưỡng?
            </div>
        </div>
    `;
});

// 8. PROFILE EDIT MODAL INTERACTION
document.getElementById("btn-edit-profile").addEventListener("click", () => {
    document.getElementById("edit-fullname").value = userProfile.full_name;
    document.getElementById("edit-age").value = userProfile.age;
    document.getElementById("edit-height").value = userProfile.height_cm;
    document.getElementById("edit-weight").value = userProfile.weight_kg;
    document.getElementById("edit-gender").value = userProfile.gender;
    document.getElementById("edit-activity").value = userProfile.physical_activity_level || "Moderately Active";
    document.getElementById("edit-calories").value = userProfile.daily_calorie_target;
    document.getElementById("edit-budget").value = userProfile.budget_vnd_max;
    
    const sleepSliderVal = mapSleepToSlider(userProfile.sleep_quality);
    editSleepSlider.value = sleepSliderVal;
    valEditSleep.textContent = `${sleepSliderVal} trên 5`;
    
    const stressSliderVal = Math.round((userProfile.stress_level || 5) / 2);
    editStressSlider.value = stressSliderVal;
    valEditStress.textContent = `${stressSliderVal} trên 5`;
    
    modalProfile.classList.remove("hidden");
});

document.getElementById("btn-modal-close").addEventListener("click", closeModal);
document.getElementById("btn-modal-cancel").addEventListener("click", closeModal);

function closeModal() {
    modalProfile.classList.add("hidden");
}

profileEditForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const editPayload = {
        full_name: document.getElementById("edit-fullname").value.trim(),
        email: userProfile.email,
        gender: document.getElementById("edit-gender").value,
        age: parseInt(document.getElementById("edit-age").value),
        height_cm: parseFloat(document.getElementById("edit-height").value),
        weight_kg: parseFloat(document.getElementById("edit-weight").value),
        daily_calorie_target: parseInt(document.getElementById("edit-calories").value),
        budget_vnd_max: parseInt(document.getElementById("edit-budget").value),
        physical_activity_level: document.getElementById("edit-activity").value,
        sleep_quality: mapSliderToSleep(parseInt(editSleepSlider.value)),
        stress_level: parseInt(editStressSlider.value) * 2,
        allergies: [],
        weight_goal: "maintain"
    };
    
    closeModal();
    showLoading(true);
    try {
        const res = await fetch("/api/v1/profile", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(editPayload)
        });
        const data = await res.json();
        
        if (data.status === "success") {
            userProfile = data.profile;
            mealPlan = data.meal_plan;
            loadDashboardData(data);
            
            addBotMessage("Đã cập nhật chỉ số sinh lý thành công! Thực đơn tuần và biểu đồ dự báo 4 tuần đã được tối ưu hóa lại theo thời gian thực.");
        }
    } catch (err) {
        alert("Cập nhật chỉ số sinh lý thất bại: " + err.message);
    } finally {
        showLoading(false);
    }
});

document.getElementById("btn-logout").addEventListener("click", () => {
    userProfile = null;
    mealPlan = [];
    switchScreen("login");
});

function showLoading(show) {
    if (show) {
        document.body.classList.add("loading-active");
    } else {
        document.body.classList.remove("loading-active");
    }
}
