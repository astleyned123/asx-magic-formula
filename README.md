# ASX Magic Formula

Joel Greenblatt's Magic Formula, applied to the ASX. Every Monday at 4:00 am
(Adelaide time) GitHub refreshes the data, republishes the ranked table and
emails you the top 30. Everything runs on free tiers.

- **Web page** (GitHub Pages): full ranked table. You can change the market cap floor, include or exclude industries, search, and sort by any column.
- **Email** (Gmail): top 30 under the default filters, with a link to the page.

## How it ranks

Pure Greenblatt:

| Measure | Formula |
|---|---|
| Earnings yield | EBIT ÷ (market cap + total debt − cash) |
| Return on capital | EBIT ÷ (net working capital + net PP&E) |

- Net working capital excludes cash and short-term debt, and is floored at zero.
- Each stock is ranked on both measures. The two ranks are added, and the lowest total ranks first.
- Ranks are recalculated on the page whenever you change a filter.

**Always removed:** loss-making companies (EBIT or net income ≤ 0), pre-revenue companies, foreign-domiciled companies, companies whose financials are more than 18 months old, companies with zero tangible capital, and companies with a negative enterprise value.

**Defaults you can change on the page:** market cap ≥ A$500m; banks, insurance, financial services, utilities and REITs excluded. Greenblatt excluded financials and utilities because EBIT and return on capital don't mean much for them.

**Data:** the ASX company directory supplies the codes, industries and market caps, and Yahoo Finance supplies the financial statements.
- EBIT is trailing twelve months where Yahoo has it, otherwise the last full year. The page's Period column shows which.
- Figures for companies that report in USD or another currency are converted to A$.

## Setup (about 10 minutes)

1. **Create a public GitHub repository**, e.g. `asx-magic-formula`. GitHub Pages is only free on public repos.
2. **Upload these files**, including the hidden `.github` folder:
   ```bash
   cd magic-formula-asx
   git init && git add . && git commit -m "ASX Magic Formula"
   git branch -M main
   git remote add origin https://github.com/<you>/asx-magic-formula.git
   git push -u origin main
   ```
3. **Turn on the page:** repo **Settings → Pages → Build and deployment**: Source *Deploy from a branch*, branch `main`, folder `/docs`.
4. **Create a Gmail app password:** at <https://myaccount.google.com/apppasswords> (requires 2-Step Verification), create one called "ASX screener" and copy the 16 characters.
5. **Add the secrets:** repo **Settings → Secrets and variables → Actions → New repository secret**:
   - `GMAIL_ADDRESS`: your Gmail address
   - `GMAIL_APP_PASSWORD`: the app password from step 4
   - `MAIL_TO`: optional, a different recipient
6. **First run:** **Actions → Weekly screen → Run workflow**, and tick *Send the email* to test the email too.
   - It takes roughly 20–40 minutes, since it pulls data for several hundred companies.
   - The page is then live at `https://<you>.github.io/asx-magic-formula/`.

After that it runs on its own every Monday.

## Things to know

- **Schedule:** GitHub sometimes starts scheduled runs 5–30 minutes late. The workflow switches automatically between Adelaide's summer and winter time.
- **Failed fetches:** if Yahoo is down or rate-limits the run so that most fetches fail, the job fails rather than publishing a half-empty list. GitHub emails you when a run fails, and last week's page stays up.
- **Data quality:** Yahoo's data for small ASX companies can be patchy, so check numbers against the annual report before buying.
- **Changing defaults:** edit `config.py` for the market cap floor, default excluded industries and email length.

## Files

| File | What it does |
|---|---|
| `screener.py` | Fetches data and writes `docs/data.json` |
| `magic_formula.py` | The formula and ranking (no network) |
| `emailer.py` | Builds and sends the email (`--preview out.html` to view without sending) |
| `gate.py` | Picks the correct 4 am slot across daylight saving |
| `docs/index.html` | The web page |
| `.github/workflows/weekly.yml` | The Monday schedule |
| `tests/` | `pip install pytest && pytest` |
