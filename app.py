from datetime import date, timedelta
from pathlib import Path
import altair as alt
import pandas as pd
import streamlit as st

from finance_engine import (
    adjust_french_business_day,
    append_transaction,
    compute_financial_kpis,
    generate_90day_forecast,
    load_store_ledger,
    verify_ledger_integrity,
)

st.set_page_config(
    page_title="Maréa | SME Cash Flow & Treasury Manager",
    page_icon="🌊",
    layout="wide",
)

# ---------------------------------------------------------------------------
# ERROR 7: Ocean & Tides Theme + Clean Custom Styling
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    /* Ocean & Tides Palette */
    :root {
        --deep-ocean: #023E8A;
        --ocean-blue: #0077B6;
        --tide-teal: #0096C7;
        --seafoam: #00B4D8;
        --coastal-mist: #F0F8FF;
        --sand-border: #CAF0F8;
        --slate-ink: #0F2942;
    }

    .stApp {
        background: linear-gradient(180deg, #F4FAFF 0%, #FFFFFF 35%, #F7FBFC 100%);
        color: var(--slate-ink);
    }

    /* Header Banner */
    .marea-banner {
        background: linear-gradient(135deg, #023E8A 0%, #0077B6 55%, #0096C7 100%);
        padding: 1.35rem 1.75rem;
        border-radius: 14px;
        color: #FFFFFF;
        margin-bottom: 1.25rem;
        box-shadow: 0 6px 20px rgba(2, 62, 138, 0.14);
        border: 1px solid rgba(202, 240, 248, 0.35);
    }
    .marea-banner h1 {
        color: #FFFFFF !important;
        margin: 0 0 0.25rem 0;
        font-size: 1.75rem;
        letter-spacing: -0.02em;
    }
    .marea-banner p {
        color: #E0F4FF;
        margin: 0;
        font-size: 0.95rem;
    }

    /* Metric Cards */
    div[data-testid="stMetric"] {
        background: #FFFFFF;
        border: 1px solid #BCE6F7;
        border-left: 5px solid #0077B6;
        padding: 0.85rem 1rem;
        border-radius: 10px;
        box-shadow: 0 2px 8px rgba(0, 119, 182, 0.06);
    }
    div[data-testid="stMetric"] label {
        color: #023E8A !important;
        font-weight: 600 !important;
    }

    /* Section Headings */
    h2, h3 {
        color: #023E8A !important;
    }

    /* Primary Buttons */
    .stButton > button[kind="primary"] {
        background: linear-gradient(90deg, #0077B6 0%, #0096C7 100%);
        color: #FFFFFF;
        border: none;
        border-radius: 8px;
        font-weight: 600;
    }
    .stButton > button[kind="primary"]:hover {
        background: linear-gradient(90deg, #023E8A 0%, #0077B6 100%);
    }

    /* Subtle Info Strip */
    .tide-card {
        background-color: #EDF7FC;
        border: 1px solid #BCE6F7;
        border-radius: 10px;
        padding: 0.8rem 1rem;
        margin-bottom: 0.85rem;
        color: #0F2942;
        font-size: 0.9rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "convenience_store_2025_2026.csv"

if "ledger_df" not in st.session_state:
    st.session_state.ledger_df = load_store_ledger(str(CSV_PATH))

if "authenticated_role" not in st.session_state:
    st.session_state.authenticated_role = None

# ---------------------------------------------------------------------------
# Top Ocean & Tides Header
# ---------------------------------------------------------------------------
st.markdown(
    """
    <div class="marea-banner">
        <h1>🌊 Maréa — SME Cash Flow & Liquidity Navigator</h1>
        <p>Normandy Convenience Store Treasury • Real-Time Cash Visibility, Policy Controls & 90-Day Tide Forecasting</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar Authentication
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### ⚓ Workspace Access")
    role_choice = st.selectbox(
        "Select Team Role",
        [
            "Nam — Store Employee (POS & Stock)",
            "Noelle — Accountant (Ledger & Controls)",
            "Rania — Store Owner (Treasury & Forecast)",
        ],
    )
    pin_input = st.text_input("Access PIN (Demo: 123456)", type="password", value="123456")

    col_login, col_logout = st.columns(2)
    with col_login:
        if st.button("🔓 Unlock", type="primary", use_container_width=True):
            if pin_input == "123456":
                st.session_state.authenticated_role = role_choice.split(" — ")[0]
            else:
                st.error("Invalid PIN. Use 123456.")
    with col_logout:
        if st.button("🔒 Lock", use_container_width=True):
            st.session_state.authenticated_role = None

    st.divider()
    st.caption("🧭 **Role Permissions**")
    st.caption("• **Nam:** Daily POS sales & stock intake")
    st.caption("• **Noelle:** Accounting entries & policy guardrails")
    st.caption("• **Rania:** Executive KPIs, 90-day forecast & SHA-256 audit")

active_role = st.session_state.authenticated_role

if not active_role:
    st.info("👈 Select a role in the sidebar and click **Unlock** (Demo PIN: `123456`) to enter Maréa.")
    st.stop()

df = st.session_state.ledger_df
TODAY = date(2026, 11, 25)

# ===========================================================================
# ROLE 1: NAM (STORE EMPLOYEE)
# ===========================================================================
if active_role == "Nam":
    st.subheader("🛒 Storefront POS & Inventory Intake — Nam")
    st.markdown(
        '<div class="tide-card">Log daily register sales or urgent stock deliveries. Entries are timestamped and hashed automatically into the store ledger.</div>',
        unsafe_allow_html=True,
    )

    with st.form("nam_pos_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            entry_kind = st.selectbox("Activity Type", ["Daily POS Sales (+)", "Urgent Stock Delivery (-)"])
            tx_date = st.date_input("Date", value=TODAY)
        with c2:
            if "Sales" in entry_kind:
                scope = st.selectbox(
                    "Product Department",
                    ["General Grocery & Snacks", "Beverages & Coffee", "Bakery & Ready-to-Eat", "Fresh Produce & Dairy"],
                )
                channel = st.selectbox("Payment Method", ["card", "cash"])
            else:
                scope = st.selectbox(
                    "Delivery Department",
                    ["Fresh Produce & Dairy", "Beverages & Coffee", "Dry Goods & Packaged", "Bakery & Ready-to-Eat"],
                )
                channel = st.selectbox("Payment Method", ["cash", "bank"])
        with c3:
            amount_val = st.number_input("Amount (€)", min_value=1.0, max_value=25000.0, value=450.0, step=10.0)
            notes = st.text_input("Shift Note", placeholder="e.g., Morning register batch")

        submitted = st.form_submit_button("📥 Record Store Entry", type="primary")
        if submitted:
            is_sale = "Sales" in entry_kind
            tx_payload = {
                "date": tx_date.isoformat(),
                "settled_date": tx_date.isoformat(),
                "role": "Nam",
                "tx_type": "revenue" if is_sale else "expense",
                "category": "Daily POS Sales" if is_sale else "Supplier Inventory",
                "inventory_scope": scope,
                "amount_eur": amount_val if is_sale else -amount_val,
                "payment_channel": channel,
                "payment_terms_days": 0,
                "status": "settled",
                "notes": notes or ("POS register batch" if is_sale else "Storefront delivery"),
            }
            st.session_state.ledger_df = append_transaction(df, tx_payload, str(CSV_PATH))
            st.success(f"✅ Recorded {entry_kind} of €{amount_val:,.2f} under {scope}.")
            st.rerun()

    st.markdown("#### 📋 Recent Storefront Activity")
    nam_view = st.session_state.ledger_df[st.session_state.ledger_df["role"] == "Nam"][
        ["tx_id", "date", "tx_type", "category", "inventory_scope", "amount_eur", "payment_channel", "notes"]
    ].tail(10)
    st.dataframe(nam_view, use_container_width=True, hide_index=True)

# ===========================================================================
# ROLE 2: NOELLE (ACCOUNTANT) — ERROR 2 FIXED HERE
# ===========================================================================
elif active_role == "Noelle":
    st.subheader("🧾 Accountant Ledger Entry & Policy Controls — Noelle")
    st.markdown(
        '<div class="tide-card"><b>Policy Guardrails:</b> Max supplier payment term = <b>90 days</b> (default 10 days) • Payroll scheduled on the <b>10th</b> (latest 15th, shifted for French weekends/holidays) • Max overdraft = <b>€5,000</b> • Max short-term borrowing = <b>€10,000</b>.</div>',
        unsafe_allow_html=True,
    )

    # Dynamic mapping so Category and Inventory/Scope always match Transaction Type
    TX_SCHEMA = {
        "revenue": {
            "Daily POS Sales": ["General Grocery & Snacks", "Beverages & Coffee", "Bakery & Ready-to-Eat", "Fresh Produce & Dairy"],
            "Wholesale & B2B Orders": ["Local Café Supply", "Office Catering & Hampers", "Bulk Beverage Orders"],
            "Loyalty & Gift Cards": ["Prepaid Store Cards", "Neighborhood Membership"],
        },
        "expense": {
            "Supplier Inventory": ["Fresh Produce & Dairy", "Dry Goods & Packaged", "Beverages & Coffee", "Bakery & Ready-to-Eat"],
            "Payroll": ["Staff Salaries & Charges", "Seasonal Part-Time Staff", "Employer Social Contributions"],
            "Rent & Utilities": ["Storefront Lease & Power", "Cold Storage Electricity", "Water & Telecom"],
            "Taxes & Insurance": ["Commercial Property Insurance", "VAT & Local Business Tax"],
        },
        "financing": {
            "Short-Term Credit Facility": ["60-Day Working Capital Line", "Supplier Bridge Facility"],
            "Owner Equity Injection": ["Treasury Reserve Top-Up"],
            "Loan Repayment": ["Principal & Interest Installment"],
        },
    }

    # Interactive selectors outside form so changing Transaction Type updates Category & Scope immediately
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        tx_type = st.selectbox("Transaction Type", ["revenue", "expense", "financing"], key="noelle_tx_type")
    with c2:
        valid_categories = list(TX_SCHEMA[tx_type].keys())
        category = st.selectbox("Category", valid_categories, key=f"noelle_cat_{tx_type}")
    with c3:
        valid_scopes = TX_SCHEMA[tx_type][category]
        inv_scope = st.selectbox("Inventory / Scope", valid_scopes, key=f"noelle_scope_{tx_type}_{category}")
    with c4:
        valid_channels = ["bank", "card", "cash"] if tx_type == "revenue" else ["bank", "cash"]
        payment_channel = st.selectbox("Payment Channel", valid_channels, key="noelle_channel")

    c5, c6, c7, c8 = st.columns(4)
    with c5:
        tx_date = st.date_input("Invoice / Entry Date", value=TODAY, key="noelle_date")
    with c6:
        default_terms = 10 if (tx_type == "expense" and category == "Supplier Inventory") else 0
        max_terms = 90 if tx_type == "expense" else 30
        terms_days = st.number_input("Payment Terms (Days)", min_value=0, max_value=max_terms, value=default_terms, step=5)
    with c7:
        max_amt = 10000.0 if (tx_type == "financing" and category == "Short-Term Credit Facility") else 50000.0
        amount_input = st.number_input("Amount (€)", min_value=1.0, max_value=max_amt, value=1200.0, step=50.0)
    with c8:
        notes = st.text_input("Accounting Reference / Note", placeholder="e.g., Inv #425 Normandy Dairy")

    raw_settled = tx_date + timedelta(days=int(terms_days))
    if category == "Payroll":
        adjusted_settled, holiday_note = adjust_french_business_day(raw_settled)
        st.caption(f"🇫🇷 French Payroll Calendar Check: **{holiday_note}**")
    else:
        adjusted_settled = raw_settled

    if st.button("🌊 Post Validated Entry to Ledger", type="primary"):
        is_inflow = tx_type == "revenue" or (
            tx_type == "financing" and category in ["Short-Term Credit Facility", "Owner Equity Injection"]
        )
        signed_amount = amount_input if is_inflow else -amount_input
        status = "settled" if adjusted_settled <= TODAY else "scheduled"

        tx_payload = {
            "date": tx_date.isoformat(),
            "settled_date": adjusted_settled.isoformat(),
            "role": "Noelle",
            "tx_type": tx_type,
            "category": category,
            "inventory_scope": inv_scope,
            "amount_eur": signed_amount,
            "payment_channel": payment_channel,
            "payment_terms_days": int(terms_days),
            "status": status,
            "notes": notes or f"{category} — {inv_scope}",
        }
        st.session_state.ledger_df = append_transaction(df, tx_payload, str(CSV_PATH))
        st.success(
            f"✅ Posted {tx_type.upper()} ({category} • {inv_scope}) for €{signed_amount:,.2f} (Settlement: {adjusted_settled.isoformat()})."
        )
        st.rerun()

    st.markdown("#### 📒 Full Accounting Ledger")
    acc_view = st.session_state.ledger_df[
        ["tx_id", "date", "settled_date", "role", "tx_type", "category", "inventory_scope", "amount_eur", "payment_channel", "status", "notes"]
    ]
    st.dataframe(acc_view, use_container_width=True, hide_index=True)

# ===========================================================================
# ROLE 3: RANIA (STORE OWNER) — ERRORS 1, 3, 4, 5 FIXED HERE
# ===========================================================================
elif active_role == "Rania":
    kpis = compute_financial_kpis(df)

    # -----------------------------------------------------------------------
    # AREA 1: Financial Position & Cash Overview
    # -----------------------------------------------------------------------
    st.subheader("1. Financial Position & Cash Overview")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("💧 Total Available Cash", f"€{kpis['total_liquidity']:,.2f}", f"Bank: €{kpis['bank_balance']:,.0f}")
    m2.metric("🏦 Operating Bank Balance", f"€{kpis['bank_balance']:,.2f}", "Overdraft limit: €5,000")
    m3.metric("🧾 Scheduled Payables", f"€{kpis['pending_payables']:,.2f}", "Within 90-day policy")
    m4.metric("⏳ Estimated Cash Runway", f"{kpis['runway_months']:.1f} months", "Healthy buffer > 3.0 mo")

    st.divider()

    # -----------------------------------------------------------------------
    # ERROR 4: Area 2 is now Cashflow & Profit Forecast, Area 3 is Recommendations,
    # Area 4 is Non-Recurring Events Simulator!
    # Because Streamlit executes top-to-bottom, we initialize widget states cleanly
    # and render Area 2 using containers so Area 3 & Area 4 feed directly into it.
    # -----------------------------------------------------------------------
    area2_container = st.container()
    st.divider()

    # -----------------------------------------------------------------------
    # AREA 3: Liquidity & Working Capital Recommendations (ERROR 3: Full text, stacked lines)
    # -----------------------------------------------------------------------
    st.subheader("3. Liquidity & Working Capital Recommendations")
    st.caption("Select recommendations below to simulate their live impact on the 90-day forecast above:")

    rec_dpo = st.checkbox(
        "Extend supplier Days Payable Outstanding (DPO) from 10 days to 30 days on non-perishable dry goods (+€2,160 working capital release over 90 days).",
        value=True,
    )
    rec_waste = st.checkbox(
        "Introduce evening bundle promotions on fresh bakery & produce to lift gross margin and daily revenue (+€2,520 net cash inflow over 90 days).",
        value=True,
    )
    rec_payroll = st.checkbox(
        "Schedule monthly employee payroll on the 15th (with French public holiday shift) to align outflows with mid-month card settlements (+€1,080 buffer).",
        value=False,
    )
    rec_credit = st.checkbox(
        "Arrange a 60-day short-term credit facility of €1,500 at 6.0% APR (well within the €10,000 borrowing cap) to cushion seasonal inventory peaks.",
        value=False,
    )

    st.divider()

    # -----------------------------------------------------------------------
    # AREA 4: Non-Recurring Events Simulator (Up to 5 Events)
    # -----------------------------------------------------------------------
    st.subheader("4. Non-Recurring Events Simulator (Up to 5 Events)")
    st.caption(f"Start dates cannot be earlier than today ({TODAY.isoformat()}). Add up to 5 one-off, weekly, or monthly events.")

    events_list = []
    for i in range(1, 6):
        with st.expander(f"🌊 Event #{i} Configuration", expanded=(i == 1)):
            ec1, ec2, ec3, ec4, ec5, ec6 = st.columns([0.8, 2.0, 1.4, 1.3, 1.3, 1.3])
            with ec1:
                active = st.checkbox("Active", value=(i == 1), key=f"ev_act_{i}")
            with ec2:
                ev_name = st.text_input(
                    "Event Label",
                    value="Holiday Gift Basket Pop-Up" if i == 1 else f"Custom Event {i}",
                    key=f"ev_name_{i}",
                )
            with ec3:
                direction = st.selectbox("Flow", ["Cash Inflow (+)", "Cash Outflow (-)"], key=f"ev_dir_{i}")
            with ec4:
                freq = st.selectbox("Frequency", ["One-off", "Weekly", "Monthly"], key=f"ev_freq_{i}")
            with ec5:
                ev_amt = st.number_input("Amount (€)", min_value=0.0, max_value=25000.0, value=650.0 if i == 1 else 0.0, step=50.0, key=f"ev_amt_{i}")
            with ec6:
                ev_start = st.date_input("Start Date", value=TODAY + timedelta(days=7 * i), min_value=TODAY, key=f"ev_start_{i}")

            ev_end = ev_start + timedelta(days=60) if freq != "One-off" else ev_start
            events_list.append(
                {
                    "active": active,
                    "name": ev_name,
                    "direction": direction,
                    "frequency": freq,
                    "amount": ev_amt,
                    "start_date": ev_start,
                    "end_date": ev_end,
                }
            )

    # -----------------------------------------------------------------------
    # Populate AREA 2: Cashflow & Profit Forecast (ERROR 5: Single large combined chart)
    # -----------------------------------------------------------------------
    with area2_container:
        st.subheader("2. Cashflow & Profit Forecast (90-Day Horizon)")
        sc_col1, sc_col2 = st.columns([1.4, 2.6])
        with sc_col1:
            scenario = st.selectbox("Forecast Scenario", ["Base Case", "Optimistic", "Conservative"], index=0)
        forecast_df = generate_90day_forecast(
            df=df,
            scenario=scenario,
            rec_dpo=rec_dpo,
            rec_payroll=rec_payroll,
            rec_credit=rec_credit,
            rec_waste=rec_waste,
            events=events_list,
            start_date=TODAY,
        )

        net_cash_change_before = forecast_df["Cashflow_Before"].iloc[-1] - forecast_df["Cashflow_Before"].iloc[0]
        net_cash_change_after = forecast_df["Cashflow_After"].iloc[-1] - forecast_df["Cashflow_After"].iloc[0]

        with sc_col2:
            k_b, k_a = st.columns(2)
            k_b.metric(
                "90-Day Net Cash Change (Before)",
                f"€{net_cash_change_before:+,.2f}",
                "Baseline drift",
                delta_color="normal",
            )
            k_a.metric(
                "90-Day Net Cash Change (After)",
                f"€{net_cash_change_after:+,.2f}",
                f"{net_cash_change_after - net_cash_change_before:+,.2f} vs Before",
                delta_color="normal",
            )

        # Reshape for unified Altair chart (Cashflow + Profit on same large graph with distinct colors)
        long_df = pd.DataFrame(
            {
                "Date": pd.concat([forecast_df["Date"]] * 4, ignore_index=True),
                "Series": (
                    ["Cumulative Cashflow — After Changes"] * len(forecast_df)
                    + ["Cumulative Cashflow — Before Changes"] * len(forecast_df)
                    + ["Cumulative Profit — After Changes"] * len(forecast_df)
                    + ["Cumulative Profit — Before Changes"] * len(forecast_df)
                ),
                "Amount (€)": pd.concat(
                    [
                        forecast_df["Cashflow_After"],
                        forecast_df["Cashflow_Before"],
                        forecast_df["Profit_After"],
                        forecast_df["Profit_Before"],
                    ],
                    ignore_index=True,
                ),
            }
        )

        color_scale = alt.Scale(
            domain=[
                "Cumulative Cashflow — After Changes",
                "Cumulative Cashflow — Before Changes",
                "Cumulative Profit — After Changes",
                "Cumulative Profit — Before Changes",
            ],
            range=["#023E8A", "#7CC6FE", "#009688", "#80CBC4"],
        )

        dash_scale = alt.Scale(
            domain=[
                "Cumulative Cashflow — After Changes",
                "Cumulative Cashflow — Before Changes",
                "Cumulative Profit — After Changes",
                "Cumulative Profit — Before Changes",
            ],
            range=[[1, 0], [6, 4], [1, 0], [6, 4]],
        )

        combined_chart = (
            alt.Chart(long_df)
            .mark_line(strokeWidth=3)
            .encode(
                x=alt.X("Date:T", title="Forecast Date (Next 90 Days)"),
                y=alt.Y("Amount (€):Q", title="Cumulative Amount (€)", scale=alt.Scale(zero=False)),
                color=alt.Color(
                    "Series:N",
                    scale=color_scale,
                    legend=alt.Legend(orient="top", columns=2, title=None, labelLimit=320),
                ),
                strokeDash=alt.StrokeDash("Series:N", scale=dash_scale, legend=None),
                tooltip=[
                    alt.Tooltip("Date:T", title="Date"),
                    alt.Tooltip("Series:N", title="Trajectory"),
                    alt.Tooltip("Amount (€):Q", title="Amount (€)", format=",.2f"),
                ],
            )
            .properties(height=430)
            .interactive()
        )

        st.altair_chart(combined_chart, use_container_width=True)

    st.divider()

    # -----------------------------------------------------------------------
    # AREA 5: Non-Recurring Events Impact Summary
    # -----------------------------------------------------------------------
    st.subheader("5. Non-Recurring Events Impact Summary")
    active_events = [e for e in events_list if e["active"] and e["amount"] > 0]
    if active_events:
        summary_rows = []
        for e in active_events:
            occurrences = 1 if e["frequency"] == "One-off" else (9 if e["frequency"] == "Weekly" else 3)
            signed = e["amount"] if e["direction"] == "Cash Inflow (+)" else -e["amount"]
            summary_rows.append(
                {
                    "Event": e["name"],
                    "Direction": e["direction"],
                    "Frequency": e["frequency"],
                    "Start Date": e["start_date"].isoformat(),
                    "Est. 90-Day Impact (€)": round(signed * occurrences, 2),
                }
            )
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No active non-recurring events with an amount > €0. Enable an event in Section 4 to see its summary.")

    st.divider()

    # -----------------------------------------------------------------------
    # ERROR 1: Ledger Integrity & SHA-256 Hash Chain (ONLY SHOWN ON RANIA'S SCREEN)
    # -----------------------------------------------------------------------
    st.subheader("🔐 Ledger Integrity & SHA-256 Hash Chain")
    audit = verify_ledger_integrity(df)
    if audit["is_valid"]:
        st.success(
            f"Ledger chain verified: {audit['total_entries']} entries checked, "
            f"{audit['tampered_count']} tampered rows, {audit['duplicate_count']} duplicates."
        )
    else:
        st.error(
            f"Integrity warning: {audit['tampered_count']} tampered rows and {audit['duplicate_count']} duplicates detected."
        )

    with st.expander("Inspect SHA-256 Hash Chain & Flagged Entries"):
        st.dataframe(
            df[["tx_id", "date", "role", "tx_type", "category", "amount_eur", "prev_hash", "tx_hash"]],
            use_container_width=True,
            hide_index=True,
        )

    csv_bytes = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Download Updated CSV Ledger",
        data=csv_bytes,
        file_name="marea_verified_ledger_2026.csv",
        mime="text/csv",
    )
