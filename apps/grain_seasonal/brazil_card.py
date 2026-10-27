"""The Brazil section's graphic: a JSA Research card with four figures, a weekly line and a note.

The card is one self-contained block of HTML with an inline SVG chart, drawn here rather than by
Plotly, for two reasons. What is on screen is then exactly what the PNG button saves, because
both come from the same string; and the PNG is made in the browser (html2canvas, loaded from
jsDelivr on the first click) so nothing is rendered on the server, where Cloud's kaleido is
fragile. All chart styling is therefore inline attributes: html2canvas rasterises an inline SVG
on its own, without the page's stylesheets.

Two small Streamlit components carry it: one shows the card (scaled to the page's width, with a
hover readout of each week) and one is the PNG button that sits in the export row beside Copy and
CSV. The PNG always renders at the card's own width, whatever the screen.
"""
from __future__ import annotations

import html
import math

import pandas as pd
import streamlit as st

import brazil_board as bb

CARD_W = 1320                      # the card's own width, in CSS pixels
PAD = 12                           # card padding
SVG_W = CARD_W - 2 * PAD
SVG_H = 590
PLOT_LEFT, PLOT_RIGHT, PLOT_TOP, PLOT_BOTTOM = 92, 16, 14, 48
X_LABELS = 11                      # about this many dates along the bottom

NAVY, GREEN, GRAY = "#2D2C6B", "#3D5A3E", "#5D6270"
UP, DOWN, GRID, AXIS_TEXT = "#2F6B34", "#A32A2A", "#E6E8EC", "#606573"
SANS = "Gill Sans MT, Gill Sans, Calibri, Segoe UI, Helvetica, Arial, sans-serif"
SERIF = "Georgia, Times New Roman, serif"

NICE_STEPS = (10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000)

DISCLAIMER = (
    "Futures and options trading involves substantial risk of loss and is not suitable for all "
    "investors. Past performance is not indicative of future results. The information herein was "
    "obtained from sources believed to be reliable but is not guaranteed as to accuracy or "
    "completeness, and is provided for informational purposes only. It is not a solicitation to "
    "buy or sell any commodity interest. John Stewart and Associates is an NFA-registered "
    "Independent Introducing Broker."
)

HTML2CANVAS_ESM = "https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/+esm"


# ── The card ─────────────────────────────────────────────────────────────────

def nice_axis(low: float, high: float) -> tuple[float, float, int]:
    """(axis bottom, axis top, tick step) with a tenth of the range spare above and below,
    snapped to round numbers so the gridlines land on them."""
    span = max(high - low, 1.0)
    lo, hi = low - 0.1 * span, high + 0.1 * span
    step = next((s for s in NICE_STEPS if (hi - lo) / s <= 7.5), NICE_STEPS[-1])
    return math.floor(lo / step) * step, math.ceil(hi / step) * step, step


