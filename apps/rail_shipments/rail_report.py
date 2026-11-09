"""
rail_report.py — Monthly grain rail shipment email for jsagroup@jpsi.com

Pulls USDA AMS rail data, builds three charts (railroad % vs LY, state
progress, weekly MY trend) plus the full state table, and emails an HTML
report via Microsoft Graph.

Usage:
    python rail_report.py              # send the report now
    python rail_report.py --preview    # write _rail_preview.html; no send

Cron (droplet, first business day of each month — guard in run_rail_report.sh):
    0 6 1-3 * 1-5  /root/usda-rail-dashboard/venv/bin/bash /root/usda-rail-dashboard/deploy/run_rail_report.sh
"""
from __future__ import annotations

import argparse
import base64
import io
import os
import sys
import tempfile
from datetime import datetime, date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import requests

# ── Brand / config ─────────────────────────────────────────────────────────────
JPSI_DARK  = "#32373c"
JPSI_BLUE  = "#0693e3"
GREEN      = "#16a34a"
RED        = "#dc2626"
GRAY_LIGHT = "#f8fafc"
BORDER_CLR = "#e2e8f0"
TEXT_MUTED = "#64748b"

API_URL           = "https://agtransport.usda.gov/resource/27k8-utc2.json"
CARS_TO_BU        = 4_000
MIN_COMPLETE_WEEK = 48

TO_ADDR    = "jsagroup@jpsi.com"
BCC_ADDR   = "rail@jpsi.com"
SENDER     = os.environ.get("GRAPH_SENDER", "basis-tracker@jpsi.com")
FROM_NAME  = "JSA Rail Dashboard"

DASH_URL   = "https://jsa-us-rail-dashboard.streamlit.app"
JPSI_LOGO  = "https://www.jpsi.com/wp-content/themes/gate39media/img/logo-white.png"

# Chart layout
CHART_W    = 7.8    # inches — fills 700px email container at 90dpi
CHART_DPI  = 110

# My-year color palette (current year first = green)
MY_PALETTE = [
    "#16a34a", "#0693e3", "#d97706", "#7c3aed",
    "#dc2626", "#0891b2", "#6b7280",
]

DISCLAIMER = (
    "Source: USDA AMS Agricultural Transportation Hub. This communication is provided "
    "for informational purposes only and does not constitute investment advice. "
    "Information is believed reliable but accuracy is not guaranteed. "
    "&copy; John Stewart &amp; Associates, Inc. 2026"
)


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
    df["date"]    = pd.to_datetime(df["date"])
    df["all"]     = pd.to_numeric(df["all"], errors="coerce").fillna(0).astype(int)
    df            = df.rename(columns={"all": "carloads"})
    df["est_bushels"] = df["carloads"] * CARS_TO_BU

    m, y   = df["date"].dt.month, df["date"].dt.year
    is_sep = m >= 9
    sy     = np.where(is_sep, y, y - 1)
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


# ── Chart helpers ──────────────────────────────────────────────────────────────
def _wm(ax):
    """JSA watermark on chart."""
    ax.text(0.5, 0.5, "JOHN STEWART\nAND ASSOCIATES", transform=ax.transAxes,
            fontsize=20, color="#32373c", alpha=0.06, ha="center", va="center",
            rotation=30, fontweight="bold", family="sans-serif")


def _chart_style(ax):
    """Shared clean axis style."""
    ax.set_facecolor("white")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(BORDER_CLR)
    ax.spines["bottom"].set_color(BORDER_CLR)
    ax.tick_params(colors=TEXT_MUTED, labelsize=8.5)
    ax.yaxis.grid(True, color="#f1f5f9", linewidth=0.8, zorder=0)


