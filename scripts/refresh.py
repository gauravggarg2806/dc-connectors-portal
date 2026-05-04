#!/usr/bin/env python3
"""
refresh.py — Data Cloud Connectors Dashboard: full data refresh

Pulls issues from three sources, enriches with GUS, builds the dashboard HTML.

Usage:
    python3 scripts/refresh.py [--no-gus] [--open]

Sources:
  1. Google Sheets  — the beta feedback form responses sheet
  2. Gmail          — emails to/from datacloud-connectors-beta@salesforce.com
  3. Slack          — #datacloud-connectors-beta-feedback channel messages

Requirements:
    pip install google-auth google-auth-oauthlib google-auth-httplib2 \
                google-api-python-client slack-sdk simple-salesforce

    See README.md for full setup instructions.
"""

import argparse
import json
import os
import sys
import re
import csv
import io
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA_PATH = ROOT / "data" / "issues_cache.json"
DASHBOARD_PATH = ROOT / "datacloud-connectors-dashboard.html"
CONFIG_PATH = ROOT / "config.json"

# ─── Connector classification ─────────────────────────────────────────────────

CONNECTOR_TYPE_MAP = {
    "databricks": "Homegrown", "amazon rds": "Homegrown", "amazon aurora": "Homegrown",
    "azure postgresql": "Homegrown", "azure mysql": "Homegrown", "heroku postgresql": "Homegrown",
    "jira": "Homegrown", "amazon athena": "Homegrown", "microsoft fabric": "Homegrown",
    "ms fabric": "Homegrown", "azure sql server": "Homegrown", "servicenow": "Homegrown",
    "service now": "Homegrown", "b2c": "Homegrown",
    "google analytics": "CData", "ga4": "CData", "hubspot": "CData", "linkedin": "CData",
    "sap": "CData", "wordpress": "CData", "zendesk": "CData", "mongodb": "CData",
    "shopify": "CData", "odata": "CData", "adobe": "CData", "confluence": "CData",
    "instagram": "CData", "platform events": "CData", "azure cosmos db": "CData",
    "cosmos db": "CData", "dynamics": "CData", "netsuite": "CData",
    "ibm cloud object storage": "CData", "ibm db2": "CData", "ibm informix": "CData",
    "sharepoint": "WDC", "onedrive": "WDC", "google drive": "WDC",
    "google sheets": "WDC", "excel online": "WDC", "box": "WDC",
    "dropbox": "WDC", "teams": "WDC",
}

PM_OWNER_MAP = {
    "databricks": "Gaurav", "amazon rds": "Gaurav", "amazon aurora": "Gaurav",
    "azure postgresql": "Gaurav", "azure mysql": "Gaurav", "heroku postgresql": "Gaurav",
    "amazon athena": "Gaurav", "microsoft fabric": "Gaurav", "ms fabric": "Gaurav",
    "azure sql server": "Gaurav", "ibm cloud object storage": "Gaurav",
    "ibm db2": "Gaurav", "ibm informix": "Gaurav", "google analytics": "Gaurav",
    "ga4": "Gaurav", "hubspot": "Gaurav", "servicenow": "Gaurav",
    "service now": "Gaurav", "zendesk": "Gaurav",
    "jira": "Sriram", "linkedin": "Sriram", "sap": "Sriram", "wordpress": "Sriram",
    "mongodb": "Sriram", "shopify": "Sriram", "odata": "Sriram", "adobe": "Sriram",
    "dynamics": "Sriram", "netsuite": "Sriram",
    "sharepoint": "Vasanthi", "onedrive": "Vasanthi", "google drive": "Vasanthi",
    "google sheets": "Vasanthi", "instagram": "Vasanthi", "confluence": "Vasanthi",
    "azure cosmos db": "Vasanthi", "cosmos db": "Vasanthi", "platform events": "Vasanthi",
    "teams": "Vasanthi", "b2c": "Gaurav",
}

def classify(name):
    c = (name or "").lower()
    ct = next((t for kw, t in CONNECTOR_TYPE_MAP.items() if kw in c), "Unknown")
    pm = next((p for kw, p in PM_OWNER_MAP.items() if kw in c), "Unknown")
    return ct, pm