def _chart_svg(weekly: pd.DataFrame, summary: bb.Summary) -> tuple[str, list[dict]]:
    """The line chart as an SVG string, plus each week's position for the hover readout."""
    values = [float(v) for v in weekly["centavos"]]
    n = len(values)
    axis_lo, axis_hi, step = nice_axis(min(values), max(values))
    plot_w = SVG_W - PLOT_LEFT - PLOT_RIGHT
    plot_h = SVG_H - PLOT_TOP - PLOT_BOTTOM

    def x_of(i: int) -> float:
        return PLOT_LEFT + i * plot_w / (n - 1)

    def y_of(v: float) -> float:
        return PLOT_TOP + (axis_hi - v) / (axis_hi - axis_lo) * plot_h

    parts = [f'<svg class="jb-svg" xmlns="http://www.w3.org/2000/svg" width="{SVG_W}" height="{SVG_H}" '
             f'viewBox="0 0 {SVG_W} {SVG_H}">']
    tick = axis_lo
    while tick <= axis_hi + 1e-9:
        y = y_of(tick)
        parts.append(f'<line x1="{PLOT_LEFT}" x2="{SVG_W - PLOT_RIGHT}" y1="{y:.1f}" y2="{y:.1f}" '
                     f'stroke="{GRID}" stroke-width="1.3"/>')
        parts.append(f'<text x="{PLOT_LEFT - 12}" y="{y + 5:.1f}" text-anchor="end" font-family="{SANS}" '
                     f'font-size="16" fill="{AXIS_TEXT}">{tick:,.0f}</text>')
        tick += step
    parts.append(f'<text transform="rotate(-90)" x="{-(PLOT_TOP + plot_h / 2):.1f}" y="22" '
                 f'text-anchor="middle" font-family="{SANS}" font-size="15" fill="{AXIS_TEXT}">'
                 f'Reais/bu (centavos)</text>')

    every = max(1, math.ceil(n / X_LABELS))
    for i in range(0, n, every):
        x = x_of(i)
        anchor = "end" if x > SVG_W - 46 else "middle"
        parts.append(f'<text x="{x:.1f}" y="{SVG_H - PLOT_BOTTOM + 30}" text-anchor="{anchor}" '
                     f'font-family="{SANS}" font-size="16" fill="{AXIS_TEXT}">'
                     f'{bb.fmt_date(weekly.index[i].date())}</text>')

    points = " ".join(f"{x_of(i):.1f},{y_of(v):.1f}" for i, v in enumerate(values))
    parts.append(f'<polyline points="{points}" fill="none" stroke="{NAVY}" stroke-width="3.4" '
                 f'stroke-linejoin="round" stroke-linecap="round"/>')
    end_x, end_y = x_of(n - 1), y_of(values[-1])
    parts.append(f'<circle cx="{end_x:.1f}" cy="{end_y:.1f}" r="7" fill="{NAVY}"/>')
    label_y = end_y - 16 if end_y - 16 > PLOT_TOP + 16 else end_y + 30
    parts.append(f'<text x="{end_x - 14:.1f}" y="{label_y:.1f}" text-anchor="end" font-family="{SERIF}" '
                 f'font-weight="700" font-size="24" fill="{NAVY}">{bb.fmt_centavos(values[-1])}</text>')
    parts.append(f'<rect class="jb-capture" x="{PLOT_LEFT}" y="{PLOT_TOP}" width="{plot_w}" '
                 f'height="{plot_h}" fill="#ffffff" fill-opacity="0"/>')
    parts.append("</svg>")

    hover = []
    for i, (day, row) in enumerate(weekly.iterrows()):
        hover.append({
            "x": round(x_of(i), 1), "y": round(y_of(values[i]), 1),
            "date": f"{day:%a} {bb.fmt_date(day.date())}",
            "reais": bb.fmt_reais(values[i]),
            "centavos": bb.fmt_centavos(values[i]),
            "cbot": f"{row['cbot']:,.2f}", "fx": f"{row['usdbrl']:.4f}", "contract": row["contract"],
        })
    return "".join(parts), hover


def _tile(label: str, value: str, note: str, tone: str = "") -> str:
    return (f'<div class="jb-tile"><div class="jb-label">{html.escape(label)}</div>'
            f'<div class="jb-value {tone}">{html.escape(value)}</div>'
            f'<div class="jb-note">{html.escape(note)}</div></div>')


def _tone(value: float | None) -> str:
    if not value:
        return ""
    return "up" if value > 0 else "down"


