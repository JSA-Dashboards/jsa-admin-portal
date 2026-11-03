"""Copy and PNG buttons that turn a chart, a table or a card into a snapshot image.

Copy puts the image on the clipboard (paste it into Outlook, Teams or Excel) and PNG saves the same
image as a file. Everything happens in the browser on the click, so nothing is rendered on the server
and Streamlit Cloud's fragile kaleido is never involved.

* chart: the live Plotly chart on the page, found by the key it was drawn under, at the size and scale
  its camera icon uses, on an opaque background, with a disclaimer in a strip underneath when one is
  given. The camera icon itself gets the same treatment from png_disclaimer.
* table: the pandas Styler's HTML (the colours and number formats of the on-screen table) laid out
  off-screen with a title, a note, the watermark and the disclaimer, then captured with html2canvas.
* card: ready-made card HTML (the Brazil graphic) laid out at its own width and captured the same way.

html2canvas is loaded from jsDelivr on the first click only. The clipboard write is started
synchronously inside the click with a Promise<Blob>, which keeps the browser's user-gesture
requirement satisfied while the image is still being drawn; where the clipboard is unavailable
(non-HTTPS, older Firefox) the PNG downloads instead.

Keep this file identical in every dashboard that carries it: the portal runs them in one process and
registers a single component under this name for all of them.
"""
from __future__ import annotations

import re

import streamlit as st

HTML2CANVAS_ESM = "https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/+esm"
BUTTONS_WIDTH = 190   # two buttons side by side

# The chart half of the browser code, shared with png_disclaimer (which puts the same strip under the
# camera icon's images): Plotly's own picture of the chart on a canvas, the disclaimer under it.
CHART_IMAGE_JS = """
function loadImage(url) {
  return new Promise((ok, fail) => {
    const img = new Image();
    img.onload = () => ok(img);
    img.onerror = () => fail(new Error("chart image failed to load"));
    img.src = url;
  });
}

function wrapLines(ctx, text, maxWidth) {
  const lines = [];
  let line = "";
  for (const word of text.split(/\\s+/)) {
    const trial = line ? line + " " + word : word;
    if (line && ctx.measureText(trial).width > maxWidth) {
      lines.push(line);
      line = word;
    } else {
      line = trial;
    }
  }
  if (line) lines.push(line);
  return lines;
}

// [r, g, b] of the chart's paper; white where the paper is see-through.
function paperColour(gd) {
  const probe = document.createElement("canvas");
  probe.width = probe.height = 1;
  const ctx = probe.getContext("2d");
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, 1, 1);
  ctx.fillStyle = (gd._fullLayout && gd._fullLayout.paper_bgcolor) || "#ffffff";
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
  return [r, g, b];
}

function canvasBlob(canvas) {
  return new Promise((ok, fail) =>
    canvas.toBlob((blob) => (blob ? ok(blob) : fail(new Error("no image"))), "image/png"));
}

// The chart as an image: Plotly's picture at the size the camera icon would use, on the chart's own
// paper colour, with `text` (the disclaimer, if any) written in a strip underneath.
async function chartImage(Plotly, gd, opts, text) {
  // Only the sizes the chart sets: Plotly rejects an explicit undefined, and without them it
  // falls back to its own defaults, which is what the stock camera saves.
  const shot = { format: "png" };
  for (const key of ["width", "height", "scale"]) if (opts[key] != null) shot[key] = opts[key];
  const url = await Plotly.toImage(gd, shot);
  const img = await loadImage(url);
  const k = opts.scale || 1;   // device pixels per CSS pixel
  const [r, g, b] = paperColour(gd);
  const dark = 0.299 * r + 0.587 * g + 0.114 * b < 140;
  const family = getComputedStyle(document.body).fontFamily || "Arial, sans-serif";
  const font = `${11 * k}px ${family}`;
  const lead = 15.5 * k, pad = 28 * k, gap = 14 * k, foot = 16 * k;

  let lines = [];
  if (text) {
    const probe = document.createElement("canvas").getContext("2d");
    probe.font = font;
    lines = wrapLines(probe, text, img.width - 2 * pad);
  }
  const strip = lines.length ? gap + lines.length * lead + foot : 0;

  const canvas = document.createElement("canvas");
  canvas.width = img.width;
  canvas.height = Math.ceil(img.height + strip);
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = `rgb(${r}, ${g}, ${b})`;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0);

  if (lines.length) {
    ctx.strokeStyle = dark ? "rgba(255,255,255,0.16)" : "#d1d5db";
    ctx.lineWidth = Math.max(1, k);
    ctx.beginPath();
    ctx.moveTo(pad, img.height + gap / 2);
    ctx.lineTo(canvas.width - pad, img.height + gap / 2);
    ctx.stroke();

    ctx.font = font;
    ctx.fillStyle = dark ? "rgba(255,255,255,0.62)" : "#6b7280";
    ctx.textBaseline = "top";
    lines.forEach((line, i) => ctx.fillText(line, pad, img.height + gap + i * lead));
  }
  return canvasBlob(canvas);
}

function download(blob, filename) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename + ".png";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}
"""

