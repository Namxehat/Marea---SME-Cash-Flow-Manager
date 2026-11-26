from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json
import numpy as np
import pandas as pd

TODAY = pd.Timestamp("2026-11-25").normalize()

INVENTORY_CATALOG = {
    "Beverages & Snacks": 4.60,
    "Bananas & Produce": 1.50,
    "Dairy & Bakery": 3.90,
    "Household & Pantry": 4.50,
}

INVENTORY_OPTIONS_WITH_ALL = ["All Inventories"] + list(INVENTORY_CATALOG.keys())

STORE_RULES = {
    "employees_count": 5,
    "max_bank_overdraft": 5000.0,
    "max_short_term_borrowing": 10000.0,
    "max_supplier_payment_days": 90,
    "default_dpo_days": 10,
    "recommended_dpo_days": 20,
    "normal_payroll_day": 10,
    "latest_payroll_day": 15,
}

# French public holidays (fixed & common dates for 2025-2027 payroll shift helper)
FRENCH_HOLIDAYS = {
    date(2025, 1, 1), date(2025, 4, 21), date(2025, 5, 1), date(2025, 5, 8),
    date(2025, 5, 29), date(2025, 6, 9), date(2025, 7, 14), date(2025, 8, 15),
    date(2025, 11, 1), date(2025, 11, 11), date(2025, 12, 25),
    date(2026, 1, 1), date(2026, 4, 6), date(2026, 5, 1), date(2026, 5, 8),
    date(2026, 5, 14), date(2026, 5, 25), date(2026, 7, 14), date(2026, 8, 15),
    date(2026, 11, 1), date(2026, 11, 11), date(2026, 12, 25),
    date(2027, 1, 1), date(2027, 3, 29), date(2027, 5, 1), date(2027, 5, 6),
    date(2027, 5, 8), date(2027, 5, 17), date(2027, 7, 14), date(2027, 8, 15),
    date(2027, 11, 1), date(2027, 11, 11), date(2027, 12, 25),
}

REVENUE_SCENARIOS = {
    "Cautious": {
        "revenue_multiplier": 0.85,
        "description": "Conservative revenue (-15%) accounting for slower foot traffic or protests.",
    },
    "Realistic": {
        "revenue_multiplier": 1.00,
        "description": "Baseline revenue (100%) reflecting seasonal patterns and store history.",
    },
    "Optimistic": {
        "revenue_multiplier": 1.15,
        "description": "Stronger revenue (+15%) driven by holiday demand and full stock availability.",
    },
}

REQUIRED_COLUMNS = [
    "tx_id",
    "date",
    "description",
    "category",
    "tx_type",
    "inventory_type",
    "quantity",
    "unit_price",
    "amount",
    "payment_method",
    "status",
    "payment_term_days",
    "expected_delay_days",
    "entry_hash",
]


def adjust_payroll_date(target_date: pd.Timestamp, latest_day: int = 15) -> pd.Timestamp:
    """Shifts payroll off weekends and French national holidays, capped at latest_day of month."""
    d = target_date.date()
    max_cap = min(latest_day, 28)
    while d.weekday() >= 5 or d in FRENCH_HOLIDAYS:
        if d.day >= max_cap:
            break
        d += timedelta(days=1)
    return pd.Timestamp(d).normalize()


def _canonical_row_payload(row: pd.Series, prev_hash: str) -> str:
    payload = {
        "prev_hash": prev_hash,
        "tx_id": str(row.get("tx_id", "")),
        "date": str(pd.to_datetime(row["date"]).date()),
        "description": str(row.get("description", "")),
        "category": str(row.get("category", "")),
        "tx_type": str(row.get("tx_type", "")),
        "inventory_type": str(row.get("inventory_type", "")),
        "quantity": round(float(row.get("quantity", 0.0)), 2),
        "unit_price": round(float(row.get("unit_price", 0.0)), 2),
        "amount": round(float(row.get("amount", 0.0)), 2),
        "payment_method": str(row.get("payment_method", "")),
        "status": str(row.get("status", "")),
        "payment_term_days": int(row.get("payment_term_days", 0)),
        "expected_delay_days": int(row.get("expected_delay_days", 0)),
    }
    return json.dumps(payload, sort_keys=True)


