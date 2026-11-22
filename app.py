from pathlib import Path
import altair as alt
import pandas as pd
import streamlit as st

from finance_engine import (
    SCENARIO_CONFIG,
    build_cashflow_projection,
    load_transactions,
    summarize_projection,
)

st.set_page_config(
    page_title="Maréa — SME Cash Flow Manager",
    page_icon="🌊",
    layout="wide",
)

DATA_PATH = Path(__file__).parent / "data" / "sample_sme_data.csv"

if "transactions_df" not in st.session_state:
    st.session_state.transactions_df = load_transactions(str(DATA_PATH))

st.title("🌊 Maréa — SME Cash Flow Manager")
st.caption(
    "Anticipate 30, 60, and 90-day cash balances, spot shortages early, and test recovery actions."
)

# Sidebar controls for scenario, horizon, alert threshold, and quick simulations
with st.sidebar:
    st.header("Forecast Controls")
    scenario = st.selectbox(
        "Scenario",
        options=list(SCENARIO_CONFIG.keys()),
        index=1,  # Realistic default
    )
    st.caption(SCENARIO_CONFIG[scenario]["description"])

    horizon_days = st.select_slider(
        "Forecast Horizon (days)",
        options=[30, 60, 90],
        value=90,
    )

    alert_threshold = st.number_input(
        "Cash Alert Threshold (€)",
        min_value=0.0,
        max_value=100000.0,
        value=2500.0,
        step=250.0,
    )

    st.divider()
    st.subheader("Simulate Actions (What-If)")
    delay_supplier_days = st.slider(
        "Postpone Supplier Payments (days)",
        min_value=0,
        max_value=21,
        value=0,
        step=1,
    )
    accelerate_invoices_days = st.slider(
        "Collect Pending Invoices Earlier (days)",
        min_value=0,
        max_value=15,
        value=0,
        step=1,
    )

    if st.button("Reset Sample Data"):
        st.session_state.transactions_df = load_transactions(str(DATA_PATH))
        st.rerun()

tx_df = st.session_state.transactions_df
timeline_df = build_cashflow_projection(
    transactions_df=tx_df,
    horizon_days=horizon_days,
    scenario=scenario,
    alert_threshold=alert_threshold,
    delay_supplier_days=delay_supplier_days,
    accelerate_invoices_days=accelerate_invoices_days,
)
summary = summarize_projection(timeline_df, horizon_days=horizon_days)

tab_home, tab_forecast, tab_alerts, tab_tx = st.tabs(
    ["Home", "Forecast", "Alerts & Actions", "Transactions"]
)

# --- TAB 1: HOME ---
with tab_home:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Current Cash Balance", f"€{summary['current_balance']:,.0f}")
    col2.metric("30-Day Forecast", f"€{summary['bal_30d']:,.0f}")
    col3.metric("60-Day Forecast", f"€{summary['bal_60d']:,.0f}")
    col4.metric(f"{horizon_days}-Day Forecast", f"€{summary['bal_90d']:,.0f}")

    if summary["first_alert_date"]:
        st.error(
            f"⚠️ **Cash Alert:** Forecast balance drops below **€{alert_threshold:,.0f}** "
            f"starting **{summary['first_alert_date']}** "
            f"(lowest projected point: **€{summary['lowest_forecast_balance']:,.0f}** on **{summary['lowest_forecast_date']}**)."
        )
    else:
        st.success(
            f"✅ No cash shortage below **€{alert_threshold:,.0f}** detected over the next **{horizon_days} days** under the **{scenario}** scenario."
        )

    chart_df = timeline_df.copy()
    chart_df["date_str"] = chart_df["date"].dt.strftime("%Y-%m-%d")

    line_chart = (
        alt.Chart(chart_df)
        .mark_line(strokeWidth=2.5)
        .encode(
            x=alt.X("date:T", title="Date"),
            y=alt.Y("balance:Q", title="Cash Balance (€)"),
            color=alt.Color(
                "period:N",
                title="Series",
                scale=alt.Scale(
                    domain=["Actual", "Forecast"],
                    range=["#1f77b4", "#ff7f0e"],
                ),
            ),
            strokeDash=alt.StrokeDash(
                "period:N",
                scale=alt.Scale(
                    domain=["Actual", "Forecast"],
                    range=[[1, 0], [5, 4]],
                ),
            ),
            tooltip=[
                alt.Tooltip("date:T", title="Date"),
                alt.Tooltip("period:N", title="Type"),
                alt.Tooltip("balance:Q", title="Balance (€)", format=",.2f"),
                alt.Tooltip("events:N", title="Cash Events"),
            ],
        )
        .properties(height=360)
    )

    threshold_rule = (
        alt.Chart(pd.DataFrame({"threshold": [alert_threshold]}))
        .mark_rule(color="#d62728", strokeDash=[3, 3], strokeWidth=1.5)
        .encode(y="threshold:Q")
    )

    st.altair_chart(line_chart + threshold_rule, use_container_width=True)
    st.caption(
        f"Solid blue = Actuals | Dashed orange = {scenario} Forecast | Red dashed line = Alert Threshold (€{alert_threshold:,.0f})"
    )

