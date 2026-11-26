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
)

st.set_page_config(
    page_title="Maréa — Convenience Store Cash Flow & Ledger",
    page_icon="🏪",
    layout="wide",
)

CSV_PATH = Path(__file__).parent / "convenience_store_2025_2026.csv"

USERS = {
    "Nam": {"role": "employee", "label": "Nam — Store Employee"},
    "Noelle": {"role": "accountant", "label": "Noelle — Accountant"},
    "Rania": {"role": "owner", "label": "Rania — Store Owner"},
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
    st.session_state.ledger_df = load_store_ledger(str(CSV_PATH))

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


# --- LOGIN GATE ---
if st.session_state.auth_user is None:
    st.title("🏪 Maréa — Convenience Store Cash Flow Manager")
    st.caption("Sign in with your username and 6-digit PIN (demo PIN for all accounts: `123456`).")

    with st.form("login_form"):
        username = st.selectbox("Username", options=list(USERS.keys()))
        pin = st.text_input("6-Digit Password", type="password", max_chars=6, placeholder="123456")
        submitted = st.form_submit_button("Sign In")

        if submitted:
            if not pin.isdigit() or len(pin) != 6:
                st.error("Password must be a 6-digit number.")
            elif pin != DEMO_PIN:
                st.error("Invalid 6-digit password. For demonstration, use `123456`.")
            else:
                st.session_state.auth_user = username
                st.rerun()
    st.stop()


current_user = st.session_state.auth_user
user_meta = USERS[current_user]
role = user_meta["role"]

# Top header & logout
col_title, col_logout = st.columns([5, 1])
with col_title:
    st.title("🏪 Maréa — SME Cash Flow & Ledger")
    st.caption(
        f"Signed in as **{user_meta['label']}** | Reference Date: **{TODAY.strftime('%Y-%m-%d')}** | "
        f"Staff: **{STORE_RULES['employees_count']}**"
    )
with col_logout:
    st.write("")
    if st.button("Sign Out"):
        st.session_state.auth_user = None
        st.rerun()

df = st.session_state.ledger_df


# ==============================================================================
# ROLE 1: NAM (EMPLOYEE)
# ==============================================================================
if role == "employee":
    st.subheader("Employee Transaction Entry (Sales & Inventory Receipts)")
    st.info("You can record **revenue** (client sales) or **inventory** receipts. Entries are validated and saved directly to the CSV ledger.")

    tx_type = st.selectbox("Type of Transaction", options=["revenue", "inventory"])

    st.markdown("#### Transaction Line Item")
    c_inv, c_qty, c_auto = st.columns(3)
    inv_choice = c_inv.selectbox("Type of Inventory", options=list(INVENTORY_CATALOG.keys()))
    default_price = INVENTORY_CATALOG[inv_choice]
    qty_val = c_qty.number_input("Number of Inventory (Units)", min_value=0.0, value=10.0, step=1.0)

    if tx_type == "revenue":
        c_auto.number_input(
            "Auto-Calculated Total Amount (€)",
            min_value=0.0,
            value=round(qty_val * default_price, 2),
            step=1.0,
            disabled=True,
        )
        computed_total = round(qty_val * default_price, 2)
    else:
        c_auto.text_input(
            "Auto-Calculated Total Amount (€)",
            value="Not applicable for inventory receipt",
            disabled=True,
        )
        computed_total = round(qty_val * default_price * 0.65, 2)

    with st.form("employee_tx_form", clear_on_submit=True):
        tx_date = st.date_input("Transaction Date", value=TODAY.date())
        desc = st.text_input(
            "Description",
            value=f"{'Client Sale' if tx_type == 'revenue' else 'Inventory Receipt'} — {inv_choice}",
        )
        pay_method = st.selectbox("Payment Method", options=["cash", "bank"])
        save_btn = st.form_submit_button("Save Transaction to CSV")

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
                    st.error(err)
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
                st.session_state.ledger_df = save_store_ledger(updated, str(CSV_PATH))
                st.success(f"Saved {tx_type} entry (€{abs(signed_amt):,.2f}) to `{CSV_PATH.name}`.")
                st.rerun()


# ==============================================================================
# ROLE 2: NOELLE (ACCOUNTANT)
# ==============================================================================
elif role == "accountant":
    st.subheader("Accountant Ledger Entry & Policy Controls")
    st.caption(
        f"Payment Channel: **bank** | Max supplier payment term = **{STORE_RULES['max_supplier_payment_days']} days** "
        f"(default {STORE_RULES['default_dpo_days']} days) | Payroll normally on the **{STORE_RULES['normal_payroll_day']}th** "
        f"(latest **{STORE_RULES['latest_payroll_day']}th** of following month, adjusted for French holidays) | "
        f"Max overdraft = **€{STORE_RULES['max_bank_overdraft']:,.0f}** | Max short-term borrowing = **€{STORE_RULES['max_short_term_borrowing']:,.0f}**."
    )

    c1, c2, c3 = st.columns(3)
    tx_type = c1.selectbox(
        "Transaction Type",
        options=list(ACCOUNTANT_CATEGORIES_BY_TYPE.keys()),
        key="acc_tx_type",
    )
    category = c2.selectbox(
        "Category",
        options=ACCOUNTANT_CATEGORIES_BY_TYPE[tx_type],
        key=f"acc_category_{tx_type}",
    )
    inv_type = c3.selectbox(
        "Inventory / Scope",
        options=ACCOUNTANT_INVENTORY_BY_TYPE[tx_type],
        key=f"acc_inv_{tx_type}",
    )

    pay_method = "bank"

    with st.form("accountant_tx_form", clear_on_submit=True):
        c5, c6, c7, c8 = st.columns(4)
        tx_date = c5.date_input("Date", value=TODAY.date())
        raw_amount = c6.number_input("Amount (€, positive magnitude)", min_value=0.01, value=500.0, step=50.0)
        term_days = c7.number_input("Payment Term (days)", min_value=0, max_value=180, value=STORE_RULES["default_dpo_days"], step=1)
        status_val = c8.selectbox("Status", options=["actual", "planned"])

        desc = st.text_input("Accounting Description / Reference", placeholder="e.g., November Supplier Settlement or Tax Filing")
        submitted = st.form_submit_button("Record & Save to CSV")

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
                    st.error(err)
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
                st.session_state.ledger_df = save_store_ledger(updated, str(CSV_PATH))
                st.success(f"Recorded entry and saved to `{CSV_PATH.name}`.")
                st.rerun()

    st.markdown("#### Recent Ledger Entries")
    st.dataframe(df.tail(15), use_container_width=True, hide_index=True)


# ==============================================================================
# ROLE 3: RANIA (OWNER) — 5 REQUIRED AREAS + REVENUE SCENARIO + AUDIT CHAIN
# ==============================================================================
else:
    kpis = compute_financial_kpis(df)
    thresh_rec = recommend_cashflow_threshold(df)

    # --- AREA 1: P&L, TOTAL CASH + BANK, OVERDRAFT + BORROWINGS ---
    st.subheader("1. Financial Position & Cash Overview")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Profit & Loss (Actuals)", f"€{kpis['profit_and_loss']:,.2f}")
    m2.metric("Total Cash + Cash in Bank", f"€{kpis['total_cash_and_bank']:,.2f}")
    m3.metric("Overdraft + Short-Term Borrowings", f"€{kpis['total_debt_and_overdraft']:,.2f}")
    m4.metric("Recommended Alert Threshold", f"€{thresh_rec['recommended_threshold']:,.2f}")

    st.caption(
        f"Breakdown — Cash on hand: €{kpis['cash_balance']:,.2f} | Bank balance: €{kpis['bank_balance']:,.2f} | "
        f"Overdraft used: €{kpis['overdraft_used']:,.2f} (Limit €{STORE_RULES['max_bank_overdraft']:,.0f}) | "
        f"Short-term borrowings: €{kpis['short_term_borrowings']:,.2f} (Limit €{STORE_RULES['max_short_term_borrowing']:,.0f})"
    )

    st.divider()

    # --- AREA 2: ACTIONABLE RECOMMENDATIONS WITH DECISION CHECKBOXES ---
    st.subheader("2. Liquidity & Working Capital Recommendations")
    r1, r2, r3 = st.columns(3)
    apply_dpo_20 = r1.checkbox(
        "Extend supplier Days Payable Outstanding (DPO) to 20 days starting 10/12/2026 (currently 10 days, which tightens near-term liquidity).",
        value=False,
    )
    apply_payroll_15th = r2.checkbox(
        "Schedule monthly employee payroll on the 15th of the following month (within the statutory/policy window, adjusted for French holidays).",
        value=False,
    )
    apply_loan_1000 = r3.checkbox(
        "Arrange a 60-day short-term credit facility of €1,000 prior to 20/12/2026 to reinforce cash buffer during peak outflows.",
        value=False,
    )

    st.divider()

    # --- AREA 4: 5 NON-RECURRING EVENT LINES ---
    st.subheader("4. Non-Recurring Events Simulator (Up to 5 Events)")
    st.caption(f"Start dates cannot be earlier than today (**{TODAY.strftime('%Y-%m-%d')}**).")

    active_events: list[dict] = []
    for i in range(1, 6):
        with st.expander(f"Non-Recurring Event #{i}", expanded=(i == 1)):
            c_desc, c_tx, c_inv, c_dmg, c_start, c_end = st.columns([2.2, 1.3, 1.5, 1.1, 1.3, 1.3])
            ev_desc = c_desc.text_input(
                "Event Description",
                key=f"ev_desc_{i}",
                placeholder="e.g., Local transport protest" if i == 1 else ("e.g., Banana supplier shortage" if i == 2 else ""),
            )
            ev_tx = c_tx.selectbox(
                "Affected Transaction",
                options=["revenue", "inventories", "tax"],
                key=f"ev_tx_{i}",
            )
            ev_inv = c_inv.selectbox(
                "Affected Inventory",
                options=INVENTORY_OPTIONS_WITH_ALL,
                key=f"ev_inv_{i}",
            )
            ev_dmg = c_dmg.number_input(
                "Damage / Impact (%)",
                min_value=0.0,
                max_value=100.0,
                value=0.0,
                step=5.0,
                key=f"ev_dmg_{i}",
            )
            ev_start = c_start.date_input(
                "Start Date",
                value=TODAY.date(),
                min_value=TODAY.date(),
                key=f"ev_start_{i}",
            )
            ev_end = c_end.date_input(
                "End Date",
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

    # --- AREA 3: 30 / 60 / 90-DAY FORECAST & BEFORE/AFTER LINE GRAPHS ---
    st.subheader("3. Cashflow & Profit Forecast (Before vs. After Adjustments)")
    ctrl1, ctrl2 = st.columns([1, 2])
    horizon_days = ctrl1.selectbox("Forecast Window (Days)", options=[30, 60, 90], index=0)
    revenue_scenario = ctrl2.selectbox("Revenue Scenario", options=list(REVENUE_SCENARIOS.keys()), index=1)
    st.caption(REVENUE_SCENARIOS[revenue_scenario]["description"])

    proj_df = build_owner_forecast(
        df=df,
        horizon_days=int(horizon_days),
        scenario=revenue_scenario,
        apply_dpo_20=apply_dpo_20,
        apply_payroll_15th=apply_payroll_15th,
        apply_loan_1000=apply_loan_1000,
        events=active_events,
    )

    cf_long = proj_df.melt(
        id_vars=["date"],
        value_vars=["cum_cash_before", "cum_cash_after"],
        var_name="Series",
        value_name="Cumulative Cashflow (€)",
    )
    cf_long["Series"] = cf_long["Series"].map({
        "cum_cash_before": "Before Changes (Area 2 & 4)",
        "cum_cash_after": "After Changes (Area 2 & 4)",
    })

    profit_long = proj_df.melt(
        id_vars=["date"],
        value_vars=["cum_profit_before", "cum_profit_after"],
        var_name="Series",
        value_name="Cumulative Profit (€)",
    )
    profit_long["Series"] = profit_long["Series"].map({
        "cum_profit_before": "Before Changes (Area 2 & 4)",
        "cum_profit_after": "After Changes (Area 2 & 4)",
    })

    g1, g2 = st.columns(2)
    with g1:
        st.markdown(f"**Cumulative Cashflow ({horizon_days} Days — {revenue_scenario})**")
        chart_cf = (
            alt.Chart(cf_long)
            .mark_line(strokeWidth=2.5)
            .encode(
                x=alt.X("date:T", title="Date"),
                y=alt.Y("Cumulative Cashflow (€):Q"),
                color=alt.Color("Series:N"),
                tooltip=["date:T", "Series:N", alt.Tooltip("Cumulative Cashflow (€):Q", format=",.2f")],
            )
            .properties(height=300)
        )
        st.altair_chart(chart_cf, use_container_width=True)

    with g2:
        st.markdown(f"**Cumulative Profit Trajectory ({horizon_days} Days — {revenue_scenario})**")
        chart_pr = (
            alt.Chart(profit_long)
            .mark_line(strokeWidth=2.5)
            .encode(
                x=alt.X("date:T", title="Date"),
                y=alt.Y("Cumulative Profit (€):Q"),
                color=alt.Color("Series:N"),
                tooltip=["date:T", "Series:N", alt.Tooltip("Cumulative Profit (€):Q", format=",.2f")],
            )
            .properties(height=300)
        )
        st.altair_chart(chart_pr, use_container_width=True)

    st.divider()

    # --- AREA 5: EVENT IMPACT SUMMARY BOX ---
    st.subheader("5. Non-Recurring Events Impact Summary")
    impact_summary = evaluate_non_recurring_events(active_events)
    s1, s2, s3 = st.columns(3)
    s1.metric("Estimated Revenue Impact", f"€{impact_summary['total_revenue_delta']:,.2f}")
    s2.metric("Estimated Inventory/Cost Delta", f"€{impact_summary['total_cost_delta']:,.2f}")
    s3.metric("Estimated Net Cashflow Impact", f"€{impact_summary['total_cashflow_delta']:,.2f}")

    if impact_summary["summaries"]:
        for line in impact_summary["summaries"]:
            st.write(f"• {line}")
    else:
        st.info("No active non-recurring events entered yet. Add details in Section 4 above to see calculated impacts.")

    # --- OWNER-ONLY: LEDGER INTEGRITY (SHA-256 HASH CHAIN) & CSV EXPORT ---
    st.divider()
    st.subheader("🔐 Ledger Integrity & SHA-256 Hash Chain")
    audited_df, audit_stats = audit_ledger_integrity(st.session_state.ledger_df)

    if audit_stats["is_clean"]:
        st.success(f"Ledger chain verified: {len(audited_df)} entries checked, 0 tampered rows, 0 duplicates.")
    else:
        st.warning(
            f"Audit alert: **{audit_stats['tampered_count']}** tampered hash(es) and "
            f"**{audit_stats['duplicate_count']}** duplicate entry/entries detected."
        )

    with st.expander("Inspect SHA-256 Hash Chain & Flagged Entries"):
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
        label="Download Updated CSV Ledger",
        data=csv_bytes,
        file_name="convenience_store_2025_2026.csv",
        mime="text/csv",
    )