def _png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=CHART_DPI, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ── Chart 1: Railroad % vs LY ──────────────────────────────────────────────────
def chart_railroad_pct(df: pd.DataFrame, current_my: str, max_wk: int, ly: str | None) -> bytes:
    rr_data = []
    for rr in sorted(df["railroad"].dropna().unique()):
        cur = int(df[(df.marketing_year == current_my) & (df.my_week <= max_wk) & (df.railroad == rr)]["est_bushels"].sum())
        ly_v = int(df[(df.marketing_year == ly) & (df.my_week <= max_wk) & (df.railroad == rr)]["est_bushels"].sum()) if ly else 0
        if cur > 0 and ly_v > 0:
            rr_data.append((rr, (cur - ly_v) / ly_v * 100))

    if not rr_data:
        fig, ax = plt.subplots(figsize=(CHART_W, 2.8))
        ax.text(0.5, 0.5, "No railroad data", ha="center", va="center", transform=ax.transAxes)
        return _png(fig)

    names, pcts = zip(*rr_data)
    colors = [GREEN if p >= 0 else RED for p in pcts]

    fig, ax = plt.subplots(figsize=(CHART_W, 3.0))
    ax.set_facecolor("white")
    fig.patch.set_facecolor("white")

    bars = ax.bar(names, pcts, color=colors, width=0.55, zorder=3)
    ax.axhline(0, color="#94a3b8", linewidth=0.8, zorder=2)

    for bar, pct in zip(bars, pcts):
        y_pos = pct + (0.5 if pct >= 0 else -0.5)
        va    = "bottom" if pct >= 0 else "top"
        ax.text(bar.get_x() + bar.get_width() / 2, y_pos, f"{pct:+.1f}%",
                ha="center", va=va, fontsize=8.5, fontweight="bold", color=JPSI_DARK)

    ax.set_title(f"Railroad % vs Last Year — {current_my} MYtD (Week {max_wk})",
                 fontsize=10.5, fontweight="bold", color=JPSI_DARK, pad=8)
    ax.set_ylabel("% vs LY", fontsize=8.5, color=TEXT_MUTED)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:+.0f}%"))
    _chart_style(ax)
    _wm(ax)
    plt.tight_layout(pad=0.8)
    return _png(fig)


# ── Chart 2: State progress horizontal bar ─────────────────────────────────────
def chart_state_pct(state_rows: list) -> bytes:
    rows = [r for r in state_rows if r["% vs LY"] is not None and not np.isnan(r["% vs LY"])]
    rows.sort(key=lambda r: r["% vs LY"], reverse=True)

    # top 8 positive + top 7 negative (or fewer if not enough)
    pos = [r for r in rows if r["% vs LY"] >= 0][:8]
    neg = [r for r in rows if r["% vs LY"] <  0][-7:]
    show = pos + neg
    show.sort(key=lambda r: r["% vs LY"])   # ascending for horizontal chart

    if not show:
        fig, ax = plt.subplots(figsize=(CHART_W, 2.8))
        ax.text(0.5, 0.5, "No state data", ha="center", va="center", transform=ax.transAxes)
        return _png(fig)

    labels = [r["State"] for r in show]
    pcts   = [r["% vs LY"] for r in show]
    colors = [GREEN if p >= 0 else RED for p in pcts]
    h      = max(3.0, len(show) * 0.32)

    fig, ax = plt.subplots(figsize=(CHART_W, h))
    ax.set_facecolor("white")
    fig.patch.set_facecolor("white")

    bars = ax.barh(labels, pcts, color=colors, height=0.6, zorder=3)
    ax.axvline(0, color="#94a3b8", linewidth=0.8, zorder=2)

    for bar, pct in zip(bars, pcts):
        x_pos = pct + (0.5 if pct >= 0 else -0.5)
        ha    = "left" if pct >= 0 else "right"
        ax.text(x_pos, bar.get_y() + bar.get_height() / 2, f"{pct:+.1f}%",
                ha=ha, va="center", fontsize=8, fontweight="bold", color=JPSI_DARK)

    ax.set_title(f"State % vs Last Year — MYtD",
                 fontsize=10.5, fontweight="bold", color=JPSI_DARK, pad=8)
    ax.set_xlabel("% vs LY", fontsize=8.5, color=TEXT_MUTED)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:+.0f}%"))
    ax.tick_params(axis="y", labelsize=8.5, colors=JPSI_DARK)
    _chart_style(ax)
    _wm(ax)
    plt.tight_layout(pad=0.8)
    return _png(fig)