# --- TAB 2: FORECAST ---
with tab_forecast:
    st.subheader(f"{horizon_days}-Day Cash Flow Projection ({scenario})")
    forecast_only = timeline_df[timeline_df["period"] == "Forecast"].copy()
    forecast_only["date"] = forecast_only["date"].dt.strftime("%Y-%m-%d")

    st.dataframe(
        forecast_only[
            ["date", "net_flow", "balance", "below_threshold", "events"]
        ].rename(
            columns={
                "date": "Date",
                "net_flow": "Daily Net Flow (€)",
                "balance": "Projected Balance (€)",
                "below_threshold": "Below Threshold",
                "events": "Scheduled Items",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

# --- TAB 3: ALERTS & ACTIONS ---
with tab_alerts:
    st.subheader("Shortage Detection & Action Impact")
    st.write(
        "Use the **Simulate Actions** sliders in the sidebar to test postponing supplier outflows or collecting pending client invoices earlier."
    )

    alerts_df = summary["alerts_df"]
    if alerts_df.empty:
        st.info("No forecast days fall below your current threshold.")
    else:
        display_alerts = alerts_df.copy()
        display_alerts["date"] = display_alerts["date"].dt.strftime("%Y-%m-%d")
        st.dataframe(
            display_alerts[["date", "balance", "net_flow", "events"]].rename(
                columns={
                    "date": "Alert Date",
                    "balance": "Forecast Balance (€)",
                    "net_flow": "Daily Net Flow (€)",
                    "events": "Drivers / Events",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

# --- TAB 4: TRANSACTIONS ---
with tab_tx:
    st.subheader("Add Income, Expense, or Expected Invoice")
    with st.form("add_transaction_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        tx_date = c1.date_input("Date", value=pd.Timestamp("2026-12-08"))
        tx_desc = c2.text_input("Description", placeholder="e.g., Client D Invoice")
        tx_cat = c3.selectbox(
            "Category",
            [
                "Client Invoice",
                "Payroll",
                "Rent",
                "Taxes",
                "Supplier",
                "Cash Reserve",
                "General",
            ],
        )

        c4, c5, c6, c7 = st.columns(4)
        tx_type = c4.selectbox("Direction", ["outflow", "inflow"])
        tx_abs_amount = c5.number_input("Amount (€)", min_value=1.0, value=1500.0, step=100.0)
        tx_status = c6.selectbox("Status", ["planned", "actual"])
        tx_delay = c7.number_input("Expected Delay (days)", min_value=-10, max_value=90, value=0, step=1)

        submitted = st.form_submit_button("Add Transaction")
        if submitted:
            signed_amount = float(tx_abs_amount) if tx_type == "inflow" else -float(tx_abs_amount)
            new_row = pd.DataFrame(
                [
                    {
                        "date": pd.to_datetime(tx_date).normalize(),
                        "description": tx_desc.strip() or "New Entry",
                        "category": tx_cat,
                        "type": tx_type,
                        "amount": signed_amount,
                        "status": tx_status,
                        "expected_delay_days": int(tx_delay),
                    }
                ]
            )
            st.session_state.transactions_df = (
                pd.concat([st.session_state.transactions_df, new_row], ignore_index=True)
                .sort_values("date")
                .reset_index(drop=True)
            )
            st.success("Transaction added and forecast updated.")
            st.rerun()

    st.subheader("Current Ledger")
    view_df = st.session_state.transactions_df.copy()
    view_df["date"] = view_df["date"].dt.strftime("%Y-%m-%d")
    st.dataframe(view_df, use_container_width=True, hide_index=True)
