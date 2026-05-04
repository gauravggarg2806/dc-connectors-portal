# Data Cloud Connectors Beta — Issue Dashboard

A self-refreshing issue tracker for Salesforce Data Cloud Beta connectors. Pulls live data from Google Sheets, Gmail, and Slack, enriches it with GUS work item status, and builds a single-file interactive HTML dashboard.

**Live demo:** https://dc-connectors-dashboard-75f6dd75b882.herokuapp.com

![Dashboard screenshot](https://i.imgur.com/placeholder.png)

---

## What it does

- Reads every response from the beta feedback Google Form (Sheet)
- Reads all emails to/from `datacloud-connectors-beta@salesforce.com`
- Reads `#datacloud-connectors-beta-feedback` Slack channel
- Looks up the linked GUS work item for each issue and pulls live status + assignee
- Builds a filterable, searchable HTML dashboard with:
  - Status/severity breakdown by connector type (CData / Homegrown / WDC)
  - PM ownership filter (Gaurav / Sriram / Vasanthi)
  - Click-through detail panel with full GUS ticket info
  - Blockers with no assigned engineer highlighted

---

## Quick start (local)

```bash
# 1. Clone
git clone https://github.com/gauravggarg28/dc-connectors-portal
cd dc-connectors-portal

# 2. Install Python deps
pip install -r requirements.txt

# 3. Install Node deps (for the web server)
npm install

# 4. Configure credentials
cp config.example.json config.json
# → edit config.json with your credentials (see Setup below)

# 5. Refresh the dashboard (fetches live data + rebuilds HTML)
python3 scripts/refresh.py --open

# 6. Serve locally
npm start
# → open http://localhost:3000
```

---

## Setup: credentials

Copy `config.example.json` → `config.json` and fill in:

### Google Sheets + Gmail

You need a **Google Cloud Service Account** with domain-wide delegation.

1. Go to [Google Cloud Console](https://console.cloud.google.com) → IAM → Service Accounts → Create
2. Download the JSON key → set `google_service_account_json` in config.json
3. Enable **Google Sheets API** and **Gmail API** in your project
4. Grant domain-wide delegation to the service account in Google Workspace Admin
5. Set `gmail_delegated_email` to the email you want to read mail as

```json
{
  "google_service_account_json": "/path/to/service-account-key.json",
  "gmail_delegated_email": "your-email@your-org.com"
}
```

### Slack

1. Create a Slack App at https://api.slack.com/apps
2. Add OAuth scopes: `channels:history`, `channels:read`, `groups:history`, `groups:read`
3. Install to workspace and copy the **Bot User OAuth Token** (`xoxb-...`)
4. Invite the bot to `#datacloud-connectors-beta-feedback`

```json
{
  "slack_bot_token": "xoxb-your-token-here"
}
```

### GUS (Salesforce internal only)

Uses the Salesforce CLI (`sf`) authenticated to GUS. If you're outside Salesforce, skip with `--no-gus`.

```bash
sf org login web --alias gus --instance-url https://gus.lightning.force.com
```

---

## Refresh options

```bash
# Full refresh (all sources + GUS)
python3 scripts/refresh.py

# Skip GUS (for non-Salesforce users)
python3 scripts/refresh.py --no-gus

# Refresh and open in browser
python3 scripts/refresh.py --open

# Custom SF CLI path / org alias
python3 scripts/refresh.py --sf-cli /path/to/sf --sf-org my-gus-alias
```

---

## Google Sheet format

The sheet is expected to be a Google Form response sheet with these columns:

| Col | Field |
|-----|-------|
| 0   | Timestamp |
| 1   | Reporter name |
| 2   | Company |
| 3   | Email |
| 4   | Severity (🚨 Blocker / ⚠ Major / 🟡 Minor / 💡 Enhancement) |
| 5   | Connector name |
| 6   | Issue description |
| 9   | Org ID |
| 16  | Status (Resolved / Current Sprint / Next Sprint / Not our team) |
| 17  | GUS Work Item URL |
| 18  | Notes |
| 19  | Issue ID |

To use with a different sheet, update `sheet_id` and `sheet_name` in `config.json`.

---

## Deploy to Heroku

```bash
heroku create your-app-name
git push heroku main
```

The dashboard HTML is static — rebuild locally and `git push heroku main` to redeploy.

---

## Project structure

```
dc-connectors-portal/
├── datacloud-connectors-dashboard.html   # built dashboard (committed for instant deploy)
├── server.js                             # Express server (serves dashboard at /)
├── package.json
├── Procfile                              # Heroku process file
├── requirements.txt                      # Python deps for refresh script
├── config.example.json                   # credential template (copy → config.json)
├── data/
│   └── issues_cache.json                 # last fetched issues (gitignored)
└── scripts/
    ├── refresh.py                        # main CLI: fetch → enrich → build
    └── build_connectors_dashboard.py     # HTML builder (reads issues_cache.json)
```

---

## Customising for your team

1. **Change PM owners** — edit `PM_OWNER_MAP` in `scripts/refresh.py`
2. **Change connector types** — edit `CONNECTOR_TYPE_MAP`
3. **Different beta email** — pass to `fetch_email_issues()` in refresh.py
4. **Different Slack channel** — pass `channel_name` to `fetch_slack_issues()`
5. **Different GUS object** — edit the SOQL in `enrich_with_gus()`
6. **Rebrand the dashboard title** — edit `HTML_TEMPLATE` in `scripts/build_connectors_dashboard.py`

---

## Built by

Gaurav Garg — Salesforce Data 360 Connectivity PM  
Maintained with [Claude Code](https://claude.ai/code)
