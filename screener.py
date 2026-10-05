"""Weekly ASX Magic Formula refresh.

1. Download the ASX company directory (codes, names, GICS industry group, market cap).
2. Pull fundamentals for every company above FETCH_FLOOR_AUD from Yahoo Finance.
3. Drop loss-making, pre-revenue and foreign-domiciled companies.
4. Compute earnings yield and return on capital and write docs/data.json.

Ranking itself happens in the web page and the email, so filters can change
without re-fetching anything.

Run: python screener.py
"""

from __future__ import annotations

import io
import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

import config
from magic_formula import Excluded, Financials, compute_metrics

OUT = Path(__file__).parent / "docs" / "data.json"
WORKERS = 4
RETRIES = 3

_fx_cache: dict[str, float] = {"AUD": 1.0}


# ---------- universe ----------

def load_universe() -> pd.DataFrame:
    resp = requests.get(config.ASX_DIRECTORY_URL, timeout=60,
                        headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df = df.rename(columns={
        "ASX code": "code", "Company name": "name",
        "GICs industry group": "industry", "Market Cap": "market_cap_aud",
    })
    df["market_cap_aud"] = pd.to_numeric(df["market_cap_aud"], errors="coerce")
    df["industry"] = df["industry"].fillna("Not Applic").astype(str).str.strip()
    df["name"] = df["name"].astype(str).str.title()
    return df.dropna(subset=["market_cap_aud"])


# ---------- statement helpers ----------

def _latest(df: pd.DataFrame | None, names: list[str]):
    """Value of the first matching row in the newest column, else None."""
    if df is None or df.empty:
        return None
    col = df.columns[0]
    for n in names:
        if n in df.index:
            v = df.at[n, col]
            if pd.notna(v):
                return float(v)
    return None


def _col_date(df: pd.DataFrame | None) -> pd.Timestamp | None:
    """Date of a statement's newest column, or None if empty/undated."""
    if df is None or df.empty:
        return None
    try:
        return pd.Timestamp(df.columns[0])
    except (ValueError, TypeError):
        return None


BALANCE_REQUIRED = ["Total Assets", "Current Assets", "Current Liabilities"]


def _newest_complete(*frames: pd.DataFrame | None) -> pd.DataFrame | None:
    """Newest balance sheet that has every line item the formula needs.

    Half-year balance sheets on Yahoo are sometimes thinner than annual ones,
    so a newer but incomplete sheet loses to an older complete one.
    """
    ok = [f for f in frames
          if _col_date(f) is not None
          and all(_latest(f, [n]) is not None for n in BALANCE_REQUIRED)]
    if not ok:
        return None
    return max(ok, key=_col_date)


def fx_to_aud(currency: str) -> float:
    currency = (currency or "AUD").upper()
    if currency not in _fx_cache:
        rate = yf.Ticker(f"{currency}AUD=X").fast_info["last_price"]
        if not rate or rate <= 0:
            raise RuntimeError(f"no FX rate for {currency}")
        _fx_cache[currency] = float(rate)
    return _fx_cache[currency]


def _intangibles(balance: pd.DataFrame) -> float:
    """Goodwill plus other intangibles (excluded from tangible capital)."""
    combined = _latest(balance, ["Goodwill And Other Intangible Assets"])
    if combined is not None:
        return combined
    return (_latest(balance, ["Goodwill"]) or 0.0) + (_latest(balance, ["Other Intangible Assets"]) or 0.0)


# ---------- per company ----------

def fetch_one(row) -> dict:
    t = yf.Ticker(f"{row.code}.AX")
    info = t.info or {}

    country = info.get("country")
    if country and country != "Australia":
        raise Excluded("foreign-domiciled")
    if not country:
        raise Excluded("missing company data")

    # Pure Greenblatt uses trailing twelve months; fall back to the last
    # full year where Yahoo has no trailing figures for the company.
    income, statement = t.ttm_income_stmt, "TTM"
    if (_col_date(income) is None
            or _latest(income, ["EBIT", "Operating Income"]) is None):
        income, statement = t.income_stmt, "FY"
    period_end = _col_date(income)
    if period_end is None:
        raise Excluded("missing earnings data")

    balance = _newest_complete(t.quarterly_balance_sheet, t.balance_sheet)
    if balance is None:
        raise Excluded("missing balance sheet data")

    if (pd.Timestamp.now() - period_end).days > config.MAX_STATEMENT_AGE_DAYS:
        raise Excluded("stale financials")

    f = Financials(
        ebit=_latest(income, ["EBIT", "Operating Income"]),
        revenue=_latest(income, ["Total Revenue", "Operating Revenue"]),
        net_income=_latest(income, ["Net Income", "Net Income Common Stockholders"]),
        current_assets=_latest(balance, ["Current Assets"]),
        current_liabilities=_latest(balance, ["Current Liabilities"]),
        cash=_latest(balance, ["Cash Cash Equivalents And Short Term Investments",
                               "Cash And Cash Equivalents"]),
        current_debt=_latest(balance, ["Current Debt And Capital Lease Obligation",
                                       "Current Debt"]),
        total_assets=_latest(balance, ["Total Assets"]),
        intangibles=_intangibles(balance),
        total_debt=_latest(balance, ["Total Debt"]),
    )
    currency = info.get("financialCurrency") or "AUD"
    metrics = compute_metrics(f, float(row.market_cap_aud), fx_to_aud(currency))

    return {
        "code": row.code,
        "name": row.name,
        "industry": row.industry,
        "market_cap_aud": float(row.market_cap_aud),
        **metrics,
        "statement": statement,
        "period_end": period_end.strftime("%Y-%m-%d"),
        "currency": currency,
    }


def fetch_with_retry(row):
    for attempt in range(RETRIES):
        try:
            return fetch_one(row)
        except Excluded:
            raise
        except Exception as e:  # network / rate-limit / parsing
            if attempt == RETRIES - 1:
                raise Excluded(f"fetch error") from e
            time.sleep(5 * (attempt + 1))


# ---------- main ----------

def main() -> int:
    universe = load_universe()
    candidates = universe[universe["market_cap_aud"] >= config.FETCH_FLOOR_AUD]
    print(f"ASX directory: {len(universe)} companies, "
          f"{len(candidates)} above A${config.FETCH_FLOOR_AUD/1e6:.0f}m")

    stocks, reasons = [], Counter()
    with ThreadPoolExecutor(WORKERS) as pool:
        futures = {pool.submit(fetch_with_retry, r): r.code
                   for r in candidates.itertuples(index=False)}
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                stocks.append(fut.result())
            except Excluded as e:
                reasons[str(e)] += 1
            if i % 50 == 0:
                print(f"  {i}/{len(futures)} processed, {len(stocks)} qualify")

    # Guard against Yahoo outages or rate limiting: if most fetches failed,
    # keep last week's data rather than publishing a gutted list.
    failed = reasons["fetch error"] + reasons["missing company data"]
    if failed > 0.5 * len(candidates):
        print(f"ERROR: {failed}/{len(candidates)} fetches failed; not publishing.")
        return 1

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fetch_floor_aud": config.FETCH_FLOOR_AUD,
        "default_floor_aud": config.DEFAULT_FLOOR_AUD,
        "default_excluded_industries": config.DEFAULT_EXCLUDED_INDUSTRIES,
        "industries": sorted(candidates["industry"].unique().tolist()),
        "screened": len(candidates),
        "exclusions": dict(reasons.most_common()),
        "stocks": sorted(stocks, key=lambda s: s["code"]),
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1))
    print(f"Wrote {len(stocks)} qualifying stocks to {OUT}. Excluded: {dict(reasons)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