def build_card(weekly: pd.DataFrame, summary: bb.Summary, *, logo_uri: str,
               watermark_uri: str | None, source: str, year: int) -> tuple[str, list[dict]]:
    """(card HTML, hover points) for one market."""
    m = summary.market
    svg, hover = _chart_svg(weekly, summary)

    if summary.year_ago_pct is None:
        year_tile = _tile("vs. year ago", "n/a", "less than a year of data")
    else:
        year_tile = _tile("vs. year ago", bb.fmt_pct(summary.year_ago_pct),
                          f"from {bb.fmt_centavos(summary.year_ago)} on {bb.fmt_date(summary.year_ago_date)}",
                          _tone(summary.year_ago_pct))
    tiles = "".join([
        _tile(f"Latest ({bb.fmt_date(summary.latest_date)})", bb.fmt_centavos(summary.latest),
              bb.fmt_reais(summary.latest)),
        _tile("Week change", f"{summary.week_change:+,}", bb.week_tile_note(summary),
              _tone(summary.week_change)),
        _tile("Period high", bb.fmt_centavos(summary.high), bb.fmt_date(summary.high_date)),
        year_tile,
    ])

    watermark = ""
    if watermark_uri:
        size = 470   # square-ish mark, centred behind the plot
        left = PLOT_LEFT + (SVG_W - PLOT_LEFT - PLOT_RIGHT - size) / 2
        top = PLOT_TOP + (SVG_H - PLOT_TOP - PLOT_BOTTOM - size) / 2
        watermark = (f'<img class="jb-wm" src="{watermark_uri}" alt="" '
                     f'style="width:{size}px;height:{size}px;left:{left:.0f}px;top:{top:.0f}px">')

    card = (
        f'<div class="jb-card">'
        f'<div class="jb-head"><div>'
        f'<div class="jb-kicker">JSA Research · {html.escape(m.name)} · Brazil</div>'
        f'<div class="jb-title">Spot CBOT {html.escape(m.name)} Valued in Brazilian Reais</div>'
        f'<div class="jb-subtitle">{html.escape(bb.subtitle(summary))}</div>'
        f'</div><img class="jb-logo" src="{logo_uri}" alt="John Stewart and Associates"></div>'
        f'<div class="jb-rule"></div>'
        f'<div class="jb-tiles">{tiles}</div>'
        f'<div class="jb-chart">{watermark}{svg}</div>'
        f'<div class="jb-why"><b>Why it matters:</b> {html.escape(bb.why_it_matters(summary))}'
        f'<br>Source: {html.escape(source)}</div>'
        f'<div class="jb-disc"><b>IMPORTANT DISCLAIMER:</b> {html.escape(DISCLAIMER)} '
        f'© {year} John Stewart and Associates.</div>'
        f'</div>'
    )
    return card, hover


# ── Streamlit components ─────────────────────────────────────────────────────

_CARD_CSS = f"""
.jb-card {{ box-sizing: border-box; width: {CARD_W}px; padding: {PAD}px {PAD}px 16px; background: #fff;
  color: #1F2330; font-family: {SANS}; line-height: 1.3; text-align: left; }}
.jb-card *, .jb-card *::before, .jb-card *::after {{ box-sizing: border-box; }}
.jb-head {{ display: flex; justify-content: space-between; align-items: flex-start; }}
.jb-kicker {{ font-size: 15px; font-weight: 700; letter-spacing: 0.19em; text-transform: uppercase;
  color: {GREEN}; line-height: 1.2; }}
.jb-title {{ font-family: {SERIF}; font-weight: 700; font-size: 35px; line-height: 1.15; color: {NAVY};
  margin: 3px 0 4px; }}
.jb-subtitle {{ font-size: 17px; color: {GRAY}; }}
.jb-logo {{ height: 70px; width: auto; display: block; margin: 0 4px 0 24px; }}
.jb-rule {{ border-top: 3px solid {GREEN}; margin: 16px 0 20px; }}
.jb-tiles {{ display: flex; gap: 13px; }}
.jb-tile {{ flex: 1 1 0; min-width: 0; height: 96px; background: #F6F7F4; border-left: 5px solid {GREEN};
  padding: 13px 16px 0 15px; }}
.jb-label {{ font-size: 14.5px; letter-spacing: 0.07em; text-transform: uppercase; color: {GRAY};
  line-height: 1.1; }}
.jb-value {{ font-family: {SERIF}; font-weight: 700; font-size: 34px; line-height: 1.1; color: {NAVY};
  margin-top: 6px; }}
.jb-value.up {{ color: {UP}; }}
.jb-value.down {{ color: {DOWN}; }}
.jb-note {{ font-size: 14.5px; color: {GRAY}; line-height: 1.2; margin-top: 1px; }}
.jb-chart {{ position: relative; margin-top: 22px; height: {SVG_H}px; }}
.jb-wm {{ position: absolute; opacity: 0.09; pointer-events: none; }}
.jb-svg {{ position: absolute; left: 0; top: 0; display: block; }}
.jb-why {{ border-top: 1px solid #E3E5E9; margin-top: 8px; padding-top: 12px; font-size: 16px;
  line-height: 1.5; color: #1F2330; }}
.jb-disc {{ border-top: 2px solid {NAVY}; margin-top: 14px; padding-top: 10px; font-size: 12px;
  line-height: 1.55; color: #3C4150; }}
.jb-disc b {{ letter-spacing: 0.09em; color: {NAVY}; }}
"""

