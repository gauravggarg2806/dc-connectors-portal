#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Data Cloud Connectors Beta — Dashboard Builder
Reads issues from /tmp/connectors_issues_data.json (pre-enriched with GUS data),
builds the full interactive HTML dashboard.
Called by the /refresh-connectors-dashboard skill.
"""
import json
import csv
import io
import os
import sys
from datetime import datetime

DASHBOARD_PATH = os.path.expanduser("~/Connectors KT plan/datacloud-connectors-dashboard.html")
HEROKU_APP_DIR = os.path.expanduser("~/.claude/heroku-apps/dc-connectors-dash")
DATA_PATH = "/tmp/connectors_issues_data.json"

# Connector type mapping derived from connectivity_kt_guide.html
CONNECTOR_TYPE_MAP = {
    # Homegrown JDBC
    'databricks': 'Homegrown',
    'amazon rds mysql': 'Homegrown',
    'amazon rds sql server': 'Homegrown',
    'amazon rds postgresql': 'Homegrown',
    'amazon rds oracle': 'Homegrown',
    'amazon rds mariadb': 'Homegrown',
    'amazon aurora postgresql': 'Homegrown',
    'amazon aurora mysql': 'Homegrown',
    'azure postgresql': 'Homegrown',
    'azure mysql': 'Homegrown',
    'heroku postgresql': 'Homegrown',
    'jira': 'Homegrown',
    'amazon athena': 'Homegrown',
    'microsoft fabric': 'Homegrown',
    'ms fabric': 'Homegrown',
    'azure sql server': 'Homegrown',
    'service now': 'Homegrown',
    'servicenow': 'Homegrown',
    'b2c enterprise': 'Homegrown',
    'b2ce': 'Homegrown',
    # CData
    'ibm cloud object storage': 'CData',
    'ibm db2': 'CData',
    'ibm informix': 'CData',
    'google analytics': 'CData',
    'ga4': 'CData',
    'hubspot': 'CData',
    'linkedin': 'CData',
    'linkedin ads': 'CData',
    'sap concur': 'CData',
    'sap hana': 'CData',
    'sap': 'CData',
    'wordpress': 'CData',
    'zendesk': 'CData',
    'mongodb': 'CData',
    'shopify': 'CData',
    'odata': 'CData',
    'adobe analytics': 'CData',
    'adobe': 'CData',
    'confluence': 'CData',
    'instagram': 'CData',
    'salesforce platform events': 'CData',
    'platform events': 'CData',
    'azure cosmos db': 'CData',
    'cosmos db': 'CData',
    # WDC
    'sharepoint': 'WDC',
    'onedrive': 'WDC',
    'google drive': 'WDC',
    'google sheets': 'WDC',
    'excel online': 'WDC',
    'box': 'WDC',
    'dropbox': 'WDC',
}

# PM owner mapping: connector keyword → PM name
PM_OWNER_MAP = {
    # Gaurav Garg owns
    'databricks': 'Gaurav',
    'amazon rds': 'Gaurav',
    'amazon aurora': 'Gaurav',
    'azure postgresql': 'Gaurav',
    'azure mysql': 'Gaurav',
    'heroku postgresql': 'Gaurav',
    'amazon athena': 'Gaurav',
    'microsoft fabric': 'Gaurav',
    'ms fabric': 'Gaurav',
    'azure sql server': 'Gaurav',
    'ibm cloud object storage': 'Gaurav',
    'ibm db2': 'Gaurav',
    'ibm informix': 'Gaurav',
    'google analytics': 'Gaurav',
    'ga4': 'Gaurav',
    'hubspot': 'Gaurav',
    'service now': 'Gaurav',
    'servicenow': 'Gaurav',
    'zendesk': 'Gaurav',
    # Sriram Sethuraman owns
    'jira': 'Sriram',
    'linkedin': 'Sriram',
    'sap': 'Sriram',
    'wordpress': 'Sriram',
    'mongodb': 'Sriram',
    'shopify': 'Sriram',
    'odata': 'Sriram',
    'adobe': 'Sriram',
    # WDC / Vasanthi transitioning to Keshav
    'sharepoint': 'Vasanthi',
    'onedrive': 'Vasanthi',
    'google drive': 'Vasanthi',
    'google sheets': 'Vasanthi',
    'instagram': 'Vasanthi',
    'confluence': 'Vasanthi',
    'azure cosmos db': 'Vasanthi',
    'cosmos db': 'Vasanthi',
    'platform events': 'Vasanthi',
    # Arsheen
    'salesforce platform events': 'Arsheen',
    'b2c': 'Arsheen',
}


def classify_connector(connector_name):
    """Return (connector_type, pm_owner) for a connector name string."""
    if not connector_name:
        return 'Unknown', 'Unknown'
    c = connector_name.lower()
    conn_type = 'Unknown'
    for kw, t in CONNECTOR_TYPE_MAP.items():
        if kw in c:
            conn_type = t
            break
    pm = 'Unknown'
    for kw, p in PM_OWNER_MAP.items():
        if kw in c:
            pm = p
            break
    return conn_type, pm


def normalize_severity(sev):
    if any(x in sev for x in ['🚨', 'Blocker', 'blocker', 'unusable']):
        return 'Blocker', '#dc2626'
    elif any(x in sev for x in ['⚠', 'Major', 'major', 'core functionality']):
        return 'Major', '#ea580c'
    elif any(x in sev for x in ['🟡', 'Minor', 'minor', 'workaround']):
        return 'Minor', '#ca8a04'
    elif any(x in sev for x in ['💡', 'Enhancement']):
        return 'Enhancement', '#2563eb'
    return 'Unknown', '#6b7280'


def normalize_status(st):
    if st == 'Resolved':
        return 'Resolved', '#16a34a'
    elif st == 'Current Sprint':
        return 'In Progress', '#2563eb'
    elif st == 'Next Sprint':
        return 'Queued', '#7c3aed'
    elif st in ('Not our team', 'Not valid'):
        return 'Closed/N/A', '#6b7280'
    return 'Open', '#dc2626'


def parse_sheet_issues(csv_text):
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    if not rows:
        return []
    data_rows = [r for r in rows[1:] if r and len(r) > 5 and r[0].strip() and '/' in r[0]]

    def gf(row, idx, default=''):
        try:
            return row[idx].strip() if idx < len(row) else default
        except:
            return default

    issues = []
    for row in data_rows:
        sev_label, sev_color = normalize_severity(gf(row, 4))
        st_label, st_color = normalize_status(gf(row, 16))
        notes = gf(row, 18)
        engineer = 'See Work Item'
        for kw in ['working on it', 'is working', 'are working']:
            if kw in notes.lower():
                engineer = notes.split('.')[0]
                break
        connector = gf(row, 5)
        conn_type, pm_owner = classify_connector(connector)
        issues.append({
            'id': gf(row, 19) or f'SHEET-{len(issues)+1}',
            'date': gf(row, 0)[:12],
            'connector': connector,
            'connector_type': conn_type,
            'pm_owner': pm_owner,
            'name': gf(row, 1),
            'company': gf(row, 2),
            'email': gf(row, 3),
            'severity_label': sev_label,
            'severity_color': sev_color,
            'status_label': st_label,
            'status_color': st_color,
            'engineer': engineer,
            'case_id': '',
            'org_id': gf(row, 9),
            'description': gf(row, 6)[:800],
            'notes': notes[:300],
            'work_item': gf(row, 17),
            'source': 'Google Sheet'
        })
    return issues


def build_email_issues(gmail_results):
    """
    Parse Gmail search results (list of dicts with subject/sender/date/snippet/id)
    and produce structured issue records.
    """
    issues = []
    seen_subjects = set()
    for msg in gmail_results:
        subject = msg.get('subject', '')
        sender = msg.get('sender', '')
        date = msg.get('date', '')
        snippet = msg.get('snippet', '')
        msg_id = msg.get('id', '')

        # Deduplicate by normalized subject
        norm = subject.lower().replace('re: ', '').replace('re:', '').strip()
        if norm in seen_subjects:
            continue
        seen_subjects.add(norm)

        # Detect connector
        connector = 'Unknown'
        connectors_map = [
            ('sap hana', 'SAP HANA Connector'),
            ('ga4', 'GA4 Data Cloud Connector'),
            ('confluence', 'Confluence Beta Connector'),
            ('cosmos db', 'Azure Cosmos DB (Beta) Connector'),
            ('platform events', 'Salesforce Platform Events Beta Connector'),
            ('instagram', 'Instagram Beta Connector'),
            ('shopify', 'Shopify Connector'),
            ('sharepoint structured', 'SharePoint Structured Connector'),
            ('sharepoint', 'SharePoint Connector'),
            ('odata', 'OData Connector (Beta)'),
            ('hubspot', 'HubSpot Connector'),
            ('databricks', 'Databricks Connector (Beta)'),
            ('fabric', 'Microsoft Fabric Beta Connector'),
            ('mongodb', 'MongoDB Connector (Beta)'),
            ('google drive', 'Google Drive Connector (Beta)'),
            ('azure', 'Azure Connector'),
            ('zendesk', 'Zendesk Connector'),
        ]
        subj_lower = subject.lower()
        for kw, name in connectors_map:
            if kw in subj_lower or kw in snippet.lower():
                connector = name
                break

        # Severity heuristic
        if any(x in subj_lower for x in ['urgent', 'blocker', 'critical', 'error', 'failure', 'failed', 'timeout']):
            sev_label, sev_color = 'Blocker', '#dc2626'
        elif any(x in subj_lower for x in ['issue', 'problem', 'not able', 'unable']):
            sev_label, sev_color = 'Major', '#ea580c'
        elif any(x in subj_lower for x in ['question', 'inquiry', 'roadmap', 'request']):
            sev_label, sev_color = 'Minor', '#ca8a04'
        else:
            sev_label, sev_color = 'Major', '#ea580c'

        # Status heuristic
        sf_engineers = ['arsheen', 'vasanthi', 'sriram', 'praveen', 'anurag', 'danny', 'mridul', 'akash', 'poorva', 'jashan']
        engineer = 'Pending Assignment'
        snippet_lower = snippet.lower()
        for eng in sf_engineers:
            if eng in sender.lower() or eng in snippet_lower:
                engineer = sender.split('<')[0].strip() if '<' in sender else sender
                break

        has_reply = subject.lower().startswith('re:')
        if has_reply and any(e in snippet_lower for e in sf_engineers):
            st_label, st_color = 'In Progress', '#2563eb'
        else:
            st_label, st_color = 'Open', '#dc2626'

        # Parse date
        date_str = date[:10] if date else ''

        # Extract case ID
        import re
        case_match = re.search(r'#?(\d{9,})', subject + ' ' + snippet)
        case_id = case_match.group(1) if case_match else ''

        conn_type, pm_owner = classify_connector(connector)
        issues.append({
            'id': f'EMAIL-{msg_id[:8]}',
            'date': date_str,
            'connector': connector,
            'connector_type': conn_type,
            'pm_owner': pm_owner,
            'name': msg.get('sender_name', sender.split('<')[0].strip()),
            'company': '',
            'email': sender,
            'severity_label': sev_label,
            'severity_color': sev_color,
            'status_label': st_label,
            'status_color': st_color,
            'engineer': engineer,
            'case_id': case_id,
            'org_id': '',
            'description': f"Subject: {subject}\n\n{snippet}",
            'notes': f"Gmail ID: {msg_id}",
            'work_item': '',
            'source': 'Email'
        })
    return issues


HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Data Cloud Connectors Beta — Issues Dashboard</title>
<style>
  :root {
    --bg: #0f1117; --surface: #1a1d27; --surface2: #22263a;
    --border: #2e3250; --text: #e2e8f0; --muted: #8892a4;
    --accent: #6366f1; --red: #dc2626; --orange: #ea580c;
    --yellow: #ca8a04; --green: #16a34a; --blue: #2563eb;
    --purple: #7c3aed; --gray: #6b7280; --teal: #0891b2;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 14px; line-height: 1.6; }
  .header { background: linear-gradient(135deg,#1a1d27 0%,#22263a 100%); border-bottom: 1px solid var(--border); padding: 20px 32px; display: flex; justify-content: space-between; align-items: center; position: sticky; top: 0; z-index: 100; }
  .header h1 { font-size: 20px; font-weight: 700; color: #fff; }
  .header h1 span { color: var(--accent); }
  .header-meta { display: flex; align-items: center; gap: 16px; }
  .last-updated { font-size: 12px; color: var(--muted); }
  .refresh-btn { background: var(--accent); color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 600; display: flex; align-items: center; gap: 6px; transition: opacity .2s; }
  .refresh-btn:hover { opacity: .85; }
  .sources-badge { background: var(--surface2); border: 1px solid var(--border); color: var(--muted); font-size: 11px; padding: 4px 10px; border-radius: 4px; }
  .main { padding: 24px 32px; max-width: 1800px; margin: 0 auto; }
  .section-title { font-size: 13px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .08em; margin-bottom: 12px; }
  .summary-grid { display: grid; grid-template-columns: repeat(6,1fr); gap: 12px; margin-bottom: 28px; }
  .stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px; text-align: center; transition: border-color .2s,transform .1s; cursor: pointer; }
  .stat-card:hover { border-color: var(--accent); transform: translateY(-1px); }
  .stat-card.active { border-color: var(--accent); background: #1e2235; }
  .stat-num { font-size: 32px; font-weight: 800; line-height: 1; margin-bottom: 4px; }
  .stat-label { font-size: 11px; color: var(--muted); font-weight: 500; text-transform: uppercase; letter-spacing: .06em; }
  .type-matrix { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 20px; margin-bottom: 28px; }
  .type-matrix h3 { font-size: 13px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; margin-bottom: 14px; }
  .type-matrix table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .type-matrix th { background: var(--surface2); color: var(--muted); font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; padding: 8px 12px; text-align: center; border: 1px solid var(--border); }
  .type-matrix th:first-child { text-align: left; }
  .type-matrix td { padding: 10px 12px; border: 1px solid var(--border); text-align: center; font-weight: 700; font-size: 15px; cursor: pointer; transition: background .15s; }
  .type-matrix td:first-child { text-align: left; font-size: 13px; font-weight: 600; color: var(--text); }
  .type-matrix td.cell-open { color: #f87171; }
  .type-matrix td.cell-inprog { color: #60a5fa; }
  .type-matrix td.cell-closed { color: #4ade80; }
  .type-matrix td.cell-total { color: #818cf8; }
  .type-matrix td.cell-pct { min-width: 110px; }
  .type-matrix tr:hover > td { background: var(--surface2); }
  .type-matrix tfoot td { background: var(--surface2); font-size:12px; font-weight:700; border-top: 2px solid var(--border); }
  .type-badge-cdata { display: inline-block; background: rgba(37,99,235,.15); color: #60a5fa; border: 1px solid rgba(37,99,235,.3); padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; }
  .type-badge-homegrown { display: inline-block; background: rgba(124,58,237,.15); color: #a78bfa; border: 1px solid rgba(124,58,237,.3); padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; }
  .type-badge-wdc { display: inline-block; background: rgba(234,88,12,.15); color: #fb923c; border: 1px solid rgba(234,88,12,.3); padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; }
  .type-badge-unknown { display: inline-block; background: rgba(107,114,128,.15); color: #9ca3af; border: 1px solid rgba(107,114,128,.3); padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; }
  .breakdown-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 28px; }
  .breakdown-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 20px; }
  .breakdown-card h3 { font-size: 13px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; margin-bottom: 14px; }
  .bar-item { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
  .bar-label { width: 260px; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--text); display:flex; align-items:center; gap:5px; }
  .bar-track { flex: 1; height: 8px; background: var(--surface2); border-radius: 4px; overflow: hidden; }
  .bar-fill { height: 100%; border-radius: 4px; transition: width .5s ease; }
  .bar-count { width: 24px; text-align: right; font-size: 12px; color: var(--muted); }
  .filter-bar { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-bottom: 20px; }
  .filter-bar input { background: var(--surface); border: 1px solid var(--border); color: var(--text); padding: 8px 14px; border-radius: 8px; font-size: 13px; width: 280px; outline: none; }
  .filter-bar input:focus { border-color: var(--accent); }
  .filter-group { display: flex; gap: 6px; flex-wrap: wrap; }
  .filter-btn { background: var(--surface); border: 1px solid var(--border); color: var(--muted); padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; font-weight: 500; transition: all .15s; white-space: nowrap; }
  .filter-btn:hover { border-color: var(--accent); color: var(--text); }
  .filter-btn.active { color: white; }
  .filter-btn[data-status="all"].active { background: var(--accent); border-color: var(--accent); }
  .filter-btn[data-status="Open"].active,.filter-btn[data-sev="Blocker"].active { background: var(--red); border-color: var(--red); }
  .filter-btn[data-status="In Progress"].active { background: var(--blue); border-color: var(--blue); }
  .filter-btn[data-status="Queued"].active { background: var(--purple); border-color: var(--purple); }
  .filter-btn[data-status="Resolved"].active { background: var(--green); border-color: var(--green); }
  .filter-btn[data-status="Closed/N/A"].active { background: var(--gray); border-color: var(--gray); }
  .filter-btn[data-status="Closed"].active { background: var(--green); border-color: var(--green); }
  .filter-btn[data-status="New Feature Requested"].active { background: var(--accent); border-color: var(--accent); }
  .filter-btn[data-sev="Major"].active { background: var(--orange); border-color: var(--orange); }
  .filter-btn[data-sev="Minor"].active { background: var(--yellow); border-color: var(--yellow); }
  .filter-btn[data-gus="true"].active { background: var(--teal); border-color: var(--teal); }
  .filter-btn[data-type="Structured"].active { background: #0f766e; border-color: #0f766e; }
  .filter-btn[data-type="Unstructured"].active { background: #7c3aed; border-color: #7c3aed; }
  .filter-btn[data-ctype="CData"].active { background: var(--blue); border-color: var(--blue); }
  .filter-btn[data-ctype="Homegrown"].active { background: var(--purple); border-color: var(--purple); }
  .filter-btn[data-ctype="WDC"].active { background: var(--orange); border-color: var(--orange); }
  .filter-btn[data-pm].active { background: #0e7490; border-color: #0e7490; }
  .sort-select { background: var(--surface); border: 1px solid var(--border); color: var(--text); padding: 6px 10px; border-radius: 6px; font-size: 12px; cursor: pointer; margin-left: auto; }
  .issues-count { font-size: 12px; color: var(--muted); margin-bottom: 10px; }
  .issues-table { width: 100%; border-collapse: collapse; }
  .issues-table th { background: var(--surface2); color: var(--muted); font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--border); position: sticky; top: 64px; z-index: 5; }
  .issues-table td { padding: 12px 14px; border-bottom: 1px solid var(--border); vertical-align: top; }
  .issues-table tr:hover > td { background: var(--surface2); }
  .issue-row { cursor: pointer; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
  .badge-red { background: rgba(220,38,38,.15); color: #f87171; border: 1px solid rgba(220,38,38,.3); }
  .badge-orange { background: rgba(234,88,12,.15); color: #fb923c; border: 1px solid rgba(234,88,12,.3); }
  .badge-yellow { background: rgba(202,138,4,.15); color: #facc15; border: 1px solid rgba(202,138,4,.3); }
  .badge-green { background: rgba(22,163,74,.15); color: #4ade80; border: 1px solid rgba(22,163,74,.3); }
  .badge-blue { background: rgba(37,99,235,.15); color: #60a5fa; border: 1px solid rgba(37,99,235,.3); }
  .badge-purple { background: rgba(124,58,237,.15); color: #a78bfa; border: 1px solid rgba(124,58,237,.3); }
  .badge-gray { background: rgba(107,114,128,.15); color: #9ca3af; border: 1px solid rgba(107,114,128,.3); }
  .badge-indigo { background: rgba(99,102,241,.15); color: #818cf8; border: 1px solid rgba(99,102,241,.3); }
  .badge-teal { background: rgba(8,145,178,.15); color: #22d3ee; border: 1px solid rgba(8,145,178,.3); }
  .source-tag { font-size: 10px; color: var(--muted); background: var(--surface2); border: 1px solid var(--border); border-radius: 3px; padding: 1px 5px; margin-left: 4px; }
  .gus-link { font-size: 11px; color: #22d3ee; text-decoration: none; font-family: monospace; font-weight: 600; }
  .gus-link:hover { text-decoration: underline; }
  .gus-closed { color: #4ade80; }
  .gus-open { color: #f87171; }
  .gus-progress { color: #60a5fa; }
  .gus-waiting { color: #facc15; }
  .detail-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.6); z-index: 200; backdrop-filter: blur(3px); }
  .detail-overlay.open { display: flex; align-items: flex-start; justify-content: flex-end; }
  .detail-panel { background: var(--surface); border-left: 1px solid var(--border); width: 620px; max-width: 95vw; height: 100vh; overflow-y: auto; animation: slideIn .2s ease; }
  @keyframes slideIn { from { transform: translateX(40px); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
  .detail-header { padding: 20px 24px; border-bottom: 1px solid var(--border); background: var(--surface2); position: sticky; top: 0; z-index: 10; }
  .detail-header-top { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; }
  .detail-id { font-size: 11px; color: var(--muted); font-family: monospace; }
  .close-btn { background: none; border: none; color: var(--muted); cursor: pointer; font-size: 20px; line-height: 1; padding: 2px; transition: color .15s; }
  .close-btn:hover { color: var(--text); }
  .detail-title { font-size: 16px; font-weight: 700; color: #fff; line-height: 1.3; }
  .detail-meta { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
  .detail-body { padding: 20px 24px; }
  .detail-section { margin-bottom: 20px; }
  .detail-section-title { font-size: 11px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .08em; margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px solid var(--border); }
  .detail-section-title.gus { color: #22d3ee; border-color: rgba(8,145,178,.3); }
  .detail-row { display: flex; gap: 12px; margin-bottom: 8px; }
  .detail-key { font-size: 12px; color: var(--muted); width: 110px; flex-shrink: 0; font-weight: 500; }
  .detail-val { font-size: 13px; color: var(--text); flex: 1; word-break: break-word; }
  .detail-val a { color: var(--accent); text-decoration: none; }
  .detail-val a.gus-ticket-link { color: #22d3ee; }
  .detail-val a:hover { text-decoration: underline; }
  .detail-desc { background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; font-size: 13px; line-height: 1.7; white-space: pre-wrap; color: var(--text); }
  .gus-box { background: rgba(8,145,178,.07); border: 1px solid rgba(8,145,178,.25); border-radius: 8px; padding: 14px 16px; }
  .days-badge { background: rgba(99,102,241,.15); color: #818cf8; border: 1px solid rgba(99,102,241,.3); border-radius: 4px; padding: 2px 8px; font-size: 12px; font-weight: 600; }
  .no-results { text-align: center; color: var(--muted); padding: 48px 20px; font-size: 14px; }
  @media (max-width:1200px) { .summary-grid { grid-template-columns: repeat(4,1fr); } }
  @media (max-width:900px) { .breakdown-grid { grid-template-columns: 1fr; } .summary-grid { grid-template-columns: repeat(3,1fr); } .main { padding: 16px; } }
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>Data Cloud Connectors Beta &nbsp;<span>Issue Dashboard</span></h1>
    <div class="last-updated">Sources: gauravgarg@salesforce.com · Google Sheets tracker · #datacloud-connectors-beta-feedback · GUS</div>
  </div>
  <div class="header-meta">
    <span class="sources-badge">Last refreshed: BUILD_TIMESTAMP</span>
    <button class="refresh-btn" onclick="location.reload()">&#8635; Refresh</button>
  </div>
</div>
<div class="main">
  <div class="section-title">Summary Overview</div>
  <div class="summary-grid" id="summaryGrid">
    <div class="stat-card active" data-filter="all" onclick="filterByStatus('all',this)">
      <div class="stat-num" style="color:#818cf8" id="total">—</div>
      <div class="stat-label">Total Issues</div>
    </div>
    <div class="stat-card" data-filter="Active" onclick="filterByStatus('Active',this)">
      <div class="stat-num" style="color:#f87171" id="active">—</div>
      <div class="stat-label">Active (Open + In Progress)</div>
    </div>
    <div class="stat-card" data-filter="Resolved" onclick="filterByStatus('Resolved',this)">
      <div class="stat-num" style="color:#4ade80" id="resolved">—</div>
      <div class="stat-label">Resolved / Closed</div>
    </div>
    <div class="stat-card" data-filter-sev="Blocker" onclick="filterBySev('Blocker',this)">
      <div class="stat-num" style="color:#f87171" id="blockers">—</div>
      <div class="stat-label">Blockers</div>
    </div>
    <div class="stat-card" data-filter-gus="true" onclick="filterByGus(this)">
      <div class="stat-num" style="color:#22d3ee" id="gus_linked">—</div>
      <div class="stat-label">GUS Linked</div>
    </div>
  </div>
  <div class="type-matrix">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;flex-wrap:wrap;gap:10px">
      <h3 style="margin-bottom:0">Issues by Connector Type &amp; Status</h3>
      <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
        <span style="font-size:11px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.06em">Filter by PM:</span>
        <button class="filter-btn" id="mtx-pm-all" style="font-size:11px;padding:3px 9px" onclick="filterMatrixByPm('all',this)">All</button>
        <button class="filter-btn" id="mtx-pm-Arsheen+Sriram" style="font-size:11px;padding:3px 9px" onclick="filterMatrixByPm('Arsheen+Sriram',this)">Arsheen + Sriram</button>
        <button class="filter-btn" id="mtx-pm-Vasanthi+Gaurav" style="font-size:11px;padding:3px 9px" onclick="filterMatrixByPm('Vasanthi+Gaurav',this)">Vasanthi + Gaurav</button>
        <button class="filter-btn" id="mtx-pm-Krassimira" style="font-size:11px;padding:3px 9px" onclick="filterMatrixByPm('Krassimira',this)">Krassimira</button>
        <button class="filter-btn" id="mtx-pm-Sasha" style="font-size:11px;padding:3px 9px" onclick="filterMatrixByPm('Sasha',this)">Sasha</button>
        <button class="filter-btn" id="mtx-pm-Vijay" style="font-size:11px;padding:3px 9px" onclick="filterMatrixByPm('Vijay',this)">Vijay</button>
      </div>
    </div>
    <table id="typeMatrixTable">
      <thead><tr>
        <th>Type</th>
        <th style="color:#f87171">Active (Open + In Progress)</th>
        <th style="color:#4ade80">Resolved / Closed</th>
        <th style="color:#818cf8">Total</th>
        <th style="color:#f87171">% Active</th>
      </tr></thead>
      <tbody id="typeMatrixBody"></tbody>
      <tfoot id="typeMatrixFoot"></tfoot>
    </table>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:28px">
    <div class="breakdown-card"><h3>Top Connectors by Issue Count</h3><div id="connectorBars"></div></div>
    <div class="breakdown-card">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;flex-wrap:wrap;gap:8px">
        <h3 style="margin-bottom:0">Issues by Connector Type</h3>
        <div style="display:flex;gap:5px;flex-wrap:wrap" id="donutStatusBtns">
          <button class="filter-btn active" style="font-size:11px;padding:3px 9px;background:var(--accent);border-color:var(--accent);color:#fff" onclick="buildTypeDonut('all',this)">All</button>
          <button class="filter-btn" style="font-size:11px;padding:3px 9px" onclick="buildTypeDonut('Active',this)">Active</button>
          <button class="filter-btn" style="font-size:11px;padding:3px 9px" onclick="buildTypeDonut('Resolved',this)">Resolved / Closed</button>
        </div>
      </div>
      <div style="display:flex;align-items:center;gap:28px;justify-content:center;padding:8px 0">
        <div style="position:relative;width:160px;height:160px;flex-shrink:0">
          <canvas id="typeDonut" width="160" height="160"></canvas>
          <div id="donutCenter" style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;pointer-events:none">
            <div style="font-size:28px;font-weight:800;color:#fff" id="donutTotal">—</div>
            <div style="font-size:11px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.05em" id="donutLabel">Total</div>
          </div>
        </div>
        <div id="donutLegend" style="display:flex;flex-direction:column;gap:10px;min-width:160px"></div>
      </div>
    </div>
  </div>
  <div class="section-title">Issue Details</div>
  <div class="filter-bar">
    <input type="text" id="searchInput" placeholder="Search connector, company, reporter, GUS ticket..." oninput="applyFilters()">
    <div class="filter-group" id="statusFilters">
      <button class="filter-btn active" data-status="all" onclick="filterByStatus('all',this)">All</button>
      <button class="filter-btn" data-status="Active" onclick="filterByStatus('Active',this)">Active</button>
      <button class="filter-btn" data-status="Resolved" onclick="filterByStatus('Resolved',this)">Resolved</button>
      <button class="filter-btn" data-status="Closed/N/A" onclick="filterByStatus('Closed/N/A',this)">Closed/N/A</button>
      <button class="filter-btn" data-status="Closed" onclick="filterByStatus('Closed',this)">Closed (GUS)</button>
      <button class="filter-btn" data-status="New Feature Requested" onclick="filterByStatus('New Feature Requested',this)">New Feature Requested</button>
    </div>
    <div class="filter-group" id="sevFilters">
      <button class="filter-btn" data-sev="Blocker" onclick="filterBySev('Blocker',this)">Blocker</button>
      <button class="filter-btn" data-sev="Major" onclick="filterBySev('Major',this)">Major</button>
      <button class="filter-btn" data-sev="Minor" onclick="filterBySev('Minor',this)">Minor</button>
    </div>
    <div class="filter-group" id="connTypeFilters">
      <span style="font-size:11px;color:var(--muted);margin-right:2px">TYPE:</span>
      <button class="filter-btn" data-ctype="CData" onclick="filterByConnType('CData',this)">CData</button>
      <button class="filter-btn" data-ctype="Homegrown" onclick="filterByConnType('Homegrown',this)">Homegrown</button>
      <button class="filter-btn" data-ctype="WDC" onclick="filterByConnType('WDC',this)">WDC</button>
    </div>
    <div class="filter-group" id="pmFilters">
      <span style="font-size:11px;color:var(--muted);margin-right:2px">PM:</span>
      <button class="filter-btn" data-pm="Arsheen+Sriram" onclick="filterByPm('Arsheen+Sriram',this)">Arsheen + Sriram</button>
      <button class="filter-btn" data-pm="Vasanthi+Gaurav" onclick="filterByPm('Vasanthi+Gaurav',this)">Vasanthi + Gaurav</button>
      <button class="filter-btn" data-pm="Krassimira" onclick="filterByPm('Krassimira',this)">Krassimira</button>
      <button class="filter-btn" data-pm="Sasha" onclick="filterByPm('Sasha',this)">Sasha</button>
      <button class="filter-btn" data-pm="Vijay" onclick="filterByPm('Vijay',this)">Vijay</button>
    </div>
    <div class="filter-group" id="gusFilters">
      <button class="filter-btn" data-gus="true" onclick="filterByGus(this)">GUS Linked</button>
    </div>
    <div class="filter-group" id="typeFilters">
      <button class="filter-btn" data-type="Structured" onclick="filterByType('Structured',this)">Structured</button>
      <button class="filter-btn" data-type="Unstructured" onclick="filterByType('Unstructured',this)">Unstructured</button>
    </div>
    <select class="sort-select" onchange="applyFilters()">
      <option value="date-desc">Newest First</option>
      <option value="date-asc">Oldest First</option>
      <option value="sev">By Severity</option>
      <option value="status">By Status</option>
      <option value="connector">By Connector</option>
      <option value="gus-status">By GUS Status</option>
    </select>
  </div>
  <div class="issues-count" id="issueCount"></div>
  <table class="issues-table">
    <thead><tr>
      <th style="width:100px">ID / Date</th>
      <th style="width:170px">Connector</th>
      <th style="width:90px">Type</th>
      <th style="width:80px">PM</th>
      <th style="width:80px">Severity</th>
      <th style="width:95px">Status</th>
      <th style="width:150px">Reporter / Company</th>
      <th style="width:130px">Engineer</th>
      <th style="width:120px">GUS Ticket</th>
      <th style="width:90px">GUS Status</th>
      <th style="width:55px">Days Open</th>
      <th style="min-width:160px">Description</th>
    </tr></thead>
    <tbody id="issuesTbody"></tbody>
  </table>
  <div class="no-results" id="noResults" style="display:none">No issues match your filter.</div>
</div>
<div class="detail-overlay" id="detailOverlay" onclick="closeDetail(event)">
  <div class="detail-panel" id="detailPanel">
    <div class="detail-header">
      <div class="detail-header-top">
        <span class="detail-id" id="dId"></span>
        <button class="close-btn" onclick="closeDetail()">×</button>
      </div>
      <div class="detail-title" id="dTitle"></div>
      <div class="detail-meta" id="dMeta"></div>
    </div>
    <div class="detail-body" id="dBody"></div>
  </div>
</div>
<script>
const ISSUES = ISSUES_JSON_PLACEHOLDER;
let activeStatus='all', activeSev=null, activeGus=false, activeType=null, activeConnType=null, activePm=null, searchTerm='';
function isUnstructured(c){return/unstructured|site pages|site assets/i.test(c||'');}
function connTypeBadge(t){const m={CData:'type-badge-cdata',Homegrown:'type-badge-homegrown',WDC:'type-badge-wdc',Unknown:'type-badge-unknown'};return`<span class="${m[t]||'type-badge-unknown'}">${t||'?'}</span>`;}
function pctOpenBar(open,tot){
  if(!tot)return'—';
  const pct=Math.round(open/tot*100);
  const col=pct>60?'#f87171':pct>30?'#fb923c':'#4ade80';
  return`<div style="display:flex;align-items:center;gap:6px"><div style="flex:1;height:6px;background:var(--surface2);border-radius:3px;overflow:hidden;min-width:50px"><div style="width:${pct}%;height:100%;background:${col};border-radius:3px;transition:width .4s"></div></div><span style="font-size:12px;font-weight:700;color:${col};width:36px;text-align:right">${pct}%</span></div>`;
}
function buildTypeMatrix(pmFilter){
  pmFilter=pmFilter||'all';
  const types=['CData','Homegrown','WDC','Unknown'];
  let totAct=0,totRes=0,totAll=0;
  const rows=types.map(t=>{
    const subset=ISSUES.filter(i=>(i.connector_type||'Unknown')===t&&pmMatch(pmFilter,i));
    const act=subset.filter(isActive).length;
    const res=subset.filter(isClosed).length;
    const tot=subset.length;
    if(!tot)return'';
    totAct+=act;totRes+=res;totAll+=tot;
    return`<tr><td onclick="filterByConnType('${t}',null)">${connTypeBadge(t)}</td><td class="cell-open" onclick="filterByConnTypeAndStatus('${t}','Active')">${act||'—'}</td><td class="cell-closed" onclick="filterByConnTypeAndStatus('${t}','Resolved')">${res||'—'}</td><td class="cell-total">${tot}</td><td class="cell-pct">${pctOpenBar(act,tot)}</td></tr>`;
  }).filter(Boolean);
  document.getElementById('typeMatrixBody').innerHTML=rows.join('');
  document.getElementById('typeMatrixFoot').innerHTML=`<tr><td style="color:var(--muted);font-size:12px">All Types</td><td class="cell-open">${totAct||'—'}</td><td class="cell-closed">${totRes||'—'}</td><td class="cell-total">${totAll}</td><td class="cell-pct">${pctOpenBar(totAct,totAll)}</td></tr>`;
}
function buildTypeDonut(statusFilter,el){
  statusFilter=statusFilter||'all';
  // Update button active states
  document.querySelectorAll('#donutStatusBtns .filter-btn').forEach(b=>{b.classList.remove('active');b.style.background='';b.style.borderColor='';b.style.color='';});
  if(el){el.classList.add('active');el.style.background='var(--accent)';el.style.borderColor='var(--accent)';el.style.color='#fff';}
  const statusBtnColors={'Open':'#dc2626','In Progress':'#2563eb','Queued':'#7c3aed','Resolved':'#16a34a','Closed':'#16a34a'};
  if(el&&statusFilter!=='all'){el.style.background=statusBtnColors[statusFilter]||'var(--accent)';el.style.borderColor=statusBtnColors[statusFilter]||'var(--accent)';}
  const types=['CData','Homegrown','WDC','Unknown'];
  const typeColors={'CData':'#3b82f6','Homegrown':'#a78bfa','WDC':'#fb923c','Unknown':'#6b7280'};
  const matchStatus=i=>statusFilter==='all'||(statusFilter==='Active'?isActive(i):statusFilter==='Resolved'?isClosed(i):i.status_label===statusFilter);
  const counts=types.map(t=>ISSUES.filter(i=>(i.connector_type||'Unknown')===t&&matchStatus(i)).length);
  const total=counts.reduce((a,b)=>a+b,0);
  document.getElementById('donutTotal').textContent=total||'0';
  const labelMap={'all':'Total','Active':'Active','Resolved':'Resolved/Closed'};
  document.getElementById('donutLabel').textContent=labelMap[statusFilter]||statusFilter;
  const canvas=document.getElementById('typeDonut');
  const ctx=canvas.getContext('2d');
  const cx=80,cy=80,r=70,inner=44;
  ctx.clearRect(0,0,160,160);
  if(!total){
    ctx.beginPath();ctx.arc(cx,cy,r,0,2*Math.PI);ctx.fillStyle='#22263a';ctx.fill();
    ctx.beginPath();ctx.arc(cx,cy,inner,0,2*Math.PI);ctx.fillStyle='#1a1d27';ctx.fill();
  } else {
    let angle=-Math.PI/2;
    types.forEach((t,i)=>{
      if(!counts[i])return;
      const slice=2*Math.PI*(counts[i]/total);
      ctx.beginPath();ctx.moveTo(cx,cy);ctx.arc(cx,cy,r,angle,angle+slice);ctx.closePath();
      ctx.fillStyle=typeColors[t];ctx.fill();
      angle+=slice;
    });
    ctx.beginPath();ctx.arc(cx,cy,inner,0,2*Math.PI);ctx.fillStyle='#1a1d27';ctx.fill();
  }
  document.getElementById('donutLegend').innerHTML=types.map((t,i)=>{
    const pct=total?Math.round(counts[i]/total*100):0;
    const dimmed=!counts[i];
    const ofLabel={'all':'total','Active':'active','Resolved':'resolved/closed'};
    return`<div style="display:flex;align-items:center;gap:8px;cursor:pointer;opacity:${dimmed?.35:1}" onclick="filterByConnTypeAndDonut('${t}','${statusFilter}')"><div style="width:10px;height:10px;border-radius:2px;background:${typeColors[t]};flex-shrink:0"></div><div><div style="font-size:12px;font-weight:600;color:var(--text)">${t} <span style="color:var(--muted);font-weight:400">(${counts[i]})</span></div><div style="font-size:11px;color:var(--muted)">${pct}% of ${ofLabel[statusFilter]||statusFilter.toLowerCase()}</div></div></div>`;
  }).join('');
}
function filterByConnTypeAndDonut(ctype,status){
  activeConnType=ctype;
  if(status!=='all'){activeStatus=status;}
  document.querySelectorAll('#connTypeFilters .filter-btn').forEach(b=>b.classList.remove('active'));
  const ctBtn=document.querySelector(`#connTypeFilters .filter-btn[data-ctype="${ctype}"]`);ctBtn?.classList.add('active');
  if(status!=='all'){
    document.querySelectorAll('#statusFilters .filter-btn').forEach(b=>b.classList.remove('active'));
    const stBtn=document.querySelector(`#statusFilters .filter-btn[data-status="${status}"]`);stBtn?.classList.add('active');
  }
  renderTable();
  document.getElementById('issuesTbody').scrollIntoView({behavior:'smooth',block:'nearest'});
}

function parseDateStr(s){if(!s)return null;const m=s.match(/(\d+)\/(\d+)\/(\d+)/);if(!m)return null;return new Date(parseInt(m[3]),parseInt(m[1])-1,parseInt(m[2]));}
function daysAgo(d){const p=parseDateStr(d);if(!p)return null;return Math.floor((new Date()-p)/86400000);}
function daysLabel(n){if(n===null)return'—';if(n===0)return'Today';if(n===1)return'1 day';return n+' days';}
function sevBadge(l){const m={Blocker:'badge-red',Major:'badge-orange',Minor:'badge-yellow',Enhancement:'badge-blue',Unknown:'badge-gray'};return`<span class="badge ${m[l]||'badge-gray'}">${l}</span>`;}
function statusBadge(l){const m={Open:'badge-red','In Progress':'badge-blue',Queued:'badge-purple',Resolved:'badge-green','Closed/N/A':'badge-gray','Closed':'badge-green','New Feature Requested':'badge-indigo'};return`<span class="badge ${m[l]||'badge-gray'}">${l}</span>`;}
function gusBadge(s,type){if(!s)return'<span style="color:var(--muted);font-size:11px">—</span>';if((type||'').toLowerCase()==='user story')return`<span class="badge badge-indigo">User Story</span>`;const lc=s.toLowerCase();let cls='badge-gray';if(lc==='closed'||lc==='fixed')cls='badge-green';else if(['in progress','active','in review','qa'].includes(lc))cls='badge-blue';else if(['new','never','triaged','scheduled'].includes(lc))cls='badge-red';else if(lc==='waiting')cls='badge-yellow';return`<span class="badge ${cls}">${s}</span>`;}
function statusBadgeEx(l){const m={Open:'badge-red','In Progress':'badge-blue',Queued:'badge-purple',Resolved:'badge-green','Closed/N/A':'badge-gray','Closed':'badge-green','New Feature Requested':'badge-indigo'};return`<span class="badge ${m[l]||'badge-gray'}">${l}</span>`;}
function sourceBadge(s){return`<span class="source-tag">${s}</span>`;}
function sevOrder(l){return{Blocker:0,Major:1,Minor:2,Enhancement:3,Unknown:4}[l]??5;}
function statusOrder(l){return{Open:0,'In Progress':1,Queued:2,'New Feature Requested':3,Resolved:4,'Closed':5,'Closed/N/A':6}[l]??7;}
function gusStatusOrder(s){if(!s)return 99;const lc=s.toLowerCase();if(['in progress','active'].includes(lc))return 0;if(['new','triaged','never'].includes(lc))return 1;if(lc==='waiting')return 2;if(lc==='closed'||lc==='fixed')return 3;return 5;}

const isActive=i=>['Open','In Progress','Queued'].includes(i.status_label);
const isClosed=i=>['Resolved','Closed/N/A','Closed','New Feature Requested'].includes(i.status_label);
const pmMatch=(pm,issue)=>{
  if(!pm||pm==='all')return true;
  const p=issue.pm_owner||'Unknown';
  if(pm==='Arsheen+Sriram')return p==='Arsheen'||p==='Sriram';
  if(pm==='Vasanthi+Gaurav')return p==='Vasanthi'||p==='Gaurav';
  return p===pm;
};
function updateStats(){
  document.getElementById('total').textContent=ISSUES.length;
  document.getElementById('active').textContent=ISSUES.filter(isActive).length;
  document.getElementById('resolved').textContent=ISSUES.filter(isClosed).length;
  document.getElementById('blockers').textContent=ISSUES.filter(i=>i.severity_label==='Blocker').length;
  document.getElementById('gus_linked').textContent=ISSUES.filter(i=>i.gus_work_num).length;
}
function normalizeConnector(c){
  c=c||'Unknown';
  if(/sharepoint/i.test(c))return'SharePoint';if(/hubspot/i.test(c))return'HubSpot';if(/shopify/i.test(c))return'Shopify';
  if(/confluence/i.test(c))return'Confluence';if(/google drive/i.test(c))return'Google Drive';
  if(/databricks/i.test(c))return'Databricks';if(/fabric/i.test(c))return'MS Fabric';
  if(/odata/i.test(c))return'OData';if(/instagram/i.test(c))return'Instagram';
  if(/adobe/i.test(c))return'Adobe';if(/sap/i.test(c))return'SAP';if(/zendesk/i.test(c))return'Zendesk';
  if(/mongodb/i.test(c))return'MongoDB';return c.length>25?c.substring(0,23)+'…':c;
}
function buildConnectorBars(){
  const counts={};const typeFor={};
  ISSUES.forEach(i=>{const k=normalizeConnector(i.connector);counts[k]=(counts[k]||0)+1;if(!typeFor[k])typeFor[k]=i.connector_type||'Unknown';});
  const sorted=Object.entries(counts).sort((a,b)=>b[1]-a[1]).slice(0,12);const max=sorted[0]?.[1]||1;
  const colors=['#6366f1','#2563eb','#7c3aed','#dc2626','#ea580c','#16a34a','#0891b2','#ca8a04','#9333ea','#d97706','#0ea5e9','#e11d48'];
  document.getElementById('connectorBars').innerHTML=sorted.map(([n,c],i)=>`<div class="bar-item"><div class="bar-label" title="${n}">${connTypeBadge(typeFor[n])}<span style="overflow:hidden;text-overflow:ellipsis">${n}</span></div><div class="bar-track"><div class="bar-fill" style="width:${(c/max*100).toFixed(1)}%;background:${colors[i%colors.length]}"></div></div><div class="bar-count">${c}</div></div>`).join('');
}
function buildStatusBreakdown(){
  const family={};const so=['Open','In Progress','Queued','Resolved','Closed/N/A'];
  ISSUES.forEach(i=>{
    const c=normalizeConnector(i.connector);
    if(!family[c])family[c]={};family[c][i.status_label]=(family[c][i.status_label]||0)+1;
  });
  const sorted=Object.entries(family).sort((a,b)=>Object.values(b[1]).reduce((s,v)=>s+v,0)-Object.values(a[1]).reduce((s,v)=>s+v,0)).slice(0,12);
  const sc={Open:'#dc2626','In Progress':'#2563eb',Queued:'#7c3aed',Resolved:'#16a34a','Closed/N/A':'#6b7280'};
  document.getElementById('statusBreakdown').innerHTML=sorted.map(([name,cts])=>{const tot=Object.values(cts).reduce((s,v)=>s+v,0);const segs=so.map(s=>cts[s]?`<div title="${s}: ${cts[s]}" style="width:${(cts[s]/tot*100).toFixed(1)}%;background:${sc[s]};height:100%;display:inline-block;"></div>`:'').join('');return`<div class="bar-item"><div class="bar-label" title="${name}">${name}</div><div class="bar-track">${segs}</div><div class="bar-count">${tot}</div></div>`;}).join('');
}
function getSort(){return document.querySelector('.sort-select')?.value||'date-desc';}
function getSortedFiltered(){
  let items=ISSUES.filter(i=>{
    const ms=activeStatus==='all'||(activeStatus==='Active'?isActive(i):activeStatus==='Resolved'?isClosed(i):i.status_label===activeStatus);
    const mv=!activeSev||i.severity_label===activeSev;
    const mg=!activeGus||!!i.gus_work_num;
    const mt=!activeType||(activeType==='Unstructured'?isUnstructured(i.connector):!isUnstructured(i.connector));
    const mct=!activeConnType||(i.connector_type||'Unknown')===activeConnType;
    const mpm=!activePm||pmMatch(activePm,i);
    const t=searchTerm.toLowerCase();
    const mk=!t||[i.connector,i.name,i.company,i.description,i.notes,i.engineer,i.id,i.gus_work_num,i.gus_assignee,i.gus_subject,i.gus_status,i.connector_type,i.pm_owner].some(f=>(f||'').toLowerCase().includes(t));
    return ms&&mv&&mg&&mt&&mct&&mpm&&mk;
  });
  const sort=getSort();
  items.sort((a,b)=>{
    if(sort==='date-asc')return(parseDateStr(a.date)||0)-(parseDateStr(b.date)||0);
    if(sort==='sev')return sevOrder(a.severity_label)-sevOrder(b.severity_label);
    if(sort==='status')return statusOrder(a.status_label)-statusOrder(b.status_label);
    if(sort==='connector')return(a.connector||'').localeCompare(b.connector||'');
    if(sort==='gus-status')return gusStatusOrder(a.gus_status)-gusStatusOrder(b.gus_status);
    return(parseDateStr(b.date)||0)-(parseDateStr(a.date)||0);
  });
  return items;
}
function applyFilters(){searchTerm=document.getElementById('searchInput').value;renderTable();}
function filterByStatus(status,el){
  activeStatus=status;activeSev=null;activeGus=false;
  document.querySelectorAll('#statusFilters .filter-btn').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('#sevFilters .filter-btn').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('#gusFilters .filter-btn').forEach(b=>b.classList.remove('active'));
  el?.classList.add('active');
  document.querySelectorAll('.stat-card').forEach(c=>c.classList.remove('active'));
  document.querySelector(`.stat-card[data-filter="${status}"]`)?.classList.add('active');
  renderTable();
}
function filterBySev(sev,el){
  if(activeSev===sev){activeSev=null;document.querySelectorAll('#sevFilters .filter-btn').forEach(b=>b.classList.remove('active'));}
  else{activeSev=sev;document.querySelectorAll('#sevFilters .filter-btn').forEach(b=>b.classList.remove('active'));el?.classList.add('active');document.querySelectorAll('.stat-card').forEach(c=>c.classList.remove('active'));document.querySelector(`.stat-card[data-filter-sev="${sev}"]`)?.classList.add('active');}
  renderTable();
}
function filterByGus(el){
  activeGus=!activeGus;
  document.querySelectorAll('#gusFilters .filter-btn').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.stat-card').forEach(c=>c.classList.remove('active'));
  if(activeGus){el?.classList.add('active');document.querySelector('.stat-card[data-filter-gus="true"]')?.classList.add('active');}
  else{document.querySelector('#statusFilters .filter-btn[data-status="all"]')?.classList.add('active');document.querySelector('.stat-card[data-filter="all"]')?.classList.add('active');}
  renderTable();
}
function filterByType(type,el){
  if(activeType===type){activeType=null;document.querySelectorAll('#typeFilters .filter-btn').forEach(b=>b.classList.remove('active'));}
  else{activeType=type;document.querySelectorAll('#typeFilters .filter-btn').forEach(b=>b.classList.remove('active'));el?.classList.add('active');}
  renderTable();
}
function filterByConnType(ctype,el){
  if(activeConnType===ctype){activeConnType=null;document.querySelectorAll('#connTypeFilters .filter-btn').forEach(b=>b.classList.remove('active'));}
  else{activeConnType=ctype;document.querySelectorAll('#connTypeFilters .filter-btn').forEach(b=>b.classList.remove('active'));if(el)el.classList.add('active');else{const btn=document.querySelector(`#connTypeFilters .filter-btn[data-ctype="${ctype}"]`);btn?.classList.add('active');}}
  renderTable();
}
function filterByPm(pm,el){
  if(activePm===pm){activePm=null;document.querySelectorAll('#pmFilters .filter-btn').forEach(b=>b.classList.remove('active'));}
  else{activePm=pm;document.querySelectorAll('#pmFilters .filter-btn').forEach(b=>b.classList.remove('active'));el?.classList.add('active');}
  renderTable();
}
function filterByConnTypeAndStatus(ctype,status){
  activeConnType=ctype;activeStatus=status;activePm=null;
  document.querySelectorAll('#connTypeFilters .filter-btn').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('#statusFilters .filter-btn').forEach(b=>b.classList.remove('active'));
  const ctBtn=document.querySelector(`#connTypeFilters .filter-btn[data-ctype="${ctype}"]`);ctBtn?.classList.add('active');
  const stBtn=document.querySelector(`#statusFilters .filter-btn[data-status="${status}"]`);stBtn?.classList.add('active');
  renderTable();
}
function filterMatrixByPm(pm,el){
  document.querySelectorAll('[id^="mtx-pm-"]').forEach(b=>b.classList.remove('active'));
  el?.classList.add('active');
  buildTypeMatrix(pm);
}
function renderTable(){
  const items=getSortedFiltered();
  document.getElementById('issueCount').textContent=`Showing ${items.length} of ${ISSUES.length} issues`;
  document.getElementById('noResults').style.display=items.length===0?'block':'none';
  document.getElementById('issuesTbody').innerHTML=items.map(issue=>{
    const da=daysAgo(issue.date);const isRes=['Resolved','Closed/N/A'].includes(issue.status_label);
    const dDisp=isRes?`<span style="color:var(--muted)">${daysLabel(da)}</span>`:(da!==null&&da>14?`<span class="days-badge" style="background:rgba(220,38,38,.15);color:#f87171;border-color:rgba(220,38,38,.3)">${daysLabel(da)}</span>`:`<span class="days-badge">${daysLabel(da)}</span>`);
    const desc=(issue.description||'').substring(0,110)+((issue.description||'').length>110?'…':'');
    const eng=issue.gus_assignee||(issue.engineer||'—').split('(')[0].trim().substring(0,28);
    const safeId=issue.id.replace(/'/g,"\\'");
    // GUS ticket column
    let gusCell='<span style="color:var(--muted);font-size:11px">—</span>';
    if(issue.gus_work_num){
      const wLink=issue.work_item?`href="${issue.work_item}" target="_blank"`:'';
      gusCell=`<a class="gus-link" ${wLink}>${issue.gus_work_num}</a>`;
      if(issue.gus_sprint){gusCell+=`<div style="font-size:10px;color:var(--muted);margin-top:2px">${issue.gus_sprint.substring(0,22)}</div>`;}
    }
    const ctBadge=connTypeBadge(issue.connector_type||'Unknown');
    const pmDisp=issue.pm_owner||'—';
    return`<tr class="issue-row" onclick="openDetail('${safeId}')"><td><div style="font-family:monospace;font-size:11px;color:var(--accent)">${issue.id}</div><div style="font-size:11px;color:var(--muted);margin-top:2px">${(issue.date||'').substring(0,10)}</div>${sourceBadge(issue.source)}</td><td><strong style="font-size:13px">${issue.connector}</strong></td><td>${ctBadge}</td><td style="font-size:12px;color:var(--muted)">${pmDisp}</td><td>${sevBadge(issue.severity_label)}</td><td>${statusBadge(issue.status_label)}</td><td><div style="font-weight:600;font-size:13px">${issue.name||'—'}</div><div style="font-size:11px;color:var(--muted)">${issue.company||''}</div></td><td style="font-size:12px">${eng}</td><td>${gusCell}</td><td>${gusBadge(issue.gus_status||'',issue.gus_type||'')}</td><td>${dDisp}</td><td style="font-size:12px;color:var(--muted);max-width:240px">${desc}</td></tr>`;
  }).join('');
}
function openDetail(id){
  const issue=ISSUES.find(i=>i.id===id);if(!issue)return;
  document.getElementById('dId').textContent=`ID: ${issue.id}  ·  Source: ${issue.source}`;
  document.getElementById('dTitle').textContent=issue.connector;
  const da=daysAgo(issue.date);const isRes=['Resolved','Closed/N/A'].includes(issue.status_label);
  const gusMeta=issue.gus_work_num?`<span class="badge badge-teal">GUS: ${issue.gus_work_num}</span>`:'';
  document.getElementById('dMeta').innerHTML=`${sevBadge(issue.severity_label)}${statusBadge(issue.status_label)}${gusMeta}${issue.case_id?`<span class="badge badge-indigo">Case #${issue.case_id}</span>`:''}<span class="badge badge-indigo">${da!==null?daysLabel(da)+(isRes?' (resolved)':' open'):'Date unknown'}</span>`;

  let body=`<div class="detail-section"><div class="detail-section-title">Reporter Info</div><div class="detail-row"><span class="detail-key">Name</span><span class="detail-val">${issue.name||'—'}</span></div><div class="detail-row"><span class="detail-key">Company</span><span class="detail-val">${issue.company||'—'}</span></div><div class="detail-row"><span class="detail-key">Email</span><span class="detail-val">${issue.email||'—'}</span></div><div class="detail-row"><span class="detail-key">Reported On</span><span class="detail-val">${issue.date||'—'}</span></div></div>`;

  body+=`<div class="detail-section"><div class="detail-section-title">Issue Details</div><div class="detail-row"><span class="detail-key">Connector</span><span class="detail-val"><strong>${issue.connector||'—'}</strong></span></div><div class="detail-row"><span class="detail-key">Type</span><span class="detail-val">${connTypeBadge(issue.connector_type||'Unknown')}</span></div><div class="detail-row"><span class="detail-key">PM Owner</span><span class="detail-val">${issue.pm_owner||'—'}</span></div><div class="detail-row"><span class="detail-key">Severity</span><span class="detail-val">${sevBadge(issue.severity_label)}</span></div><div class="detail-row"><span class="detail-key">Status</span><span class="detail-val">${statusBadge(issue.status_label)}</span></div>${issue.org_id&&issue.org_id!=='none'?`<div class="detail-row"><span class="detail-key">Org ID</span><span class="detail-val" style="font-family:monospace;font-size:12px">${issue.org_id}</span></div>`:''}${issue.case_id?`<div class="detail-row"><span class="detail-key">Case ID</span><span class="detail-val">#${issue.case_id}</span></div>`:''}${issue.work_item?`<div class="detail-row"><span class="detail-key">Work Item</span><span class="detail-val"><a href="${issue.work_item}" target="_blank">Open GUS Work Item ↗</a></span></div>`:''}<div class="detail-row"><span class="detail-key">Days Open</span><span class="detail-val">${da!==null?`<span class="days-badge">${daysLabel(da)}${isRes?' (until resolved)':''}</span>`:'—'}</span></div></div>`;

  // GUS Ticket section — only shown when linked
  if(issue.gus_work_num){
    const gusWorkLink=issue.work_item?`<a class="gus-ticket-link" href="${issue.work_item}" target="_blank">${issue.gus_work_num} ↗</a>`:`<span style="color:#22d3ee;font-family:monospace">${issue.gus_work_num}</span>`;
    const modDate=issue.gus_last_modified?(issue.gus_last_modified||'').substring(0,10):'—';
    const sprint=issue.gus_sprint||'—';
    const pts=issue.gus_story_points!=null?issue.gus_story_points:'—';
    const assignee=issue.gus_assignee||'—';
    const gusType=issue.gus_type||'';
    const subject=issue.gus_subject?`<div class="detail-desc" style="margin-top:8px;font-size:12px">${(issue.gus_subject).replace(/</g,'&lt;').replace(/>/g,'&gt;')}</div>`:'';
    const typeRow=gusType?`<div class="detail-row"><span class="detail-key">Type</span><span class="detail-val">${gusType==='User Story'?'<span class="badge badge-indigo">User Story — New Feature Requested</span>':gusType}</span></div>`:'';
    body+=`<div class="detail-section"><div class="detail-section-title gus">GUS Ticket Details</div><div class="gus-box"><div class="detail-row"><span class="detail-key">Work #</span><span class="detail-val">${gusWorkLink}</span></div><div class="detail-row"><span class="detail-key">GUS Status</span><span class="detail-val">${gusBadge(issue.gus_status||'',gusType)}</span></div>${typeRow}<div class="detail-row"><span class="detail-key">Assignee</span><span class="detail-val">${assignee}</span></div><div class="detail-row"><span class="detail-key">Sprint</span><span class="detail-val">${sprint}</span></div><div class="detail-row"><span class="detail-key">Story Points</span><span class="detail-val">${pts}</span></div><div class="detail-row"><span class="detail-key">Last Modified</span><span class="detail-val">${modDate}</span></div></div>${subject}</div>`;
  }

  body+=`<div class="detail-section"><div class="detail-section-title">Engineer Assigned</div><div class="detail-desc">${issue.gus_assignee||issue.engineer||'Not yet assigned'}</div></div>`;
  body+=`<div class="detail-section"><div class="detail-section-title">Description & Steps</div><div class="detail-desc">${(issue.description||'No description available.').replace(/</g,'&lt;').replace(/>/g,'&gt;')}</div></div>`;
  if(issue.notes&&issue.notes.trim())body+=`<div class="detail-section"><div class="detail-section-title">Internal Notes / Resolution</div><div class="detail-desc">${issue.notes.replace(/</g,'&lt;').replace(/>/g,'&gt;')}</div></div>`;
  document.getElementById('dBody').innerHTML=body;
  document.getElementById('detailOverlay').classList.add('open');
}
function closeDetail(e){if(!e||e.target===document.getElementById('detailOverlay'))document.getElementById('detailOverlay').classList.remove('open');}
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeDetail();});
updateStats();buildConnectorBars();buildTypeMatrix();buildTypeDonut();renderTable();
</script>
</body>
</html>'''


DEEP_ANALYSIS_HTML = '''
<style>
  .da-section { padding: 24px 32px; max-width: 1800px; margin: 0 auto; margin-top: 40px; }
  .da-toggle { display: flex; align-items: center; gap: 14px; cursor: pointer; user-select: none; padding: 18px 24px; background: linear-gradient(135deg,#1a1d27 0%,#22263a 100%); border: 1px solid #6366f1; border-radius: 12px; margin: 0 32px 0 32px; }
  .da-toggle h2 { font-size: 18px; font-weight: 800; color: #818cf8; margin: 0; letter-spacing: -.01em; }
  .da-toggle .da-subtitle { font-size: 12px; color: #8892a4; margin-top: 3px; }
  .da-toggle .da-chevron { margin-left: auto; font-size: 20px; color: #6366f1; transition: transform .3s; }
  .da-toggle.open .da-chevron { transform: rotate(180deg); }
  .da-body { display: none; padding: 0 32px 40px; }
  .da-body.open { display: block; }
  .da-intro { background: rgba(99,102,241,.08); border: 1px solid rgba(99,102,241,.25); border-radius: 10px; padding: 16px 20px; margin-bottom: 28px; font-size: 13px; color: #cbd5e1; line-height: 1.7; }
  .da-intro strong { color: #818cf8; }
  .da-buckets-grid { display: grid; grid-template-columns: repeat(5,1fr); gap: 14px; margin-bottom: 32px; }
  .da-bucket-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px 18px; text-align: center; }
  .da-bucket-num { font-size: 36px; font-weight: 800; line-height: 1; margin-bottom: 6px; }
  .da-bucket-label { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }
  .da-bucket-sub { font-size: 10px; color: var(--muted); margin-top: 4px; opacity: .7; }
  .da-connector-grid { display: grid; grid-template-columns: repeat(3,1fr); gap: 16px; margin-bottom: 32px; }
  .da-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 18px 20px; }
  .da-card-header { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 12px; gap: 10px; }
  .da-card-title { font-size: 14px; font-weight: 700; color: #fff; line-height: 1.3; }
  .da-card-badges { display: flex; gap: 5px; flex-wrap: wrap; flex-shrink: 0; }
  .da-finding { margin-bottom: 10px; padding: 10px 12px; background: var(--surface2); border-radius: 7px; border-left: 3px solid; }
  .da-finding-title { font-size: 12px; font-weight: 700; margin-bottom: 4px; }
  .da-finding-body { font-size: 12px; color: #cbd5e1; line-height: 1.6; }
  .da-action { font-size: 11px; color: #86efac; margin-top: 5px; display: flex; gap: 5px; }
  .da-action::before { content: "→"; color: #4ade80; flex-shrink: 0; }
  .da-ids { font-size: 10px; color: var(--muted); font-family: monospace; margin-top: 6px; }
  .da-cross-section { background: var(--surface); border: 1px solid rgba(99,102,241,.4); border-radius: 10px; padding: 20px; margin-bottom: 28px; }
  .da-cross-section h3 { font-size: 13px; font-weight: 700; color: #818cf8; text-transform: uppercase; letter-spacing: .08em; margin-bottom: 16px; }
  .da-cross-item { display: flex; gap: 14px; margin-bottom: 14px; padding-bottom: 14px; border-bottom: 1px solid var(--border); }
  .da-cross-item:last-child { margin-bottom: 0; padding-bottom: 0; border-bottom: none; }
  .da-cross-icon { font-size: 22px; flex-shrink: 0; width: 32px; text-align: center; }
  .da-cross-content { flex: 1; }
  .da-cross-title { font-size: 13px; font-weight: 700; color: #e2e8f0; margin-bottom: 4px; }
  .da-cross-body { font-size: 12px; color: #94a3b8; line-height: 1.6; }
  .da-priority-table { width: 100%; border-collapse: collapse; font-size: 12px; margin-bottom: 28px; }
  .da-priority-table th { background: var(--surface2); color: var(--muted); font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; padding: 8px 12px; text-align: left; border: 1px solid var(--border); }
  .da-priority-table td { padding: 10px 12px; border: 1px solid var(--border); vertical-align: top; }
  .da-priority-table tr:nth-child(even) td { background: rgba(255,255,255,.02); }
  .da-p1 { color: #f87171; font-weight: 700; }
  .da-p2 { color: #fb923c; font-weight: 700; }
  .da-p3 { color: #facc15; font-weight: 700; }
  .badge-bug { background: rgba(220,38,38,.15); color: #f87171; border: 1px solid rgba(220,38,38,.3); display:inline-block;padding:2px 7px;border-radius:4px;font-size:10px;font-weight:700; }
  .badge-doc { background: rgba(37,99,235,.15); color: #60a5fa; border: 1px solid rgba(37,99,235,.3); display:inline-block;padding:2px 7px;border-radius:4px;font-size:10px;font-weight:700; }
  .badge-clarif { background: rgba(202,138,4,.15); color: #facc15; border: 1px solid rgba(202,138,4,.3); display:inline-block;padding:2px 7px;border-radius:4px;font-size:10px;font-weight:700; }
  .badge-feat { background: rgba(124,58,237,.15); color: #a78bfa; border: 1px solid rgba(124,58,237,.3); display:inline-block;padding:2px 7px;border-radius:4px;font-size:10px;font-weight:700; }
  .badge-notsup { background: rgba(107,114,128,.15); color: #9ca3af; border: 1px solid rgba(107,114,128,.3); display:inline-block;padding:2px 7px;border-radius:4px;font-size:10px;font-weight:700; }
  @media(max-width:1200px){.da-connector-grid{grid-template-columns:repeat(2,1fr);}.da-buckets-grid{grid-template-columns:repeat(3,1fr);}}
  @media(max-width:900px){.da-connector-grid{grid-template-columns:1fr;}.da-buckets-grid{grid-template-columns:repeat(2,1fr);}}
</style>

<div class="da-toggle" id="daToggle" onclick="toggleDA()">
  <div>
    <h2>&#128300; DEEP Analysis — 102 Issues Across 20 Connectors</h2>
    <div class="da-subtitle">AI-powered root cause analysis · Categorized into Bug Fixes, Documentation Updates, Customer Clarifications, Feature Requests &amp; Not Supported</div>
  </div>
  <span class="da-chevron">&#9660;</span>
</div>
<div class="da-body" id="daBody">
<div class="da-section">

  <div class="da-intro">
    <strong>Methodology:</strong> 20 parallel research agents analyzed all 102 reported issues, cross-referencing the KT guide, engineering meeting notes, CData driver documentation, Salesforce Help articles, GUS work items, and Slack threads. Each connector cluster was independently researched for root causes, and findings were synthesized into 5 logical categories. This section <strong>does not affect the live dashboard</strong> above.
    <br><br>
    <strong>Research date:</strong> April 28, 2026 &nbsp;·&nbsp; <strong>Issues analyzed:</strong> 102 &nbsp;·&nbsp; <strong>Connectors covered:</strong> 20+ &nbsp;·&nbsp; <strong>Agents deployed:</strong> 20
  </div>

  <!-- Bucket Summary Cards -->
  <div class="section-title" style="margin-bottom:12px">Issue Category Breakdown</div>
  <div class="da-buckets-grid">
    <div class="da-bucket-card" style="border-color:rgba(220,38,38,.4)">
      <div class="da-bucket-num" style="color:#f87171">32</div>
      <div class="da-bucket-label">Bug Fixes</div>
      <div class="da-bucket-sub">Product defects requiring engineering action</div>
    </div>
    <div class="da-bucket-card" style="border-color:rgba(37,99,235,.4)">
      <div class="da-bucket-num" style="color:#60a5fa">31</div>
      <div class="da-bucket-label">Documentation Updates</div>
      <div class="da-bucket-sub">Missing or incorrect customer-facing docs</div>
    </div>
    <div class="da-bucket-card" style="border-color:rgba(202,138,4,.4)">
      <div class="da-bucket-num" style="color:#facc15">22</div>
      <div class="da-bucket-label">Customer Clarifications</div>
      <div class="da-bucket-sub">Setup confusion, expectation mismatches</div>
    </div>
    <div class="da-bucket-card" style="border-color:rgba(124,58,237,.4)">
      <div class="da-bucket-num" style="color:#a78bfa">13</div>
      <div class="da-bucket-label">Feature Requests</div>
      <div class="da-bucket-sub">Capabilities not yet built</div>
    </div>
    <div class="da-bucket-card" style="border-color:rgba(107,114,128,.4)">
      <div class="da-bucket-num" style="color:#9ca3af">4</div>
      <div class="da-bucket-label">Not Supported</div>
      <div class="da-bucket-sub">Architectural limitations by design</div>
    </div>
  </div>

  <!-- Cross-cutting patterns -->
  <div class="section-title" style="margin-bottom:12px">Cross-Cutting Patterns</div>
  <div class="da-cross-section">
    <h3>&#9888; Critical Systemic Issues Found Across Multiple Connectors</h3>

    <div class="da-cross-item">
      <div class="da-cross-icon">&#128274;</div>
      <div class="da-cross-content">
        <div class="da-cross-title">OAuth Token Refresh Non-Persistence — Affects Jira, SharePoint Unstructured, Confluence Unstructured, Instagram</div>
        <div class="da-cross-body">The Named Credentials / 360 Admin Service layer does not persist newly-generated OAuth refresh tokens after use. Atlassian and Microsoft OAuth implementations rotate refresh tokens on each use — if the new token isn't stored, the next refresh cycle fails silently. Initial connection test passes; auth drops after 1–24 hours. Root cause is in DCF's credential store, not in the connectors themselves. <strong>Single fix in the 360 Admin Service would resolve across 4+ connectors.</strong></div>
      </div>
    </div>

    <div class="da-cross-item">
      <div class="da-cross-icon">&#9201;</div>
      <div class="da-cross-content">
        <div class="da-cross-title">CData 4-Hour Query Timeout — Not Exposed in UI (HubSpot, Shopify, Confluence, Box, GA4)</div>
        <div class="da-cross-body">The CData JDBC driver has a hard-coded 14,400-second (4-hour) query timeout per run segment. Large tables (HubSpot Contacts 1M+, Shopify orderLineItems, Confluence all-spaces) exceed this limit during initial load. The platform's real limit is 48 hours, but the CData driver fails at 4 hours. This value is configurable in CData but was intentionally excluded from the UI. <strong>Exposing one connection parameter would unblock 5+ connectors.</strong></div>
      </div>
    </div>

    <div class="da-cross-item">
      <div class="da-cross-icon">&#128296;</div>
      <div class="da-cross-content">
        <div class="da-cross-title">Named Credentials HTTP Header Injection Doesn't Work for CData JDBC Connectors</div>
        <div class="da-cross-body">Customers expect Salesforce Named Credentials to inject auth headers into CData connector calls. This only works for REST/HTTP connectors — not for JDBC-backed CData connectors, which manage their own credential layer through the CData driver properties. Documented in OData, GraphQL, and ADP cases. No Salesforce Help article explains this architectural distinction. Three separate credential management layers exist (DCF, WDC, CData driver), each requiring different auth configuration.</div>
      </div>
    </div>

    <div class="da-cross-item">
      <div class="da-cross-icon">&#128214;</div>
      <div class="da-cross-content">
        <div class="da-cross-title">Zero Test Accounts Across 5+ Connectors — Blocking GA</div>
        <div class="da-cross-body">NetSuite, Cosmos DB, Instagram, Elasticsearch, Zendesk Standard, and Adobe Analytics have zero permanent test accounts. Without a stable test environment, regression testing is impossible and production bugs go undetected until reported by beta customers. This is the #1 structural barrier to GA for these connectors. Anindita Talukdar confirmed this is the stance: "not to take anything to GA unless there is a strong customer ask and we have test infrastructure."</div>
      </div>
    </div>

    <div class="da-cross-item">
      <div class="da-cross-icon">&#129302;</div>
      <div class="da-cross-content">
        <div class="da-cross-title">No End-to-End "Connector → UDL → Agentforce" Setup Guide (7 Issues)</div>
        <div class="da-cross-body">7 separate issues (SharePoint, Google Drive, Zendesk, Confluence, MongoDB, Fabric) trace to customers attempting to wire a connector into Agentforce as a knowledge source with no published guide. The unstructured connector setup docs end at data ingestion — there's no guide continuing through UDLO creation, vector embedding enablement, and linking to Agentforce. <strong>One guide would deflect ~7 active tickets.</strong></div>
      </div>
    </div>

    <div class="da-cross-item">
      <div class="da-cross-icon">&#128737;</div>
      <div class="da-cross-content">
        <div class="da-cross-title">CData ZC Filter Pushdown Bug — Blocks Zero Copy GA for All CData Connectors</div>
        <div class="da-cross-body">CData Zero Copy GA is paused platform-wide due to a confirmed SQL filter pushdown bug where WHERE clause filters don't propagate to the source. Affects MongoDB, HubSpot, Shopify, OData, and others. Some tables (like HubSpot Contacts) require mandatory filter fields in ZC mode — without filter pushdown, these tables can't return data. MongoDB ZC filter pushdown is a known CData-level issue causing report failures. <strong>Engineering dependency on CData vendor fix before ZC GA can proceed.</strong></div>
      </div>
    </div>
  </div>

  <!-- Connector-by-connector Deep Dives -->
  <div class="section-title" style="margin-bottom:12px">Connector-Level Root Cause Analysis</div>
  <div class="da-connector-grid">

    <!-- SharePoint Unstructured -->
    <div class="da-card">
      <div class="da-card-header">
        <div class="da-card-title">SharePoint Unstructured (Mulesoft) — 14 Issues</div>
        <div class="da-card-badges"><span class="badge-wdc">WDC</span></div>
      </div>
      <div class="da-finding" style="border-color:#f87171">
        <div class="da-finding-title" style="color:#f87171">&#128308; Bug: MDF UDLO Save Fails (IDs 16, 20)</div>
        <div class="da-finding-body">Connection creation (DCF) succeeds but saving the UDLO via MDF (Metadata Driven Framework) fails. Known MDF platform instability — it was built as a short-term solution with documented tech debt. Also affects subsequent saves of a partially-created UDLO from prior failed attempts.</div>
        <div class="da-action">Escalate to Anindita Talukdar's MDF team; add UDLO creation retry logic and clearer error codes.</div>
      </div>
      <div class="da-finding" style="border-color:#f87171">
        <div class="da-finding-title" style="color:#f87171">&#128308; Bug: March 2026 Regression — Previously Working Connections Broke (IDs 24, SHEET-42)</div>
        <div class="da-finding-body">Two customers report streams working then silently breaking since March 2026. Pattern indicates a patch regression affecting credential refresh integration between the Mulesoft connector and DCF. Simultaneous failure across prod+sandbox confirms it's not customer config.</div>
        <div class="da-action">Pull Splunk logs for first failure timestamp; correlate to 260.x patch notes; raise urgent patch request.</div>
      </div>
      <div class="da-finding" style="border-color:#f87171">
        <div class="da-finding-title" style="color:#f87171">&#128308; Bug: OAuth Token Not Refreshed — Auth Drops After ~1 Hour (DC-2026-1HMQV)</div>
        <div class="da-finding-body">Same pattern as confirmed Jira token rotation bug. Microsoft Azure AD rotates refresh tokens on each use; Named Credentials layer doesn't persist the new token. Connection works initially then fails on next refresh cycle.</div>
        <div class="da-action">Audit Mulesoft connector's token storage path against DCF 360 Admin Service; cross-reference Jira fix.</div>
      </div>
      <div class="da-finding" style="border-color:#60a5fa">
        <div class="da-finding-title" style="color:#60a5fa">&#128309; Doc: Test Connection Tests Wrong Endpoint (DC-2026-7ZNZL, DC-2026-7UC4W)</div>
        <div class="da-finding-body">Test connection fails but same credentials work in Postman. DCF test connection may be hitting a different scope or Graph API resource URL than the actual data pull. Azure AD application may lack admin consent (app-level, not delegated permissions).</div>
        <div class="da-action">Document exact Graph API endpoint and required scopes (Sites.Read.All, Files.Read.All) tested during connection test; add admin consent requirement to setup guide.</div>
      </div>
      <div class="da-finding" style="border-color:#60a5fa">
        <div class="da-finding-title" style="color:#60a5fa">&#128309; Doc: Unified→Enterprise Knowledge Schema Gap — Missing \'Label\' Field (ID 25)</div>
        <div class="da-finding-body">Customers migrating from Unified Knowledge to Enterprise Knowledge find the \'Label\' field removed from the connector schema. No migration guide or field mapping table exists. Will scale as Enterprise Knowledge adoption increases.</div>
        <div class="da-action">Publish migration guide: Unified Knowledge → Enterprise Knowledge field mapping for SharePoint connector. Keshav Sharma (PM) + Docs team.</div>
      </div>
      <div class="da-ids">Affected: 16, 20, 24, 25, 32, 34, SHEET-42, DC-2026-7ZNZL, DC-2026-7UC4W, DC-2026-JNYY3, DC-2026-1HMQV, DC-2026-QH2F0, EMAIL-19dd140a, EMAIL-19db5729, EMAIL-19dac573</div>
    </div>

    <!-- SharePoint Structured -->
    <div class="da-card">
      <div class="da-card-header">
        <div class="da-card-title">SharePoint Structured (WDC) — 7 Issues</div>
        <div class="da-card-badges"><span class="badge-wdc">WDC</span></div>
      </div>
      <div class="da-finding" style="border-color:#60a5fa">
        <div class="da-finding-title" style="color:#60a5fa">&#128309; Doc: Wrong URL Format — Site URL vs File URL Confusion (IDs 17, 18, 19, 27, DC-2026-R0L49)</div>
        <div class="da-finding-body">Most frequent issue. The connector requires the SharePoint <em>site root URL</em> (e.g., tenant.sharepoint.com/sites/SiteName), not a file URL or sharing link. The gRPC error "Unable to find a file" is the connector's FetchTableNames call failing to resolve a file-path URL. No documentation explains this distinction.</div>
        <div class="da-action">Create KB article with: correct URL format, wrong URL examples, how to find site URL. Add inline tooltip in wizard. Improve gRPC error message.</div>
      </div>
      <div class="da-finding" style="border-color:#facc15">
        <div class="da-finding-title" style="color:#facc15">&#128993; Clarification: Wrong Connector — PDF/PPT Need Unstructured, Not Structured (DC-2026-QH2F0)</div>
        <div class="da-finding-body">Customer trying to use PDF/PowerPoint files with the Structured connector. SharePoint Structured only supports Excel (.xlsx) and CSV — it reads tabular data. PDFs and PowerPoints require the SharePoint Documents (Unstructured) Mulesoft connector. Two SharePoint entries in the connector catalog with no clear disambiguation is the root cause.</div>
        <div class="da-action">Update catalog descriptions with supported file types per variant. Accelerate 264 P0 Unified Connectivity UX item (single logo per data source).</div>
      </div>
      <div class="da-finding" style="border-color:#facc15">
        <div class="da-finding-title" style="color:#facc15">&#128993; Clarification: Zero Copy Not Supported (ID 19)</div>
        <div class="da-finding-body">Customer attempted Zero Copy mode with the WDC connector. WDC stack has no federation/pushdown capability — Batch Ingest only. Not a bug, but undocumented constraint.</div>
        <div class="da-action">Add prominent Batch Ingest-only note to connector docs. Flag ZC migration to DCF as a long-term roadmap item if demand increases.</div>
      </div>
      <div class="da-ids">Affected: 17, 18, 19, 27, DC-2026-R0L49, DC-2026-QH2F0, DC-2026-XXGRK</div>
    </div>

    <!-- HubSpot -->
    <div class="da-card">
      <div class="da-card-header">
        <div class="da-card-title">HubSpot (CData JDBC) — 5 Issues</div>
        <div class="da-card-badges"><span class="badge-cdata">CData</span></div>
      </div>
      <div class="da-finding" style="border-color:#60a5fa">
        <div class="da-finding-title" style="color:#60a5fa">&#128309; Doc: Required OAuth Scopes Not Documented (ID 14, EMAIL-19da9f00)</div>
        <div class="da-finding-body">The CData driver exposes OAuthRequiredScopes as a connection property but it\'s not surfaced in the Data Cloud UI or documented in the Salesforce guide. Without correct scopes, OAuth token authenticates (test passes) but returns empty object list. Required: crm.objects.contacts.read, crm.objects.companies.read, crm.objects.deals.read, oauth.</div>
        <div class="da-action">Add "Required OAuth Scopes" section to HubSpot connector guide. Expose OAuthRequiredScopes as a pre-filled UI field.</div>
      </div>
      <div class="da-finding" style="border-color:#f87171">
        <div class="da-finding-title" style="color:#f87171">&#128308; Bug: 4-Hour Timeout on Contacts for Large Orgs (ID 30)</div>
        <div class="da-finding-body">HubSpot Contacts with 1M+ records exceeds the 14,400-second CData driver timeout during initial load. The HubSpot API limits pagination to 250 records/page — thousands of API calls needed for large orgs. No date-range filter is applied by default.</div>
        <div class="da-action">Investigate exposing CData timeout as configurable UI parameter. Recommend incremental refresh using UpdatedAt filter as workaround. Reference MongoDB timeout WI as precedent.</div>
      </div>
      <div class="da-finding" style="border-color:#f87171">
        <div class="da-finding-title" style="color:#f87171">&#128308; Bug: Special Characters (&amp;, numbers) in Field Names Cause Full Stream Failure (DC-2026-8R1HM)</div>
        <div class="da-finding-body">HubSpot custom properties with ampersand or leading numbers in display names cause the entire data stream to fail. Root cause: DCF Parquet writer cannot handle special characters in column names. Ethan Pyke has a 264 backlog item for a new Parquet writer — apply column name sanitization as a short-term fix.</div>
        <div class="da-action">Apply column name sanitization in CData→Parquet pipeline. Accelerate Ethan Pyke\'s Parquet writer 264 item. Configure CData to use API names not display labels.</div>
      </div>
      <div class="da-ids">Affected: 14, 30, DC-2026-8R1HM, SHEET-43, EMAIL-19da9f00</div>
    </div>

    <!-- Shopify -->
    <div class="da-card">
      <div class="da-card-header">
        <div class="da-card-title">Shopify (CData JDBC) — 6 Issues</div>
        <div class="da-card-badges"><span class="badge-cdata">CData</span></div>
      </div>
      <div class="da-finding" style="border-color:#f87171">
        <div class="da-finding-title" style="color:#f87171">&#128308; Bug: orderLineItems Timeout — No Server-Side Filter Available (IDs 38, DC-2026-E9F2O, EMAIL-19daaa3d)</div>
        <div class="da-finding-body">The Shopify orderLineItems table has no server-side filtering beyond resourceId — the connector must scan the entire table. For enterprise Shopify stores with millions of orders, this consistently exceeds the 4-hour CData timeout. Praveen Yadav asked CData (Daniel Eich) about adding date-range filters on Apr 10 — pending response. A 24-hour timeout workaround was applied for one customer, confirming the timeout IS configurable.</div>
        <div class="da-action">Urgently follow up with Daniel Eich (CData) to add created_at/updated_at filters for orderLineItems. Expose configurable timeout in UI. Exclude table from initial sync as workaround for large stores.</div>
      </div>
      <div class="da-finding" style="border-color:#facc15">
        <div class="da-finding-title" style="color:#facc15">&#128993; Clarification: Product Reviews &amp; Behavioral Events Not Available (DC-2026-06DCB)</div>
        <div class="da-finding-body">Product reviews are in a third-party Shopify app, not the Admin API that CData queries. Behavioral events (clicks, views) are in Shopify Pixels/storefront analytics, also not accessible via Admin API. These objects fundamentally don\'t exist in CData\'s Shopify schema.</div>
        <div class="da-action">Document "What\'s Not Included" section in Shopify connector guide. File Feature Request with CData for Product Reviews API support if customer demand warrants.</div>
      </div>
      <div class="da-finding" style="border-color:#60a5fa">
        <div class="da-finding-title" style="color:#60a5fa">&#128309; Doc: Auth Setup Guide Outdated — Shopify Moved to Access Token Auth Model (EMAIL-19dcf613)</div>
        <div class="da-finding-body">Shopify deprecated API key+password auth in favor of access tokens. Customers following the current guide fail setup. The guide needs to be updated for Shopify\'s current Custom App access token flow and required read permission scopes.</div>
        <div class="da-action">Audit Shopify connector setup guide against current Shopify API requirements. Tag Lyman Ng for documentation refresh.</div>
      </div>
      <div class="da-ids">Affected: 38, DC-2026-E9F2O, DC-2026-06DCB, DC-2026-V1HA8, EMAIL-19daaa3d, EMAIL-19dcf613</div>
    </div>

    <!-- Confluence -->
    <div class="da-card">
      <div class="da-card-header">
        <div class="da-card-title">Confluence (CData + Mulesoft Unstructured) — 7 Issues</div>
        <div class="da-card-badges"><span class="badge-cdata">CData</span><span class="badge-wdc">Unstr.</span></div>
      </div>
      <div class="da-finding" style="border-color:#f87171">
        <div class="da-finding-title" style="color:#f87171">&#128308; Critical Bug: Production Pages+PageContents Streams Broken Since Oct 2025 (SHEET-44)</div>
        <div class="da-finding-body">Both structured streams failing since October 2025 across prod and sandbox. Simultaneous dual-stream failure across two environments strongly indicates Atlassian deprecated a Confluence REST API endpoint used by the CData driver. CData v1 endpoints were deprecated in favor of v2 in 2023–2024. A CData JAR update targeting Confluence API v2 is likely required.</div>
        <div class="da-action">URGENT: File CData bug with Anand Singh/Pratik Goyal. Pull Splunk logs for exact HTTP error (403/404/410). If API deprecation confirmed, request emergency CData JAR hotfix via 3-sub-cycle process.</div>
      </div>
      <div class="da-finding" style="border-color:#60a5fa">
        <div class="da-finding-title" style="color:#60a5fa">&#128309; Doc: CQL Not Supported — Customers Trying Wrong Filter Syntax (IDs 7, EMAIL-19dbc443)</div>
        <div class="da-finding-body">Customers who know Confluence natively attempt to use CQL (Confluence Query Language) in the filter field. CData uses SQL WHERE clause syntax mapped to REST API parameters — CQL is not supported. SpaceKey is the primary supported filter. No Salesforce Help article documents this.</div>
        <div class="da-action">Update Confluence connector help article with supported filter fields and SQL syntax examples. Note explicitly that CQL is not applicable.</div>
      </div>
      <div class="da-finding" style="border-color:#f87171">
        <div class="da-finding-title" style="color:#f87171">&#128308; Bug: UDLO Refresh Fails After Initial Load (EMAIL-19db749a)</div>
        <div class="da-finding-body">Same OAuth token rotation pattern as Jira and SharePoint Unstructured. Atlassian rotates refresh tokens; Named Credentials layer doesn\'t persist the new token. Connection test passes; refresh fails at next auth cycle.</div>
        <div class="da-action">Coordinate with 360 Admin Service team (Cheryl/Larry Tong) to fix refresh token persistence for Atlassian OAuth. Cross-reference Jira structured connector fix.</div>
      </div>
      <div class="da-ids">Affected: 7, 8, 35, SHEET-44, EMAIL-19dbc443, EMAIL-19db57fa, EMAIL-19db749a</div>
    </div>

    <!-- Zendesk -->
    <div class="da-card">
      <div class="da-card-header">
        <div class="da-card-title">Zendesk (CData + UDLO) — 3 Issues</div>
        <div class="da-card-badges"><span class="badge-cdata">CData</span></div>
      </div>
      <div class="da-finding" style="border-color:#f87171">
        <div class="da-finding-title" style="color:#f87171">&#128308; Bug: Custom Fields Missing — CData IncludeCustomFields Not Exposed (EMAIL-19db558c)</div>
        <div class="da-finding-body">CData exposes IncludeCustomFields as a driver property but the Data Cloud UI doesn\'t surface it. Custom Zendesk properties are structurally unavailable. Same issue exists for Jira. Additionally, W-19626478 is tracking a Zendesk driver upgrade that has broken standard date fields — newer CData driver deprecated Basic auth in favor of OAuth but the connector hardcodes AuthScheme=Basic. Dead end: current driver has data issues, new driver breaks auth, no plan to fix because CData is phasing out.</div>
        <div class="da-action">Expose IncludeCustomFields as optional UI property. Link customer case to W-19626478. Given CData phase-out, evaluate Zendesk direct API path for long-term fix.</div>
      </div>
      <div class="da-finding" style="border-color:#60a5fa">
        <div class="da-finding-title" style="color:#60a5fa">&#128309; Doc: Feature Manager "Connectors Beta" Flag Required for UDLO — Not Documented (ID 26)</div>
        <div class="da-finding-body">Two prerequisites needed to see Zendesk in the UDLO flow: (1) create connector under Other Connectors (not Data Streams), (2) enable "Connectors Beta" in Feature Manager. The second step is not documented anywhere in the Zendesk UDLO setup guide, causing customers to be stuck despite completing all visible steps.</div>
        <div class="da-action">Update c360-a-create-zendesk-udlo.html with explicit Feature Manager prerequisite. Check if there\'s also a framework UI bug with Yoav Marom\'s DCF framework team.</div>
      </div>
      <div class="da-ids">Affected: 26, DC-2026-SYAT7, EMAIL-19db558c</div>
    </div>

    <!-- Microsoft Fabric & Databricks -->
    <div class="da-card">
      <div class="da-card-header">
        <div class="da-card-title">Microsoft Fabric &amp; Databricks (Homegrown) — 3 Issues</div>
        <div class="da-card-badges"><span class="badge-homegrown">Homegrown</span></div>
      </div>
      <div class="da-finding" style="border-color:#a78bfa">
        <div class="da-finding-title" style="color:#a78bfa">&#128994; Feature Request: RTBF / Record Deletion Not Supported in Batch Ingest (ID 4)</div>
        <div class="da-finding-body">The Fabric connector (and all batch ingest connectors) does not propagate source deletions. When a record is deleted in Fabric for RTBF compliance, it simply isn\'t included in the next pull — the existing DLO record remains until a full refresh or a separate Data Cloud delete API call. No documentation covers this. GA readiness for regulated industries (Raja Group, Emirates) is blocked.</div>
        <div class="da-action">BLOCK GA: Document RTBF workaround (Data Cloud delete API) before Fabric GA. Evaluate deletion detection mode (snapshot diff) as a 264 engineering item.</div>
      </div>
      <div class="da-finding" style="border-color:#f87171">
        <div class="da-finding-title" style="color:#f87171">&#128308; Bug: Databricks SocketException Under 1 Minute (DC-2026-5QVRC)</div>
        <div class="da-finding-body">Sub-60-second SocketException is a network-layer failure, not a data-volume timeout. Most likely cause: IP allowlisting not configured on Databricks cluster, or cluster auto-suspend state causing JDBC connection failure before the 1-minute mark. Not related to data volume.</div>
        <div class="da-action">Ask customer: Is IP allowlist configured? Is auto-suspend enabled? Pull DCF pod logs for exact socket error type. Praveen Surapaneni (Databricks DRI) to investigate. Publish IP allowlisting guide for Databricks GA.</div>
      </div>
      <div class="da-ids">Affected: 4, 21, DC-2026-5QVRC</div>
    </div>

    <!-- GA4 & Google Analytics -->
    <div class="da-card">
      <div class="da-card-header">
        <div class="da-card-title">GA4 / Google Analytics (CData) — 2 Issues</div>
        <div class="da-card-badges"><span class="badge-cdata">CData</span></div>
      </div>
      <div class="da-finding" style="border-color:#60a5fa">
        <div class="da-finding-title" style="color:#60a5fa">&#128309; Doc: GCP OAuth App Config Completely Undocumented — Internal Setup Guide Marked "No" (ID 29)</div>
        <div class="da-finding-body">The GA4 connector requires configuring a GCP OAuth application but the internal setup guide was never completed (marked "no" as of April 2026). GA4 Events stream returns empty due to UA vs GA4 property ID confusion — customers entering old Universal Analytics property IDs get no data. No guide exists for the GCP OAuth app setup flow.</div>
        <div class="da-action">Create GCP OAuth app setup guide for GA4 connector. Explicitly document property ID format difference (UA: UA-XXXXX vs GA4: G-XXXXXX). Add mandatory date-range filter requirement to Events stream.</div>
      </div>
      <div class="da-finding" style="border-color:#f87171">
        <div class="da-finding-title" style="color:#f87171">&#128308; Bug: Events Stream Requires Mandatory Filter — Returns Empty Without It</div>
        <div class="da-finding-body">GA4 Events requires specific mandatory filter parameters (date ranges, property IDs) that are not surfaced in the UI. Without these, the CData driver returns no rows — a silent empty-result failure rather than an error. This matches the cross-cutting CData ZC mandatory filter fields issue.</div>
        <div class="da-action">Identify mandatory filter fields for GA4 Events from CData docs. Surface them as required fields in the data stream wizard. Add to the "mandatory filter tables" documentation.</div>
      </div>
      <div class="da-ids">Affected: ID:29, SHEET (GA4 issues)</div>
    </div>

    <!-- SAP / LinkedIn / OData / Adobe -->
    <div class="da-card">
      <div class="da-card-header">
        <div class="da-card-title">SAP, LinkedIn, OData, Adobe (CData) — 8 Issues</div>
        <div class="da-card-badges"><span class="badge-cdata">CData</span></div>
      </div>
      <div class="da-finding" style="border-color:#60a5fa">
        <div class="da-finding-title" style="color:#60a5fa">&#128309; Doc: SAP — Cloud vs On-Prem Not Distinguished in Docs</div>
        <div class="da-finding-body">SAP HANA Cloud and SAP HANA On-Premises have different JDBC endpoints and auth requirements. Customers configuring the wrong variant see cryptic connection failures. Documentation does not distinguish the two setup paths. A save-after-test Gack is a confirmed product bug.</div>
        <div class="da-action">Add separate setup sections for SAP HANA Cloud vs On-Prem. File WI for save-after-test Gack.</div>
      </div>
      <div class="da-finding" style="border-color:#f87171">
        <div class="da-finding-title" style="color:#f87171">&#128308; Bug: OData — Named Credentials HTTP Headers Don\'t Work for CData JDBC</div>
        <div class="da-finding-body">OData connector is CData JDBC-based. Named Credentials HTTP header injection (standard Salesforce auth pattern) does NOT work for JDBC connectors — CData manages its own credential layer. Additionally, client_credentials OAuth flow is unsupported in OData\'s current implementation.</div>
        <div class="da-action">Document the Named Credentials limitation for CData JDBC connectors explicitly. Raise client_credentials flow support as a Feature Request with CData.</div>
      </div>
      <div class="da-finding" style="border-color:#9ca3af">
        <div class="da-finding-title" style="color:#9ca3af">&#9940; Not Supported: Adobe Commerce Bearer Token Deprecated by Default</div>
        <div class="da-finding-body">Adobe Commerce bearer token auth was deprecated by Adobe as the default; it now requires a non-standard admin panel setting to re-enable. Additionally, Adobe 2FA blocks both auth modes — no workaround exists in the current connector. No test accounts for Adobe Analytics or Commerce available.</div>
        <div class="da-action">Document Adobe 2FA as a known limitation. Document the admin setting required for bearer token re-enablement. Procure test accounts before any GA attempt.</div>
      </div>
      <div class="da-ids">Affected: SAP issues, OData issues, Adobe issues, LinkedIn issues</div>
    </div>

    <!-- NetSuite / CosmosDB / Instagram / Elasticsearch -->
    <div class="da-card">
      <div class="da-card-header">
        <div class="da-card-title">NetSuite, Cosmos DB, Instagram, Elasticsearch — 8 Issues</div>
        <div class="da-card-badges"><span class="badge-cdata">CData</span></div>
      </div>
      <div class="da-finding" style="border-color:#60a5fa">
        <div class="da-finding-title" style="color:#60a5fa">&#128309; Doc: NetSuite — SuiteAnalytics Connect Prerequisite Undocumented</div>
        <div class="da-finding-body">NetSuite requires SuiteAnalytics Connect as a separate license/feature before the JDBC connector can work. This prerequisite is not mentioned in Salesforce\'s connector documentation. Customers without SuiteAnalytics Connect see authentication failures with no actionable error message.</div>
        <div class="da-action">Add SuiteAnalytics Connect prerequisite as Step 0 in the NetSuite connector setup guide.</div>
      </div>
      <div class="da-finding" style="border-color:#facc15">
        <div class="da-finding-title" style="color:#facc15">&#128993; Clarification: Cosmos DB — Nested Documents by Design, Not a Bug</div>
        <div class="da-finding-body">Customers expecting flat relational schemas see nested document structures in Cosmos DB data. This is the NoSQL document model — by design. CData flattens some nesting but deep nested arrays remain nested. Not a bug but needs documentation.</div>
        <div class="da-action">Add "Data Model Expectations" section to Cosmos DB docs explaining document nesting behavior and how to handle it in Data Cloud transformations.</div>
      </div>
      <div class="da-finding" style="border-color:#9ca3af">
        <div class="da-finding-title" style="color:#9ca3af">&#9940; Not Supported: Instagram Token Expiry + No Permanent Test Accounts</div>
        <div class="da-finding-body">Instagram token expiry behavior is undocumented. All 5 connectors (NetSuite, Cosmos DB, Instagram, Elasticsearch, Zendesk Standard) have zero permanent test accounts, making regression testing impossible and blocking GA timelines.</div>
        <div class="da-action">Procure test accounts as a prerequisite for GA. Document Instagram token expiry and refresh cadence. Consider GA only when stable test infrastructure exists.</div>
      </div>
      <div class="da-ids">Affected: NetSuite issues, Cosmos DB issues, Instagram issues, Elasticsearch issues</div>
    </div>

    <!-- Zero Copy (MongoDB / AWS Glue) -->
    <div class="da-card">
      <div class="da-card-header">
        <div class="da-card-title">Zero Copy — MongoDB &amp; AWS Glue — 4 Issues</div>
        <div class="da-card-badges"><span class="badge-cdata">CData</span><span class="badge-homegrown">ZC</span></div>
      </div>
      <div class="da-finding" style="border-color:#60a5fa">
        <div class="da-finding-title" style="color:#60a5fa">&#128309; Doc: AWS Glue — Lake Formation Grants Missing from Docs (Critical)</div>
        <div class="da-finding-body">AWS Lake Formation grants are a second independent access gate beyond standard S3/IAM permissions. Without Lake Formation grants, Data Cloud can authenticate and connect but returns zero data — no error message. This prerequisite is completely missing from all AWS Glue connector documentation. Most common root cause of "connection works, no data" for AWS Glue.</div>
        <div class="da-action">Add AWS Lake Formation setup as a required step in the AWS Glue connector documentation immediately. Include screenshot walkthrough.</div>
      </div>
      <div class="da-finding" style="border-color:#f87171">
        <div class="da-finding-title" style="color:#f87171">&#128308; Bug: MongoDB ZC Filter Pushdown — Confirmed CData Issue Causing Report Failures</div>
        <div class="da-finding-body">MongoDB Zero Copy filter pushdown is a known CData-level bug. WHERE clause filters don\'t propagate to MongoDB, causing full table scans and report failures when filtered queries are expected. This is part of the broader CData ZC filter pushdown bug blocking CData ZC GA.</div>
        <div class="da-action">Track with CData vendor (Daniel Eich) as part of ZC GA readiness. Do not promote MongoDB ZC to GA until filter pushdown is verified. Communicate current ZC GA pause to affected customers.</div>
      </div>
      <div class="da-ids">Affected: DC-2026-2W7QV, MongoDB ZC issues, AWS Glue ZC issues</div>
    </div>

    <!-- Power BI / Box / B2C -->
    <div class="da-card">
      <div class="da-card-header">
        <div class="da-card-title">Power BI, Box, B2C, Google Drive — 6 Issues</div>
        <div class="da-card-badges"><span class="badge-wdc">WDC</span><span class="badge-homegrown">Mixed</span></div>
      </div>
      <div class="da-finding" style="border-color:#f87171">
        <div class="da-finding-title" style="color:#f87171">&#128308; Bug: Box — SocketTimeoutException (Infrastructure Bug)</div>
        <div class="da-finding-body">Box connector experiences SocketTimeoutException during data pull — classified as an infrastructure-level bug in the WDC/DCF layer, not a Box API issue. Different from the CData 4-hour timeout pattern; this is a socket-level timeout hitting before any meaningful data transfer.</div>
        <div class="da-action">Escalate to DCF infrastructure team. Pull Splunk for exact timeout threshold. Distinguish from CData timeout class.</div>
      </div>
      <div class="da-finding" style="border-color:#f87171">
        <div class="da-finding-title" style="color:#f87171">&#128308; Bug: Google Drive — Shared Drive 404 (Missing supportsAllDrives=true)</div>
        <div class="da-finding-body">Google Drive API calls for Shared Drives require the supportsAllDrives=true parameter flag. The connector is missing this flag, causing 404s on all Shared Drive content. Also: appProperties field naming bug is a GA blocker, and DWD (Domain-Wide Delegation) security escalation reverted the connector from GA to Beta.</div>
        <div class="da-action">Add supportsAllDrives=true to all Google Drive API calls. Fix appProperties field naming bug. Resolve DWD security escalation before GA re-promotion.</div>
      </div>
      <div class="da-finding" style="border-color:#60a5fa">
        <div class="da-finding-title" style="color:#60a5fa">&#128309; Doc: B2C Production-Only Constraint Undocumented</div>
        <div class="da-finding-body">B2C connector only works in production orgs — sandbox/scratch org deployments fail. This constraint is not documented. Customers spending days debugging sandbox deployments before discovering this limitation.</div>
        <div class="da-action">Add production-only requirement prominently to B2C connector documentation as a known limitation.</div>
      </div>
      <div class="da-ids">Affected: Box issues, B2C issues, Google Drive issues, Power BI issues</div>
    </div>

  </div><!-- end da-connector-grid -->

  <!-- Priority Action Table -->
  <div class="section-title" style="margin-bottom:12px">Top Priority Recommended Actions</div>
  <table class="da-priority-table">
    <thead>
      <tr>
        <th>Priority</th>
        <th>Action</th>
        <th>Category</th>
        <th>Affected Connectors</th>
        <th>Owner</th>
        <th>Impact</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td class="da-p1">P1 — Urgent</td>
        <td>Fix OAuth refresh token non-persistence in Named Credentials / 360 Admin Service</td>
        <td><span class="badge-bug">Bug Fix</span></td>
        <td>Jira, SharePoint, Confluence, Instagram</td>
        <td>360 Admin Service (Cheryl/Larry Tong) + Anindita\'s MDF team</td>
        <td>Resolves silent auth drops across 4+ connectors with one platform fix</td>
      </tr>
      <tr>
        <td class="da-p1">P1 — Urgent</td>
        <td>File emergency CData JAR hotfix for Confluence REST API deprecation (broken since Oct 2025)</td>
        <td><span class="badge-bug">Bug Fix</span></td>
        <td>Confluence Structured</td>
        <td>Anand Singh / Pratik Goyal (CData) + Ashima Purohit\'s team</td>
        <td>6-month production breakage. Pull Splunk logs, confirm API v1→v2 deprecation, request 3-sub-cycle hotfix</td>
      </tr>
      <tr>
        <td class="da-p1">P1 — Urgent</td>
        <td>Follow up with CData (Daniel Eich) on Shopify orderLineItems server-side filter — add created_at/updated_at</td>
        <td><span class="badge-bug">Bug Fix</span> <span class="badge-feat">Feature Request</span></td>
        <td>Shopify</td>
        <td>Sriram Sethuraman (PM) + Daniel Eich (CData)</td>
        <td>Unblocks Caspari Inc (11 tenants) — core commerce object unavailable for large merchants</td>
      </tr>
      <tr>
        <td class="da-p1">P1 — GA Blocker</td>
        <td>Document RTBF/data deletion behavior for Fabric connector before GA (regulatory)</td>
        <td><span class="badge-doc">Documentation</span></td>
        <td>Microsoft Fabric</td>
        <td>Gaurav Garg (PM) + Damian/Akanksha (Eng)</td>
        <td>Blocks GA for Raja Group and Emirates — regulated industries with compliance requirements</td>
      </tr>
      <tr>
        <td class="da-p2">P2 — High</td>
        <td>Expose CData query timeout as configurable connection parameter in UI</td>
        <td><span class="badge-bug">Bug Fix</span></td>
        <td>HubSpot, Shopify, Confluence, Box, GA4</td>
        <td>Ankit Arora\'s team (DCF Core Framework)</td>
        <td>Single engineering change unblocks large-dataset initial loads across 5+ connectors</td>
      </tr>
      <tr>
        <td class="da-p2">P2 — High</td>
        <td>Create end-to-end "Connector → UDL → Agentforce Knowledge" setup guide</td>
        <td><span class="badge-doc">Documentation</span></td>
        <td>SharePoint, Google Drive, Zendesk, Confluence</td>
        <td>PM (Gaurav/Keshav) + Docs (Lyman Ng)</td>
        <td>Deflects ~7 active tickets. Highest-value documentation gap as Agentforce use cases scale</td>
      </tr>
      <tr>
        <td class="da-p2">P2 — High</td>
        <td>Add AWS Lake Formation grants as required Step 0 in AWS Glue connector docs</td>
        <td><span class="badge-doc">Documentation</span></td>
        <td>AWS Glue (Zero Copy)</td>
        <td>Gaurav Garg (PM) + Lyman Ng (Docs)</td>
        <td>Most common root cause of "connects but no data" for AWS Glue. One doc change deflects entire issue class</td>
      </tr>
      <tr>
        <td class="da-p2">P2 — High</td>
        <td>Fix Google Drive supportsAllDrives=true missing from API calls + appProperties field naming bug</td>
        <td><span class="badge-bug">Bug Fix</span></td>
        <td>Google Drive</td>
        <td>Google Drive connector eng team</td>
        <td>GA blocker — Shared Drive content returns 404; appProperties bug is confirmed GA blocker</td>
      </tr>
      <tr>
        <td class="da-p3">P3 — Medium</td>
        <td>Document required OAuth scopes for HubSpot connector; expose OAuthRequiredScopes in UI</td>
        <td><span class="badge-doc">Documentation</span></td>
        <td>HubSpot</td>
        <td>Gaurav Garg (PM) + Engineering (DCF UI)</td>
        <td>Unblocks active GUS case W-21532326 (LavaBox) and all future HubSpot setup issues</td>
      </tr>
      <tr>
        <td class="da-p3">P3 — Medium</td>
        <td>Create SharePoint Structured URL format KB article; add wizard tooltip; improve gRPC error message</td>
        <td><span class="badge-doc">Documentation</span> <span class="badge-bug">Bug Fix</span></td>
        <td>SharePoint Structured</td>
        <td>Krassimira Iordanova (PM) + Mridul Agarwal (Eng)</td>
        <td>5 of 7 SharePoint Structured tickets trace to one root cause — correct URL format is undocumented</td>
      </tr>
      <tr>
        <td class="da-p3">P3 — Medium</td>
        <td>Add SuiteAnalytics Connect prerequisite to NetSuite docs; document Cosmos DB nesting behavior</td>
        <td><span class="badge-doc">Documentation</span></td>
        <td>NetSuite, Cosmos DB</td>
        <td>Sriram Sethuraman (PM) + Lyman Ng (Docs)</td>
        <td>Prevents setup failures that could be avoided entirely with a single prerequisite note</td>
      </tr>
      <tr>
        <td class="da-p3">P3 — Medium</td>
        <td>Procure permanent test accounts for NetSuite, Cosmos DB, Instagram, Elasticsearch, Zendesk</td>
        <td><span class="badge-notsup">Infrastructure</span></td>
        <td>5 connectors</td>
        <td>All PMs + Leadership</td>
        <td>GA prerequisite. Without test infrastructure, regression testing is impossible and production bugs go undetected</td>
      </tr>
    </tbody>
  </table>

</div><!-- end da-section -->
</div><!-- end da-body -->
<script>
function toggleDA(){
  const t=document.getElementById('daToggle');
  const b=document.getElementById('daBody');
  t.classList.toggle('open');
  b.classList.toggle('open');
}
</script>
'''


def build_html(issues, timestamp):
    issues_json = json.dumps(issues, ensure_ascii=True)
    html = HTML_TEMPLATE.replace('BUILD_TIMESTAMP', timestamp)
    html = html.replace('ISSUES_JSON_PLACEHOLDER', issues_json)
    # Inject Deep Analysis section before </body>
    html = html.replace('</body>\n</html>', DEEP_ANALYSIS_HTML + '\n</body>\n</html>')
    return html


def main(sheet_csv_path=None, gmail_json_path=None, issues_json_path=None):
    issues = []

    # Load from pre-built issues JSON (fastest path, used by cron)
    if issues_json_path and os.path.exists(issues_json_path):
        with open(issues_json_path) as f:
            issues = json.load(f)
        print(f"Loaded {len(issues)} issues from {issues_json_path}")

    # Or build from sheet CSV + gmail JSON
    else:
        if sheet_csv_path and os.path.exists(sheet_csv_path):
            with open(sheet_csv_path) as f:
                issues += parse_sheet_issues(f.read())
            print(f"Parsed {len(issues)} issues from sheet")

        if gmail_json_path and os.path.exists(gmail_json_path):
            with open(gmail_json_path) as f:
                gmail_data = json.load(f)
            email_issues = build_email_issues(gmail_data)
            issues += email_issues
            print(f"Parsed {len(email_issues)} issues from Gmail")

    if not issues:
        print("WARNING: No issues found. Dashboard will be empty.", file=sys.stderr)

    # Backfill connector_type and pm_owner for any issues missing them
    for issue in issues:
        if not issue.get('connector_type') or issue['connector_type'] == 'Unknown':
            ct, pm = classify_connector(issue.get('connector', ''))
            issue['connector_type'] = ct
            if not issue.get('pm_owner') or issue['pm_owner'] == 'Unknown':
                issue['pm_owner'] = pm

    timestamp = datetime.now().strftime("%B %d, %Y %I:%M %p")
    html = build_html(issues, timestamp)

    with open(DASHBOARD_PATH, 'w') as f:
        f.write(html)
    print(f"Dashboard written to {DASHBOARD_PATH} ({len(issues)} issues, {timestamp})")

    # Deploy to Heroku
    deploy_to_heroku(html, timestamp)

    return DASHBOARD_PATH


def deploy_to_heroku(html, timestamp):
    """Copy updated HTML to the Heroku app repo and git push to redeploy."""
    import subprocess
    static_path = os.path.join(HEROKU_APP_DIR, 'public', 'index.html')
    if not os.path.isdir(HEROKU_APP_DIR):
        print(f"WARNING: Heroku app dir not found at {HEROKU_APP_DIR}, skipping deploy.", file=sys.stderr)
        return
    with open(static_path, 'w') as f:
        f.write(html)
    result = subprocess.run(
        ['git', 'add', 'public/index.html'],
        cwd=HEROKU_APP_DIR, capture_output=True, text=True
    )
    result = subprocess.run(
        ['git', 'commit', '-m', f'Dashboard refresh: {timestamp}'],
        cwd=HEROKU_APP_DIR, capture_output=True, text=True
    )
    if 'nothing to commit' in result.stdout + result.stderr:
        print("Heroku: no changes to deploy.")
        return
    push = subprocess.run(
        ['git', 'push', 'heroku', 'main'],
        cwd=HEROKU_APP_DIR, capture_output=True, text=True
    )
    if push.returncode == 0:
        print("Heroku deploy: success — https://dc-connectors-dashboard-75f6dd75b882.herokuapp.com/")
    else:
        print(f"Heroku deploy failed: {push.stderr[-300:]}", file=sys.stderr)


if __name__ == '__main__':
    # Called directly: rebuild from last known data cache
    cache = DATA_PATH if os.path.exists(DATA_PATH) else None
    out = main(issues_json_path=cache)
    print(f"Done: {out}")