# ── Chart 3: Weekly shipments by marketing year ────────────────────────────────
def chart_weekly_my(df: pd.DataFrame) -> bytes:
    all_years = sorted(df["marketing_year"].unique(), reverse=True)
    show_yrs  = all_years[:6]     # current + 5 prior

    weekly = (
        df.groupby(["marketing_year", "my_week"])["est_bushels"]
        .sum()
        .reset_index()
    )
    weekly["est_bu_m"] = weekly["est_bushels"] / 1_000_000

    max_wk_current = int(weekly[weekly.marketing_year == show_yrs[0]]["my_week"].max()) if show_yrs else 52
    x_max = max(max_wk_current + 2, 20)

    fig, ax = plt.subplots(figsize=(CHART_W, 3.2))
    ax.set_facecolor("white")
    fig.patch.set_facecolor("white")

    for i, yr in enumerate(reversed(show_yrs)):
        d   = weekly[weekly.marketing_year == yr].sort_values("my_week")
        lw  = 2.2 if i == len(show_yrs) - 1 else 1.3
        alp = 1.0 if i == len(show_yrs) - 1 else 0.75
        ax.plot(d["my_week"], d["est_bu_m"], color=MY_PALETTE[len(show_yrs) - 1 - i],
                linewidth=lw, alpha=alp, label=yr, zorder=3)

    ax.set_title("Weekly Grain Rail Shipments by Marketing Year",
                 fontsize=10.5, fontweight="bold", color=JPSI_DARK, pad=8)
    ax.set_xlabel("Marketing Year Week", fontsize=8.5, color=TEXT_MUTED)
    ax.set_ylabel("Est. Bushels (M)", fontsize=8.5, color=TEXT_MUTED)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}M"))
    ax.set_xlim(1, x_max)
    ax.legend(fontsize=7.5, loc="upper right", framealpha=0.85, edgecolor=BORDER_CLR)
    _chart_style(ax)
    _wm(ax)
    plt.tight_layout(pad=0.8)
    return _png(fig)


# ── HTML img tag ───────────────────────────────────────────────────────────────
def _img_tag(png: bytes, cid: str | None, *, for_preview: bool) -> str:
    """Return <img> tag: data: URL for preview, cid: for send."""
    if for_preview:
        b64 = base64.b64encode(png).decode("ascii")
        src = f"data:image/png;base64,{b64}"
    else:
        src = f"cid:{cid}"
    return (
        f'<div style="margin:12px 0;border-radius:6px;overflow:hidden;'
        f'border:1px solid {BORDER_CLR}">'
        f'<img src="{src}" alt="chart" style="width:100%;display:block;max-width:100%">'
        f'</div>'
    )


