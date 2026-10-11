"""
rail_report.py — Monthly state shipment progress email for jsagroup@jpsi.com

Pulls USDA AMS rail data, computes MYtD state totals vs prior year,
and emails an HTML report via Microsoft Graph (app-only OAuth).

Usage:
    python rail_report.py              # send the report now
    python rail_report.py --preview    # print HTML to stdout, no send

Cron (droplet, 1st of each month at 6:00 AM):
    0 6 1 * * /root/usda-rail-dashboard/venv/bin/python /root/usda-rail-dashboard/rail_report.py
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, date
from pathlib import Path

import numpy as np
import pandas as pd
import requests

# ── Config ─────────────────────────────────────────────────────────────────────
API_URL      = "https://agtransport.usda.gov/resource/27k8-utc2.json"
CARS_TO_BU   = 4_000
MIN_COMPLETE_WEEK = 48
TO_ADDR      = "jsagroup@jpsi.com"
SENDER       = os.environ.get("GRAPH_SENDER", "basis-tracker@jpsi.com")
FROM_NAME    = "JSA Rail Dashboard"

JPSI_DARK = "#32373c"
JPSI_BLUE = "#0693e3"
GREEN     = "#16a34a"
RED       = "#dc2626"

# ── Data ───────────────────────────────────────────────────────────────────────
def _load() -> pd.DataFrame:
    rows, limit, offset = [], 50_000, 0
    while True:
        r = requests.get(
            API_URL,
            params={"$limit": limit, "$offset": offset, "$order": "date ASC"},
            timeout=90,
        )
        r.raise_for_status()
        batch = r.json()
        rows.extend(batch)
        if len(batch) < limit:
            break
        offset += limit

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df["all"]  = pd.to_numeric(df["all"], errors="coerce").fillna(0).astype(int)
    df         = df.rename(columns={"all": "carloads"})
    df["est_bushels"] = df["carloads"] * CARS_TO_BU

    m, y = df["date"].dt.month, df["date"].dt.year
    is_sep = m >= 9
    sy = np.where(is_sep, y, y - 1)
    df["marketing_year"] = [f"{s}/{str(s+1)[2:]}" for s in sy]
    my_starts = pd.to_datetime({"year": sy, "month": np.full(len(df), 9), "day": np.full(len(df), 1)})
    df["my_week"] = ((df["date"] - my_starts).dt.days // 7 + 1).astype(int)

    return df[["date", "marketing_year", "my_week", "railroad", "state", "carloads", "est_bushels"]]


def _oly_avg(vals: list) -> int:
    v = sorted(x for x in vals if x > 0)
    if len(v) >= 4:
        v = v[1:-1]
    return int(np.mean(v)) if v else 0


def _fmt_bu(n: float) -> str:
    n = int(n) if pd.notna(n) else 0
    if n >= 1_000_000_000: return f"{n/1_000_000_000:.2f}B"
    if n >= 1_000_000:     return f"{n/1_000_000:.1f}M"
    return f"{n:,.0f}"


def _fmt_pct(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%"


# ── Build report ───────────────────────────────────────────────────────────────
def build_report(df: pd.DataFrame) -> tuple[str, str]:
    """Returns (subject, html_body)."""
    all_years  = sorted(df["marketing_year"].unique(), reverse=True)
    current_my = all_years[0]

    wk_max = df.groupby("marketing_year")["my_week"].max()
    comp_yrs = sorted(y for y, w in wk_max.items() if w >= MIN_COMPLETE_WEEK)

    cur_df  = df[df["marketing_year"] == current_my]
    max_wk  = int(cur_df["my_week"].max()) if len(cur_df) else 0
    ly      = comp_yrs[-1] if comp_yrs else None
    oly_pool = comp_yrs[-6:] if comp_yrs else []

    latest_date = df["date"].max().strftime("%B %d, %Y")
    now_label   = datetime.now().strftime("%B %Y")

    # ── National summary ────────────────────────────────────────────────────────
    cur_tot = int(df[(df["marketing_year"] == current_my) & (df["my_week"] <= max_wk)]["est_bushels"].sum())
    ly_tot  = int(df[(df["marketing_year"] == ly) & (df["my_week"] <= max_wk)]["est_bushels"].sum()) if ly else 0
    nat_pct = ((cur_tot - ly_tot) / ly_tot * 100) if ly_tot else None

    # ── State table ─────────────────────────────────────────────────────────────
    all_states = sorted(df["state"].unique())
    state_rows = []
    for s in all_states:
        cur_s = int(df[(df["marketing_year"] == current_my) & (df["my_week"] <= max_wk) & (df["state"] == s)]["est_bushels"].sum())
        ly_s  = int(df[(df["marketing_year"] == ly) & (df["my_week"] <= max_wk) & (df["state"] == s)]["est_bushels"].sum()) if ly else 0
        oly_s = _oly_avg([
            int(df[(df["marketing_year"] == y) & (df["my_week"] <= max_wk) & (df["state"] == s)]["est_bushels"].sum())
            for y in oly_pool
        ]) if oly_pool else 0
        if cur_s == 0:
            continue
        pct_ly  = (cur_s - ly_s)  / ly_s  * 100 if ly_s  else None
        pct_oly = (cur_s - oly_s) / oly_s * 100 if oly_s else None
        state_rows.append({
            "State": s, "MYtD Bu": cur_s,
            "vs LY Bu": cur_s - ly_s, "% vs LY": pct_ly,
            "vs 6yr Avg": cur_s - oly_s, "% vs Avg": pct_oly,
        })

    state_rows.sort(key=lambda x: x["MYtD Bu"], reverse=True)

    # ── HTML ────────────────────────────────────────────────────────────────────
    def _pct_cell(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return "<td style='text-align:right;color:#6b7280'>—</td>"
        color = GREEN if v >= 0 else RED
        arrow = "▲" if v >= 0 else "▼"
        return f"<td style='text-align:right;color:{color};font-weight:600'>{arrow} {abs(v):.1f}%</td>"

    table_rows = ""
    for i, r in enumerate(state_rows):
        bg = "#f9fafb" if i % 2 else "#ffffff"
        vs_ly_color = GREEN if r["vs LY Bu"] >= 0 else RED
        table_rows += f"""
        <tr style='background:{bg}'>
          <td style='padding:6px 10px;font-weight:600;color:{JPSI_DARK}'>{r["State"]}</td>
          <td style='text-align:right;padding:6px 10px'>{_fmt_bu(r["MYtD Bu"])} bu</td>
          <td style='text-align:right;padding:6px 10px;color:{vs_ly_color}'>{_fmt_bu(abs(r["vs LY Bu"]))} bu {"▲" if r["vs LY Bu"] >= 0 else "▼"}</td>
          {_pct_cell(r["% vs LY"])}
          {_pct_cell(r["% vs Avg"])}
        </tr>"""

    nat_color = GREEN if (nat_pct or 0) >= 0 else RED
    nat_arrow = "▲" if (nat_pct or 0) >= 0 else "▼"
    nat_pct_str = f"{nat_arrow} {abs(nat_pct):.1f}%" if nat_pct is not None else "—"

    html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:'Segoe UI',Arial,sans-serif">
<div style="max-width:700px;margin:24px auto;background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08)">

  <!-- Header -->
  <div style="background:{JPSI_DARK};padding:20px 28px;display:flex;align-items:center;gap:16px">
    <img src="https://www.jpsi.com/wp-content/themes/gate39media/img/logo-white.png"
         height="36" style="object-fit:contain" alt="JSA">
    <div>
      <div style="color:#ffffff;font-size:18px;font-weight:700">Grain Rail Shipment Report</div>
      <div style="color:#9ca3af;font-size:13px">{now_label} · Data through {latest_date}</div>
    </div>
  </div>

  <!-- Summary cards -->
  <div style="padding:20px 28px;background:#f0f7ff;border-bottom:1px solid #e2e8f0">
    <div style="font-size:12px;color:#6b7280;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px">
      {current_my} Marketing Year · Week {max_wk} MYtD · vs {ly or "N/A"}
    </div>
    <div style="display:flex;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;gap:16px">
      <div style="display:flex;gap:32px;flex-wrap:wrap">
        <div>
          <div style="font-size:22px;font-weight:700;color:{JPSI_DARK}">{_fmt_bu(cur_tot)} bu</div>
          <div style="font-size:12px;color:#6b7280">Total MYtD Shipments</div>
        </div>
        <div>
          <div style="font-size:22px;font-weight:700;color:{nat_color}">{nat_pct_str}</div>
          <div style="font-size:12px;color:#6b7280">vs Prior Year</div>
        </div>
        <div>
          <div style="font-size:22px;font-weight:700;color:{JPSI_DARK}">{_fmt_bu(ly_tot)} bu</div>
          <div style="font-size:12px;color:#6b7280">{ly} MYtD (same weeks)</div>
        </div>
      </div>
      <a href="https://jsa-us-rail-dashboard.streamlit.app"
         style="display:inline-block;background:{JPSI_BLUE};color:#ffffff;font-size:13px;font-weight:600;
                padding:10px 18px;border-radius:6px;text-decoration:none;white-space:nowrap;
                align-self:center">
        View Dashboard →
      </a>
    </div>
  </div>

  <!-- State table -->
  <div style="padding:20px 28px">
    <div style="font-size:14px;font-weight:700;color:{JPSI_DARK};margin-bottom:12px">
      State Shipment Progress — MYtD Week {max_wk}
    </div>
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead>
        <tr style="background:{JPSI_DARK};color:#ffffff">
          <th style="padding:8px 10px;text-align:left;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.04em">State</th>
          <th style="padding:8px 10px;text-align:right;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.04em">MYtD</th>
          <th style="padding:8px 10px;text-align:right;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.04em">vs LY</th>
          <th style="padding:8px 10px;text-align:right;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.04em">% vs LY</th>
          <th style="padding:8px 10px;text-align:right;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.04em">% vs 6yr Avg</th>
        </tr>
      </thead>
      <tbody>
        {table_rows}
      </tbody>
    </table>
  </div>

  <!-- Footer -->
  <div style="padding:16px 28px;background:#f9fafb;border-top:1px solid #e2e8f0;font-size:11px;color:#9ca3af">
    Source: USDA AMS Agricultural Transportation Hub &nbsp;·&nbsp;
    <a href="https://jsa-us-rail-dashboard.streamlit.app" style="color:{JPSI_BLUE}">View live dashboard</a>
    &nbsp;·&nbsp; John Stewart &amp; Associates, Inc.
  </div>

</div>
</body>
</html>"""

    subject = f"JSA Rail Shipment Update — {now_label} (Week {max_wk}, {current_my} MY)"
    return subject, html