_VIEW_HTML = '<div class="jb-root"><div class="jb-stage"></div></div>'

_VIEW_CSS = _CARD_CSS + """
.jb-root { width: 100%; }
.jb-stage { position: relative; overflow: hidden; }
.jb-stage .jb-card { transform-origin: 0 0; margin: 0 auto; }
.jb-xhair { pointer-events: none; }
.jb-tip { position: absolute; z-index: 5; display: none; pointer-events: none; white-space: nowrap;
  background: #fff; border: 1px solid #c9ccd4; border-radius: 6px; padding: 7px 10px; font-size: 14px;
  line-height: 1.35; color: #1F2330; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.14); }
.jb-tip b { color: #2D2C6B; }
"""

_VIEW_JS = """
export default function (component) {
  const { data, parentElement } = component;
  const root = parentElement.querySelector(".jb-root");
  const stage = root.querySelector(".jb-stage");
  stage.innerHTML = data.html;
  const card = stage.firstElementChild;
  if (!card) return;

  // Show the card at its own size, shrunk to fit a narrower page.
  const fit = () => {
    const scale = Math.min(1, (root.clientWidth || data.width) / data.width);
    card.style.transform = scale < 1 ? "scale(" + scale + ")" : "none";
    stage.style.height = Math.ceil(card.offsetHeight * scale) + "px";
  };
  fit();
  const observer = new ResizeObserver(fit);
  observer.observe(root);

  // Hover readout: a guide line, a dot on the week and a small card with its numbers.
  const svg = card.querySelector("svg.jb-svg");
  const chart = card.querySelector(".jb-chart");
  if (svg && chart && data.points && data.points.length) {
    const NS = "http://www.w3.org/2000/svg";
    const guide = document.createElementNS(NS, "line");
    guide.setAttribute("class", "jb-xhair");
    guide.setAttribute("stroke", "#3D5A3E");
    guide.setAttribute("stroke-width", "1.5");
    guide.setAttribute("stroke-dasharray", "5 4");
    guide.style.display = "none";
    const dot = document.createElementNS(NS, "circle");
    dot.setAttribute("class", "jb-xhair");
    dot.setAttribute("r", "6");
    dot.setAttribute("fill", "#fff");
    dot.setAttribute("stroke", "#2D2C6B");
    dot.setAttribute("stroke-width", "3");
    dot.style.display = "none";
    svg.appendChild(guide);
    svg.appendChild(dot);
    const tip = document.createElement("div");
    tip.className = "jb-tip";
    chart.appendChild(tip);

    const pts = data.points;
    svg.addEventListener("mousemove", (ev) => {
      const box = svg.getBoundingClientRect();
      const x = ((ev.clientX - box.left) / box.width) * data.svgW;
      let best = 0, gap = Infinity;
      for (let i = 0; i < pts.length; i++) {
        const d = Math.abs(pts[i].x - x);
        if (d < gap) { gap = d; best = i; }
      }
      const p = pts[best];
      guide.setAttribute("x1", p.x); guide.setAttribute("x2", p.x);
      guide.setAttribute("y1", 14); guide.setAttribute("y2", data.svgH - 48);
      dot.setAttribute("cx", p.x); dot.setAttribute("cy", p.y);
      guide.style.display = ""; dot.style.display = "";
      tip.innerHTML = "<b>" + p.date + "</b><br>" + p.reais + " &middot; " + p.centavos + " centavos<br>CBOT "
        + p.cbot + "&cent; (" + p.contract + ") &times; " + p.fx + " BRL/USD";
      tip.style.display = "block";
      const wide = tip.offsetWidth;
      const left = p.x + 16 + wide > data.svgW ? p.x - 16 - wide : p.x + 16;
      tip.style.left = Math.max(0, left) + "px";
      tip.style.top = Math.max(0, p.y - 70) + "px";
    });
    svg.addEventListener("mouseleave", () => {
      guide.style.display = "none"; dot.style.display = "none"; tip.style.display = "none";
    });
  }
  return () => observer.disconnect();
}
"""