def compute_hash_chain(df: pd.DataFrame) -> pd.DataFrame:
    """Computes a sequential SHA-256 hash chain across all rows in order."""
    out = df.copy().reset_index(drop=True)
    prev_hash = "GENESIS"
    computed_hashes = []
    for _, row in out.iterrows():
        digest = hashlib.sha256(
            _canonical_row_payload(row, prev_hash).encode("utf-8")
        ).hexdigest()[:16]
        computed_hashes.append(digest)
        prev_hash = digest
    out["computed_hash"] = computed_hashes
    return out


def audit_ledger_integrity(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Flags duplicate transactions and hash-chain tampering."""
    if df.empty:
        return df.copy(), {"tampered_count": 0, "duplicate_count": 0, "is_clean": True}

    chained = compute_hash_chain(df)
    dup_mask = chained.duplicated(
        subset=["date", "description", "category", "tx_type", "amount", "status"],
        keep="first",
    )

    tampered_flags = []
    for _, row in chained.iterrows():
        stored = str(row.get("entry_hash", "")).strip()
        # Blank entry_hash on initial starter seed is initialized on save; non-matching non-blank hash = tampered
        is_tampered = bool(stored) and (stored != row["computed_hash"])
        tampered_flags.append(is_tampered)

    chained["is_duplicate"] = dup_mask
    chained["is_tampered"] = tampered_flags
    chained["audit_status"] = np.where(
        chained["is_tampered"],
        "TAMPERED",
        np.where(chained["is_duplicate"], "DUPLICATE", "OK"),
    )

    tampered_count = int(chained["is_tampered"].sum())
    duplicate_count = int(chained["is_duplicate"].sum())
    return chained, {
        "tampered_count": tampered_count,
        "duplicate_count": duplicate_count,
        "is_clean": (tampered_count == 0 and duplicate_count == 0),
    }


def seal_ledger_hashes(df: pd.DataFrame) -> pd.DataFrame:
    """Writes valid SHA-256 chain hashes into entry_hash so saved CSV rows have verified hashes."""
    chained = compute_hash_chain(df)
    chained["entry_hash"] = chained["computed_hash"]
    return chained[REQUIRED_COLUMNS]


def load_store_ledger(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    for col in REQUIRED_COLUMNS:
        if col not in df.columns:
            df[col] = "" if col in {"tx_id", "entry_hash", "inventory_type"} else 0

    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["date"]).copy()
    df["tx_id"] = df["tx_id"].astype(str)
    df["description"] = df["description"].fillna("Store Entry").astype(str)
    df["category"] = df["category"].fillna("General").astype(str)
    df["tx_type"] = df["tx_type"].fillna("expense").astype(str).str.lower()
    df["inventory_type"] = df["inventory_type"].fillna("None").astype(str)
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0.0)
    df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce").fillna(0.0)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["payment_method"] = df["payment_method"].fillna("bank").astype(str).str.lower()
    df["status"] = df["status"].fillna("actual").astype(str).str.lower()
    df["payment_term_days"] = (
        pd.to_numeric(df["payment_term_days"], errors="coerce").fillna(0).astype(int)
    )
    df["expected_delay_days"] = (
        pd.to_numeric(df["expected_delay_days"], errors="coerce").fillna(0).astype(int)
    )
    df["entry_hash"] = df["entry_hash"].fillna("").astype(str)

    # Seal hashes cleanly on load if starter hashes were left blank
    if (df["entry_hash"].str.strip() == "").all():
        df = seal_ledger_hashes(df)

    return df.reset_index(drop=True)


def save_store_ledger(df: pd.DataFrame, csv_path: str) -> pd.DataFrame:
    sealed = seal_ledger_hashes(df)
    sealed_to_save = sealed.copy()
    sealed_to_save["date"] = sealed_to_save["date"].dt.strftime("%Y-%m-%d")
    sealed_to_save.to_csv(csv_path, index=False)
    return sealed


def recommend_cashflow_threshold(df: pd.DataFrame) -> dict:
    """Recommends an alert threshold from historical monthly net cashflow variability."""
    actuals = df[df["status"] == "actual"].copy()
    if actuals.empty:
        return {"recommended_threshold": 2000.0, "median_monthly_net": 0.0, "std_monthly_net": 0.0}

    actuals["month"] = actuals["date"].dt.to_period("M")
    monthly_net = actuals.groupby("month")["amount"].sum()
    median_net = float(monthly_net.median()) if not monthly_net.empty else 0.0
    std_net = float(monthly_net.std()) if len(monthly_net) > 1 else 1000.0
    # Conservative buffer: ~40% of monthly volatility, clamped between EUR 1,500 and EUR 6,000
    rec = float(np.clip(abs(std_net) * 0.4, 1500.0, 6000.0))
    return {
        "recommended_threshold": round(rec, 2),
        "median_monthly_net": round(median_net, 2),
        "std_monthly_net": round(std_net, 2),
    }


def compute_financial_kpis(df: pd.DataFrame) -> dict:
    """Computes P&L, total cash + cash in bank, and current overdraft + borrowings."""
    actuals = df[df["status"] == "actual"].copy()

    total_revenue = float(actuals[actuals["tx_type"] == "revenue"]["amount"].sum())
    operating_costs = float(
        abs(actuals[actuals["tx_type"].isin(["expense", "inventory"])]["amount"].sum())
    )
    profit_and_loss = total_revenue - operating_costs

    cash_balance = float(
        actuals[actuals["payment_method"] == "cash"]["amount"].sum()
    )
    bank_balance = float(
        actuals[actuals["payment_method"] != "cash"]["amount"].sum()
    )
    total_cash_and_bank = cash_balance + bank_balance

    # Track active overdraft (negative bank balance) and active short-term borrowings
    overdraft_used = float(max(0.0, -bank_balance))
    borrowings_rows = actuals[
        actuals["category"].str.lower().str.contains("borrowing|loan")
    ]
    short_term_borrowings = float(max(0.0, borrowings_rows["amount"].sum()))

    return {
        "total_revenue": total_revenue,
        "operating_costs": operating_costs,
        "profit_and_loss": profit_and_loss,
        "cash_balance": cash_balance,
        "bank_balance": bank_balance,
        "total_cash_and_bank": total_cash_and_bank,
        "overdraft_used": overdraft_used,
        "short_term_borrowings": short_term_borrowings,
        "total_debt_and_overdraft": overdraft_used + short_term_borrowings,
    }


def evaluate_non_recurring_events(events: list[dict]) -> dict:
    """Computes structured financial & cashflow impacts for up to 5 non-recurring events."""
    total_revenue_delta = 0.0
    total_cost_delta = 0.0
    total_cashflow_delta = 0.0
    summaries: list[str] = []

    for idx, ev in enumerate(events, start=1):
        name = (ev.get("description") or f"Event {idx}").strip()
        affected_tx = (ev.get("affected_tx") or "revenue").lower()
        inv_type = ev.get("affected_inventory") or "All Inventories"
        damage_pct = float(ev.get("damage_pct") or 0.0)
        start_d = pd.to_datetime(ev.get("start_date")).normalize()
        end_d = pd.to_datetime(ev.get("end_date")).normalize()

        if not name or damage_pct == 0.0:
            continue

        active_days = max(1, int((end_d - start_d).days) + 1)
        scale_factor = damage_pct / 100.0
        inv_factor = 1.0 if inv_type == "All Inventories" else 0.35

        # Base daily magnitudes for a 5-employee convenience store
        if affected_tx == "revenue":
            rev_impact = -round(140.0 * active_days * scale_factor * inv_factor, 2)
            cost_impact = 0.0
            cf_impact = rev_impact
            summaries.append(
                f"'{name}' ({start_d.date()} to {end_d.date()}, {inv_type}, {damage_pct:.0f}% impact): "
                f"estimated revenue change of €{rev_impact:,.2f} and cashflow impact of €{cf_impact:,.2f}."
            )
        elif affected_tx == "inventories":
            # Supply disruption lowers supplier cost outflow but can also reduce sellable stock revenue
            cost_impact = round(45.0 * active_days * scale_factor * inv_factor, 2)  # positive = cost reduction
            rev_impact = -round(60.0 * active_days * scale_factor * inv_factor, 2)
            cf_impact = round(cost_impact + rev_impact, 2)
            summaries.append(
                f"'{name}' ({start_d.date()} to {end_d.date()}, {inv_type}, {damage_pct:.0f}% supply impact): "
                f"reduces inventory costs by €{cost_impact:,.2f}, decreases revenue by €{abs(rev_impact):,.2f}, "
                f"net cashflow impact €{cf_impact:,.2f}."
            )
        else:  # tax or other charges
            cost_impact = -round(35.0 * active_days * scale_factor, 2)
            rev_impact = 0.0
            cf_impact = cost_impact
            summaries.append(
                f"'{name}' ({start_d.date()} to {end_d.date()}, {affected_tx}): "
                f"adds €{abs(cost_impact):,.2f} in tax/other charges and €{cf_impact:,.2f} cashflow impact."
            )

        total_revenue_delta += rev_impact
        total_cost_delta += cost_impact
        total_cashflow_delta += cf_impact

    return {
        "total_revenue_delta": round(total_revenue_delta, 2),
        "total_cost_delta": round(total_cost_delta, 2),
        "total_cashflow_delta": round(total_cashflow_delta, 2),
        "summaries": summaries,
    }


def build_owner_forecast(
    df: pd.DataFrame,
    horizon_days: int = 30,
    scenario: str = "Realistic",
    apply_dpo_20: bool = False,
    apply_payroll_15th: bool = False,
    apply_loan_1000: bool = False,
    events: list[dict] | None = None,
) -> pd.DataFrame:
    """
    Projects daily cashflow and cumulative net profit/cash balance over 30/60/90 days,
    comparing baseline (before Area 2 & Area 4 changes) vs adjusted (after changes).
    """
    events = events or []
    rev_cfg = REVENUE_SCENARIOS.get(scenario, REVENUE_SCENARIOS["Realistic"])
    rev_mult = float(rev_cfg["revenue_multiplier"])

    actuals = df[df["status"] == "actual"].copy()
    planned = df[df["status"] != "actual"].copy()

    anchor = TODAY
    end_dt = anchor + timedelta(days=horizon_days)
    cal = pd.date_range(start=anchor, end=end_dt, freq="D")

    # Baseline daily cashflow & profit from planned rows + baseline daily run-rate
    base_cf = pd.Series(0.0, index=cal)
    base_profit = pd.Series(0.0, index=cal)

    # Smooth baseline daily revenue & recurring store costs across forecast horizon
    avg_daily_rev = 85.0 * rev_mult
    avg_daily_cost = 65.0
    base_cf += avg_daily_rev - avg_daily_cost
    base_profit += avg_daily_rev - avg_daily_cost

    for _, row in planned.iterrows():
        dt = pd.to_datetime(row["date"]).normalize()
        amt = float(row["amount"])
        cat = str(row["category"]).lower()
        tx_type = str(row["tx_type"]).lower()

        if tx_type == "revenue":
            amt = amt * rev_mult

        if anchor <= dt <= end_dt:
            base_cf.loc[dt] += amt
            if tx_type in {"revenue", "expense", "inventory"}:
                base_profit.loc[dt] += amt

    # Adjusted series (starts from baseline, applies Area 2 recommendations + Area 4 events)
    adj_cf = base_cf.copy()
    adj_profit = base_profit.copy()

    if apply_dpo_20:
        # Extending DPO from 10 to 20 days starting 2026-12-10 defers ~10 days of supplier outflow
        dpo_shift_start = pd.Timestamp("2026-12-10")
        for dt in adj_cf.index:
            if dt >= dpo_shift_start and dt < dpo_shift_start + timedelta(days=10):
                adj_cf.loc[dt] += 132.0  # frees cash on December window
            elif dt >= dpo_shift_start + timedelta(days=10) and dt < dpo_shift_start + timedelta(days=20):
                adj_cf.loc[dt] -= 132.0

    if apply_payroll_15th:
        # Shifting monthly payroll from 10th to 15th relieves cash on the 10th-14th
        for dt in adj_cf.index:
            if dt.day == 10:
                adj_cf.loc[dt] += 8600.0
                target_15 = adjust_payroll_date(dt.replace(day=15), latest_day=15)
                if target_15 in adj_cf.index:
                    adj_cf.loc[target_15] -= 8600.0

    if apply_loan_1000:
        # Short-term 60-day loan of EUR 1,000 drawn before 2026-12-20 (modeled on 2026-12-18)
        draw_dt = pd.Timestamp("2026-12-18")
        if draw_dt in adj_cf.index:
            adj_cf.loc[draw_dt] += 1000.0
        repay_dt = draw_dt + timedelta(days=60)
        if repay_dt in adj_cf.index:
            adj_cf.loc[repay_dt] -= 1015.0  # principal + minor 1.5% short-term interest
            adj_profit.loc[repay_dt] -= 15.0

    # Apply Area 4 non-recurring events across their active date ranges
    for ev in events:
        name = (ev.get("description") or "").strip()
        dmg = float(ev.get("damage_pct") or 0.0)
        if not name or dmg == 0.0:
            continue
        s_dt = max(anchor, pd.to_datetime(ev.get("start_date")).normalize())
        e_dt = min(end_dt, pd.to_datetime(ev.get("end_date")).normalize())
        if s_dt > e_dt:
            continue

        affected_tx = (ev.get("affected_tx") or "revenue").lower()
        inv_type = ev.get("affected_inventory") or "All Inventories"
        inv_factor = 1.0 if inv_type == "All Inventories" else 0.35
        scale = dmg / 100.0

        for dt in pd.date_range(start=s_dt, end=e_dt, freq="D"):
            if affected_tx == "revenue":
                delta = -140.0 * scale * inv_factor
                adj_cf.loc[dt] += delta
                adj_profit.loc[dt] += delta
            elif affected_tx == "inventories":
                cost_saved = 45.0 * scale * inv_factor
                rev_lost = -60.0 * scale * inv_factor
                adj_cf.loc[dt] += cost_saved + rev_lost
                adj_profit.loc[dt] += cost_saved + rev_lost
            else:
                tax_delta = -35.0 * scale
                adj_cf.loc[dt] += tax_delta
                adj_profit.loc[dt] += tax_delta

    start_bal = float(actuals["amount"].sum()) if not actuals.empty else 0.0
    start_pnl = float(
        actuals[actuals["tx_type"] == "revenue"]["amount"].sum()
        - abs(actuals[actuals["tx_type"].isin(["expense", "inventory"])]["amount"].sum())
    ) if not actuals.empty else 0.0

    out = pd.DataFrame({
        "date": cal,
        "cashflow_before": base_cf.values,
        "cashflow_after": adj_cf.values,
        "cum_cash_before": start_bal + np.cumsum(base_cf.values),
        "cum_cash_after": start_bal + np.cumsum(adj_cf.values),
        "cum_profit_before": start_pnl + np.cumsum(base_profit.values),
        "cum_profit_after": start_pnl + np.cumsum(adj_profit.values),
    })
    return out
