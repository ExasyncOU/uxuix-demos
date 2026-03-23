"""
report.py - GV Overconfirmation v2.0 - Notifications + HTML Report + Push

Start-Notification, HTML-Report-Generierung, Report-Push via Edge Function.
"""

import json
import urllib.request
from datetime import date, datetime

from config import (
    REPORT, DRY_RUN, IDIS_USER, REPORT_URL, MACHINE_TOKEN,
    EMAIL_TO, EMAIL_CC, EMAIL_BCC, P,
)


# ======================================================================
# START-BENACHRICHTIGUNG
# ======================================================================
def push_start_notification():
    """Sendet Start-Email via Supabase Edge Function."""
    if not REPORT_URL or not MACHINE_TOKEN:
        P("  Start-Notification uebersprungen (kein REPORT_URL oder MACHINE_TOKEN)")
        return
    today = date.today().strftime("%d.%m.%Y")
    mode = "DRY RUN" if DRY_RUN else "PRODUCTION"
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px">
    <div style="background:#1a5276;color:white;padding:12px 20px;border-radius:8px">
        <h2 style="margin:0;font-size:18px">GV Overconfirmation gestartet</h2>
        <p style="margin:4px 0 0;opacity:0.8">{today} | {IDIS_USER} | {mode} | v2.0</p>
    </div>
    <p style="margin-top:12px;color:#555">
        IDIS User <b>{IDIS_USER}</b> wird verarbeitet (bidirektional: oben + unten gleichzeitig).
    </p>