def norm_sev(sev):
    if any(x in sev for x in ["🚨", "Blocker", "blocker", "unusable"]):
        return "Blocker", "#dc2626"
    elif any(x in sev for x in ["⚠", "Major", "major", "core functionality"]):
        return "Major", "#ea580c"
    elif any(x in sev for x in ["🟡", "Minor", "minor", "workaround"]):
        return "Minor", "#ca8a04"
    elif any(x in sev for x in ["💡", "Enhancement"]):
        return "Enhancement", "#2563eb"
    return "Unknown", "#6b7280"

def norm_status(st):
    if st == "Resolved":           return "Resolved",     "#16a34a"
    elif st == "Current Sprint":   return "In Progress",  "#2563eb"
    elif st == "Next Sprint":      return "Queued",       "#7c3aed"
    elif st in ("Not our team", "Not valid"): return "Closed/N/A", "#6b7280"
    return "Open", "#dc2626"


# ─── Source: Google Sheets ────────────────────────────────────────────────────

def fetch_sheet_issues(sheet_id, sheet_name="Form Responses 1"):
    """Fetch the beta feedback Google Sheet via the Sheets API."""
    try:
        from googleapiclient.discovery import build
        from google.oauth2 import service_account
    except ImportError:
        print("  ⚠ google-api-python-client not installed. Skipping Sheets.")
        return []

    cfg = load_config()
    creds_path = cfg.get("google_service_account_json")
    if not creds_path or not os.path.exists(creds_path):
        print("  ⚠ google_service_account_json not set in config.json. Skipping Sheets.")
        return []

    creds = service_account.Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    service = build("sheets", "v4", credentials=creds)
    result = service.spreadsheets().values().get(
        spreadsheetId=sheet_id, range=sheet_name
    ).execute()
    rows = result.get("values", [])
    if not rows:
        return []

    def gf(row, idx, default=""):
        try: return row[idx].strip() if idx < len(row) else default
        except: return default

    issues = []
    for row in rows[1:]:
        if not (row and len(row) > 5 and row[0].strip() and "/" in row[0]):
            continue
        sl, sc = norm_sev(gf(row, 4))
        stl, stc = norm_status(gf(row, 16))
        notes = gf(row, 18)
        eng = "See Work Item"
        conn = gf(row, 5)
        ct, pm = classify(conn)
        issues.append({
            "id": gf(row, 19) or f"SHEET-{len(issues)+1}",
            "date": gf(row, 0)[:12], "connector": conn,
            "connector_type": ct, "pm_owner": pm,
            "name": gf(row, 1), "company": gf(row, 2), "email": gf(row, 3),
            "severity_label": sl, "severity_color": sc,
            "status_label": stl, "status_color": stc,
            "engineer": eng, "case_id": "", "org_id": gf(row, 9),
            "description": gf(row, 6)[:800], "notes": notes[:300],
            "work_item": gf(row, 17), "source": "Google Sheet",
        })
    print(f"  ✓ Sheet: {len(issues)} issues")
    return issues


# ─── Source: Gmail ────────────────────────────────────────────────────────────

