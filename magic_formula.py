"""Pure Greenblatt Magic Formula maths. No network access in this file.

Earnings yield  = EBIT / Enterprise value
Return on capital = EBIT / (Net working capital + Net fixed assets)

Enterprise value      = Market cap + Total debt - Cash
Net working capital   = (Current assets - Cash) - (Current liabilities - Short-term debt),
                        floored at zero (Greenblatt's treatment)
Net fixed assets      = Net property, plant & equipment

Each stock is ranked on both measures (1 = best); the two ranks are summed
and the lowest combined score ranks first.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Financials:
    """Statement line items, all in the company's reporting currency."""
    ebit: float | None
    revenue: float | None
    net_income: float | None
    current_assets: float | None
    current_liabilities: float | None
    cash: float | None
    current_debt: float | None
    net_ppe: float | None
    total_debt: float | None


class Excluded(Exception):
    """Raised when a company fails a screen; the message is the reason."""


def _num(x) -> float | None:
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def compute_metrics(f: Financials, market_cap_aud: float, fx_to_aud: float) -> dict:
    """Return earnings yield and return on capital, or raise Excluded."""
    ebit = _num(f.ebit)
    revenue = _num(f.revenue)
    net_income = _num(f.net_income)

    if revenue is None or revenue <= 0:
        raise Excluded("pre-revenue")
    if ebit is None or net_income is None:
        raise Excluded("missing earnings data")
    if ebit <= 0 or net_income <= 0:
        raise Excluded("loss-making")

    ca = _num(f.current_assets)
    cl = _num(f.current_liabilities)
    ppe = _num(f.net_ppe)
    if ca is None or cl is None or ppe is None:
        raise Excluded("missing balance sheet data")
    cash = _num(f.cash) or 0.0
    current_debt = _num(f.current_debt) or 0.0
    total_debt = _num(f.total_debt) or 0.0

    nwc = max((ca - cash) - (cl - current_debt), 0.0)
    capital = nwc + max(ppe, 0.0)
    if capital <= 0:
        raise Excluded("no tangible capital")

    ev_aud = market_cap_aud + (total_debt - cash) * fx_to_aud
    if ev_aud <= 0:
        raise Excluded("negative enterprise value")

    return {
        "ebit_aud": ebit * fx_to_aud,
        "ev_aud": ev_aud,
        "capital_aud": capital * fx_to_aud,
        "earnings_yield": ebit * fx_to_aud / ev_aud,
        "roc": ebit / capital,
    }


def _rank_desc(values: list[float]) -> list[int]:
    """Rank 1 = largest value. Ties share the lower (better) rank."""
    order = sorted(range(len(values)), key=lambda i: -values[i])
    ranks = [0] * len(values)
    for pos, i in enumerate(order):
        if pos > 0 and values[i] == values[order[pos - 1]]:
            ranks[i] = ranks[order[pos - 1]]
        else:
            ranks[i] = pos + 1
    return ranks


def rank(rows: list[dict], floor_aud: float, excluded_industries: set[str]) -> list[dict]:
    """Filter rows, rank them, and return new dicts sorted best first.

    Ranks are always recomputed on the filtered set, because Magic Formula
    ranks are relative to the universe being screened. The web page
    (docs/index.html) implements exactly the same logic in JavaScript.
    """
    pool = [
        dict(r) for r in rows
        if r["market_cap_aud"] >= floor_aud and r["industry"] not in excluded_industries
    ]
    ey_ranks = _rank_desc([r["earnings_yield"] for r in pool])
    roc_ranks = _rank_desc([r["roc"] for r in pool])
    for r, e, c in zip(pool, ey_ranks, roc_ranks):
        r["ey_rank"], r["roc_rank"], r["score"] = e, c, e + c
    pool.sort(key=lambda r: (r["score"], r["ey_rank"], r["code"]))
    for i, r in enumerate(pool, 1):
        r["rank"] = i
    return pool
