"""Settings for the ASX Magic Formula screener. Edit these to change behaviour."""

# Companies below this market cap (A$) are never fetched. The web page's
# market cap filter can't go lower than this.
FETCH_FLOOR_AUD = 100_000_000

# Default market cap floor (A$) used by the web page on load and by the email.
DEFAULT_FLOOR_AUD = 500_000_000

# GICS industry groups excluded by default (web page + email). Greenblatt
# excluded financials and utilities because EBIT and return on capital
# aren't meaningful for them; REITs sat inside financials when he wrote it.
# These are only defaults: every industry can be toggled on the web page.
DEFAULT_EXCLUDED_INDUSTRIES = [
    "Banks",
    "Insurance",
    "Financial Services",
    "Diversified Financials",
    "Utilities",
    "Equity Real Estate Investment Trusts (REITs)",
    "Mortgage Real Estate Investment Trusts (REITs)",
]

# Number of stocks listed in the Monday email.
EMAIL_TOP_N = 30

# Financial statements older than this are treated as stale and skipped.
MAX_STATEMENT_AGE_DAYS = 550

ASX_DIRECTORY_URL = (
    "https://asx.api.markitdigital.com/asx-research/1.0/companies/directory/file"
)
