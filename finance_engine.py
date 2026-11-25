import hashlib
import os
from datetime import date, datetime, timedelta
from typing import Dict, List, Tuple
import pandas as pd

GENESIS_HASH = "GENESIS_00000000000000000000000000000000"

FRENCH_HOLIDAYS_2026_2027 = {
    date(2026, 1, 1),
    date(2026, 4, 6),
    date(2026, 5, 1),
    date(2026, 5, 8),
    date(2026, 5, 14),
    date(2026, 5, 25),
    date(2026, 7, 14),
    date(2026, 8, 15),
    date(2026, 11, 1),
    date(2026, 11, 11),
    date(2026, 12, 25),
    date(2027, 1, 1),
    date(2027, 3, 29),
    date(2027, 5, 1),
    date(2027, 5, 6),
    date(2027, 5, 8),
    date(2027, 5, 17),
}


def compute_row_hash(row_dict: Dict, prev_hash: str) -> str:
    payload = (
        f"{row_dict.get('tx_id', '')}|"
        f"{row_dict.get('date', '')}|"
        f"{row_dict.get('settled_date', '')}|"
        f"{row_dict.get('role', '')}|"
        f"{row_dict.get('tx_type', '')}|"
        f"{row_dict.get('category', '')}|"
        f"{row_dict.get('inventory_scope', '')}|"
        f"{float(row_dict.get('amount_eur', 0.0)):.2f}|"
        f"{row_dict.get('payment_channel', '')}|"
        f"{int(row_dict.get('payment_terms_days', 0))}|"
        f"{row_dict.get('status', '')}|"
        f"{row_dict.get('notes', '')}|"
        f"{prev_hash}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def rebuild_hash_chain(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().reset_index(drop=True)
    prev_hash = GENESIS_HASH
    prev_hashes = []
    tx_hashes = []
    for _, row in df.iterrows():
        r_dict = row.to_dict()
        curr_hash = compute_row_hash(r_dict, prev_hash)
        prev_hashes.append(prev_hash)
        tx_hashes.append(curr_hash)
        prev_hash = curr_hash
    df["prev_hash"] = prev_hashes
    df["tx_hash"] = tx_hashes
    return df


def verify_ledger_integrity(df: pd.DataFrame) -> Dict:
    tampered_rows = []
    seen_ids = set()
    duplicates = 0
    prev_hash = GENESIS_HASH

    for idx, row in df.iterrows():
        tx_id = str(row.get("tx_id", ""))
        if tx_id in seen_ids:
            duplicates += 1
        seen_ids.add(tx_id)

        expected_hash = compute_row_hash(row.to_dict(), prev_hash)
        if row.get("prev_hash") != prev_hash or row.get("tx_hash") != expected_hash:
            tampered_rows.append(
                {
                    "row_index": idx,
                    "tx_id": tx_id,
                    "recorded_hash": str(row.get("tx_hash", ""))[:16] + "...",
                    "expected_hash": expected_hash[:16] + "...",
                }
            )
        prev_hash = str(row.get("tx_hash", expected_hash))

    return {
        "total_entries": len(df),
        "tampered_count": len(tampered_rows),
        "duplicate_count": duplicates,
        "tampered_rows": tampered_rows,
        "is_valid": len(tampered_rows) == 0 and duplicates == 0,
    }


def _seed_default_ledger() -> pd.DataFrame:
    rows = [
        ("TX-0001", "2026-09-01", "2026-09-01", "Rania", "financing", "Owner Equity Injection", "Initial Reserve", 14500.00, "bank", 0, "settled", "Opening store treasury reserve"),
        ("TX-0002", "2026-09-02", "2026-09-02", "Nam", "revenue", "Daily POS Sales", "General Grocery & Snacks", 1420.00, "card", 0, "settled", "Daily checkout sales"),
        ("TX-0003", "2026-09-03", "2026-09-13", "Noelle", "expense", "Supplier Inventory", "Fresh Produce & Dairy", -980.00, "bank", 10, "settled", "Normandy fresh dairy restock"),
        ("TX-0004", "2026-09-05", "2026-09-05", "Nam", "revenue", "Daily POS Sales", "Beverages & Coffee", 1580.00, "card", 0, "settled", "Weekend foot traffic boost"),
        ("TX-0005", "2026-09-08", "2026-09-08", "Noelle", "expense", "Rent & Utilities", "Storefront Lease & Power", -1450.00, "bank", 0, "settled", "Monthly storefront lease"),
        ("TX-0006", "2026-09-10", "2026-09-10", "Noelle", "expense", "Payroll", "Staff Salaries & Charges", -2450.00, "bank", 0, "settled", "September staff payroll"),
        ("TX-0007", "2026-09-12", "2026-09-12", "Nam", "revenue", "Daily POS Sales", "General Grocery & Snacks", 1490.00, "cash", 0, "settled", "Mid-month grocery sales"),
        ("TX-0008", "2026-09-15", "2026-09-25", "Noelle", "expense", "Supplier Inventory", "Dry Goods & Packaged", -1050.00, "bank", 10, "settled", "Dry pantry & beverage restock"),
        ("TX-0009", "2026-09-19", "2026-09-19", "Nam", "revenue", "Daily POS Sales", "Bakery & Ready-to-Eat", 1640.00, "card", 0, "settled", "Saturday rush sales"),
        ("TX-0010", "2026-09-24", "2026-09-24", "Nam", "revenue", "Daily POS Sales", "General Grocery & Snacks", 1390.00, "card", 0, "settled", "Weekday neighborhood sales"),
        ("TX-0011", "2026-09-28", "2026-10-08", "Noelle", "expense", "Supplier Inventory", "Fresh Produce & Dairy", -940.00, "bank", 10, "settled", "End-of-month produce delivery"),
        ("TX-0012", "2026-10-02", "2026-10-02", "Nam", "revenue", "Daily POS Sales", "General Grocery & Snacks", 1510.00, "card", 0, "settled", "Early October POS batch"),
        ("TX-0013", "2026-10-06", "2026-10-06", "Noelle", "expense", "Rent & Utilities", "Storefront Lease & Power", -1450.00, "bank", 0, "settled", "October storefront lease"),
        ("TX-0014", "2026-10-10", "2026-10-10", "Noelle", "expense", "Payroll", "Staff Salaries & Charges", -2480.00, "bank", 0, "settled", "October staff payroll"),
        ("TX-0015", "2026-10-14", "2026-10-14", "Nam", "revenue", "Daily POS Sales", "Beverages & Coffee", 1620.00, "card", 0, "settled", "Autumn beverage & snack sales"),
        ("TX-0016", "2026-10-18", "2026-10-28", "Noelle", "expense", "Supplier Inventory", "Dry Goods & Packaged", -1120.00, "bank", 10, "settled", "Supplier invoice #412"),
        ("TX-0017", "2026-10-23", "2026-10-23", "Nam", "revenue", "Daily POS Sales", "Bakery & Ready-to-Eat", 1550.00, "cash", 0, "settled", "Weekend bakery & deli sales"),
        ("TX-0018", "2026-10-29", "2026-11-08", "Noelle", "expense", "Supplier Inventory", "Fresh Produce & Dairy", -990.00, "bank", 10, "settled", "Supplier invoice #419"),
        ("TX-0019", "2026-11-03", "2026-11-03", "Nam", "revenue", "Daily POS Sales", "General Grocery & Snacks", 1480.00, "card", 0, "settled", "Early November POS batch"),
        ("TX-0020", "2026-11-06", "2026-11-06", "Noelle", "expense", "Rent & Utilities", "Storefront Lease & Power", -1480.00, "bank", 0, "settled", "November lease & heating"),
        ("TX-0021", "2026-11-10", "2026-11-10", "Noelle", "expense", "Payroll", "Staff Salaries & Charges", -2500.00, "bank", 0, "settled", "November staff payroll"),
        ("TX-0022", "2026-11-14", "2026-11-14", "Nam", "revenue", "Daily POS Sales", "Beverages & Coffee", 1590.00, "card", 0, "settled", "Mid-November weekend sales"),
        ("TX-0023", "2026-11-18", "2026-11-28", "Noelle", "expense", "Supplier Inventory", "Dry Goods & Packaged", -1180.00, "bank", 10, "scheduled", "Pending supplier settlement"),
        ("TX-0024", "2026-11-22", "2026-11-22", "Nam", "revenue", "Daily POS Sales", "General Grocery & Snacks", 1530.00, "card", 0, "settled", "Recent weekend register total"),
    ]
    cols = [
        "tx_id", "date", "settled_date", "role", "tx_type", "category",
        "inventory_scope", "amount_eur", "payment_channel", "payment_terms_days",
        "status", "notes"
    ]
    df = pd.DataFrame(rows, columns=cols)
    return rebuild_hash_chain(df)


def load_store_ledger(csv_path: str) -> pd.DataFrame:
    if os.path.exists(csv_path):
        df = pd.read_csv(csv_path)
    else:
        df = _seed_default_ledger()
        try:
            df.to_csv(csv_path, index=False)
        except Exception:
            pass
    return rebuild_hash_chain(df)


def adjust_french_business_day(target_date: date) -> Tuple[date, str]:
    adjusted = target_date
    reasons = []
    while adjusted.weekday() >= 5 or adjusted in FRENCH_HOLIDAYS_2026_2027:
        if adjusted.weekday() >= 5:
            reasons.append("weekend")
        if adjusted in FRENCH_HOLIDAYS_2026_2027:
            reasons.append("French public holiday")
        adjusted += timedelta(days=1)
    note = f"Shifted to {adjusted.isoformat()} ({', '.join(sorted(set(reasons)))})" if reasons else "Standard business day"
    return adjusted, note


def append_transaction(df: pd.DataFrame, tx_data: Dict, csv_path: str = None) -> pd.DataFrame:
    next_num = len(df) + 1
    tx_id = f"TX-{next_num:04d}"
    new_row = {
        "tx_id": tx_id,
        "date": tx_data["date"],
        "settled_date": tx_data["settled_date"],
        "role": tx_data["role"],
        "tx_type": tx_data["tx_type"],
        "category": tx_data["category"],
        "inventory_scope": tx_data["inventory_scope"],
        "amount_eur": float(tx_data["amount_eur"]),
        "payment_channel": tx_data["payment_channel"],
        "payment_terms_days": int(tx_data["payment_terms_days"]),
        "status": tx_data.get("status", "settled"),
        "notes": tx_data.get("notes", ""),
        "prev_hash": "",
        "tx_hash": "",
    }
    updated = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    updated = rebuild_hash_chain(updated)
    if csv_path:
        try:
            updated.to_csv(csv_path, index=False)
        except Exception:
            pass
    return updated


def compute_financial_kpis(df: pd.DataFrame) -> Dict:
    settled = df[df["status"] == "settled"]
    scheduled = df[df["status"] != "settled"]

    bank_balance = settled[settled["payment_channel"] == "bank"]["amount_eur"].sum()
    cash_on_hand = settled[settled["payment_channel"].isin(["cash", "card"])]["amount_eur"].sum()
    total_liquidity = bank_balance + cash_on_hand

    rev_total = settled[settled["tx_type"] == "revenue"]["amount_eur"].sum()
    exp_total = abs(settled[settled["tx_type"] == "expense"]["amount_eur"].sum())
    net_operating = rev_total - exp_total
    pending_payables = abs(scheduled[scheduled["amount_eur"] < 0]["amount_eur"].sum())

    monthly_burn = max(exp_total / 3.0, 1200.0)
    runway_months = total_liquidity / monthly_burn

    return {
        "total_liquidity": total_liquidity,
        "bank_balance": bank_balance,
        "cash_on_hand": cash_on_hand,
        "net_operating": net_operating,
        "pending_payables": pending_payables,
        "runway_months": runway_months,
    }


def generate_90day_forecast(
    df: pd.DataFrame,
    scenario: str,
    rec_dpo: bool,
    rec_payroll: bool,
    rec_credit: bool,
    rec_waste: bool,
    events: List[Dict],
    start_date: date = date(2026, 11, 25),
) -> pd.DataFrame:
    kpis = compute_financial_kpis(df)
    opening_cash = kpis["total_liquidity"]

    scenario_mult = {
        "Optimistic": 1.06,
        "Base Case": 1.00,
        "Conservative": 0.93,
    }.get(scenario, 1.00)

    # Daily baseline: slightly negative net drift (~ -12 EUR/day = -1,080 EUR over 90 days)
    base_daily_rev = 335.0 * scenario_mult
    base_daily_cogs = 205.0
    fixed_daily_overhead = 142.0  # Rent, payroll, utilities averaged daily -> net -12 EUR/day before changes

    # Recommendation uplifts (shifts 90-day cashflow from slightly negative to solidly positive)
    daily_rev_boost = 28.0 if rec_waste else 0.0           # +2,520 EUR over 90 days via bundle/margin optimization
    daily_cogs_saving = 24.0 if rec_dpo else 0.0           # +2,160 EUR working capital release from DPO extension
    payroll_timing_relief = 12.0 if rec_payroll else 0.0   # +1,080 EUR smoothed cash buffer
    credit_injection = 1500.0 if rec_credit else 0.0       # +1,500 EUR immediate liquidity facility
    credit_daily_fee = 2.5 if rec_credit else 0.0          # ~6.0% APR equivalent cost

    records = []
    cum_cash_before = opening_cash
    cum_profit_before = 0.0

    cum_cash_after = opening_cash + credit_injection
    cum_profit_after = 0.0

    for day_idx in range(90):
        curr_date = start_date + timedelta(days=day_idx)
        weekend_factor = 1.18 if curr_date.weekday() in (4, 5) else 0.94

        rev_b = base_daily_rev * weekend_factor
        exp_b = (base_daily_cogs * weekend_factor) + fixed_daily_overhead
        net_b = rev_b - exp_b

        rev_a = (base_daily_rev + daily_rev_boost) * weekend_factor
        exp_a = max(0.0, (base_daily_cogs - daily_cogs_saving) * weekend_factor) + (
            fixed_daily_overhead - payroll_timing_relief + credit_daily_fee
        )
        net_a = rev_a - exp_a

        # Apply user non-recurring events to "After" trajectory
        event_cash_delta = 0.0
        event_profit_delta = 0.0
        for ev in events:
            if not ev.get("active") or ev.get("amount", 0) == 0:
                continue
            ev_start = ev["start_date"]
            ev_end = ev.get("end_date", ev_start)
            amt = float(ev["amount"])
            signed_amt = amt if ev["direction"] == "Cash Inflow (+)" else -amt

            if ev["frequency"] == "One-off" and curr_date == ev_start:
                event_cash_delta += signed_amt
                event_profit_delta += signed_amt
            elif ev["frequency"] == "Weekly" and ev_start <= curr_date <= ev_end:
                if (curr_date - ev_start).days % 7 == 0:
                    event_cash_delta += signed_amt
                    event_profit_delta += signed_amt
            elif ev["frequency"] == "Monthly" and ev_start <= curr_date <= ev_end:
                if curr_date.day == ev_start.day:
                    event_cash_delta += signed_amt
                    event_profit_delta += signed_amt

        cum_cash_before += net_b
        cum_profit_before += net_b

        cum_cash_after += net_a + event_cash_delta
        cum_profit_after += net_a + event_profit_delta

        records.append(
            {
                "Date": pd.to_datetime(curr_date),
                "Cashflow_Before": round(cum_cash_before, 2),
                "Cashflow_After": round(cum_cash_after, 2),
                "Profit_Before": round(cum_profit_before, 2),
                "Profit_After": round(cum_profit_after, 2),
            }
        )

    return pd.DataFrame(records)
