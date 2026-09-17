"""A "Copy" button that puts a PNG snapshot of a chart or table on the clipboard.

Everything happens in the browser when the button is clicked, so nothing is rendered on
the server and Streamlit Cloud's fragile kaleido isn't involved:

* Charts: the Plotly figure JSON is drawn off-screen with plotly.js and exported to PNG
  (white background, so it pastes cleanly into Outlook/Teams dark mode).
* Tables: the pandas Styler HTML (same colours and number formats as the on-screen
  table) is laid out off-screen and captured with html2canvas.

Both libraries are loaded from jsDelivr on the first click only. The clipboard write is
started synchronously inside the click with a Promise<Blob>, which keeps the browser's
user-gesture requirement satisfied while the image is still being drawn. Where the
clipboard is unavailable (non-HTTPS, older Firefox) the PNG downloads instead.
"""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

# plotly.js ships as a UMD bundle; jsDelivr's "+esm" rewrite of it does not parse, so it
# is loaded with a plain script tag (CCv2 runs in the page, not an iframe, so this works).
PLOTLY_UMD = "https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"
HTML2CANVAS_ESM = "https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/+esm"
CHART_WIDTH = 1400

_HTML = """
<button type="button" class="jsa-snap-btn"
        title="Copy a snapshot image — paste into email, Teams or Excel">Copy</button>
"""

_CSS = """
.jsa-snap-btn {
  width: 90px; height: 2.5rem; padding: 0 0.75rem; cursor: pointer;
  font: inherit; font-size: 0.875rem; color: inherit;
  background: var(--st-secondary-background-color, #ffffff);
  border: 1px solid rgba(49, 51, 63, 0.2); border-radius: 0.5rem;
  white-space: nowrap;
}
.jsa-snap-btn:hover { border-color: var(--st-primary-color, #ff4b4b); color: var(--st-primary-color, #ff4b4b); }
.jsa-snap-btn:disabled { opacity: 0.6; cursor: progress; }
"""

_JS = f"""
const PLOTLY_UMD = "{PLOTLY_UMD}";
const HTML2CANVAS_ESM = "{HTML2CANVAS_ESM}";
const CHART_WIDTH = {CHART_WIDTH};

function dataUrlToBlob(url) {{
  return fetch(url).then((r) => r.blob());
}}

function loadPlotly() {{
  if (window.Plotly) return Promise.resolve(window.Plotly);
  if (!window.__jsaPlotlyLoading) {{
    window.__jsaPlotlyLoading = new Promise((ok, fail) => {{
      const tag = document.createElement("script");
      tag.src = PLOTLY_UMD;
      tag.onload = () => ok(window.Plotly);
      tag.onerror = () => fail(new Error("plotly.js failed to load"));
      document.head.appendChild(tag);
    }});
  }}
  return window.__jsaPlotlyLoading;
}}

async function chartBlob(figure) {{
  const Plotly = await loadPlotly();
  const layout = Object.assign({{}}, figure.layout || {{}});
  layout.paper_bgcolor = "#ffffff";
  if (!layout.plot_bgcolor || layout.plot_bgcolor.startsWith("rgba(0, 0, 0, 0") ||
      layout.plot_bgcolor.startsWith("rgba(0,0,0,0")) {{
    layout.plot_bgcolor = "#ffffff";
  }}
  const height = Math.max(layout.height || 450, 360);
  const url = await Plotly.toImage(
    {{ data: figure.data || [], layout }},
    {{ format: "png", width: CHART_WIDTH, height, scale: 2 }}
  );
  return dataUrlToBlob(url);
}}

async function tableBlob(html, watermark) {{
  const mod = await import(HTML2CANVAS_ESM);
  const html2canvas = mod.default || mod;
  const host = document.createElement("div");
  host.style.cssText = "position:fixed;left:-100000px;top:0;background:#fff;padding:12px;" +
    "display:inline-block;font-family:'Source Sans Pro',Arial,sans-serif;font-size:13px;color:#31333f;";
  const style = document.createElement("style");
  style.textContent =
    ".jsa-snap-table table{{border-collapse:collapse;}}" +
    ".jsa-snap-table th,.jsa-snap-table td{{padding:5px 10px;border-bottom:1px solid #e6e9ef;" +
    "white-space:nowrap;text-align:right;}}" +
    ".jsa-snap-table th{{font-weight:600;color:#555;background:#f7f8fa;}}" +
    ".jsa-snap-table td:first-child,.jsa-snap-table th:first-child{{text-align:left;}}";
  const wrap = document.createElement("div");
  wrap.className = "jsa-snap-table";
  wrap.style.position = "relative";
  wrap.innerHTML = html;
  if (watermark) {{
    const mark = document.createElement("img");
    mark.src = watermark;
    mark.style.cssText = "position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);" +
      "max-width:34%;max-height:80%;opacity:0.10;pointer-events:none;";
    wrap.appendChild(mark);
  }}
  host.appendChild(style);
  host.appendChild(wrap);
  document.body.appendChild(host);
  try {{
    if (watermark) {{
      const img = wrap.querySelector("img");
      if (img && !img.complete) await new Promise((ok) => {{ img.onload = ok; img.onerror = ok; }});
    }}
    const canvas = await html2canvas(host, {{ scale: 2, backgroundColor: "#ffffff", logging: false }});
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
  const btn = parentElement.querySelector(".jsa-snap-btn");
  if (!btn || !data) return;

  const flash = (text) => {{
    btn.textContent = text;
    setTimeout(() => {{ btn.textContent = "Copy"; btn.disabled = false; }}, 1800);
  }};

  btn.onclick = () => {{
    btn.disabled = true;
    btn.textContent = "Copying…";
    const blobPromise = data.kind === "chart"
      ? chartBlob(data.figure)
      : tableBlob(data.html, data.watermark);

    const canClip = navigator.clipboard && window.ClipboardItem && window.isSecureContext;
    if (canClip) {{
      // Must be called synchronously in the click; the Promise resolves later.
      navigator.clipboard
        .write([new ClipboardItem({{ "image/png": blobPromise }})])
        .then(() => flash("Copied ✓"))
        .catch(() => blobPromise.then((b) => {{ download(b, data.filename); flash("Saved"); }})
          .catch(() => flash("Failed")));
    }} else {{
      blobPromise.then((b) => {{ download(b, data.filename); flash("Saved"); }})
        .catch(() => flash("Failed"));
    }}
  }};
}}
"""

_COMPONENT = st.components.v2.component(
    "jsa_snapshot_copy", html=_HTML, css=_CSS, js=_JS, isolate_styles=False,
)


def copy_chart_button(fig, filename: str, key: str):
    """Copy button for a Plotly figure."""
    _COMPONENT(key=f"snap_{key}", width=90,
               data={"kind": "chart", "figure": json.loads(fig.to_json()), "filename": filename})


def copy_table_button(styler: "pd.io.formats.style.Styler", filename: str, key: str,
                      watermark_uri: str | None = None):
    """Copy button for a table, snapshotting the Styler's HTML (colours and formats)."""
    html = styler.hide(axis="index").to_html()
    _COMPONENT(key=f"snap_{key}", width=90,
               data={"kind": "table", "html": html, "watermark": watermark_uri,
                     "filename": filename})
