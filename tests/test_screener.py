import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gate  # noqa: E402
import screener  # noqa: E402
from magic_formula import Excluded, Financials, compute_metrics, rank  # noqa: E402


def fin(**kw):
    base = dict(ebit=100, revenue=1000, net_income=60, current_assets=300,
                current_liabilities=200, cash=50, current_debt=20, net_ppe=400,
                total_debt=150)
    base.update(kw)
    return Financials(**base)


# ---------- formula ----------

def test_greenblatt_metrics():
    m = compute_metrics(fin(), market_cap_aud=900, fx_to_aud=1.0)
    # EV = 900 + 150 - 50 = 1000 ; NWC = (300-50) - (200-20) = 70 ; capital = 470
    assert m["ev_aud"] == 1000
    assert m["earnings_yield"] == pytest.approx(0.10)
    assert m["roc"] == pytest.approx(100 / 470)


def test_negative_nwc_floored_at_zero():
    m = compute_metrics(fin(current_liabilities=900), 900, 1.0)
    assert m["capital_aud"] == 400


def test_currency_conversion_only_affects_aud_amounts():
    usd = compute_metrics(fin(), market_cap_aud=900 * 1.5, fx_to_aud=1.5)
    aud = compute_metrics(fin(), market_cap_aud=900, fx_to_aud=1.0)
    assert usd["earnings_yield"] == pytest.approx(aud["earnings_yield"])
    assert usd["roc"] == pytest.approx(aud["roc"])


@pytest.mark.parametrize("kw,reason", [
    (dict(revenue=0), "pre-revenue"),
    (dict(revenue=None), "pre-revenue"),
    (dict(ebit=-5), "loss-making"),
    (dict(net_income=-1), "loss-making"),
    (dict(net_ppe=None), "missing balance sheet data"),
    (dict(net_ppe=0, current_liabilities=900), "no tangible capital"),
    (dict(cash=5000, current_assets=5300), "negative enterprise value"),
])
def test_exclusions(kw, reason):
    with pytest.raises(Excluded, match=reason):
        compute_metrics(fin(**kw), 900, 1.0)


def row(code, ey, roc, cap=1e9, ind="Materials"):
    return dict(code=code, name=code, industry=ind, market_cap_aud=cap,
                earnings_yield=ey, roc=roc)


def test_rank_combined_score_and_filters():
    rows = [
        row("AAA", 0.20, 0.10),               # EY 1, ROC 3 -> 4
        row("BBB", 0.10, 0.50),               # EY 3, ROC 1 -> 4 (tie broken by EY rank)
        row("CCC", 0.15, 0.30),               # EY 2, ROC 2 -> 4
        row("SML", 0.99, 0.99, cap=1e8),      # below floor
        row("BNK", 0.99, 0.99, ind="Banks"),  # excluded industry
    ]
    out = rank(rows, 5e8, {"Banks"})
    assert [r["code"] for r in out] == ["AAA", "CCC", "BBB"]
    assert [r["score"] for r in out] == [4, 4, 4]
    assert [r["rank"] for r in out] == [1, 2, 3]


def test_ranks_recomputed_on_filtered_set():
    rows = [row("AAA", 0.2, 0.2), row("BIG", 0.3, 0.3, ind="Banks")]
    assert rank(rows, 0, set())[0]["code"] == "BIG"
    assert rank(rows, 0, {"Banks"})[0]["ey_rank"] == 1


def test_ties_share_rank():
    out = rank([row("A", 0.1, 0.3), row("B", 0.1, 0.2)], 0, set())
    assert out[0]["ey_rank"] == out[1]["ey_rank"] == 1


# ---------- fetch path with a fake Yahoo ticker ----------

def frame(items, date):
    return pd.DataFrame({pd.Timestamp(date): items})


def fake_ticker(country="Australia", currency="AUD", ttm=True, half_year_complete=True):
    recent = (pd.Timestamp.now() - pd.Timedelta(days=60)).strftime("%Y-%m-%d")
    old = (pd.Timestamp.now() - pd.Timedelta(days=240)).strftime("%Y-%m-%d")
    income = {"EBIT": 100.0, "Total Revenue": 1000.0, "Net Income": 60.0}
    bs = {"Current Assets": 300.0, "Current Liabilities": 200.0, "Net PPE": 400.0,
          "Cash And Cash Equivalents": 50.0, "Current Debt": 20.0, "Total Debt": 150.0}
    half = dict(bs) if half_year_complete else {"Current Assets": 1.0}
    return SimpleNamespace(
        info={"country": country, "financialCurrency": currency},
        ttm_income_stmt=frame(income, recent) if ttm else pd.DataFrame(),
        income_stmt=frame({**income, "EBIT": 80.0}, old),
        quarterly_balance_sheet=frame({**half, "Net PPE": 999.0} if half_year_complete else half, recent),
        balance_sheet=frame(bs, old),
    )


ROW = SimpleNamespace(code="XYZ", name="Xyz Ltd", industry="Materials", market_cap_aud=900.0)


def test_fetch_uses_ttm_and_newest_balance_sheet():
    with mock.patch.object(screener.yf, "Ticker", return_value=fake_ticker()):
        r = screener.fetch_one(ROW)
    assert r["statement"] == "TTM"
    assert r["roc"] == pytest.approx(100 / (70 + 999))


def test_fetch_falls_back_to_annual_and_complete_balance_sheet():
    t = fake_ticker(ttm=False, half_year_complete=False)
    with mock.patch.object(screener.yf, "Ticker", return_value=t):
        r = screener.fetch_one(ROW)
    assert r["statement"] == "FY"
    assert r["roc"] == pytest.approx(80 / 470)


def test_fetch_excludes_foreign():
    with mock.patch.object(screener.yf, "Ticker", return_value=fake_ticker(country="New Zealand")):
        with pytest.raises(Excluded, match="foreign"):
            screener.fetch_one(ROW)


def test_fetch_converts_usd_reporters():
    screener._fx_cache["USD"] = 1.5
    with mock.patch.object(screener.yf, "Ticker", return_value=fake_ticker(currency="USD")):
        r = screener.fetch_one(ROW)
    # EV = 900 + (150 - 50) * 1.5 = 1050 ; EBIT = 150 A$
    assert r["ev_aud"] == pytest.approx(1050)
    assert r["earnings_yield"] == pytest.approx(150 / 1050)


# ---------- schedule gate ----------

@pytest.mark.parametrize("now,cron,expected", [
    (datetime(2026, 10, 11, 17, 30, tzinfo=timezone.utc), "30 17 * * 0", True),   # ACDT
    (datetime(2026, 10, 11, 18, 30, tzinfo=timezone.utc), "30 18 * * 0", False),
    (datetime(2026, 6, 14, 18, 30, tzinfo=timezone.utc), "30 18 * * 0", True),    # ACST
    (datetime(2026, 6, 14, 17, 30, tzinfo=timezone.utc), "30 17 * * 0", False),
])
def test_gate(now, cron, expected):
    assert gate.should_run("schedule", cron, now) is expected
    assert gate.should_run("workflow_dispatch", "", now) is True