</body></html>"""
    try:
        payload = {
            "machine_token": MACHINE_TOKEN,
            "report_type": "gv_overconfirmation_start",
            "email_to": EMAIL_TO,
            "email_cc": EMAIL_CC,
            "email_bcc": EMAIL_BCC,
            "data": {"date": str(date.today()), "user": IDIS_USER, "mode": mode},
            "html_report": html,
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            REPORT_URL, data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        if result.get("email", {}).get("sent"):
            P(f"  Start-Notification gesendet")
        else:
            P(f"  Start-Notification: {result.get('email', {}).get('error', 'unbekannt')[:60]}")
    except Exception as e:
        P(f"  Start-Notification fehlgeschlagen: {str(e)[:60]}")


# ======================================================================
# REPORT HTML GENERIERUNG
# ======================================================================
def generate_report_html():
    """Generiert den vollstaendigen HTML-Report."""
    today = date.today().strftime("%d.%m.%Y")
    dur = REPORT["duration_seconds"]
    dur_str = f"{int(dur // 60)}m {int(dur % 60)}s"

    td = 'style="padding:6px 12px;border:1px solid #ddd"'
    td_c = 'style="padding:6px 12px;border:1px solid #ddd;text-align:center"'
    td_s = 'style="padding:4px 8px;border:1px solid #ddd;font-size:13px"'

    mode_badge = ('<span style="background:#e67e22;color:white;padding:2px 8px;border-radius:4px;'
                  'font-size:12px">DRY RUN</span>' if DRY_RUN else
                  '<span style="background:#27ae60;color:white;padding:2px 8px;border-radius:4px;'
                  'font-size:12px">PRODUCTION</span>')

    bi_badge = ('<span style="background:#2563eb;color:white;padding:2px 8px;border-radius:4px;'
                'font-size:12px">BIDIREKTIONAL</span>' if REPORT["bidirectional"] else
                '<span style="background:#7f8c8d;color:white;padding:2px 8px;border-radius:4px;'
                'font-size:12px">ZIGZAG</span>')

    # Zusammenfassung
    summary_html = f"""
    <table style="border-collapse:collapse;width:100%;margin-top:12px">
        <tr><td {td} style="font-weight:bold">User</td><td {td}>{REPORT['user']}</td></tr>
        <tr><td {td} style="font-weight:bold">Orders gesamt</td><td {td_c}>{REPORT['total_orders']}</td></tr>
        <tr><td {td} style="font-weight:bold">Verarbeitet</td><td {td_c} style="color:#27ae60">{REPORT['total_amended']}</td></tr>
        <tr><td {td} style="font-weight:bold">Already processed</td><td {td_c}>{REPORT['total_already_processed']}</td></tr>
        <tr><td {td} style="font-weight:bold">Skipped (Bundle=0)</td><td {td_c}>{REPORT['total_skipped']}</td></tr>
        <tr><td {td} style="font-weight:bold">Fehler</td><td {td_c} style="color:{'#c0392b' if REPORT['total_errors'] > 0 else '#27ae60'}">{REPORT['total_errors']}</td></tr>
    </table>"""

    # Amendments Detail
    amend_html = ""
    if REPORT["amended_details"]:
        amend_rows = ""
        for a in REPORT["amended_details"]:
            amend_rows += f"""<tr>
                <td {td_s}>{a['order']}</td>
                <td {td_s} style="text-align:center">{a.get('direction', '')}</td>
                <td {td_s} style="text-align:right">{a['ordered']}</td>
                <td {td_s} style="text-align:right">{a['old_committed']}</td>
                <td {td_s} style="text-align:right;font-weight:bold">{a['new_committed']}</td>
                <td {td_s} style="text-align:right;color:#2563eb">+{a['delta']}</td>
                <td {td_s} style="text-align:center">{a['bundle']}</td>
            </tr>"""
        amend_html = f"""
        <h2 style="color:#2563eb;margin-top:24px">Hochgesetzte Orders ({len(REPORT['amended_details'])})</h2>
        <table style="border-collapse:collapse;width:100%">
            <tr style="background:#2563eb;color:white">
                <th style="padding:6px 8px;text-align:left">Order</th>
                <th style="padding:6px 8px;text-align:center">Richtung</th>
                <th style="padding:6px 8px;text-align:right">Bestellt</th>
                <th style="padding:6px 8px;text-align:right">Alt</th>
                <th style="padding:6px 8px;text-align:right">Neu</th>
                <th style="padding:6px 8px;text-align:right">Delta</th>
                <th style="padding:6px 8px;text-align:center">Bundle</th>
            </tr>
            {amend_rows}
        </table>"""

    # Fehler
    error_html = ""
    if REPORT["errors"]:
        error_rows = ""
        for e in REPORT["errors"]:
            error_rows += f"""<tr>
                <td {td_s}>{e['order']}</td>
                <td {td_s}>{e['reason']}</td>
                <td {td_s}>{e.get('details', '')}</td>
            </tr>"""
        error_html = f"""
        <h2 style="color:#c0392b;margin-top:24px">Fehler ({len(REPORT['errors'])})</h2>
        <table style="border-collapse:collapse;width:100%">
            <tr style="background:#c0392b;color:white">
                <th style="padding:6px 8px;text-align:left">Order</th>
                <th style="padding:6px 8px;text-align:left">Grund</th>
                <th style="padding:6px 8px;text-align:left">Details</th>
            </tr>
            {error_rows}
        </table>"""
    else:
        error_html = '<p style="color:#27ae60;font-weight:bold;margin-top:16px">Keine Fehler.</p>'

    # Warnings
    warn_html = ""
    if REPORT["warnings"]:
        warn_items = "".join(f"<li>{w}</li>" for w in REPORT["warnings"])
        warn_html = f'<h3 style="color:#e67e22;margin-top:16px">Hinweise</h3><ul>{warn_items}</ul>'

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:800px;margin:0 auto;padding:20px;color:#333">
    <div style="background:#1a5276;color:white;padding:16px 24px;border-radius:8px 8px 0 0">
        <h1 style="margin:0;font-size:20px">GV Spedition OC Report {mode_badge} {bi_badge}</h1>
        <p style="margin:4px 0 0;opacity:0.8">{today} | {REPORT['user']} | Dauer: {dur_str} | v2.0</p>
    </div>
    <div style="background:#f8f9fa;padding:20px 24px;border:1px solid #ddd;border-top:none">
        {summary_html}
        {amend_html}
        {error_html}
        {warn_html}
    </div>
    <div style="background:#ecf0f1;padding:12px 24px;border-radius:0 0 8px 8px;border:1px solid #ddd;border-top:none;font-size:12px;color:#7f8c8d">
        GV Overconfirmation v2.0 (modular) | Exasync IDIS Automation | {datetime.now().strftime('%H:%M:%S')}
    </div>
</body></html>"""
    return html


# ======================================================================
# REPORT PUSH (Supabase Edge Function)
# ======================================================================
def push_report(html_report=""):
    """Pusht den Report an die Supabase Edge Function und sendet Email."""
    if not REPORT_URL or not MACHINE_TOKEN:
        P("  Report-Push uebersprungen (kein REPORT_URL oder MACHINE_TOKEN)")
        return
    try:
        payload = {
            "machine_token": MACHINE_TOKEN,
            "report_type": "gv_overconfirmation",
            "data": REPORT,
            "email_to": EMAIL_TO,
            "email_cc": EMAIL_CC,
            "email_bcc": EMAIL_BCC,
        }
        if html_report:
            payload["html_report"] = html_report

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            REPORT_URL, data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        P(f"  Report gepusht: {result.get('ok', False)}")
        email = result.get("email", {})
        if email.get("sent"):
            P(f"  Email gesendet an: {email.get('to', EMAIL_TO)}")
        elif email.get("error"):
            P(f"  Email fehlgeschlagen: {email.get('error', '')[:60]}")
    except Exception as e:
        P(f"  Report push fehlgeschlagen: {str(e)[:80]}")
