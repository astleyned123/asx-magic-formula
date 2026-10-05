"""Email the weekly Magic Formula summary (default filters, top N).

Environment variables (set as GitHub Actions secrets):
  GMAIL_ADDRESS       Gmail account that sends the email
  GMAIL_APP_PASSWORD  16-character Gmail app password (not your normal password)
  MAIL_TO             Recipient (optional; defaults to GMAIL_ADDRESS)
  PAGE_URL            Link to the hosted page (optional; derived on GitHub)

Run: python emailer.py              send the email
     python emailer.py --preview f  write the email HTML to file f instead
"""

from __future__ import annotations

import html
import json
import os
import smtplib
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

import config
from magic_formula import rank

DATA = Path(__file__).parent / "docs" / "data.json"
ADL = ZoneInfo("Australia/Adelaide")


def page_url() -> str:
    if os.environ.get("PAGE_URL"):
        return os.environ["PAGE_URL"]
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/{name}/"
    return ""


def fmt_cap(v: float) -> str:
    return f"${v/1e9:,.1f}b" if v >= 1e9 else f"${v/1e6:,.0f}m"


def build(data: dict) -> tuple[str, str, str]:
    """Return (subject, plain text, html) for the email."""
    ranked = rank(data["stocks"], data["default_floor_aud"],
                  set(data["default_excluded_industries"]))
    top = ranked[: config.EMAIL_TOP_N]
    asof = datetime.fromisoformat(data["generated_at"]).astimezone(ADL)
    date = asof.strftime("%a %d %b %Y")
    floor = fmt_cap(data["default_floor_aud"])
    url = page_url()
    subject = f"ASX Magic Formula — top {len(top)} — {date}"

    text_lines = [f"ASX Magic Formula, {date}",
                  f"{len(ranked)} stocks ranked (market cap ≥ {floor}, financials/utilities/REITs excluded)", ""]
    text_lines += [f"{r['rank']:>3}. {r['code']:<4} {r['name'][:32]:<32} "
                   f"EY {r['earnings_yield']*100:5.1f}%  ROC {r['roc']*100:6.1f}%"
                   for r in top]
    if url:
        text_lines += ["", f"Full table and filters: {url}"]

    cell = "padding:6px 10px;border-bottom:1px solid #e5e5e5;"
    num = cell + "text-align:right;font-variant-numeric:tabular-nums;"
    rows = "".join(
        f"<tr><td style='{num}color:#666'>{r['rank']}</td>"
        f"<td style='{cell}font-weight:600'>{html.escape(r['code'])}</td>"
        f"<td style='{cell}'>{html.escape(r['name'])}<div style='color:#888;font-size:12px'>"
        f"{html.escape(r['industry'])}</div></td>"
        f"<td style='{num}'>{fmt_cap(r['market_cap_aud'])}</td>"
        f"<td style='{num}'>{r['earnings_yield']*100:.1f}%</td>"
        f"<td style='{num}'>{r['roc']*100:.1f}%</td></tr>"
        for r in top)
    th = "padding:6px 10px;text-align:left;font-size:12px;color:#666;border-bottom:2px solid #222;"
    thr = th + "text-align:right;"
    link = (f"<p style='margin:20px 0'><a href='{html.escape(url)}' style='color:#0b5cad'>"
            f"Open the full table and filters →</a></p>") if url else ""
    body = f"""<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#222;max-width:720px">
<h2 style="margin:0 0 4px">ASX Magic Formula</h2>
<p style="margin:0 0 16px;color:#666">{date} · {len(ranked)} stocks ranked · market cap ≥ {floor} ·
financials, utilities &amp; REITs excluded</p>
<table style="border-collapse:collapse;width:100%;font-size:14px">
<tr><th style="{thr}">#</th><th style="{th}">Code</th><th style="{th}">Company</th>
<th style="{thr}">Mkt cap</th><th style="{thr}">Earnings yield</th><th style="{thr}">ROC</th></tr>
{rows}</table>{link}
<p style="color:#999;font-size:12px">Earnings yield = EBIT / EV. ROC = EBIT / (net working capital + net fixed assets).
Data from ASX and Yahoo Finance; check figures against company reports before acting.</p></div>"""
    return subject, "\n".join(text_lines), body


def main() -> int:
    data = json.loads(DATA.read_text())
    subject, text, body = build(data)

    if len(sys.argv) == 3 and sys.argv[1] == "--preview":
        Path(sys.argv[2]).write_text(body)
        print(f"Preview written to {sys.argv[2]}\n\n{text}")
        return 0

    sender = os.environ["GMAIL_ADDRESS"]
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = os.environ.get("MAIL_TO") or sender
    msg.set_content(text)
    msg.add_alternative(body, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(sender, os.environ["GMAIL_APP_PASSWORD"])
        s.send_message(msg)
    print(f"Sent: {subject}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