_HTML = """
<div class="jsa-snap-row">
  <button type="button" class="jsa-snap-btn" data-act="copy"
          title="Copy a snapshot image: paste it into email, Teams or Excel">Copy</button>
  <button type="button" class="jsa-snap-btn" data-act="png"
          title="Download the same snapshot as a PNG file">PNG</button>
</div>
"""

# Dressed like Streamlit's own buttons beside it (CSV).
_CSS = """
.jsa-snap-row { display: flex; gap: 8px; }
.jsa-snap-btn {
  width: 90px; height: 2.5rem; padding: 0 0.75rem; cursor: pointer;
  font: inherit; font-size: 1rem; color: inherit;
  background: var(--st-background-color, #ffffff);
  border: 1px solid color-mix(in srgb, currentColor 20%, transparent); border-radius: 0.5rem;
  white-space: nowrap;
}
.jsa-snap-btn:hover { border-color: var(--st-primary-color, #ff4b4b); color: var(--st-primary-color, #ff4b4b); }
.jsa-snap-btn:disabled { opacity: 0.6; cursor: progress; }
"""

_BUTTONS_JS = """
async function html2canvasFn() {
  const mod = await import(HTML2CANVAS_ESM);
  return mod.default || mod;
}

// The chart this button belongs to: the one drawn under its key, else the closest one above it.
function findChart(button, key) {
  if (key) {
    const box = document.querySelector(".st-key-" + key);
    const gd = box && box.querySelector(".js-plotly-plot");
    if (gd) return gd;
  }
  let nearest = null;
  for (const gd of document.querySelectorAll(".js-plotly-plot")) {
    if (gd.offsetParent === null) continue;   // in a tab that isn't showing
    if (gd.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING) nearest = gd;
  }
  return nearest;
}

async function chartBlob(data, button) {
  const gd = findChart(button, data.chartKey);
  const Plotly = window.Plotly;
  if (!gd || !gd._context || !Plotly || !Plotly.toImage) throw new Error("chart not ready");
  const opts = Object.assign({ format: "png" }, gd._context.toImageButtonOptions);
  return chartImage(Plotly, gd, opts, data.disclaimer || "");
}

async function tableBlob(data) {
  const html2canvas = await html2canvasFn();
  const host = document.createElement("div");
  host.style.cssText = "position:fixed;left:-100000px;top:0;background:#fff;padding:14px;" +
    "display:inline-block;font-family:'Source Sans Pro',Arial,sans-serif;font-size:13px;color:#31333f;";
  const style = document.createElement("style");
  style.textContent =
    ".jsa-snap-table table{border-collapse:collapse;}" +
    ".jsa-snap-table th,.jsa-snap-table td{padding:5px 10px;border-bottom:1px solid #e6e9ef;" +
    "white-space:nowrap;text-align:right;}" +
    ".jsa-snap-table th{font-weight:600;color:#555;background:#f7f8fa;}" +
    ".jsa-snap-table td:first-child,.jsa-snap-table th:first-child{text-align:left;}" +
    ".jsa-snap-title{font-size:16px;font-weight:600;color:#1f2933;margin:0 0 8px;}" +
    ".jsa-snap-note{font-size:11px;line-height:1.4;color:#6b7280;margin-top:8px;}" +
    ".jsa-snap-disclaimer{font-size:10px;line-height:1.45;color:#6b7280;margin-top:12px;" +
    "padding-top:8px;border-top:1px solid #e6e9ef;}";
  const wrap = document.createElement("div");
  wrap.className = "jsa-snap-table";
  wrap.style.position = "relative";
  if (data.title) {
    const head = document.createElement("div");
    head.className = "jsa-snap-title";
    head.textContent = data.title;
    wrap.appendChild(head);
  }
  const body = document.createElement("div");
  body.innerHTML = data.html;
  wrap.appendChild(body);
  host.appendChild(style);
  host.appendChild(wrap);
  document.body.appendChild(host);
  try {
    // Notes wrap at the table's width rather than stretching the image.
    const table = body.querySelector("table");
    for (const [cls, text] of [["jsa-snap-note", data.note], ["jsa-snap-disclaimer", data.disclaimer]]) {
      if (!text) continue;
      const block = document.createElement("div");
      block.className = cls;
      block.textContent = text;
      if (table) block.style.maxWidth = table.offsetWidth + "px";
      wrap.appendChild(block);
    }
    if (data.watermark) {
      const mark = document.createElement("img");
      mark.src = data.watermark;
      mark.style.cssText = "position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);" +
        "max-width:34%;max-height:80%;opacity:0.10;pointer-events:none;";
      wrap.appendChild(mark);
      if (!mark.complete) await new Promise((ok) => { mark.onload = ok; mark.onerror = ok; });
    }
    const canvas = await html2canvas(host, { scale: 2, backgroundColor: "#ffffff", logging: false });
    return await canvasBlob(canvas);
  } finally {
    host.remove();
  }
}

async function cardBlob(data) {
  const html2canvas = await html2canvasFn();
  // Laid out off-screen at the card's own width, from the same HTML the page shows, so the image
  // never depends on how wide the page happens to be.
  const host = document.createElement("div");
  host.style.cssText = "position:fixed;left:-100000px;top:0;background:#fff;width:" + data.width + "px;";
  host.innerHTML = "<style>" + (data.css || "") + "</style>" + data.html;
  document.body.appendChild(host);
  try {
    await Promise.all([...host.querySelectorAll("img")].map((img) =>
      img.complete ? null : new Promise((ok) => { img.onload = ok; img.onerror = ok; })));
    if (document.fonts && document.fonts.ready) await document.fonts.ready;
    const canvas = await html2canvas(host, {
      scale: 2, backgroundColor: "#ffffff", logging: false, windowWidth: data.width,
    });
    return await canvasBlob(canvas);
  } finally {
    host.remove();
  }
}

export default function (component) {
  const { data, parentElement } = component;
  if (!data) return;
  const copyBtn = parentElement.querySelector('.jsa-snap-btn[data-act="copy"]');
  const pngBtn = parentElement.querySelector('.jsa-snap-btn[data-act="png"]');
  if (!copyBtn || !pngBtn) return;

  const flash = (btn, label, text) => {
    btn.textContent = text;
    setTimeout(() => { btn.textContent = label; btn.disabled = false; }, 1800);
  };
  const makeBlob = () => data.kind === "chart" ? chartBlob(data, parentElement)
    : data.kind === "card" ? cardBlob(data) : tableBlob(data);

  copyBtn.onclick = () => {
    copyBtn.disabled = true;
    copyBtn.textContent = "Copying…";
    const blobPromise = makeBlob();
    const saveInstead = () => blobPromise
      .then((blob) => { download(blob, data.filename); flash(copyBtn, "Copy", "Saved"); })
      .catch(() => flash(copyBtn, "Copy", "Failed"));
    if (navigator.clipboard && window.ClipboardItem && window.isSecureContext) {
      // Called synchronously inside the click; the Promise resolves once the image is drawn.
      navigator.clipboard.write([new ClipboardItem({ "image/png": blobPromise })])
        .then(() => flash(copyBtn, "Copy", "Copied ✓"))
        .catch(saveInstead);
    } else {
      saveInstead();
    }
  };

  pngBtn.onclick = () => {
    pngBtn.disabled = true;
    pngBtn.textContent = "Saving…";
    makeBlob()
      .then((blob) => { download(blob, data.filename); flash(pngBtn, "PNG", "Saved ✓"); })
      .catch(() => flash(pngBtn, "PNG", "Failed"));
  };
}
"""