def fetch_email_issues(beta_email="datacloud-connectors-beta@salesforce.com", max_results=50):
    """Fetch emails to/from the beta alias via Gmail API."""
    try:
        from googleapiclient.discovery import build
        from google.oauth2 import service_account
    except ImportError:
        print("  ⚠ google-api-python-client not installed. Skipping Gmail.")
        return []

    cfg = load_config()
    creds_path = cfg.get("google_service_account_json")
    delegated_email = cfg.get("gmail_delegated_email")
    if not creds_path or not delegated_email:
        print("  ⚠ gmail_delegated_email not set in config.json. Skipping Gmail.")
        return []

    creds = service_account.Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        subject=delegated_email,
    )
    service = build("gmail", "v1", credentials=creds)
    query = f"to:{beta_email} OR from:{beta_email}"
    resp = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    messages = resp.get("messages", [])

    sev_color = {"Blocker": "#dc2626", "Major": "#ea580c", "Minor": "#ca8a04", "Enhancement": "#2563eb"}
    seen, issues = set(), []
    for m in messages:
        msg = service.users().messages().get(userId="me", id=m["id"], format="metadata",
            metadataHeaders=["Subject", "From", "Date"]).execute()
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        subject = headers.get("Subject", "")
        sender  = headers.get("From", "")
        date    = headers.get("Date", "")[:16]
        snippet = msg.get("snippet", "")

        norm = re.sub(r"^(re|fw|fwd):\s*", "", subject.lower()).strip()
        if norm in seen:
            continue
        seen.add(norm)

        connector = "Unknown"
        for kw, name in [
            ("sharepoint", "Microsoft SharePoint"), ("confluence", "Confluence"),
            ("mongodb", "MongoDB"), ("shopify", "Shopify"), ("dynamics", "Microsoft Dynamics 365"),
            ("azure sql", "Azure SQL Server"), ("ms sql", "Azure SQL Server"),
            ("google drive", "Google Drive"), ("ga4", "Google Analytics GA4"),
            ("google analytics", "Google Analytics"), ("adobe", "Adobe Commerce"),
            ("teams", "Microsoft Teams"), ("netsuite", "Oracle NetSuite"),
            ("fabric", "Microsoft Fabric"), ("databricks", "Databricks"),
            ("zendesk", "Zendesk"), ("hubspot", "HubSpot"),
        ]:
            if kw in subject.lower() or kw in snippet.lower():
                connector = name
                break

        subj_lower = subject.lower()
        if any(x in subj_lower for x in ["urgent", "blocker", "error", "failure", "failed"]):
            sl, sc = "Blocker", "#dc2626"
        elif any(x in subj_lower for x in ["issue", "problem", "not able", "unable"]):
            sl, sc = "Major", "#ea580c"
        else:
            sl, sc = "Minor", "#ca8a04"

        sf_engs = ["arsheen", "vasanthi", "sriram", "akash", "praveen", "anurag", "gaurav", "yamini"]
        eng = ""
        for e in sf_engs:
            if e in sender.lower():
                eng = sender.split("<")[0].strip()
                break
        stl = "In Progress" if (eng and "re:" in subject.lower()) else "Open"
        stc = "#2563eb" if stl == "In Progress" else "#dc2626"

        ct, pm = classify(connector)
        issues.append({
            "id": f"EMAIL-{m['id'][:8]}",
            "date": date[:10], "connector": connector,
            "connector_type": ct, "pm_owner": pm,
            "name": sender.split("<")[0].strip(), "company": "", "email": sender,
            "severity_label": sl, "severity_color": sl and sev_color.get(sl, "#6b7280"),
            "status_label": stl, "status_color": stc,
            "engineer": eng, "case_id": "", "org_id": "",
            "description": subject, "notes": snippet[:300],
            "work_item": "", "source": "Email",
        })
    print(f"  ✓ Gmail: {len(issues)} issues")
    return issues


# ─── Source: Slack ────────────────────────────────────────────────────────────