# ── Email send ─────────────────────────────────────────────────────────────────
def _send(subject: str, html: str) -> None:
    import msal

    tenant = os.environ["GRAPH_TENANT_ID"]
    client = os.environ["GRAPH_CLIENT_ID"]
    secret = os.environ["GRAPH_CLIENT_SECRET"]
    sender = os.environ.get("GRAPH_SENDER", "basis-tracker@jpsi.com")

    app = msal.ConfidentialClientApplication(
        client_id=client,
        authority=f"https://login.microsoftonline.com/{tenant}",
        client_credential=secret,
    )
    tok = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    access = tok.get("access_token")
    if not access:
        raise RuntimeError(f"Graph auth failed: {tok.get('error_description') or tok}")

    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": html},
            "toRecipients": [{"emailAddress": {"address": TO_ADDR}}],
            "from": {"emailAddress": {"address": sender, "name": FROM_NAME}},
        },
        "saveToSentItems": True,
    }

    r = requests.post(
        f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail",
        headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    print(f"Sent: {subject}")


# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true", help="Print HTML, don't send")
    args = parser.parse_args()

    # Load .env if present
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    print("Fetching USDA rail data…")
    df = _load()
    print(f"Loaded {len(df):,} rows through {df['date'].max().date()}")

    subject, html = build_report(df)
    print(f"Subject: {subject}")

    if args.preview:
        print(html)
    else:
        _send(subject, html)