# ── Build report ───────────────────────────────────────────────────────────────
def build_report(df: pd.DataFrame, *, for_preview: bool = False) -> tuple[str, str, dict]:
    """Returns (subject, html_body, inline_images).

    inline_images is {cid: png_bytes} — only populated when not for_preview.
    """
    all_years  = sorted(df["marketing_year"].unique(), reverse=True)
    current_my = all_years[0]

    wk_max    = df.groupby("marketing_year")["my_week"].max()
    comp_yrs  = sorted(y for y, w in wk_max.items() if w >= MIN_COMPLETE_WEEK)
    ly        = comp_yrs[-1] if comp_yrs else None
    oly_pool  = comp_yrs[-6:] if comp_yrs else []

    cur_df    = df[df["marketing_year"] == current_my]
    max_wk    = int(cur_df["my_week"].max()) if len(cur_df) else 0
    latest_dt = df["date"].max().strftime("%B %d, %Y")
    now_label = datetime.now().strftime("%B %Y")

    # ── National totals ──────────────────────────────────────────────────────
    cur_tot = int(df[(df.marketing_year == current_my) & (df.my_week <= max_wk)]["est_bushels"].sum())
    ly_tot  = int(df[(df.marketing_year == ly) & (df.my_week <= max_wk)]["est_bushels"].sum()) if ly else 0
    nat_pct = ((cur_tot - ly_tot) / ly_tot * 100) if ly_tot else None

    # ── State rows ───────────────────────────────────────────────────────────
    all_states = sorted(df["state"].unique())
    state_rows = []
    for s in all_states:
        cur_s = int(df[(df.marketing_year == current_my) & (df.my_week <= max_wk) & (df.state == s)]["est_bushels"].sum())
        ly_s  = int(df[(df.marketing_year == ly) & (df.my_week <= max_wk) & (df.state == s)]["est_bushels"].sum()) if ly else 0
        oly_s = _oly_avg([
            int(df[(df.marketing_year == y) & (df.my_week <= max_wk) & (df.state == s)]["est_bushels"].sum())
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

    # ── Generate charts ──────────────────────────────────────────────────────
    print("Generating charts…")
    png_rr    = chart_railroad_pct(df, current_my, max_wk, ly)
    png_state = chart_state_pct(state_rows)
    png_wkly  = chart_weekly_my(df)

    inline_images: dict = {}
    CID_RR    = "chart_rr_pct"
    CID_STATE = "chart_state_pct"
    CID_WKLY  = "chart_weekly_my"

    if not for_preview:
        inline_images = {
            CID_RR:    png_rr,
            CID_STATE: png_state,
            CID_WKLY:  png_wkly,
        }

    img_rr    = _img_tag(png_rr,    CID_RR,    for_preview=for_preview)
    img_state = _img_tag(png_state, CID_STATE, for_preview=for_preview)
    img_wkly  = _img_tag(png_wkly,  CID_WKLY,  for_preview=for_preview)

    # ── State table HTML ─────────────────────────────────────────────────────
    def _pct_cell(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return "<td style='text-align:right;color:#9ca3af;padding:7px 10px'>—</td>"
        color = GREEN if v >= 0 else RED
        arrow = "▲" if v >= 0 else "▼"
        return f"<td style='text-align:right;color:{color};font-weight:600;padding:7px 10px'>{arrow} {abs(v):.1f}%</td>"

    table_rows = ""
    for i, r in enumerate(state_rows):
        bg = "#f9fafb" if i % 2 else "#ffffff"
        vs_ly_color = GREEN if r["vs LY Bu"] >= 0 else RED
        table_rows += (
            f"<tr style='background:{bg}'>"
            f"<td style='padding:7px 10px;font-weight:600;color:{JPSI_DARK}'>{r['State']}</td>"
            f"<td style='text-align:right;padding:7px 10px;color:{JPSI_DARK}'>{_fmt_bu(r['MYtD Bu'])} bu</td>"
            f"<td style='text-align:right;padding:7px 10px;color:{vs_ly_color}'>"
            f"{'▲' if r['vs LY Bu'] >= 0 else '▼'} {_fmt_bu(abs(r['vs LY Bu']))} bu</td>"
            f"{_pct_cell(r['% vs LY'])}"
            f"{_pct_cell(r['% vs Avg'])}"
            f"</tr>"
        )

    nat_color  = GREEN if (nat_pct or 0) >= 0 else RED
    nat_arrow  = "▲" if (nat_pct or 0) >= 0 else "▼"
    nat_pct_str = f"{nat_arrow} {abs(nat_pct):.1f}%" if nat_pct is not None else "—"

    _ff  = "font-family:'Segoe UI',Arial,Helvetica,sans-serif"
    _sec = (f"padding:10px 24px 6px;font-size:11px;font-weight:700;color:{TEXT_MUTED};"
            f"text-transform:uppercase;letter-spacing:.08em;background:{GRAY_LIGHT};"
            f"border-top:1px solid {BORDER_CLR};border-bottom:1px solid {BORDER_CLR}")

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f0f4f8;{_ff}">
<div style="max-width:700px;margin:24px auto;background:#ffffff;border-radius:8px;
            overflow:hidden;box-shadow:0 2px 10px rgba(0,0,0,0.10)">

  <!-- Header -->
  <table width="100%" style="background:{JPSI_DARK};border-collapse:collapse">
    <tr>
      <td style="padding:18px 24px">
        <img src="{JPSI_LOGO}" height="34" alt="JSA" style="display:block;height:34px">
      </td>
      <td align="right" style="padding:18px 24px">
        <div style="color:#ffffff;font-size:17px;font-weight:700;line-height:1.2">
          Grain Rail Shipment Report
        </div>
        <div style="color:#94a3b8;font-size:12px;margin-top:3px">
          {now_label} &nbsp;·&nbsp; Data through {latest_dt}
        </div>
      </td>
    </tr>
  </table>

  <!-- Summary bar -->
  <div style="background:#eff6ff;padding:16px 24px;border-bottom:1px solid #dbeafe">
    <div style="font-size:11px;color:{TEXT_MUTED};text-transform:uppercase;
                letter-spacing:.06em;margin-bottom:10px">
      {current_my} Marketing Year &nbsp;·&nbsp; Week {max_wk} MYtD
      &nbsp;·&nbsp; Compared to {ly or "N/A"}
    </div>
    <table width="100%" style="border-collapse:collapse">
      <tr>
        <td style="padding:0 24px 0 0">
          <div style="font-size:24px;font-weight:700;color:{JPSI_DARK}">{_fmt_bu(cur_tot)} bu</div>
          <div style="font-size:11px;color:{TEXT_MUTED}">Total MYtD Shipments</div>
        </td>
        <td style="padding:0 24px">
          <div style="font-size:24px;font-weight:700;color:{nat_color}">{nat_pct_str}</div>
          <div style="font-size:11px;color:{TEXT_MUTED}">vs Prior Year</div>
        </td>
        <td style="padding:0 24px">
          <div style="font-size:24px;font-weight:700;color:{JPSI_DARK}">{_fmt_bu(ly_tot)} bu</div>
          <div style="font-size:11px;color:{TEXT_MUTED}">{ly} MYtD (same weeks)</div>
        </td>
        <td align="right" style="white-space:nowrap">
          <a href="{DASH_URL}"
             style="display:inline-block;background:{JPSI_BLUE};color:#ffffff;
                    font-size:12px;font-weight:700;padding:9px 16px;border-radius:5px;
                    text-decoration:none">
            View Dashboard &rarr;
          </a>
        </td>
      </tr>
    </table>
  </div>

  <!-- Chart 1: Railroad performance -->
  <div style="{_sec}">Railroad Performance</div>
  <div style="padding:16px 24px">
    {img_rr}
  </div>

  <!-- Chart 2: State progress -->
  <div style="{_sec}">State Progress — MYtD % vs Last Year</div>
  <div style="padding:16px 24px">
    {img_state}
  </div>

  <!-- Chart 3: Weekly trend -->
  <div style="{_sec}">Weekly Shipment Trend by Marketing Year</div>
  <div style="padding:16px 24px">
    {img_wkly}
  </div>

  <!-- State table -->
  <div style="{_sec}">State Shipment Detail — MYtD Week {max_wk}</div>
  <div style="padding:16px 24px">
    <table style="width:100%;border-collapse:collapse;font-size:12.5px">
      <thead>
        <tr style="background:{JPSI_DARK};color:#ffffff">
          <th style="padding:8px 10px;text-align:left;font-size:10px;
                     text-transform:uppercase;letter-spacing:.06em">State</th>
          <th style="padding:8px 10px;text-align:right;font-size:10px;
                     text-transform:uppercase;letter-spacing:.06em">MYtD</th>
          <th style="padding:8px 10px;text-align:right;font-size:10px;
                     text-transform:uppercase;letter-spacing:.06em">vs LY</th>
          <th style="padding:8px 10px;text-align:right;font-size:10px;
                     text-transform:uppercase;letter-spacing:.06em">% vs LY</th>
          <th style="padding:8px 10px;text-align:right;font-size:10px;
                     text-transform:uppercase;letter-spacing:.06em">% vs 6yr Avg</th>
        </tr>
      </thead>
      <tbody>
        {table_rows}
      </tbody>
    </table>
  </div>

  <!-- Footer -->
  <div style="padding:14px 24px;background:{GRAY_LIGHT};border-top:1px solid {BORDER_CLR};
              font-size:10px;color:#9ca3af;line-height:1.5">
    {DISCLAIMER}
    &nbsp;·&nbsp;
    <a href="{DASH_URL}" style="color:{JPSI_BLUE}">Live Dashboard</a>
  </div>

</div>
</body>
</html>"""

    subject = f"JSA Rail Shipment Update — {now_label} (Week {max_wk}, {current_my} MY)"
    return subject, html, inline_images


# ── Email send ─────────────────────────────────────────────────────────────────
def _send(subject: str, html: str, inline_images: dict) -> None:
    """Send via Microsoft Graph with inline PNG attachments and BCC."""
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

    # Inline PNG attachments (cid references in HTML body)
    atts = []
    for cid, png_bytes in inline_images.items():
        atts.append({
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": f"{cid}.png",
            "contentId": cid,
            "isInline": True,
            "contentBytes": base64.b64encode(png_bytes).decode("ascii"),
        })

    message: dict = {
        "subject": subject,
        "body":    {"contentType": "HTML", "content": html},
        "toRecipients":  [{"emailAddress": {"address": TO_ADDR}}],
        "bccRecipients": [{"emailAddress": {"address": BCC_ADDR}}],
        "from": {"emailAddress": {"address": sender, "name": FROM_NAME}},
    }
    if atts:
        message["attachments"] = atts

    r = requests.post(
        f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail",
        headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json"},
        json={"message": message, "saveToSentItems": True},
        timeout=60,
    )
    r.raise_for_status()
    print(f"Sent: {subject}")


# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true",
                        help="Write _rail_preview.html, do not send")
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

    subject, html, inline_images = build_report(df, for_preview=args.preview)
    print(f"Subject: {subject}")

    if args.preview:
        out = Path(__file__).parent / "_rail_preview.html"
        out.write_text(html, encoding="utf-8")
        print(f"Preview written to {out}")
    else:
        _send(subject, html, inline_images)