_PNG_HTML = '<button type="button" class="jb-png" title="Download this graphic as a PNG image">PNG</button>'

_PNG_CSS = _CARD_CSS + """
/* Dressed like Streamlit's own buttons beside it (Copy, CSV). */
.jb-png { width: 90px; height: 2.5rem; padding: 0 0.75rem; cursor: pointer; font: inherit; font-size: 1rem;
  color: inherit; background: var(--st-background-color, #ffffff);
  border: 1px solid color-mix(in srgb, currentColor 20%, transparent); border-radius: 0.5rem;
  white-space: nowrap; }
.jb-png:hover { border-color: var(--st-primary-color, #ff4b4b); color: var(--st-primary-color, #ff4b4b); }
.jb-png:disabled { opacity: 0.6; cursor: progress; }
"""

_PNG_JS = f"""
const HTML2CANVAS_ESM = "{HTML2CANVAS_ESM}";

async function cardBlob(data) {{
  const mod = await import(HTML2CANVAS_ESM);
  const html2canvas = mod.default || mod;
  // The card is laid out off-screen at its own width, from the same HTML the page shows, so the
  // image never depends on how wide the page happens to be.
  const host = document.createElement("div");
  host.style.cssText = "position:fixed;left:-100000px;top:0;background:#fff;width:" + data.width + "px;";
  host.innerHTML = data.html;
  document.body.appendChild(host);
  try {{
    await Promise.all([...host.querySelectorAll("img")].map((img) =>
      img.complete ? null : new Promise((ok) => {{ img.onload = ok; img.onerror = ok; }})));
    if (document.fonts && document.fonts.ready) await document.fonts.ready;
    const canvas = await html2canvas(host, {{
      scale: 2, backgroundColor: "#ffffff", logging: false, windowWidth: data.width,
    }});
    return await new Promise((ok) => canvas.toBlob(ok, "image/png"));
  }} finally {{
    host.remove();
  }}
}}

function download(blob, filename) {{
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename + ".png";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}}

export default function (component) {{
  const {{ data, parentElement }} = component;
  const btn = parentElement.querySelector(".jb-png");
  if (!btn || !data) return;
  const flash = (text) => {{
    btn.textContent = text;
    setTimeout(() => {{ btn.textContent = "PNG"; btn.disabled = false; }}, 1800);
  }};
  btn.onclick = async () => {{
    btn.disabled = true;
    btn.textContent = "Saving…";
    try {{
      download(await cardBlob(data), data.filename);
      flash("Saved ✓");
    }} catch (e) {{
      flash("Failed");
    }}
  }};
}}
"""


def _view_component():
    # Registered on every call rather than once at import, for the reason given in table_png.
    return st.components.v2.component("jsa_brazil_card", html=_VIEW_HTML, css=_VIEW_CSS, js=_VIEW_JS,
                                      isolate_styles=False)


def _png_component():
    return st.components.v2.component("jsa_brazil_card_png", html=_PNG_HTML, css=_PNG_CSS, js=_PNG_JS,
                                      isolate_styles=False)


def show_card(card_html: str, hover: list[dict], key: str) -> None:
    """Show the card, scaled to the page's width, with its hover readout."""
    _view_component()(key=f"brazilcard_{key}", width="stretch",
                      data={"html": card_html, "points": hover, "width": CARD_W,
                            "svgW": SVG_W, "svgH": SVG_H})


def png_button(card_html: str, filename: str, key: str) -> None:
    """A PNG download button that saves the card at its own size, twice the pixel density."""
    _png_component()(key=f"brazilpng_{key}", width=90,
                     data={"html": card_html, "width": CARD_W, "filename": filename})