_JS = f'const HTML2CANVAS_ESM = "{HTML2CANVAS_ESM}";\n' + CHART_IMAGE_JS + _BUTTONS_JS


def _component():
    """Registered on every call rather than once at import: re-registering the same definition is a
    no-op, while a module that outlives the runtime's component registry (a test harness, an app host
    that swaps pages) would otherwise keep a component it forgot."""
    return st.components.v2.component("jsa_snapshot_buttons", html=_HTML, css=_CSS, js=_JS,
                                      isolate_styles=False)


def class_safe(key: str | None) -> str:
    """The suffix of the `st-key-` class Streamlit puts on an element drawn under `key`: anything that
    isn't a letter, digit, underscore or hyphen becomes a hyphen, one per UTF-16 code unit, which is
    how the browser counts, so an emoji turns into two."""
    return "".join(c if re.fullmatch(r"[A-Za-z0-9_-]", c) else "-" * (2 if ord(c) > 0xFFFF else 1)
                   for c in key or "")


def chart_buttons(chart_key: str | None, filename: str, key: str, disclaimer: str = "") -> None:
    """Copy / PNG for the Plotly chart drawn under `chart_key` (the closest chart above the button
    when that is empty or not on the page). `disclaimer` is plain text written under the image."""
    _component()(key=f"snap_{key}", width=BUTTONS_WIDTH,
                 data={"kind": "chart", "chartKey": class_safe(chart_key), "filename": filename,
                       "disclaimer": disclaimer})


def table_buttons(styler, filename: str, key: str, title: str = "", note: str = "",
                  watermark_uri: str | None = None, disclaimer: str = "") -> None:
    """Copy / PNG for a table, snapshotting the Styler's HTML (colours and formats). The title goes
    above the table, the note and the disclaimer (plain text) under it, wrapped to its width."""
    html = styler.hide(axis="index").to_html()
    _component()(key=f"snap_{key}", width=BUTTONS_WIDTH,
                 data={"kind": "table", "html": html, "title": title, "note": note,
                       "watermark": watermark_uri, "disclaimer": disclaimer, "filename": filename})


def card_buttons(card_html: str, css: str, width: int, filename: str, key: str) -> None:
    """Copy / PNG for a ready-made graphic: its HTML and the CSS it needs, laid out `width` px wide."""
    _component()(key=f"snap_{key}", width=BUTTONS_WIDTH,
                 data={"kind": "card", "html": card_html, "css": css, "width": width,
                       "filename": filename})
