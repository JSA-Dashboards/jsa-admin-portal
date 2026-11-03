"""The JSA disclaimer inside every chart image saved from Plotly's camera icon.

A saved image goes further than the page does, and the camera button has no way to put text on
what it saves. So while this component is on the page it takes that button over: the click asks
Plotly for the same PNG as before (the chart's own toImageButtonOptions: filename, size, scale),
sets it on a canvas and writes the disclaimer in a strip underneath, in the chart's own
background colour so a dark chart doesn't grow a white footer. If anything goes wrong Plotly's
stock download runs instead. The hook comes off again when the component leaves the page, so
inside the portal it only ever touches this dashboard's charts.

All of it happens in the browser on the click; nothing is rendered on the server. The image code is
snapshot_buttons', which makes the same picture for the Copy and PNG buttons under each chart.
"""
from __future__ import annotations

import streamlit as st

from snapshot_buttons import CHART_IMAGE_JS

_HOOK_JS = """
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
    chartImage(Plotly, gd, opts, text)
      .then((blob) => download(blob, opts.filename))
      .catch(() => Plotly.downloadImage(gd, opts));
  };
  document.addEventListener("click", onClick, true);
  return () => document.removeEventListener("click", onClick, true);
}
"""

_JS = CHART_IMAGE_JS + _HOOK_JS


def _component():
    """Registered on every call rather than once at import, for the reason given in snapshot_buttons."""
    return st.components.v2.component("jsa_png_disclaimer", js=_JS, isolate_styles=False)


def install(text: str) -> None:
    """Make the camera icon on this page's charts save its PNG with `text` underneath."""
    _component()(key="png_disclaimer", data={"text": text})