def fetch_slack_issues(channel_name="datacloud-connectors-beta-feedback", limit=50):
    """Fetch recent messages from the beta feedback Slack channel."""
    try:
        from slack_sdk import WebClient
        from slack_sdk.errors import SlackApiError
    except ImportError:
        print("  ⚠ slack-sdk not installed. Skipping Slack.")
        return []

    cfg = load_config()
    token = cfg.get("slack_bot_token")
    if not token:
        print("  ⚠ slack_bot_token not set in config.json. Skipping Slack.")
        return []

    client = WebClient(token=token)
    try:
        ch_resp = client.conversations_list(types="public_channel,private_channel", limit=200)
        channel = next((c for c in ch_resp["channels"] if c["name"] == channel_name), None)
        if not channel:
            print(f"  ⚠ Slack channel #{channel_name} not found.")
            return []
        history = client.conversations_history(channel=channel["id"], limit=limit)
    except SlackApiError as e:
        print(f"  ⚠ Slack error: {e.response['error']}")
        return []

    issues = []
    sev_color = {"Blocker": "#dc2626", "Major": "#ea580c", "Minor": "#ca8a04"}
    for msg in history.get("messages", []):
        text = msg.get("text", "")
        if not text or len(text) < 30:
            continue
        if any(kw in text.lower() for kw in ["error", "issue", "problem", "not working",
                                               "fails", "failure", "support case", "case #"]):
            connector = "Unknown"
            for kw, name in [
                ("sharepoint", "Microsoft SharePoint"), ("confluence", "Confluence"),
                ("mongodb", "MongoDB"), ("shopify", "Shopify"),
                ("google drive", "Google Drive"), ("adobe", "Adobe Commerce"),
                ("dynamics", "Microsoft Dynamics 365"), ("netsuite", "Oracle NetSuite"),
                ("ga4", "Google Analytics GA4"), ("google analytics", "Google Analytics"),
            ]:
                if kw in text.lower():
                    connector = name
                    break
            sl = "Blocker" if "urgent" in text.lower() or "blocker" in text.lower() else "Major"
            ct, pm = classify(connector)
            ts = msg.get("ts", "")
            date_str = datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d") if ts else ""
            issues.append({
                "id": f"SLACK-{ts[:8]}",
                "date": date_str, "connector": connector,
                "connector_type": ct, "pm_owner": pm,
                "name": msg.get("username", "Slack User"), "company": "", "email": "",
                "severity_label": sl, "severity_color": sev_color[sl],
                "status_label": "Open", "status_color": "#dc2626",
                "engineer": "", "case_id": "", "org_id": "",
                "description": text[:300], "notes": "",
                "work_item": "", "source": "Slack",
            })
    print(f"  ✓ Slack: {len(issues)} issues")
    return issues


# ─── GUS enrichment ───────────────────────────────────────────────────────────

