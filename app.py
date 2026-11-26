from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import altair as alt
import pandas as pd
import streamlit as st

from finance_engine import (
    INVENTORY_CATALOG,
    INVENTORY_OPTIONS_WITH_ALL,
    REVENUE_SCENARIOS,
    STORE_RULES,
    TODAY,
    audit_ledger_integrity,
    build_owner_forecast,
    compute_financial_kpis,
    evaluate_non_recurring_events,
    load_store_ledger,
    recommend_cashflow_threshold,
    save_store_ledger,
    summarize_shortage_alerts,
)

st.set_page_config(
    page_title="Maréa — Ocean Cash Flow & Ledger",
    page_icon="🌊",
    layout="wide",
)

# --- OCEAN THEME STYLING ---
st.markdown(
    """
    <style>
        .stApp {
            background: linear-gradient(180deg, #EBF8FF 0%, #F7FCFF 42%, #FFFFFF 100%);
            color: #0B2545;
        }
        [data-testid="stHeader"] {
            background: rgba(11, 37, 69, 0.03);
            backdrop-filter: blur(6px);
        }
        h1, h2, h3 {
            color: #0A3A5C !important;
            letter-spacing: -0.01em;
        }
        [data-testid="stMetric"] {
            background: linear-gradient(135deg, #FFFFFF 0%, #E0F4FC 100%);
            border: 1px solid #B8E2F4;
            border-left: 5px solid #0284C7;
            border-radius: 12px;
            padding: 14px 18px;
            box-shadow: 0 4px 14px rgba(2, 132, 199, 0.08);
        }
        [data-testid="stMetricLabel"] {
            color: #0F4C75 !important;
            font-weight: 600;
        }
        [data-testid="stMetricValue"] {
            color: #072A48 !important;
            font-weight: 700;
        }
        [data-testid="stVerticalBlockBorderWrapper"] {
            background: rgba(255, 255, 255, 0.92);
            border: 1px solid #BAE6FD !important;
            border-radius: 12px !important;
            box-shadow: 0 3px 10px rgba(14, 116, 144, 0.06);
        }
        .stButton > button, .stFormSubmitButton > button, [data-testid="stDownloadButton"] > button {
            background: linear-gradient(90deg, #0369A1 0%, #0D9488 100%);
            color: #FFFFFF !important;
            border: none;
            border-radius: 8px;
            font-weight: 600;
            box-shadow: 0 3px 8px rgba(3, 105, 161, 0.22);
        }
        .stButton > button:hover, .stFormSubmitButton > button:hover, [data-testid="stDownloadButton"] > button:hover {
            background: linear-gradient(90deg, #075985 0%, #0F766E 100%);
            color: #FFFFFF !important;
        }
        hr {
            border-color: #BAE6FD !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

BASE_DIR = Path(__file__).parent
CANDIDATE_CSVS = [
    BASE_DIR / "convenience_store_2025_2026.csv",
    BASE_DIR / "convenience_store_2025_2026-v5.csv",
    BASE_DIR / "convenience_store_2025_2026-v4.csv",
    BASE_DIR / "convenience_store_2025_2026-v3.csv",
    BASE_DIR / "convenience_store_2025_2026-v2.csv",
    BASE_DIR / "convenience_store_2025_2026 (1).csv",
]
CSV_PATH = next((p for p in CANDIDATE_CSVS if p.exists()), CANDIDATE_CSVS[0])

USERS = {
    "Nam": {"role": "employee", "label": "🐚 Nam — Store Employee"},
    "Noelle": {"role": "accountant", "label": "🧭 Noelle — Accountant"},
    "Rania": {"role": "owner", "label": "⚓ Rania — Store Owner"},
}
DEMO_PIN = "123456"

ACCOUNTANT_CATEGORIES_BY_TYPE = {
    "revenue": ["Daily Sales", "Other Revenue"],
    "inventory": ["Inventory Receipt", "Inventory Payment"],
    "expense": ["Payroll", "Rent", "Tax", "Other Store Expense"],
    "financing": ["Bank Overdraft", "Short-Term Borrowing"],
}

ACCOUNTANT_INVENTORY_BY_TYPE = {
    "revenue": INVENTORY_OPTIONS_WITH_ALL,
    "inventory": list(INVENTORY_CATALOG.keys()) + ["All Inventories"],
    "expense": ["None"],
    "financing": ["None"],
}

if "ledger_df" not in st.session_state:
    if CSV_PATH.exists():
        st.session_state.ledger_df = load_store_ledger(str(CSV_PATH))
    else:
        st.error(
            f"🌊 Dataset not found at `{CSV_PATH}`. Please place `convenience_store_2025_2026.csv` "
            "in the repository root folder."
        )
        st.stop()

if "auth_user" not in st.session_state:
    st.session_state.auth_user = None


def next_tx_id(df: pd.DataFrame) -> str:
    nums = []
    if not df.empty and "tx_id" in df.columns:
        for val in df["tx_id"].astype(str):
            if val.startswith("TX-") and val[3:].isdigit():
                nums.append(int(val[3:]))
    nxt = (max(nums) + 1) if nums else 1
    return f"TX-{nxt:04d}"


def _parse_uploaded_ledger(uploaded_file) -> pd.DataFrame:
    name = uploaded_file.name.lower()
    if name.endswith(".xlsx") or name.endswith(".xls"):
        raw = pd.read_excel(uploaded_file)
    else:
        raw = pd.read_csv(uploaded_file)

    normalized = pd.DataFrame()
    col_map = {c.strip().lower(): c for c in raw.columns}

    def _pick(candidates: list[str], default=None):
        for cand in candidates:
            if cand in col_map:
                return raw[col_map[cand]]
        return default

    date_s = _pick(["date", "tx_date", "due_date"])
    amt_s = _pick(["amount", "value", "cashflow"])
    type_s = _pick(["tx_type", "type", "flow_type"])
    status_s = _pick(["status", "state"])
    desc_s = _pick(["description", "desc", "label", "notes"])
    cat_s = _pick(["category", "cat"])

    n_rows = len(raw)
    normalized["tx_id"] = [f"IMP-{i+1:04d}" for i in range(n_rows)]
    normalized["date"] = pd.to_datetime(date_s, errors="coerce") if date_s is not None else pd.Timestamp(TODAY)
    normalized["date"] = normalized["date"].fillna(pd.Timestamp(TODAY))
    normalized["description"] = desc_s.astype(str) if desc_s is not None else "Imported Entry"
    normalized["category"] = cat_s.astype(str) if cat_s is not None else "Imported Flow"

    raw_amt = pd.to_numeric(amt_s, errors="coerce").fillna(0.0) if amt_s is not None else pd.Series([0.0] * n_rows)
    if type_s is not None:
        normalized["tx_type"] = type_s.astype(str).str.strip().str.lower()
    else:
        normalized["tx_type"] = ["revenue" if v >= 0 else "expense" for v in raw_amt]

    normalized["inventory_type"] = "None"
    normalized["amount"] = raw_amt
    normalized["status"] = status_s.astype(str).str.strip().str.lower() if status_s is not None else "planned"
    normalized["payment_method"] = "bank"
    normalized["quantity"] = 0.0
    normalized["unit_price"] = 0.0
    normalized["payment_term_days"] = 0
    normalized["expected_delay_days"] = 0
    normalized["entry_hash"] = ""
    return normalized


# --- LOGIN GATE ---
if st.session_state.auth_user is None:
    st.title("🌊 Maréa — Convenience Store Cash Flow Manager")
    st.caption("⚓ Sign in with your username and 6-digit PIN (demo PIN for all accounts: `123456`).")

    with st.container(border=True):
        with st.form("login_form"):
            username = st.selectbox("👤 Username", options=list(USERS.keys()))
            pin = st.text_input("🔑 6-Digit Password", type="password", max_chars=6, placeholder="123456")
            submitted = st.form_submit_button("🚢 Sign In")

            if submitted:
                if not pin.isdigit() or len(pin) != 6:
                    st.error("⚠️ Password must be a 6-digit number.")
                elif pin != DEMO_PIN:
                    st.error("❌ Invalid 6-digit password. For demonstration, use `123456`.")
                else:
                    st.session_state.auth_user = username
                    st.rerun()
    st.stop()


current_user = st.session_state.auth_user
user_meta = USERS[current_user]
role = user_meta["role"]

col_title, col_logout = st.columns([5, 1])
with col_title:
    st.title("🌊 Maréa — SME Cash Flow & Ledger")
    st.caption(
        f"⚓ Signed in as **{user_meta['label']}** | 📅 Reference Date: **{TODAY.strftime('%Y-%m-%d')}** | "
        f"👥 Staff: **{STORE_RULES['employees_count']}** | 🌴 Closed Sundays"
    )
with col_logout:
    st.write("")
    if st.button("🚪 Sign Out"):
        st.session_state.auth_user = None
        st.rerun()

df = st.session_state.ledger_df


# ==============================================================================
# ROLE 1: NAM (EMPLOYEE)
# ==============================================================================
if role == "employee":
    st.subheader("🐚 Employee Transaction Entry (Sales & Inventory Receipts)")
    st.info("🌊 Record **revenue** (sales) or **inventory** receipts. Entries are validated and saved to the ledger.")

    tx_type = st.selectbox("📦 Type of Transaction", options=["revenue", "inventory"])

    st.markdown("#### 🧾 Transaction Line Item")
    c_inv, c_qty, c_auto = st.columns(3)
    inv_choice = c_inv.selectbox("🛒 Type of Inventory", options=list(INVENTORY_CATALOG.keys()))
    default_price = INVENTORY_CATALOG[inv_choice]
    qty_val = c_qty.number_input("🔢 Number of Inventory (Units)", min_value=0.0, value=10.0, step=1.0)

    if tx_type == "revenue":
        c_auto.number_input(
            "💶 Auto-Calculated Total Amount (€)",
            min_value=0.0,
            value=round(qty_val * default_price, 2),
            step=1.0,
            disabled=True,
        )
        computed_total = round(qty_val * default_price, 2)
    else:
        c_auto.text_input(
            "💶 Auto-Calculated Total Amount (€)",
            value="Not applicable for inventory receipt",
            disabled=True,
        )
        computed_total = round(qty_val * default_price * 0.65, 2)

    with st.container(border=True):
        with st.form("employee_tx_form", clear_on_submit=True):
            tx_date = st.date_input("📅 Transaction Date", value=TODAY.date())
            desc = st.text_input(
                "📝 Description",
                value=f"{'Client Sale' if tx_type == 'revenue' else 'Inventory Receipt'} — {inv_choice}",
            )
            pay_method = st.selectbox("💳 Payment Method", options=["cash", "bank"])
            save_btn = st.form_submit_button("💾 Save Transaction to CSV")

            if save_btn:
                errors = []
                if qty_val <= 0:
                    errors.append("Number of inventory must be greater than 0.")
                if not desc.strip():
                    errors.append("Description cannot be empty.")
                if tx_type == "revenue" and computed_total <= 0:
                    errors.append("Calculated revenue amount must be positive.")

                if errors:
                    for err in errors:
                        st.error(f"⚠️ {err}")
                else:
                    signed_amt = computed_total if tx_type == "revenue" else -computed_total
                    new_row = pd.DataFrame([{
                        "tx_id": next_tx_id(df),
                        "date": pd.to_datetime(tx_date).normalize(),
                        "description": desc.strip(),
                        "category": "Daily Sales" if tx_type == "revenue" else "Inventory Receipt",
                        "tx_type": tx_type,
                        "inventory_type": inv_choice,
                        "quantity": float(qty_val),
                        "unit_price": float(default_price),
                        "amount": float(signed_amt),
                        "payment_method": pay_method,
                        "status": "actual",
                        "payment_term_days": 0 if tx_type == "revenue" else STORE_RULES["default_dpo_days"],
                        "expected_delay_days": 0,
                        "entry_hash": "",
                    }])
                    updated = pd.concat([df, new_row], ignore_index=True)
                    st.session_state.ledger_df = save_store_ledger(updated, str(CSV_PATH) if CSV_PATH.exists() else None)
                    st.success(f"✅ Saved {tx_type} entry (€{abs(signed_amt):,.2f}).")
                    st.rerun()


# ==============================================================================
# ROLE 2: NOELLE (ACCOUNTANT)
# ==============================================================================
elif role == "accountant":
    st.subheader("🧭 Accountant Ledger Entry, Import & Policy Controls")
    st.caption(
        f"🏦 Payment Channel: **bank** | ⏳ Max supplier payment term = **{STORE_RULES['max_supplier_payment_days']} days** "
        f"(default {STORE_RULES['default_dpo_days']} days) | 💼 Payroll normally on the **{STORE_RULES['normal_payroll_day']}th** "
        f"(latest **{STORE_RULES['latest_payroll_day']}th**, adjusted for French holidays) | "
        f"🌊 Max overdraft = **€{STORE_RULES['max_bank_overdraft']:,.0f}** | 🛟 Max short-term borrowing = **€{STORE_RULES['max_short_term_borrowing']:,.0f}**."
    )

    c1, c2, c3 = st.columns(3)
    tx_type = c1.selectbox(
        "📂 Transaction Type",
        options=list(ACCOUNTANT_CATEGORIES_BY_TYPE.keys()),
        key="acc_tx_type",
    )
    category = c2.selectbox(
        "🏷️ Category",
        options=ACCOUNTANT_CATEGORIES_BY_TYPE[tx_type],
        key=f"acc_category_{tx_type}",
    )
    inv_type = c3.selectbox(
        "📦 Inventory / Scope",
        options=ACCOUNTANT_INVENTORY_BY_TYPE[tx_type],
        key=f"acc_inv_{tx_type}",
    )

    pay_method = "bank"

    with st.container(border=True):
        with st.form("accountant_tx_form", clear_on_submit=True):
            c5, c6, c7, c8 = st.columns(4)
            tx_date = c5.date_input("📅 Date", value=TODAY.date())
            raw_amount = c6.number_input("💶 Amount (€, positive magnitude)", min_value=0.01, value=500.0, step=50.0)
            term_days = c7.number_input("⏱️ Payment Term (days)", min_value=0, max_value=180, value=STORE_RULES["default_dpo_days"], step=1)
            status_val = c8.selectbox("📌 Status", options=["actual", "planned"])

            desc = st.text_input("📝 Accounting Description / Reference", placeholder="e.g., November Supplier Settlement or Tax Filing")
            submitted = st.form_submit_button("💾 Record & Save Ledger")

            if submitted:
                errors = []
                if not desc.strip():
                    errors.append("Please enter an accounting description.")
                if tx_type == "inventory" and term_days > STORE_RULES["max_supplier_payment_days"]:
                    errors.append(f"Supplier payment term cannot exceed {STORE_RULES['max_supplier_payment_days']} days.")

                kpis = compute_financial_kpis(df)
                is_inflow = tx_type == "revenue" or category == "Short-Term Borrowing"
                signed_amt = float(raw_amount) if is_inflow else -float(raw_amount)

                if category == "Short-Term Borrowing" and (kpis["short_term_borrowings"] + raw_amount) > STORE_RULES["max_short_term_borrowing"]:
                    errors.append(f"Short-term borrowing would exceed the €{STORE_RULES['max_short_term_borrowing']:,.0f} cap.")
                if signed_amt < 0:
                    projected_bank = kpis["bank_balance"] + signed_amt
                    if projected_bank < -STORE_RULES["max_bank_overdraft"]:
                        errors.append(f"Bank outflow would exceed the €{STORE_RULES['max_bank_overdraft']:,.0f} overdraft limit.")

                if errors:
                    for err in errors:
                        st.error(f"⚠️ {err}")
                else:
                    final_date = pd.to_datetime(tx_date).normalize()
                    new_row = pd.DataFrame([{
                        "tx_id": next_tx_id(df),
                        "date": final_date,
                        "description": desc.strip(),
                        "category": category,
                        "tx_type": tx_type,
                        "inventory_type": inv_type,
                        "quantity": 0.0,
                        "unit_price": 0.0,
                        "amount": signed_amt,
                        "payment_method": pay_method,
                        "status": status_val,
                        "payment_term_days": int(term_days),
                        "expected_delay_days": 0,
                        "entry_hash": "",
                    }])
                    updated = pd.concat([df, new_row], ignore_index=True)
                    st.session_state.ledger_df = save_store_ledger(updated, str(CSV_PATH) if CSV_PATH.exists() else None)
                    st.success("✅ Recorded entry and recomputed SHA-256 hash chain.")
                    st.rerun()

    st.markdown("#### 📥 Import CSV or Excel Transactions")
    uploaded_file = st.file_uploader("Upload CSV or Excel (.xlsx/.xls) file", type=["csv", "xlsx", "xls"])
    if uploaded_file is not None and st.button("➕ Append Uploaded Rows to Ledger"):
        imp_df = _parse_uploaded_ledger(uploaded_file)
        merged = pd.concat([df, imp_df], ignore_index=True)
        st.session_state.ledger_df = save_store_ledger(merged, str(CSV_PATH) if CSV_PATH.exists() else None)
        st.success(f"✅ Appended {len(imp_df)} rows from `{uploaded_file.name}`.")
        st.rerun()

    st.markdown("#### 📜 Recent Ledger Entries")
    st.dataframe(df.tail(15), use_container_width=True, hide_index=True)


# ==============================================================================
# ROLE 3: RANIA (OWNER) — OVERVIEW, ALERTS, FORECAST, ACTIONS & INTEGRITY
# ==============================================================================
else:
    kpis = compute_financial_kpis(df)
    thresh_rec = recommend_cashflow_threshold(df)
    opening_cash_actual = float(kpis["total_cash_and_bank"])

    # --- AREA 1: FINANCIAL POSITION & SHORTAGE ALERT ---
    st.subheader("⚓ 1. Financial Position & Shortage Alert")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📈 Profit & Loss (Actuals)", f"€{kpis['profit_and_loss']:,.2f}")
    m2.metric("🌊 Available Cash + Bank", f"€{opening_cash_actual:,.2f}")
    m3.metric("🛟 Overdraft + ST Borrowings", f"€{kpis['total_debt_and_overdraft']:,.2f}")
    m4.metric("📊 Suggested Threshold", f"€{thresh_rec['recommended_threshold']:,.2f}")

    alert_threshold = st.number_input(
        "🚨 Minimum Cash Alert Threshold (€)",
        min_value=0.0,
        value=float(thresh_rec["recommended_threshold"]),
        step=250.0,
    )

    st.caption(
        f"💵 Cash on hand: €{kpis['cash_balance']:,.2f} | 🏦 Bank balance: €{kpis['bank_balance']:,.2f} | "
        f"🛟 Overdraft + ST Borrowings: €{kpis['total_debt_and_overdraft']:,.2f} | "
        f"📊 Suggested threshold: €{thresh_rec['recommended_threshold']:,.2f}"
    )

    st.divider()

    # --- AREA 2: FORECASTED CASHFLOW & PROFIT TRAJECTORY ---
    apply_dpo_20 = bool(st.session_state.get("rec_dpo_20", False))
    apply_payroll_15th = bool(st.session_state.get("rec_payroll_15th", False))
    apply_loan_1000 = bool(st.session_state.get("rec_loan_1000", False))

    current_events: list[dict] = []
    for i in range(1, 6):
        ev_desc = str(st.session_state.get(f"ev_desc_{i}", "") or "").strip()
        ev_dmg = float(st.session_state.get(f"ev_dmg_{i}", 0.0) or 0.0)
        if ev_desc and ev_dmg > 0:
            current_events.append({
                "description": ev_desc,
                "affected_tx": st.session_state.get(f"ev_tx_{i}", "revenue"),
                "affected_inventory": st.session_state.get(f"ev_inv_{i}", "All Inventories"),
                "damage_pct": ev_dmg,
                "start_date": st.session_state.get(f"ev_start_{i}", TODAY.date()),
                "end_date": st.session_state.get(f"ev_end_{i}", (TODAY + timedelta(days=7)).date()),
            })

    has_changes = any([apply_dpo_20, apply_payroll_15th, apply_loan_1000]) or len(current_events) > 0

    if has_changes:
        st.subheader("🌊 2. Forecasted Cashflow & Cumulative Profit Trajectory (Before vs. After Changes)")
    else:
        st.subheader("🌊 2. Forecasted Cashflow & Cumulative Profit Trajectory")

    ctrl1, ctrl2 = st.columns([1, 2])
    horizon_days = ctrl1.selectbox("⏳ Forecast Window (Days)", options=[30, 60, 90], index=0)
    revenue_scenario = ctrl2.selectbox("🌤️ Revenue Scenario", options=list(REVENUE_SCENARIOS.keys()), index=1)
    st.caption(f"ℹ️ {REVENUE_SCENARIOS[revenue_scenario]['description']}")

    proj_df = build_owner_forecast(
        df=df,
        horizon_days=int(horizon_days),
        scenario=revenue_scenario,
        opening_cash=opening_cash_actual,
        apply_dpo_20=apply_dpo_20,
        apply_payroll_15th=apply_payroll_15th,
        apply_loan_1000=apply_loan_1000,
        events=current_events,
    )

    alert_before = summarize_shortage_alerts(proj_df, threshold=float(alert_threshold), col="cum_cash_before")
    alert_after = summarize_shortage_alerts(proj_df, threshold=float(alert_threshold), col="cum_cash_after")

    alert_prefix = "**Before Changes Alert:**" if has_changes else "**Shortage Alert:**"
    ok_prefix = "**Before Changes:**" if has_changes else "**Liquidity Status:**"

    if alert_before["has_shortage"]:
        st.warning(
            f"⚠️ {alert_prefix} Cash falls below **€{alert_threshold:,.2f}** starting **{alert_before['first_alert_date']}** "
            f"(lowest projected balance: **€{alert_before['lowest_balance']:,.2f}** on **{alert_before['lowest_date']}**, "
            f"{alert_before['alert_days_count']} day(s) below threshold). "
            f"Causes: {' '.join(alert_before['causes'])}"
        )
    else:
        st.success(
            f"✅ {ok_prefix} Projected cash stays at or above **€{alert_threshold:,.2f}** over {horizon_days} days "
            f"(lowest balance: **€{alert_before['lowest_balance']:,.2f}** on **{alert_before['lowest_date']}**)."
        )

    if has_changes:
        after_status = (
            "no threshold breach"
            if not alert_after["has_shortage"]
            else f"first alert {alert_after['first_alert_date']}, {alert_after['alert_days_count']} day(s) below threshold"
        )
        st.info(
            f"🔄 **After Changes Comparison:** Lowest balance moves from **€{alert_before['lowest_balance']:,.2f}** "
            f"to **€{alert_after['lowest_balance']:,.2f}** ({after_status})."
        )

        cf_combined_df = proj_df.melt(
            id_vars=["date"],
            value_vars=["cum_cash_before", "cum_cash_after"],
            var_name="Series",
            value_name="Forecasted Cashflow (€)",
        )
        cf_combined_df["Series"] = cf_combined_df["Series"].map({
            "cum_cash_before": "Before Changes",
            "cum_cash_after": "After Changes",
        })

        profit_combined_df = proj_df.melt(
            id_vars=["date"],
            value_vars=["cum_profit_before", "cum_profit_after"],
            var_name="Series",
            value_name="Cumulative Profit (€)",
        )
        profit_combined_df["Series"] = profit_combined_df["Series"].map({
            "cum_profit_before": "Before Changes",
            "cum_profit_after": "After Changes",
        })

        cf_color_scale = alt.Scale(
            domain=["Before Changes", "After Changes"],
            range=["#1D4ED8", "#F97316"],
        )
        profit_color_scale = alt.Scale(
            domain=["Before Changes", "After Changes"],
            range=["#0F172A", "#E11D48"],
        )

        st.markdown(f"**💧 Forecasted Cashflow — Before vs. After Changes ({horizon_days} Days — {revenue_scenario})**")
        chart_cf = (
            alt.Chart(cf_combined_df)
            .mark_line(strokeWidth=3)
            .encode(
                x=alt.X("date:T", title="Date"),
                y=alt.Y("Forecasted Cashflow (€):Q", title="Forecasted Cashflow (€)"),
                color=alt.Color("Series:N", scale=cf_color_scale, title="Scenario Stage"),
                strokeDash=alt.StrokeDash(
                    "Series:N",
                    scale=alt.Scale(domain=["Before Changes", "After Changes"], range=[[6, 4], [1, 0]]),
                    legend=None,
                ),
                tooltip=[
                    alt.Tooltip("date:T", title="Date"),
                    alt.Tooltip("Series:N", title="Stage"),
                    alt.Tooltip("Forecasted Cashflow (€):Q", title="Cash (€)", format=",.2f"),
                ],
            )
            .properties(height=340)
        )
        st.altair_chart(chart_cf, use_container_width=True)

        st.markdown(f"**📊 Cumulative Profit Trajectory — Before vs. After Changes ({horizon_days} Days — {revenue_scenario})**")
        chart_profit = (
            alt.Chart(profit_combined_df)
            .mark_line(strokeWidth=3)
            .encode(
                x=alt.X("date:T", title="Date"),
                y=alt.Y("Cumulative Profit (€):Q", title="Cumulative Profit (€)"),
                color=alt.Color("Series:N", scale=profit_color_scale, title="Scenario Stage"),
                strokeDash=alt.StrokeDash(
                    "Series:N",
                    scale=alt.Scale(domain=["Before Changes", "After Changes"], range=[[6, 4], [1, 0]]),
                    legend=None,
                ),
                tooltip=[
                    alt.Tooltip("date:T", title="Date"),
                    alt.Tooltip("Series:N", title="Stage"),
                    alt.Tooltip("Cumulative Profit (€):Q", title="Profit (€)", format=",.2f"),
                ],
            )
            .properties(height=340)
        )
        st.altair_chart(chart_profit, use_container_width=True)
    else:
        st.markdown(f"**💧 Forecasted Cashflow ({horizon_days} Days — {revenue_scenario})**")
        chart_cf = (
            alt.Chart(proj_df)
            .mark_line(strokeWidth=3, color="#1D4ED8")
            .encode(
                x=alt.X("date:T", title="Date"),
                y=alt.Y("cum_cash_before:Q", title="Forecasted Cashflow (€)"),
                tooltip=[
                    alt.Tooltip("date:T", title="Date"),
                    alt.Tooltip("cum_cash_before:Q", title="Forecasted Cash (€)", format=",.2f"),
                ],
            )
            .properties(height=340)
        )
        st.altair_chart(chart_cf, use_container_width=True)

        st.markdown(f"**📊 Cumulative Profit Trajectory ({horizon_days} Days — {revenue_scenario})**")
        chart_profit = (
            alt.Chart(proj_df)
            .mark_line(strokeWidth=3, color="#0F172A")
            .encode(
                x=alt.X("date:T", title="Date"),
                y=alt.Y("cum_profit_before:Q", title="Cumulative Profit (€)"),
                tooltip=[
                    alt.Tooltip("date:T", title="Date"),
                    alt.Tooltip("cum_profit_before:Q", title="Cumulative Profit (€)", format=",.2f"),
                ],
            )
            .properties(height=340)
        )
        st.altair_chart(chart_profit, use_container_width=True)

    st.divider()

    # --- AREA 3: ACTIONABLE RECOMMENDATIONS ---
    st.subheader("🧭 3. Liquidity & Working Capital Recommendations")
    st.caption("☑️ Toggle actions below to compare Before vs. After cash balance and profit above.")

    with st.container(border=True):
        st.checkbox(
            "📦 **Action 1 — Supplier Payment Terms (DPO):** Extend supplier DPO to 20 days from 10/12/2026 to ease near-term cash outflows.",
            key="rec_dpo_20",
        )

    with st.container(border=True):
        st.checkbox(
            "💼 **Action 2 — Monthly Payroll Timing:** Align monthly payroll timing on the 15th (within policy rules, adjusted for French holidays).",
            key="rec_payroll_15th",
        )

    with st.container(border=True):
        st.checkbox(
            f"🛟 **Action 3 — Short-Term Liquidity Bridge:** Draw €{STORE_RULES['recommended_loan_amount']:,.0f} on 01/12/2026 and model {STORE_RULES['recommended_loan_term_days']}-day repayment + {STORE_RULES['recommended_loan_interest_pct']}% interest.",
            key="rec_loan_1000",
        )

    st.divider()

    # --- AREA 4: 5 NON-RECURRING EVENT LINES ---
    st.subheader("⚡ 4. Non-Recurring Events Simulator (Up to 5 Events)")
    st.caption(f"📅 Start dates cannot be earlier than today (**{TODAY.strftime('%Y-%m-%d')}**).")

    active_events: list[dict] = []
    for i in range(1, 6):
        with st.expander(f"🌊 Non-Recurring Event #{i}", expanded=(i == 1)):
            c_desc, c_tx, c_inv, c_dmg, c_start, c_end = st.columns([2.2, 1.3, 1.5, 1.1, 1.3, 1.3])
            ev_desc = c_desc.text_input(
                "📝 Event Description",
                key=f"ev_desc_{i}",
                placeholder="e.g., Local transport protest" if i == 1 else ("e.g., Banana supplier shortage" if i == 2 else ""),
            )
            ev_tx = c_tx.selectbox(
                "📂 Affected Transaction",
                options=["revenue", "inventories", "tax"],
                key=f"ev_tx_{i}",
            )
            ev_inv = c_inv.selectbox(
                "📦 Affected Inventory",
                options=INVENTORY_OPTIONS_WITH_ALL,
                key=f"ev_inv_{i}",
            )
            ev_dmg = c_dmg.number_input(
                "📉 Damage / Impact (%)",
                min_value=0.0,
                max_value=100.0,
                value=0.0,
                step=5.0,
                key=f"ev_dmg_{i}",
            )
            ev_start = c_start.date_input(
                "📅 Start Date",
                value=TODAY.date(),
                min_value=TODAY.date(),
                key=f"ev_start_{i}",
            )
            ev_end = c_end.date_input(
                "🏁 End Date",
                value=(TODAY + timedelta(days=7)).date(),
                min_value=ev_start,
                key=f"ev_end_{i}",
            )

            if ev_desc.strip() and ev_dmg > 0:
                active_events.append({
                    "description": ev_desc.strip(),
                    "affected_tx": ev_tx,
                    "affected_inventory": ev_inv,
                    "damage_pct": ev_dmg,
                    "start_date": ev_start,
                    "end_date": ev_end,
                })

    st.divider()

    # --- AREA 5: EVENT IMPACT SUMMARY BOX ---
    st.subheader("📋 5. Non-Recurring Events Impact Summary")
    impact_summary = evaluate_non_recurring_events(active_events)
    s1, s2, s3 = st.columns(3)
    s1.metric("📉 Estimated Revenue Impact", f"€{impact_summary['total_revenue_delta']:,.2f}")
    s2.metric("📦 Estimated Inventory/Cost Delta", f"€{impact_summary['total_cost_delta']:,.2f}")
    s3.metric("🌊 Estimated Net Cashflow Impact", f"€{impact_summary['total_cashflow_delta']:,.2f}")

    if impact_summary["summaries"]:
        for line in impact_summary["summaries"]:
            st.write(f"🌊 {line}")
    else:
        st.info("ℹ️ No active non-recurring events entered yet. Add details in Section 4 above to see calculated impacts.")

    # --- OWNER-ONLY: LEDGER INTEGRITY (SHA-256 HASH CHAIN) & CSV EXPORT ---
    st.divider()
    st.subheader("🔐 Ledger Integrity & SHA-256 Hash Chain")
    audited_df, audit_stats = audit_ledger_integrity(st.session_state.ledger_df)

    if audit_stats["is_clean"]:
        st.success(f"✅ Ledger chain verified: {len(audited_df)} entries checked, 0 tampered rows, 0 duplicates.")
    else:
        st.warning(
            f"⚠️ Audit alert: **{audit_stats['tampered_count']}** tampered hash(es) and "
            f"**{audit_stats['duplicate_count']}** duplicate entry/entries detected."
        )

    with st.expander("🔍 Inspect SHA-256 Hash Chain & Flagged Entries"):
        if audited_df.empty:
            st.info("No ledger records available to inspect.")
        else:
            show_cols = [
                c for c in [
                    "tx_id", "date", "description", "category", "tx_type",
                    "inventory_type", "amount", "payment_method", "status",
                    "entry_hash", "computed_hash", "audit_status",
                ]
                if c in audited_df.columns
            ]
            display_audit = audited_df[show_cols].copy()
            if "date" in display_audit.columns:
                display_audit["date"] = pd.to_datetime(display_audit["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            st.dataframe(display_audit, use_container_width=True, hide_index=True)

    csv_bytes = st.session_state.ledger_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Download Updated CSV Ledger",
        data=csv_bytes,
        file_name="convenience_store_2025_2026.csv",
        mime="text/csv",
    )
