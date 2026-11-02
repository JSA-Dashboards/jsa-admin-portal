"""The JSA disclaimer inside every chart image saved from Plotly's camera icon.

A saved image goes further than the page does, and the camera button has no way to put text on
what it saves. So while this component is on the page it takes that button over: the click asks
Plotly for the same PNG as before (the chart's own toImageButtonOptions: filename, size, scale),
sets it on a canvas and writes the disclaimer in a strip underneath, in the chart's own
background colour so a dark chart doesn't grow a white footer. If anything goes wrong Plotly's
stock download runs instead. The hook comes off again when the component leaves the page, so
inside the portal it only ever touches this dashboard's charts.

All of it happens in the browser on the click; nothing is rendered on the server. The tables'
PNG button (table_png.py) carries the same wording.
"""
from __future__ import annotations

import streamlit as st

_JS = """
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

async function withDisclaimer(Plotly, gd, opts, text) {
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

  const probe = document.createElement("canvas").getContext("2d");
  probe.font = font;
  const lines = wrapLines(probe, text, img.width - 2 * pad);

  const canvas = document.createElement("canvas");
  canvas.width = img.width;
  canvas.height = Math.ceil(img.height + gap + lines.length * lead + foot);
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = `rgb(${r}, ${g}, ${b})`;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0);

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
  return new Promise((ok, fail) =>
    canvas.toBlob((blob) => (blob ? ok(blob) : fail(new Error("no image"))), "image/png"));
}

function download(blob, filename) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename + ".png";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

export default function (component) {
  const { data } = component;
  const text = data && data.text;
  if (!text) return;

  const onClick = (ev) => {
    const btn = ev.target && ev.target.closest ? ev.target.closest(".modebar-btn") : null;
    if (!btn || !/^download plot as a png/i.test(btn.getAttribute("data-title") || "")) return;
    const gd = btn.closest(".js-plotly-plot");
    const Plotly = window.Plotly;
    // Without Plotly's own API to hand, leave its download alone.
    if (!gd || !gd._context || !Plotly || !Plotly.toImage) return;
    ev.preventDefault();
    ev.stopImmediatePropagation();
    // What the camera would pass: the chart's own options, else Plotly's defaults (the chart's
    // on-screen size at scale 1), so a chart without any keeps saving at the size it always did.
    const opts = Object.assign({ format: "png", filename: "newplot" }, gd._context.toImageButtonOptions);
    withDisclaimer(Plotly, gd, opts, text)
      .then((blob) => download(blob, opts.filename))
      .catch(() => Plotly.downloadImage(gd, opts));
  };
  document.addEventListener("click", onClick, true);
  return () => document.removeEventListener("click", onClick, true);
}
"""


def _component():
    """Registered on every call rather than once at import, for the reason given in table_png."""
    return st.components.v2.component("jsa_png_disclaimer", js=_JS, isolate_styles=False)


def install(text: str) -> None:
    """Make the camera icon on this page's charts save its PNG with `text` underneath."""
    _component()(key="png_disclaimer", data={"text": text})