def enrich_with_gus(issues, sf_cli="sf", sf_org="gus"):
    """Query GUS (Salesforce internal) for latest work item status."""
    gus_map = {}
    for issue in issues:
        url = issue.get("work_item", "")
        m = re.search(r"/ADM_Work__c/([a-zA-Z0-9]{15,18})/view", url)
        if m:
            gus_map[m.group(1)] = issue

    if not gus_map:
        print("  ✓ GUS: no linked work items to enrich")
        return issues

    ids = list(gus_map.keys())
    id_list = "', '".join(ids)
    soql = (
        f"SELECT Id, Name, Subject__c, Status__c, Priority__c, Type__c, "
        f"Assignee__r.Name, Sprint_Name__c, Story_Points__c, LastModifiedDate "
        f"FROM ADM_Work__c WHERE Id IN ('{id_list}') LIMIT 200"
    )
    try:
        result = subprocess.run(
            [sf_cli, "data", "query", "--target-org", sf_org, "--query", soql, "--json"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            print(f"  ⚠ GUS query failed: {result.stderr[:200]}")
            return issues
        data = json.loads(result.stdout)
        records = data.get("result", {}).get("records", [])
    except Exception as e:
        print(f"  ⚠ GUS error: {e}")
        return issues

    def gus_to_status(gus_status, gus_type, cur_status, cur_color):
        if (gus_type or "").lower() == "user story":
            return "New Feature Requested", "#6366f1"
        gs = gus_status.lower()
        if gs in ("closed", "fixed"):                           return "Closed",      "#16a34a"
        elif gs in ("in progress", "active", "in review", "qa"): return "In Progress","#2563eb"
        elif gs in ("new", "never", "scheduled", "triaged"):    return "Open",        "#dc2626"
        elif gs == "closed - not a bug":                        return "Closed/N/A",  "#6b7280"
        return cur_status, cur_color

    enriched = 0
    for rec in records:
        gus_id = rec["Id"]
        issue = gus_map.get(gus_id)
        if not issue:
            continue
        assignee = (rec.get("Assignee__r") or {}).get("Name", "")
        new_status, new_color = gus_to_status(
            rec.get("Status__c", ""), rec.get("Type__c", ""),
            issue["status_label"], issue["status_color"],
        )
        lmd = rec.get("LastModifiedDate", "")
        issue.update({
            "gus_id": gus_id,
            "gus_work_num": rec.get("Name", ""),
            "gus_status": rec.get("Status__c", ""),
            "gus_type": rec.get("Type__c", ""),
            "gus_assignee": assignee,
            "gus_subject": rec.get("Subject__c", ""),
            "gus_sprint": rec.get("Sprint_Name__c", ""),
            "gus_last_modified": lmd[:10] if lmd else "",
            "gus_status_color": new_color,
            "status_label": new_status,
            "status_color": new_color,
        })
        if assignee and assignee != "DCF India Team User":
            issue["engineer"] = assignee
        enriched += 1

    print(f"  ✓ GUS: enriched {enriched} of {len(gus_map)} linked issues")
    return issues


# ─── Config ───────────────────────────────────────────────────────────────────

def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Refresh Data Cloud Connectors Dashboard")
    parser.add_argument("--no-gus",  action="store_true", help="Skip GUS enrichment")
    parser.add_argument("--open",    action="store_true", help="Open dashboard in browser after build")
    parser.add_argument("--sf-cli",  default="sf",        help="Path to Salesforce CLI (default: sf)")
    parser.add_argument("--sf-org",  default="gus",       help="SF CLI org alias for GUS (default: gus)")
    args = parser.parse_args()

    cfg = load_config()
    sheet_id   = cfg.get("sheet_id", "1V2GOhpJmEy7WKTQAGpAD3fXVmBJadDg4FcsJeHusLmo")
    sheet_name = cfg.get("sheet_name", "Form Responses 1")

    print("\n📥  Fetching data sources...")
    sheet_issues = fetch_sheet_issues(sheet_id, sheet_name)
    email_issues = fetch_email_issues()
    slack_issues = fetch_slack_issues()

    all_issues = sheet_issues + email_issues + slack_issues
    print(f"\n📊  Total issues: {len(all_issues)}")

    if not args.no_gus:
        print("\n🔗  Enriching with GUS...")
        all_issues = enrich_with_gus(all_issues, sf_cli=args.sf_cli, sf_org=args.sf_org)

    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_PATH, "w") as f:
        json.dump(all_issues, f, indent=2)

    import shutil
    build_script = Path(__file__).parent / "build_connectors_dashboard.py"
    if build_script.exists():
        # Patch DATA_PATH and DASHBOARD_PATH in the builder to use repo-relative paths
        import importlib.util
        spec = importlib.util.spec_from_file_location("builder", build_script)
        builder = importlib.util.module_from_spec(spec)
        import sys as _sys
        orig_data = "/tmp/connectors_issues_data.json"
        orig_dash = os.path.expanduser("~/Connectors KT plan/datacloud-connectors-dashboard.html")
        # write data to the path the builder expects
        import shutil
        shutil.copy(DATA_PATH, orig_data)
        # Override output path
        os.environ["DASHBOARD_OUT"] = str(DASHBOARD_PATH)
        spec.loader.exec_module(builder)
        builder.DASHBOARD_PATH = str(DASHBOARD_PATH)
        builder.DATA_PATH = str(DATA_PATH)
        builder.main()
    else:
        print(f"⚠ build_connectors_dashboard.py not found at {build_script}")

    from collections import Counter
    counts = Counter(i["status_label"] for i in all_issues)
    blockers_no_eng = [i for i in all_issues
                       if i["severity_label"] == "Blocker"
                       and i["status_label"] == "Open"
                       and not i.get("engineer", "").strip()]
    print(f"\n✅  Dashboard built → {DASHBOARD_PATH}")
    print(f"   Status: {dict(counts)}")
    if blockers_no_eng:
        print(f"\n⚠  {len(blockers_no_eng)} open blocker(s) with no engineer:")
        for b in blockers_no_eng:
            print(f"   #{b['id']} | {b['connector']} | {b['description'][:70]}")

    if args.open:
        import webbrowser
        webbrowser.open(f"file://{DASHBOARD_PATH.resolve()}")

    print()


if __name__ == "__main__":
    main()
