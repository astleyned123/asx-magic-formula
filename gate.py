"""Decide whether this workflow run should go ahead.

Manual runs always go ahead. A scheduled run goes ahead only if its cron
slot lands on 4 am in Adelaide given the current daylight-saving offset.
Prints "run=true" or "run=false" for $GITHUB_OUTPUT.

Usage: python gate.py <event_name> <cron expression>
"""

import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# Cron slot -> Adelaide UTC offset at which that slot equals 4:00 am.
SLOTS = {
    "30 17 * * 0": timedelta(hours=10, minutes=30),  # ACDT, summer
    "30 18 * * 0": timedelta(hours=9, minutes=30),   # ACST, winter
}


def should_run(event: str, cron: str, now: datetime) -> bool:
    if event != "schedule":
        return True
    offset = now.astimezone(ZoneInfo("Australia/Adelaide")).utcoffset()
    return SLOTS.get(cron) == offset


if __name__ == "__main__":
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    cron = sys.argv[2] if len(sys.argv) > 2 else ""
    print(f"run={'true' if should_run(event, cron, datetime.now(timezone.utc)) else 'false'}")
