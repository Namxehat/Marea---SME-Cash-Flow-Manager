from datetime import timedelta
import numpy as np
import pandas as pd

REQUIRED_COLUMNS = [
    "date",
    "description",
    "category",
    "type",
    "amount",
    "status",
    "expected_delay_days",
]

SCENARIO_CONFIG = {
    "Cautious": {
        "inflow_multiplier": 0.85,
        "outflow_multiplier": 1.10,
        "extra_delay_days": 7,
        "description": "Lower collections (-15%), extra payment delays (+7 days), and higher costs (+10%).",
    },
    "Realistic": {
        "inflow_multiplier": 1.00,
        "outflow_multiplier": 1.00,
        "extra_delay_days": 0,
        "description": "Baseline projection using expected amounts and typical client payment delays.",
    },
    "Optimistic": {
        "inflow_multiplier": 1.10,
        "outflow_multiplier": 0.95,
        "extra_delay_days": -3,
        "description": "Faster collections (-3 days delay), stronger inflows (+10%), and slightly lower costs (-5%).",
    },
}


def load_transactions(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in dataset: {missing}")

    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["expected_delay_days"] = (
        pd.to_numeric(df["expected_delay_days"], errors="coerce").fillna(0).astype(int)
    )
    df["category"] = df["category"].fillna("General").astype(str)
    df["type"] = df["type"].fillna("outflow").astype(str).str.lower()
    df["status"] = df["status"].fillna("planned").astype(str).str.lower()
    df["description"] = df["description"].fillna("Transaction").astype(str)
    return df.sort_values("date").reset_index(drop=True)


def build_cashflow_projection(
    transactions_df: pd.DataFrame,
    horizon_days: int = 90,
    scenario: str = "Realistic",
    alert_threshold: float = 2000.0,
    delay_supplier_days: int = 0,
    accelerate_invoices_days: int = 0,
) -> pd.DataFrame:
    """
    Produces a daily cash flow table combining historical actuals and
    scenario-adjusted future projections with shortage flags.
    """
    if transactions_df.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "net_flow",
                "balance",
                "period",
                "below_threshold",
                "below_zero",
            ]
        )

    cfg = SCENARIO_CONFIG.get(scenario, SCENARIO_CONFIG["Realistic"])
    df = transactions_df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()

    actuals = df[df["status"] == "actual"].copy()
    planned = df[df["status"] != "actual"].copy()

    # Anchor forecast start at the latest actual date (or min date if no actuals exist)
    anchor_date = actuals["date"].max() if not actuals.empty else df["date"].min()
    forecast_end_date = anchor_date + timedelta(days=horizon_days)

    # Adjust planned items according to scenario and simulated user actions
    adjusted_planned_rows = []
    for _, row in planned.iterrows():
        amt = float(row["amount"])
        item_date = row["date"]
        cat_lower = row["category"].lower()

        if amt > 0:
            # Expected inflow / client invoice
            delay = int(row["expected_delay_days"]) + int(cfg["extra_delay_days"])
            if "invoice" in cat_lower or row["type"] == "inflow":
                delay = delay - int(accelerate_invoices_days)
            shifted_date = item_date + timedelta(days=delay)
            adjusted_amt = amt * float(cfg["inflow_multiplier"])
        else:
            # Expected outflow / expense
            delay = int(row["expected_delay_days"])
            if "supplier" in cat_lower and delay_supplier_days > 0:
                delay += int(delay_supplier_days)
            shifted_date = item_date + timedelta(days=delay)
            adjusted_amt = amt * float(cfg["outflow_multiplier"])

        adjusted_planned_rows.append(
            {
                "date": shifted_date,
                "net_flow": adjusted_amt,
                "period": "Forecast",
                "description": row["description"],
                "category": row["category"],
            }
        )

    actual_flows = pd.DataFrame(
        {
            "date": actuals["date"],
            "net_flow": actuals["amount"].astype(float),
            "period": "Actual",
            "description": actuals["description"],
            "category": actuals["category"],
        }
    )

    planned_flows = pd.DataFrame(adjusted_planned_rows)
    if not planned_flows.empty:
        planned_flows = planned_flows[
            (planned_flows["date"] > anchor_date)
            & (planned_flows["date"] <= forecast_end_date)
        ]

    combined = pd.concat([actual_flows, planned_flows], ignore_index=True)

    start_date = combined["date"].min()
    end_date = max(forecast_end_date, combined["date"].max())
    full_calendar = pd.date_range(start=start_date, end=end_date, freq="D")

    daily_flows = (
        combined.groupby("date", as_index=False)["net_flow"].sum()
        if not combined.empty
        else pd.DataFrame(columns=["date", "net_flow"])
    )

    timeline = pd.DataFrame({"date": full_calendar})
    timeline = timeline.merge(daily_flows, on="date", how="left")
    timeline["net_flow"] = timeline["net_flow"].fillna(0.0)
    timeline["balance"] = timeline["net_flow"].cumsum()
    timeline["period"] = np.where(timeline["date"] <= anchor_date, "Actual", "Forecast")
    timeline["below_threshold"] = (timeline["period"] == "Forecast") & (
        timeline["balance"] < float(alert_threshold)
    )
    timeline["below_zero"] = (timeline["period"] == "Forecast") & (
        timeline["balance"] < 0.0
    )

    # Attach readable event notes for days with non-zero cash movement
    if not combined.empty:
        notes = (
            combined.groupby("date")["description"]
            .apply(lambda s: "; ".join(s.unique()))
            .reset_index()
            .rename(columns={"description": "events"})
        )
        timeline = timeline.merge(notes, on="date", how="left")
    else:
        timeline["events"] = ""
    timeline["events"] = timeline["events"].fillna("")

    return timeline


def summarize_projection(
    timeline_df: pd.DataFrame, horizon_days: int = 90
) -> dict:
    forecast_df = timeline_df[timeline_df["period"] == "Forecast"].copy()
    actual_df = timeline_df[timeline_df["period"] == "Actual"].copy()

    current_balance = (
        float(actual_df["balance"].iloc[-1]) if not actual_df.empty else 0.0
    )

    def balance_at(days: int) -> float:
        if forecast_df.empty:
            return current_balance
        start_f = forecast_df["date"].min()
        target_date = start_f + timedelta(days=days)
        subset = forecast_df[forecast_df["date"] <= target_date]
        return (
            float(subset["balance"].iloc[-1])
            if not subset.empty
            else float(forecast_df["balance"].iloc[-1])
        )

    alerts_df = forecast_df[forecast_df["below_threshold"]]
    first_alert_date = (
        alerts_df["date"].iloc[0].strftime("%Y-%m-%d") if not alerts_df.empty else None
    )
    lowest_forecast_balance = (
        float(forecast_df["balance"].min()) if not forecast_df.empty else current_balance
    )
    lowest_forecast_date = (
        forecast_df.loc[forecast_df["balance"].idxmin(), "date"].strftime("%Y-%m-%d")
        if not forecast_df.empty
        else None
    )

    return {
        "current_balance": current_balance,
        "bal_30d": balance_at(min(30, horizon_days)),
        "bal_60d": balance_at(min(60, horizon_days)),
        "bal_90d": balance_at(horizon_days),
        "alert_count": int(len(alerts_df)),
        "first_alert_date": first_alert_date,
        "lowest_forecast_balance": lowest_forecast_balance,
        "lowest_forecast_date": lowest_forecast_date,
        "alerts_df": alerts_df,
    }
