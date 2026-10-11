import sys as _sys  # portal-sync: sibling imports resolve to this folder
from pathlib import Path as _Path  # portal-sync
_sys.path.insert(0, str(_Path(__file__).parent))  # portal-sync
import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.express as px
import plotly.graph_objects as go

# ── Page config ────────────────────────────────────────────────────────────────
pass  # portal-sync: st.set_page_config removed (Home.py makes the one call allowed per run)

# Hide the Streamlit Community Cloud viewer badge (the profile avatar that links
# to the creator's other apps) for a clean, client-facing footer.
# The Streamlit Cloud badge (creator avatar + logo) is drawn by Cloud's outer page,
# outside this iframe, so CSS here can't reach it; add the rule to the parent
# document instead (same-origin). No-op when run locally.
_BADGE_JS = """<script>(function(){try{var w=window;while(w.parent&&w.parent!==w){try{void w.parent.document;w=w.parent;}catch(e){break;}}var d=w.document;if(d.getElementById('jsa-hide-cloud-badge'))return;var s=d.createElement('style');s.id='jsa-hide-cloud-badge';s.textContent="[class*='_profileContainer_'],[class*='_viewerBadge_']{display:none !important;}";d.head.appendChild(s);}catch(e){}})();</script>"""
try:
    st.html(_BADGE_JS, unsafe_allow_javascript=True)
except TypeError:  # older Streamlit without st.html JS support
    import streamlit.components.v1 as _stc
    _stc.html(_BADGE_JS, height=0)

# ── Constants ──────────────────────────────────────────────────────────────────
API_URL      = "https://agtransport.usda.gov/resource/27k8-utc2.json"
CARS_TO_BU   = 4_000
MIN_COMPLETE_WEEK = 48   # weeks to consider a MY "complete"

DEST_MAP = {
    "BNSF": "Western",  "UP": "Western",
    "CSX":  "Eastern",  "NS": "Eastern",
    "CN":   "Central",
    "CP":   "Central/Canada", "CPKC": "Central/Canada",
    "KCS":  "Central/Mexico",
}

RR_ORDER = ["BNSF", "UP", "CSX", "NS", "CN", "CP", "CPKC", "KCS"]
RR_COLORS = {
    "BNSF": "#f97316", "UP": "#fbbf24", "CSX": "#34d399",
    "NS":   "#60a5fa", "CN": "#a78bfa", "CP":  "#f87171",
    "CPKC": "#fb923c", "KCS": "#4ade80",
}
DEST_COLORS = {
    "Western": "#f97316", "Eastern": "#60a5fa",
    "Central": "#a78bfa", "Central/Canada": "#fb923c",
    "Central/Mexico": "#4ade80",
}

MY_MONTHS = {
    1: "Sep", 2: "Oct",  3: "Nov", 4: "Dec",
    5: "Jan", 6: "Feb",  7: "Mar", 8: "Apr",
    9: "May", 10: "Jun", 11: "Jul", 12: "Aug",
}

WESTERN_STATES = ["IA", "NE", "SD", "ND", "MN", "KS", "MO"]
EASTERN_STATES = ["IL", "IN", "OH", "MI", "KY"]

PLOT_BASE = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="#ffffff",
    font=dict(color="#32373c", family="Inter, sans-serif", size=11),
    legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor="#e2e8f0"),
    margin=dict(t=50, b=40, l=40, r=20),
)
_AXIS = dict(gridcolor="#f1f5f9", linecolor="#e2e8f0")

_LOGO_IMG = dict(
    source="data:image/png;base64,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",
    xref="paper", yref="paper",
    x=0.5, y=0.5, xanchor="center", yanchor="middle",
    sizex=0.45, sizey=0.45, opacity=0.12, layer="above",
)

def _lax(**kw):
    out = dict(PLOT_BASE)
    out["xaxis"] = {**_AXIS, **kw.pop("xaxis", {})}
    out["yaxis"] = {**_AXIS, **kw.pop("yaxis", {})}
    out["images"] = [_LOGO_IMG]
    out.update(kw)
    return out

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
[data-testid="stAppViewContainer"] { background: #f8fafc; }
[data-testid="stHeader"]            { background: transparent; }
.block-container                    { padding-top: 1.2rem; }
div[data-testid="stTabs"] button[aria-selected="true"] {
    border-bottom: 2px solid #0693e3; color: #0693e3;
}
div[data-testid="stMetric"], div[data-testid="metric-container"] {
    background: #ffffff; border: 1px solid #e2e8f0;
    border-radius: 10px; padding: 14px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
div[data-testid="stDataFrame"] {
    position: relative;
}
div[data-testid="stDataFrame"]::after {
    content: "";
    position: absolute;
    top: 50%;
    left: 50%;
    width: 260px;
    height: 70px;
    transform: translate(-50%, -50%);
    background-image: url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAN4AAAA8CAYAAAAJ6wQ+AAAABHNCSVQICAgIfAhkiAAAIABJREFUeJztnXd4XMW5/7/fmbNNXbJlFctYGGEb2dqixYATHATYBtNC871JCODABZJcIJB20yEXcpMfpAEJBC44ECDAdRIIoVeFGspKsmwLGStGgLuw1Xe1u+fM+/tjV7KqLRdq9Hke8KM9c2bec868U9555x0CUEefdtzJBM8kzGahVhjAAIAtoMFHHWNAqmlJhWuf//NjjR+2OBNMsCssLF1KON0iBrcrZXpFWAVCDKgBAiIE5MOWc5cQkqCynzZGL2BS9IctzwQT7A4LAEDYooSOqIsJzBbDJqVBCgjyQxZx1xiIBTAMuA2U6VEf9VZiggnQr3giFBEqqhyBueXZ+x+/5UOWa9z4Fy/OnJzFm8QYN9Tu008wwUeBIVVVRESErg9LmL1hSq6xBHB/2HJMMMGeMLKPEHy0x5bDsJP2x0reCSYAAAWsAI189K2WE0zwCcICABFlKCJ7OkeqqanJQr7nSBoz7juNRU2Dt2rvf+INAM6elTjBBJ8MrH25WefqA4S8A0qPW/G0QIG4e/Hixd994oknevel/Akm+LiyT4oXV7DdgnahuAnmAijYRfJeCLYCAES6tns8E2b/Cf5l2SfFs9qd9XauXmS049LiKtKUMyC8AETOoGRGBC9ReBWTqiWpkpL0dndG7n85to+yf9xgOBy2IpFI8sMWZJxYs2bN8mmtpampqQ+A/WEL9ElinxSvtrbWBvBu+s/1NSfUvKW8nnkAP9OfRoBeinPVMw88+cS+lPV+UV5e7s3LyzuG5GQRiWkgStIYY7SIyiLpMzSrGxoaXtvbMsIzZuSa3NwlYosA+BM+wnNbv9+f6VZqoZCHisgUQLE6WL0J4qx0gDctYAos65VIJBL9sGX9OLNPijeCKHrEiw0QETLl8kJhNGY7a/ZrOfuRzMzMDAX1WQoCAKaCnCQAQGUUsRFEjza8HcAeK144HHaJyPFi5CsK/BQojyCleB9JDvP7D7S19XMB5gPyV4isAo0PUEdR6cu1yFYQrclk8jwAE4q3D+xXxXO73WIL4iANAA0AAjEeY8bfwi9N3YcVAFJe2u/rXHDNmjXtM2bM+LZlWa4sr9dPpW8FeSCA10TxP3p6ejZlZ2fvTSUjHOdUQl0FcgYAF4hepD3PP2r4/f4yR+lrKHIYxJwVWbnyBQDJ9LUbLaWWkuqnEOQopXwfsrgfe/Zvj7ePfOaMhSHt6CUAtJwmRgEvP2M98XeseF+HZrJ+/fpOAKiurn4HRqIAQKAXPT2b3nzzzff2Nt+eWOyxzMzMd+HI1VQ8VlJDzI+kUcml9ckAF4ngyrqVK2sxSM7GxsZeAHeGg0ER8uK0IW2CfWC/ejduASCQERUrZunxVDZqo88neAXBHyiqHxmoi+d3HfeBfWQmEpLurSGkAbL3Kb+1a9d219XV/YOUpwF8tLd5CD8NIEuMvQqjy+n09vU9ROFaEcn/gKX7xLFferylS5e63cVub0LUpI5tO7LtpA3u3NXAkoJC37Jly7y33357HMM+6tIrl7qxBs7WWMcMEMdhkN8liSNcHjUdwI79IefuSJDiAgwBEOL0quh+URQR6SNh5CNsGRSKj6BWWs8E8CxGGRI3Nzd3hEKh3+qk3jZGNiocDC9JmmRLY2Pj2vdV4I8JgUBgqlIqXF9f/wgGff99Urxlly3LM1CHEPy0AYM+oqTX5Z5lJ3fWL6WZlZHl/ZW4rTVfvOz8lxVdDX/41e82AsDJF16Y4e1yvmam4jm2ds6B4KDBnqIEpmhtTgVQvy9yjheSwkEWR63H1VN/MhBuEYgh+LVAINDc2dn5cmtra9+wVE59ff3LY+TAYDA4H5RblVJfBvAvr3jhcDhDHPlq2nD38OBre6V4S5cu1Z5peYc7Ri4icaxA8iCSASEIxAclFYIaxCIIlyiiE2I3f/Gy//hdPNH5N4/HPkFBfddOJucAKCRpAOkRIIOgS0QUyTP8ixdf0/gBebkIAAIQ0FFK7UrxGA6HJ/X09MTXrl3bg3ENI4f4czMYDOb29PTEWlpa4mPdMQwX0gYPAAgGg3nvvfdefMOGDfu8JiqUFxT47wBmaepbCvIK7s4P5d9fX1+/cjz3BwKBoKK6FkCxJbJ5PPdUVla6MzMzC2KxmKxevXoHBj3bB0lVVVU+SVdBQcGO9BLZmFRWVrqbmpoM0r1XVVXVDLftjkXeiIx8Zse5gFQXCfAIhi0h7bHiLb18qc+DnPNp5L9IlAEAhEkS7ST+aSA5ACoAQFLTPUkJKW4AU0BMUUDI68mtAeRwEWQ6jnOChsoApAPArQROAXAISQrkoMJMdTKAe/dU1n2BEDNaj+f3+6e4lDpFyGPFkewsX2ZGKBh6h8J7aPH5Xa1vERKfO3dukcvlOl0BJ0EwOTcrpyMcDD7SE4stX7t2bffweyoqKjw5Xu8MulxfAVRL0kne5lZqoSi1DEZKpxQWxqZMnvyqbcxNjY2Nrdj7eeRTAnkEgn8jWQHiCgiWhUOh14R8yhjzuN6mt0U2jXg+KxgMHqmofk4gDACG+jvhUGiriCgoFUskEstXr149EI5j1qxZ2Zk+3+dAdZxj2xlulzuvOli9RYzcHrfjjzU1NSUqKio8OZlZPyU5zQAdhBhAZRLmyUhDw50VFRWunKycMwFUAuhMP/cUMfKP3ILcv/Zu2zZZPN5fC6RPhAaUyQSe3N7e/r+tra19wWAwj4YLqfhZEhUQeLo6O7cfGgotl3r1pwiGODqocDicLbYcASUXBIPBXzHODfTwP0mcBC1bAoHAj1amLMGpOqL1ZSL4BgE3ROZXB6tvBsWCCB2Ruj0yrnz+GxdO9iLnJwr4yYDSAe8IcZMWLO1LJj+fjMdfws6PT2NMl3HMRULeLMD69O/ZAM6DwA8AfX19GQJxi2Bz0uYfBazrL5Ogx0CWhk8OZ+yJrO8DVigUOsqlrOVCtQSG/+eI80ND+bUCfVS8Qxz5SSAQmDrG/QLhbLfL9WMF+IX8O4CnhZgEqv/O9GVed8ghh5QMvqGystKdk5V1KV3u+0RwESELtdLfF/A0GHnDEE8T6CXV5S5l3RAIBA7e24err69vSyST31fgLwA0A7BJTgd4BgW/1FCPyRS5NhAIhJBeKgKAcGVlqSLPAxAVkV4AICRfhNNIltFInlJqYL5YVVU1I8uXeROhzqeYvwnwXSXmChA5SvNmr9v91crKSndLS4tD6ucArFPkcaS6EJTDxZh3AYjb7RaIEyWlnMSPAbkaxFxR0lVbWyu9QI8xeAVgDShHUuRlGFPf2tpq+/3+AzX5U6VxBBT+D4ZXCEwtwXkivFr8csTgd3Oo338wHHMHKXdAcJqCmkcPryRxvIiUgDjEpVQxUkMay6XUUQLMAtkMACRJSAEFk0gWaOjEuHu8ky88OcMS5wIKLwLRrwTNdOTijh559cHly7vDJ4czclyTkkwPqUgCIqazre2ZkgNLHnESvNcQl0NwKkkLJBzbsePReCq8C/CC7elcZ9l5T4ByBgAvAIKYl2cVBgCMNb94v2E4EFgA8EYQHQL5cv3K+lVIGSAa/H7/P1xKX0PyQg1KRUXFd0cdPhJhI3IHgCe1Ur3bO3bo/Pz8vxFcDsipPrfveQB3Ij2MmTJliunq6mqGgU3SLcCxhDwPrW/o7OzcAQDZruxieuUmAEdZ5CnhcPi6vXVLW7169btlZWVXFxYW3q9EFgnUZwGpJpkBYhYgB2qqUCAQ+M+VK1em5t1NTZttv/+bWusqBd4CYAaM+oZo864AsB3bXrVqVRcAVFRU5Li06+sCOUmIU+rrG15EagjGUCiUA+BGgt/xau/zACKRhsiDVVVVf3dZVjbBrxCMOkq9C0CampoSAP4WDAY3aPJUAG5CXmxoaHgGgNPU1NQzd+7cP7mV+ywI74JWv41EIrbf789waf0bAecYMRc01Nc/CQCH+f3rbM0jSc4ULeUAXkC6A+kzpsOj9TMCHsbUSsDFEPNL28j1SqlpRgwdx3kund6OJRKPZhnzjO31ng8qv4E8LJArksmkAoB4PN47bsXL90yZKwbn9iudCLaKcc6/6/rfv7QzVSkoiSFxWgRkrDeml1+zvBvAizU1Na8cEKz4LoDLAOQn4nE7aSctgH2kPPTyipdjNTU1D6LA+0Omh6wECg1lQU1NzWu7G4PvC1prA4jT3wr0U1lZWQSqb4rITBEsq185ZN4jjY2N2/x+/48treeR6tI8X/aTAB4dWYI81NDQ8CfszD2ZkZER8bq9D5H8GkSCfr///xobG21gwCXv4epAdSmJayD4p5B310WGzCfeDgfDzwjM8RAetHXrVgv7MFfasGFDbMOGDa8DeL2iouKX2b7satFykSJPgGAyyfkW1TfD4fCySCSSjABJNDZuCwQC3UppAZA02myvr69vG553bkbuIQJzKsgOCqqqg9VVEJBKHAEqU5uw6RNLPgWgAYCzatWq9kAg8DeL+lwQpTQMA2gBIJWVlYrCk0DYAGyAiw+bfdhNrza/uh0AXC5XDQVKbDweaUg1RpZlHSAiQQKbAQzIGBPpcAs6QEAPm4yvXr16azgcvgnGBACeA5EXIw0NNyPVaIww/DU1NfUA6KkOVouIGII99Q31HYPTjBhqklQYVjAAwOJCkuVAKkQEIQ/H7Z49DqNXW1trd3SZX0PMT0Buj/ZGYYyxXC7rnazMnKZ0mg5CHsLAhJRuCI5O5rimDM+vu8cSCO39sSSp4kog/et4cPrneD6X6xCQc0l2OzK6+5tt2xsVuEpEKBqfKy8v9w5LQgAxDJuDNTU12YTZAIBQym3bI3bUi1LSBSABhbZEIjHc0ggASZIQtU+RqTSGvcSWlpZ4/ar6l7t7ui8S45xHcnUqOgiXJJPJoiE3i1YQUQBsjCYhAChnAckCAG9AQBFJvXADC4ZrIfyhoXzbGPMMBi1nWDGrDpB/AMijksPSssKrvLOpeCIg3yG5GsA8xxP3A6neVYFfFeDpHT073urPa8eOHW/BmIsdMZdqrdcAKdc+rfV04di7ayKRiBDoEBEj4GqMzwOpP4zKiIZwRI8nIiM+3tIrl7qlU4IEPQAAIgmwGW3YK2vag8uXd1944YW/67Ri7r6++NUk6cvOmFKQn3MggLcAwIjzZ0V9NsBJABTJuW6lDwGwaVd5K+XstQbGEIOXHgMQFBirs1NSsqgiihSQ3A5gVOtqU1OTCYdC20g6IlKplPIAQ6ugjNagASJQu4xfIaIICsbcqkwzRtbjJxwIHEug4/WVK1/DsMYhPWx+qDoQAKhuI1DoVmo6gA07ZRQCIAFRHN0aLEApRLykejmyMvKb8coWeTPyXigUupciRxE8LBwOZyISiYqFkwGs60sk7vO43fMJBgB1akVFxUs5OTmfgpGZ4uDrg5dFWltb+1qB+9N/quq5cw+BMQsVGaSgaJyvcVypKKKgmNLVYYyrkubH8n0UDGrhqCDwtrW17fXXvuWWW6Jbt2zrM8YorbWd6cvIE8N5/de1I+sANIoMeMKUgOa4XeUpoijGt9cyWZZlIOIAgBB2R7rHI41JLXVAucQ1av7hcJgi9ABQikwWFhaO27pIUIBUD7C3su8rotTpotQx2EWdiNv2SwTWiQjsYW24aFFpr4ldPXcSgAhMIfawpUgkEg+QXC1AEMABSb+/CJQjBXL9mjVrOmD4LIAeKJ6YkZFRKEbOBvB8/arR1x0DgcDU6mD1j2i57xZykhH5mQhW71aQPZDa7CII17g+dHu35Qg5MLciYIFyZGHVgXvtOrRgyZJCCi4CALfHbSy3JUak+gtf+UI+AHRs7NgByHMk+z+xBnhMzQknFO9tmeOCTFcc2llZWamhrshmiGwHMNnRzqTRbtu8ebMLlGkAlBE8br9i7xwNkNZoI4k0YmhMuui9Urz9obBMNRoV5eXlY0aZc7lcBkCUQHvcxNcPvqaMUmnDA+IqPqrykWwFEaNw0Zw5c8aqOwyHw7kYVsXXrFmzQwSPArDEkSUWOQ/C7d3d3WsAGLGlDiIbBDLJpfVZJGbCqJ+OVkAwGDxYU91NymfF4Gt1dXVXRqPRdiruz2h1xM6h5gjG9cFWtLXFCNk4+DcRLvBp/eUrr7xyrz66yys1JA8AEXW5rOcBxAQyC15vPgBEIpEkBM9BpH3gSci5ym2O3pvy9hhBcvv27akY9sBaAV8D4FbAknA4POKFFhcUV1BQJUCzbew/DF0HUikvtDGgoYgIRagdx9mLHlvtj5CMuQIcn5+f/+mxEiSTyclClAn4yBtvvDHEeCJaVCrqONyWZY0azVvIFynYCKLC4/J8PRweuUQUnBtcKLacV15e7hmRgcFDIDcDchaUWgbBYy0tLd0A0N7bvlYUXyKYDfAygC2RxshoW7mUgroawHxjcG9dY91LAOD1epWkpl4cq5EUSW91gxnP/I6keERECTniWVQqhVEpDxOx9GivbMUKR1LWmwETOQkfiCvXd2687pz/PCfdC2yCjGP9NrUmJ4uQWi54N+HEr6LBtxyH52f1Wv0ba2EkUQdwcMvqEeLfw0sXvm+O05QBA4WdkZFhAKCxsXGbgrkeQBupvmSM+dTge8rKynzKhe8BcMHg+42NjW8Nvi4UJ7WUw1HNDkZMX7pwGW3R3tDEU9YxSdj28EEeQIoREUDgWJa1xwvoNTU1XqHkEpyqwHtCodBRw9NUVla6PW7P1RD4KLwZw/xORYTpiaZLiTpssHjp/9DX19cM4l4RcUhcDkf+Z+7cuUUAcPjhh+eEQ6FLlMX7SL7V2to6YjmGLrZQ8CqAKghK+pJ9TyE9tG1tbe1TxjwMQVREspWoOzGKAWT+/PkeEtUgQIov/fyW1vp0pBwAfCAPKC8v94RCoaMqKysH+Q6no/GRFnY9pEbqukoy5QXyKb/fn5n+XQGwNJrAaTMPzDKKCUVYQmlqfWN9y/BcquYHeinqCEBK+ze5AqAA1dDq6MARYU9B7iS7L5r4lBFnLgQqna4Hjn1z67rWnv68Zs2pmgXyEgiKST69td3+3RN3r3h51St1myKRyMDLam1uTUyvPCiX4OJBX7HUZ9TjbzW3bACA0hkzvB6POhHA20L0Eaq9tXnduFyWhlNaWppP4HMgpyrgxfxJBY+2trYaANi0ZcuGouKi10nMUYLFJUWlGcWlxd7SotKqrMzMbwmlwkB+1N3b/dCOHTscpFzCFk0tKrmAwEkC5BHIKykuPaCktKRz8+bNW6rnVFeUlhZfRq1OBzCZQJal9fSpxcVm05YtrZWVlZkHTJ36DUKdQmA6yDyXZRUVFRfv2LJly+a5c+dOKystvYRUpwLIJ5jhy/CVFxUVJbds2fIOxunFMmnSpDwYFBBmuUDyFdXnS0uKwyVFpcUlJUWzS4qLT3Zp11WKmGKIq6j55ObNm4dU6oKCgj5Lu6YCMpuKC0pLiucVF5ecPbWkZGZObm7d9u3bE21tbU5+QUGzpV0eEtNBHKmVWlZSUnqucczFFFYC8sO6hvq/YBSl2bx5c7SouChPUS0CeG3jqsZnB1/PKyjY6NL6BJBv2WL/buvWrSM8gTZs2GCXFhUHAPhJFSgpKZkTj/edAEAU8FDqOAB+yufzfVEZeFwe97PFxcWfLS0uPZfgsSSzAR5QWlJ8UHFRSdmWrVvG9CMumVLSA0qQZLVS6ujSkuJFJcWl5xZPKq63KpZUuJRL+ZXwDAF8NNwyf+l878srhsZE2WFvfbNQld4mCpUA+rUXBCwRHEYiaFnutwom52dEo9FkvC9hO7btEjGiPXpIK63AeQDLhWIbMX/dhR+msWHf7xLrWySLgJQXvQgWVSypqGt5dNw+juMimUxabpfbm7IQmHW1tbWDP740NDTUBgKBdVrrwykyRwTHg6aH5ONIJq9uWL36LQyqMCLSaYQtirIKIjZoWQaOSyVUFABsbfe5lW4RwVqISRqlNAx9NqUDALq6upyMSYUbDHCvodyhDClCrzLs9w1NCPlPceR6aCQFYtGhTyD9LlTjIhKJtJeVlf1qw4YN8Tlz5jzmtaxDDVRIEQGh8hLSAeEdhvJifV39Ooyyy6KpqWnLvMp5Vzju5MsirCTRLZBG9OlXB7vCNTU1bfH7/T/Qou9XFoIUHAARGIUW2zgvNDY2rtmN7E8B8gtqdd8oMvSEQqFrlRhaljXWDgokxblSQ68DMBmCTYbyaiwWa3QcJ5Gdnb1JCaoJtT4p9oONkfpkMBjcBKJRAa8YQ0eUKA24oTBmGQBQ11j3etgfvsjQLFIK+WLMeor1et2aurWsOW3xSYT6IyBZAEBwvePIBX9/8PFnh2dUU1NjTQtW/BeB7w3yXhlO/0sziXg8EYv1tXt93kvcJvOFvu3bt69YscKpOXXxAyRPAbhdxFkEl+oZIy/ohHI7Sq5WxGlA/xoin407ztkvPvjkpvDChbk52dZvIXjOEO1K9PpnH3g4sqsXMhbhqvBsaHkAxEG2cQ4b8M4YQ7RwOKwikUjaF3VMhlv69vXvDwodDodVLBajr8knEUTsccpBpNbZBLuPLaOw086wJ5uELYz9zvvz2908TCMlqxmWtl/+/blpub+sgTwtBVwCInvQ3H8aXfAjtSdrCLW1tTZqa39y9tcv2EgjFwtQSWJ4GID+jLTH6/V5fF4fBCtEnFUZ0/L//rmLz35j+9btYdt2DCA5iuppcaDHsigYJUYBA5PT1JAZh7i08mM3a3q7geFwOKezs1NaWlp6ABhHOwWKygvBry3L2p1p2YlEIuPZGT/84+3r3x8U432+4eyuIRrM8Eo/XnaV/3jzG+vZ9kT+8TKiLEuo/IMrvUAMzK4Lfjdn3V0HtFfUkThdRI4nWYlRtmunJ/xAqhUKiEjA4/LGJxdNQV80lojFokwmHQNjNjjGuEgMmj6mYdpck5oP5gEAgSICNQAe26PHH0QoFFogjrMsJysnWR2o/kvdyrrHKTydQF1vX/Rnzc3NH5cwfBN8DLEg8AzdfMoOUWbj2LcAtVfW2kBt45JLlqzNlZJbPBaPEuA4KhwDsBSEHmWxHgAgEI/LZYk7L0cyc7KMcZz2RCJ587YdXY9asH1O1FHDlx2NsWgp53xALgLoBaBAnOJfvPiq8Vl2R0ACl6aNEgLi+OpQ6CUIs8ROfLu5uXn73mQ6wQTjxUo7iw4sZopIp4bapeL18+gNj8aRGu7dc8kll/xlY/fWQ/ti8Vs9Xm+5x+s1lttyK6UAkeGuaenz+Kgst/sgl9v1vfKszGmxRPKXK274/QjnWgA4+rRF9wP6DKJ/OxJnTcrkcdE+/dRejMYExtwOqtlCZkGkl8RGJHh9pGn1O3ua2QQT7CkKkOcG/0BCObD3+DjjG264Id6xo6s0Fu0r6mzvdL+3rc1q29LWG+2J3g3wTgFWAYhzwDMkhTFGiZGpcMw3Mizrt1+4/LwZo+XvGK6HYPAyhyJxqXgTroH1lT2gbuXKR+J2colAPpuwk8fH4vHvRZoiE0o3wQeCnjbroHaSpw8ykmRC9JutzS3/2JOMjjzx2Bla6+tAHAhAiYhyHKc52td7uTsXd/Vs61nb29t7FEBLuzTTk7mdg1xCA3KwAt0zqyueb3qtKTE4/7fX/rPnwNkVJSSOHfRziYarlhQ/hO/u4TqebNu2rWvLli1bt23b1tXW1vaRje48wScPS7kTjWJ77gNwPkEXQC8pX1l42sLX2t9pfyUSiSRPOe+U7JzcwiJqOnf+/Nah4QWWQh8dP76CFn4KIMydupSE4L6u1vf+WaueMEfbx8+FmCm93dGMrLzsqwsmFRQCOBMik3ZaVOgGcKLPnf1HjNz0aoR4niIdSBtZAHg0zBIRdhBG7+dohaNyuP/wsoROTGtra2sYHuukoqLCk5OTM4M2fWIktq1jW2t/mpkzZ07OyMg4UERsY0znqlWrWgGYYDCYp42ZYbR2jDGq311Ja+2oPrUNGXhvbza2+v3+TK21XztO9+uNjaNaaCsrK7O8Ws8SWPmkE08Ys2n16tXrMej7hmeGJzsZziySXgBRx3HebWxs3Dg4TXl5ubcgK+tAcbmmaBE3gKhovT4SiWzBKPOA0tLSjOLi4gpjTIEySjl0elQisdWdzGl/peWVLgCYPXv2JLfbXQEgqZTSIhK1LOvN0d6F3+/PdJGhhDGbVq1atX74Na31EXScBOHqNdo4JMUYo0haxphsLdqmi5FIJBKtqKjwZGdnz6ZNi6QkkYQlFuGCyxizpaGh4R0MspxWVlZmeS3vXNDJFaX6lK22RlZF3sRurKuqdkVtDyC/ZWrHbRoebKiXZ08vPO/TJy08IC+v6AJN3mNB/+LUy5blAqk9TAtOP66kxj5+KTVuBHDioHwTEPlzH8zySCSSXIiFWYQcTaUylVbbett7/ujLVd9wBBeRXDdMpulCHotR9wT2NYDy0uCfBDiMlFWiEVdjOyLvF8rLy722SvyEwK2FhYUzR0nioTGHiTY304X7iiZPPqv/Qo7XO0kJz9dUN1uWdTjSrYTjOAWgPoHgHyzqqyyl/FrrkALOgUduNLb5eviQcMkoZe0KWrROUoK7RVnfwOixdZTP7f4ytetzsDCZWp/rttzfLysrG9hH6Pf7p5gM81MKFyuRMgq/59L64sFpZs+ePSk/N/+7cLl+RJG5Dlks5IVizO8CgcAiDPuO4UPCJcVTiq+EweUK6mAQ0y2qC5THe3syM7lk4EV6PJMsZR1rKetGRfULDT0nvcl3BBatk0Spey1lnYthra/W+hAFXkOtzxEln1HA5RD5k4L6AsljNPUl0PhFMpmclk7vpvBIWnKrUeZ6S6kwtQlR5FIFXDV37tzC/ryDwWCe1+39GRS+COrJAL4oWq6dM2dOHnaDAkAlOmaA/xHIU4O+3cEK8v/cLmt5+3s7To/29lXFotEFpr3n/KM+u/jknOmTv+MS3KcovwVRg4EtENIjYn4fi+Lil+5/YhsA2I7rEICoxFGmAAAPS0lEQVQp51vyrxvs9W/dcuUt0T/++ta/wMiPJRWsZkAmCuZdeOGFI8KE166o7YHhoxDZ6bFCzDQiMTr23zlove/9ID8nfzFAA9BFkRHO2i0tLd3YpleQrAfEEfDH1X7/8QDwemNjiwNzM4m3k8nkC0ivFa1atarVjpnfp1fJt1Hr+7u7u+8ywM8cmAeU4vfgNT+sqqoa906QqqqqPCqZA7BBKAsO9ftnD0/jL/L7BDxPDB6tr6+/F7a6jpSNRUVFA15JlmUdrcgjHXH+GGlo+AMUrjQGPZmZmRaQ8lHN8Hq/TYXzlchvqPUt9fX1dzkiV0DoWEovD4VC4f78ysvLvfCarxKyyDb2D+sa6n5ft7LujqRxfizEu1Qytz/typUrW/oSfdeD6KDgHVvsh0eLpjZjxoxcQg4j0ETFUwcrBgBFY2aI4MHeWOw7trH/V0SaCB4MYz/W19d3Y1+i76uArHKRhUAqCHFPtOc+AdwkHGp9d2dPz52Iq+8AqtPlck0blP8cEhcamL/WNdTdHYvFvkPKW1rr3cYHUlgKJUrmwNB2xLkUYu6S1JZ4AzCXxLHdnd2fbtuyTbZtacvp6e65Rmv1IMH/BrkAYEFqeCR9AN4G5HsJp/dbLz/++A4g1TMS8iUQ+QB6jTEPDHb1SjhSCyAyaN8dBCzp0T1jKJF6VLhz4ZxAgSJr3ol7Nhhhxr5shN0VwWAwj4qnGiN3AXhcUZ012IG2X/TIpkgUBknj4P8RWAOt7/H7/QsAiDGmE8Iel8s1eD5pVKZKCCROikkmk3ZLS0u8vr6+raGh4Q5AboXgZI/WgfHKalnWQQaIGsq1BAsNrU9jWM/T5etyCCoofOlQ/6FzO2Odbyds+5exWKyrP40ypltEiiylzgsGg9O7urrWCeU3a9eujQJAYWHhHFCdAfJPrzc0vJgeBkpDQ0OrGPktgHwKL+x/T5OyJk0FeCYMbmlsbNyAVONjGhsbNyDJn5uhB8OYaDRqU2ALxYzmHA6AednZx4DUBvgNRYrc2v3pIXnE409v2bbl2ubm5u2pUPQqAQBKKdPU1NTT1NS0JRqLfbuzt3cgmoLH43GQemEmFoupzMzMeWJJpYH5gdvtfnOg8CR7ANhKeFEwGJyXmZlpOyI/crlcW3f3jVKV1EEcFK8F16UG6ikA/yHAPSKyEpAOpRVIesSIlhRGRAxEohCsJ/ikAFeROMXsSNz04oMvdgMppcuZXrCEkC+kipM+zSFxNxGNopvg0OULinF73KOuESSViVI4uOXTAp403essEoXGpGO27O6h9wIqoxYAcFsm+aZA1gkw0+PxfGa0xELRimaHA/k2Ba2W0j8LzQ1Vi0gvKLYxZogSKKXGDO9OkceEyLKB6eMWFjwXBhu14+yAyLtQOHr27NlDwhq0trb2icKvCMwT5TyYm5V9m0upmsFpOnp6XiB4D8GlGnwoOyv7emVMFXYq8cEUyYeDpuEyxO34GhHpIaUc6QNLRcl0AJOMHunjWLe6blV9ff3QoK+WJQIZ0+g1c+bMSVDq3wVogI1OAbaTcv6sWbMGnDmam5u3b9q0aUTIxcHW9ebm5u0tLS1dw1I4Akz1uDyXaarfCOXQhoaGjldeeWUgXXtv+1oKriQxW4P3wZG7NbAomUzudl/fzjGzgQ1lyqCQ96x6/K6FWPh3O6qmwaNmgKjIyMo4X5HTRMSm0rCT9oOxaPejCvrduEhrTtLa/uijj8YBYMHSJYUuR04EJADhySCy0g+TD+J/jjntuPsB7LCNPAagAxg6NyO4qZe9Awp65IlH5ru9WccLUELBfBDlQ55CpMhQ3WiJuV+0qj/yxCP/+sLDL7RjPxEOh3OMbRaSsBzL/XlCpkHEVuAyAEPig6TkoRLRnoaVdY2BQOA8TXWzsvh9C9a3RTjCIdwYQwIKQjU85ooR5SHEaOhxGVgCgcCRFMyjQo9j9HQFbqQgmOXxHABgiGPAjh077sjNza3XWn8agmWkvs7lwkYArwJAS0tLV1VV1Q8sy7pfAQsVeB6Unh4MBi9saGhYR0MHCgJgxJzGsizDVKwr8fn6owLYScByaHjAKKKP8O0sKytjV0eXGqNNUllZWfMhMgPAVCiUgeyESDjT7Z4JYHR/XQFHsR6MgCJKgA4Kn6ISN8AR/sStra19VoV1XY7P97RY1lFK5CJQ/VQpdAB4clf5D5msCmDgAPgzzFN4qhOpuddqADj36xeGAJkFoD9Q7dRYPO/vK268fUQPoxJmNjR/nlY0YEjF5DwQh4qIKIXTJmegzgZKBvmKGVBeWfHLFQO9mrK8ZTC4gsTguJEDeaZvnSpUFwuwXXmzVwLYb4pnjKkk6UskE9+KRqNdAJCbm1tM4DOBQOCQlStXDgmAJBA3LboAyMqVK+tDodD3ANyooG4DZJ1jO0Nc8hzHoUtZGmpolSgvL/eC5mQBtwvNm9gN4XDYBcd80xj5dXe0+xEAyMzMrLWUvltELcagiFjhcNgF21zgUO6sq6t7NRQKPQ/gD0pUFdKKFw6Hq+FgQaQ+ch2Ap4PB4MsavEYZNQ3AOjiJZij3NkBqZs2addPgXQhucqoBMunI+sjKujYA6LPtt33a2gTKubNmzbp1WABfy+/3F9i23ZEO3YfW1lZMyssfNYBLMBjMgcFxBvLtRCL+OgB4Xd4GKN5O7V6MdJSy4feJEo5P8wAA0T67r66psem18vJy19y5c4uUUlMbGxtXAnCqq6srKPKV7Nzc/6qtrY3Mq5r3gGM5TyiomQAG9gqOxrjD+xlx1qfj9ikAEJFjfW7r9nMvv+Abd+T+7xu4cpAiCDYDcg8EXkmfvjP06YXGCCzo9bZbHQNBaOc1vCVG1w5O7gi3a5q/EKpQRjPTilgDIRsEvQqxUb1f9gKGQqHJCurzAmnt6elpSwfOYTAYfFyRJymof5szZ851a9as2QEA88vKfAmwxIhM7T96OR6PP+d1u38M8loITDqEQj+WZcwkUZIFYYHH45k0Y8YMnZ2dXaaUOh2CU0Xwy3gi3rwrQcvLy71iy5kgi5Mm8Vr/0CkUCq0F8IYonlpVVfVXx3HWpyu2C8QXtei14XD4BcdxqKC2K2UGnAjEtitAdVYoFHrScZy36bAdFjdQkm0AsKOn581J+fl/IPnNDG/G1wKBwO/b2traS/LyJotSX4LgjaQ4/4u0ISmRSGz1eTx3APh+ti/zumAweJMxZrN2dI5ySQ2AXFjW9QAS4XDYZdv2JCEyITQejycXwHsAZH5ZmS9JHiuQMjGyLh1OD+EZ4eeRY7YAOCEQCDyWTCbX9CsxkFpaoEgBSDiGk8rLy72jnA+htNa5ELhAZvngK66srNxhWVaepfV/QbgZKaWGiBRSsKy9vf3xWbNmvdyHPrhgbTWObMBusPr/rxyjxgpiBQAKbDVAN4FcAP3ezMcZMTlndZ535caa9c/0x7ysffDx9TU1Nd/a4PONofEEsA7zD/7MPAh+gPQcAIK4EA/0JdqH9CAvPvjk5oolFT8GRgZKLs9Keo2jzhHyTS3stB3zXu2DteNyedsdVVVVeRR+U2DCANfk5eVNA7CusrIyU0GVAdKsyAVeyx0DcE15ebm7Lzf/TBI5FB6GOB4B8M+mpqZEeXn5n/Nzcz2E+rSrL9aveAzNCc2BxS8B8h4gucrgkrycvG4AUyBIQHBOd2/Xy+kdFGOSl5d3BBTOoEHUo12LwuHwO5FIJKlsuxjackBYLmVd4aLrRgAvWZZl2cZ+FmL+DUYdoaDKDeWhaDTW7zhBiN4M4lUFuVhp13aIOYiQOzpisTeB9FDLsm7MzshupcaZlugrSgqL1guljEAcNv+jcXXjgNGipaUlHg6H7zCO0wnibA31C63UdmiJiahXmei7u7GpqRcATJ852LLUlwWwScmCyAVVVVU3rVq1qj0+ZcpCiHwBoEcDRwO4CwBMrgko4TZQ3JrqYrrdv8Mgg40GTgZ5iAAvQcmJ+dn577Wi9XkM6pnmzJmTp8lzBHwXRiBuXOSjZ4cA5QAqbGPfhXTjb4zZrpT6vQV9ZkZGxtEEp0Lw167eziHnC44GsRS6xj5uEQAo4iJjUFv7wOPXD7/xrEvPP1Zp3sbRJ/ltFLnG6sby2267bbdHai1btsyLfNepBnILhuxqkFeVOP9++69vb91dHv0sXLow1zHWctjmBSq1gUTr0395bK/PKx+F/v1w/eMTGfY7kBoFmFF+35P8Pyys6urqSsuyNr766qujOocffvjhOYlEoqy+vv5N7GLLjN/vn2JZVnFXV1frSGPFCDhnzpx8t9vtra+v35ftXR8FXOHKypIYsGVwD7srxj3UdBlno9HWDgDTIYgK8DyAAwCZTbJQyGvtHJxyztfPfzhp5DmB2cxovEd5VCKRkUmrz3hddiLXWJ7ZDuUMQk7CTqWLQ+QVCC+5/brxKx0AdPe4JMNn+kgmjWKSjrO/jzqWYf8O/x0YOvzdUyX6MJUOAOy6urpdBiZOW/JGWC6H09jYuA3Y9a7sQUj/8PwTQDLS1LRHfr7jVjzbsjsVdJsIhORWEfyM4sSo9KUCnMhUlKoFIjzUBW4Sqq3MtFoJdOmEo6E4GW7XNAVTJoIiDMR5ly4B/ygiv77rutv+5c9Um+Bfg3ErXjwaj/qyvO8QMBD804mq1ffccut7p5x33pfzc9RJAvkOSD8BH4iDIDID5BEi6QDKBEVSB6cMqBzkdRhcY0zs8btvuHt3Q5MJJvjEMG7Fa3uzrbcsmPMABVkCucdu72wHUuHYAdx79pfPfloyvAtozAkk5pLMEcBHwhKBEEiCiEGkm+DrjpgnHCv20j2/uue99+3pJpjgI8q4FS8db+XRpUuXPrlizgob1w2d19z5uzu3AfjzkksueSgLPTkeS+VCTI5R2q2MIzasOGi6kt3syNeq+5Zbbh1v8JwJJvjEsacnwpoVK1YksGLsBI/ecEMcKV/P/bWWNsEEnzg+tEMyJpjgX5kBxaNh6my4PQ76MMEEE+wp/e5fBACBQBnE8TGae6msjiSA/RpReoIJ3m+GzvGIPhF8/pjTjp8OjnliiqLwgxuiKkDEjOnVSocuEXwK4GsiMjwq5wQTfCSxAEApKho6AvkjgQWAOGP1eYSkjir5wKCoXcSvMCKg8C5D53lL1Nz97bYywQTvBxZWQOQ0IWnOpMjbAka5i9glw8Pzve+IjDgeWkBNpofJAFIH3nIpIOUC2aUX/wQTfBT4/2cQrk61zOSdAAAAAElFTkSuQmCC");
    background-size: contain;
    background-repeat: no-repeat;
    background-position: center;
    opacity: 0.12;
    pointer-events: none;
    z-index: 10;
}
</style>
""", unsafe_allow_html=True)

# ── Data fetch & transform ─────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner="Fetching USDA rail data…")
def load_data() -> pd.DataFrame:
    rows, limit, offset = [], 50_000, 0
    while True:
        r = requests.get(
            API_URL,
            params={"$limit": limit, "$offset": offset, "$order": "date ASC"},
            timeout=60,
        )
        r.raise_for_status()
        batch = r.json()
        rows.extend(batch)
        if len(batch) < limit:
            break
        offset += limit

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])

    for col in ["all", "dedicated_or_shuttle", "other"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    df = df.drop(
        columns=["submission_date", "week", "month", "year", "state_point"],
        errors="ignore",
    ).rename(columns={"all": "carloads"})

    # Marketing year fields (vectorised)
    m = df["date"].dt.month
    y = df["date"].dt.year
    is_sep_plus = m >= 9
    sy = np.where(is_sep_plus, y, y - 1)                        # MY start year

    df["marketing_year"] = [f"{s}/{str(s+1)[2:]}" for s in sy]

    my_starts = pd.to_datetime(
        {"year": sy, "month": np.full(len(df), 9), "day": np.full(len(df), 1)}
    )
    df["my_week"]  = ((df["date"] - my_starts).dt.days // 7 + 1).astype(int)
    df["my_month"] = np.where(is_sep_plus, m - 8, m + 4).astype(int)

    df["est_bushels"] = df["carloads"] * CARS_TO_BU
    df["destination"] = df["railroad"].map(DEST_MAP).fillna("Other")

    return (
        df[["date", "marketing_year", "my_week", "my_month",
            "railroad", "state", "destination",
            "carloads", "dedicated_or_shuttle", "other", "est_bushels"]]
        .sort_values(["date", "railroad", "state"])
        .reset_index(drop=True)
    )

# ── Helpers ────────────────────────────────────────────────────────────────────
def fmt_bu(n: float) -> str:
    n = int(n) if pd.notna(n) else 0
    if n >= 1_000_000_000: return f"{n/1_000_000_000:.2f}B bu"
    if n >= 1_000_000:     return f"{n/1_000_000:.1f}M bu"
    return f"{n:,.0f} bu"

def fmt_cars(n: float) -> str:
    return f"{int(n):,}" if pd.notna(n) else "—"

def fmt_pct(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%"

def oly_avg(vals: list) -> int:
    v = sorted(x for x in vals if x > 0)
    if len(v) >= 4:
        v = v[1:-1]
    return int(np.mean(v)) if v else 0

def pct_diff(curr: int, base: int):
    if not base:
        return None
    return (curr - base) / base * 100

def complete_years(df: pd.DataFrame) -> list:
    wk_max = df.groupby("marketing_year")["my_week"].max()
    return sorted(y for y, w in wk_max.items() if w >= MIN_COMPLETE_WEEK)

def mytd_sum(df: pd.DataFrame, year: str, max_wk: int,
             rr=None, state=None) -> int:
    mask = (df["marketing_year"] == year) & (df["my_week"] <= max_wk)
    if rr == "CP/CPKC":
        mask &= df["railroad"].isin(["CP", "CPKC"])
    elif rr and rr != "All":
        mask &= df["railroad"] == rr
    if state and state != "All":
        mask &= df["state"] == state
    return int(df.loc[mask, "est_bushels"].sum())

# ── Load ───────────────────────────────────────────────────────────────────────
df = load_data()

all_years   = sorted(df["marketing_year"].unique(), reverse=True)
all_rrs     = [r for r in RR_ORDER if r in df["railroad"].unique()]
all_states  = sorted(df["state"].unique())
comp_yrs    = complete_years(df)
current_my  = all_years[0]

# ── Header ─────────────────────────────────────────────────────────────────────
st.markdown("## 🚂 JSA Grain Rail Shipment Dashboard")
st.caption(
    f"Source: USDA AMS Agricultural Transportation Hub  ·  "
    f"Latest data: {df['date'].max().strftime('%b %d, %Y')}  ·  "
    f"Refreshes hourly"
)
st.divider()

# ── Tabs ───────────────────────────────────────────────────────────────────────
(tab_prog, tab_monthly, tab_map,
 tab_weekly, tab_yearly, tab_summary) = st.tabs([
    "📈 Progress", "📊 Railroad by Month", "🗺️ State Map",
    "📉 Weekly by Year", "🔥 Yearly by Railroad", "⚙️ Summary",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — PROGRESS
# ══════════════════════════════════════════════════════════════════════════════
with tab_prog:
    f1, f2, f3, f4 = st.columns([2, 2, 2, 3])
    with f1: sel_year  = st.selectbox("Marketing Year", all_years, key="p_year")
    with f2: sel_rr    = st.selectbox("Railroad", ["All"] + all_rrs, key="p_rr")
    with f3: sel_state = st.selectbox("State", ["All"] + all_states, key="p_state")
    with f4: cp_mode   = st.radio("CP/CPKC History", ["Combined", "Split"],
                                  horizontal=True, key="cp_mode")

    state_grp = st.radio(
        "State Group",
        ["🏆 Top 15", "All States", "🌾 Western  (IA · NE · SD · ND · MN · KS · MO)",
         "🏭 Eastern  (IL · IN · OH · MI · KY)"],
        horizontal=True, key="state_grp", label_visibility="collapsed",
    )

    # Context for selected year
    yr_df   = df[df["marketing_year"] == sel_year]
    max_wk  = int(yr_df["my_week"].max()) if len(yr_df) else 0
    prior   = [y for y in comp_yrs if y < sel_year]
    oly_pool = prior[-6:]
    ly       = prior[-1] if prior else None

    # Railroad list based on CP mode
    if cp_mode == "Combined":
        rr_list = [r for r in RR_ORDER if r not in ("CP", "CPKC")]
        cp_idx  = RR_ORDER.index("CP")
        rr_list.insert(cp_idx, "CP/CPKC")
    else:
        rr_list = list(RR_ORDER)

    # Apply single-RR filter
    if sel_rr != "All":
        if cp_mode == "Combined" and sel_rr in ("CP", "CPKC"):
            rr_list = ["CP/CPKC"]
        else:
            rr_list = [sel_rr]

    # ── Progress table ─────────────────────────────────────────────────────────
    oly_label = (f"{oly_pool[0]}–{oly_pool[-1]} (drop hi/lo)"
                 if oly_pool else "N/A")
    st.markdown(f"#### MYtD Shipments — {sel_year}  ·  Week {max_wk}")
    st.caption(f"vs LY: {ly or 'N/A'}  ·  6-yr avg pool: {oly_label}")

    state_arg = sel_state if sel_state != "All" else None
    rows = []
    for rr in rr_list:
        curr_v = mytd_sum(df, sel_year, max_wk, rr, state_arg)
        ly_v   = mytd_sum(df, ly, max_wk, rr, state_arg) if ly else 0
        oly_v  = oly_avg([mytd_sum(df, y, max_wk, rr, state_arg) for y in oly_pool])

        incomplete = cp_mode == "Split" and rr in ("CP", "CPKC")
        p_ly  = pct_diff(curr_v, ly_v)  if not incomplete else None
        p_avg = pct_diff(curr_v, oly_v) if not incomplete else None

        rows.append({
            "Railroad":            rr,
            "MYtD Est. Bushels":   fmt_bu(curr_v),
            "vs LY":               ("—" if incomplete else fmt_bu(curr_v - ly_v)),
            "% vs LY":             fmt_pct(p_ly),
            "vs 6-yr Avg":         ("—" if incomplete else fmt_bu(curr_v - oly_v)),
            "% vs Avg":            fmt_pct(p_avg),
            "_curr": curr_v, "_p_ly": p_ly, "_p_avg": p_avg,
            "_incomplete": incomplete,
        })

    # Total row (complete railroads only)
    total_curr = sum(r["_curr"] for r in rows if not r["_incomplete"])
    rows.append({
        "Railroad": "TOTAL",
        "MYtD Est. Bushels": fmt_bu(total_curr),
        "vs LY": "—", "% vs LY": "—", "vs 6-yr Avg": "—", "% vs Avg": "—",
        "_curr": total_curr, "_p_ly": None, "_p_avg": None, "_incomplete": False,
    })

    display_cols = ["Railroad", "MYtD Est. Bushels", "vs LY", "% vs LY", "vs 6-yr Avg", "% vs Avg"]
    tbl = pd.DataFrame(rows)[display_cols]
    st.dataframe(tbl, width='stretch', hide_index=True)

    st.divider()

    # ── RR Deviation chart ─────────────────────────────────────────────────────
    chart_rows = [r for r in rows
                  if r["Railroad"] != "TOTAL"
                  and not r["_incomplete"]
                  and r["_p_ly"] is not None]

    if chart_rows:
        rr_names  = [r["Railroad"] for r in chart_rows]
        rr_pcts   = [r["_p_ly"] for r in chart_rows]
        rr_colors = ["#16a34a" if v >= 0 else "#dc2626" for v in rr_pcts]
        rr_texts  = [fmt_pct(v) for v in rr_pcts]

        fig_rr = go.Figure(go.Bar(
            x=rr_names, y=rr_pcts,
            marker_color=rr_colors,
            text=rr_texts, textposition="outside",
        ))
        fig_rr.update_layout(**_lax(
            title=f"Railroad % vs Last Year — {sel_year} MYtD (Week {max_wk})",
            yaxis=dict(title="% vs LY", zeroline=True, zerolinecolor="#94a3b8"),
            height=380,
        ))
        st.plotly_chart(fig_rr, width='stretch')

    st.divider()

    # ── State deviation chart ──────────────────────────────────────────────────
    st.markdown("#### State Progress — MYtD % vs Last Year")

    if "Top 15" in state_grp:
        prior_comp = [y for y in comp_yrs if y != current_my][-6:]
        avgs = {
            s: oly_avg([
                int(df[(df["marketing_year"] == y) & (df["state"] == s)]["est_bushels"].sum())
                for y in prior_comp
            ])
            for s in all_states
        }
        state_list = sorted(avgs, key=avgs.get, reverse=True)[:15]
    elif "Western" in state_grp:
        state_list = WESTERN_STATES
    elif "Eastern" in state_grp:
        state_list = EASTERN_STATES
    else:
        state_list = all_states

    rr_arg = sel_rr if sel_rr != "All" else None
    state_rows = []
    for s in state_list:
        curr_s = mytd_sum(df, sel_year, max_wk, rr_arg, s)
        ly_s   = mytd_sum(df, ly, max_wk, rr_arg, s) if ly else 0
        if curr_s == 0:
            continue
        pct = pct_diff(curr_s, ly_s)
        state_rows.append({"state": s, "curr": curr_s, "pct_ly": pct})

    state_rows.sort(key=lambda x: (x["pct_ly"] or 0))

    if state_rows:
        s_df = pd.DataFrame(state_rows)
        fig_st = go.Figure(go.Bar(
            x=s_df["pct_ly"],
            y=s_df["state"],
            orientation="h",
            marker_color=["#16a34a" if (v or 0) >= 0 else "#dc2626"
                          for v in s_df["pct_ly"]],
            text=[fmt_pct(v) for v in s_df["pct_ly"]],
            textposition="outside",
        ))
        fig_st.update_layout(**_lax(
            title=f"State % vs Last Year — {sel_year} MYtD (Week {max_wk})",
            xaxis=dict(title="% vs LY", zeroline=True, zerolinecolor="#94a3b8"),
            height=max(400, len(state_rows) * 30),
        ))
        st.plotly_chart(fig_st, width='stretch')


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — RAILROAD BY MONTH
# ══════════════════════════════════════════════════════════════════════════════
with tab_monthly:
    mc1, mc2, mc3 = st.columns(3)
    with mc1: m_year  = st.selectbox("Marketing Year", all_years, key="m_year")
    with mc2: m_rr    = st.selectbox("Railroad", ["All"] + all_rrs, key="m_rr")
    with mc3: m_state = st.selectbox("State", ["All"] + all_states, key="m_state")

    m_df = df[df["marketing_year"] == m_year].copy()
    if m_rr    != "All": m_df = m_df[m_df["railroad"] == m_rr]
    if m_state != "All": m_df = m_df[m_df["state"]    == m_state]

    monthly = (
        m_df.groupby(["my_month", "railroad"])["est_bushels"]
        .sum().reset_index()
    )
    monthly["month_name"] = monthly["my_month"].map(MY_MONTHS)
    monthly = monthly.sort_values("my_month")

    fig_m = px.bar(
        monthly, x="month_name", y="est_bushels", color="railroad",
        color_discrete_map=RR_COLORS, barmode="stack",
        labels={"est_bushels": "Est. Bushels", "month_name": "Month",
                "railroad": "Railroad"},
        title=f"Monthly Grain Rail Shipments — {m_year}",
        category_orders={"month_name": list(MY_MONTHS.values())},
    )
    fig_m.update_layout(**_lax(height=450))
    st.plotly_chart(fig_m, width='stretch')

    # Pivot table
    pivot_m = (
        m_df.groupby(["railroad", "my_month"])["est_bushels"]
        .sum().unstack(fill_value=0)
    )
    pivot_m.columns = [MY_MONTHS[c] for c in pivot_m.columns]
    pivot_m["Total"] = pivot_m.sum(axis=1)
    pivot_m = pivot_m.reset_index().rename(columns={"railroad": "Railroad"})

    fmt_df = pivot_m.copy()
    for col in fmt_df.columns:
        if col != "Railroad":
            fmt_df[col] = fmt_df[col].apply(fmt_bu)

    st.dataframe(fmt_df, width='stretch', hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — STATE MAP
# ══════════════════════════════════════════════════════════════════════════════
with tab_map:
    mapc1, mapc2, mapc3, mapc4 = st.columns(4)
    with mapc1: map_year   = st.selectbox("Marketing Year", all_years, key="map_year")
    with mapc2: map_rr     = st.selectbox("Railroad", ["All"] + all_rrs, key="map_rr")
    with mapc3: map_metric = st.radio("Metric", ["Est. Bushels", "Carloads"],
                                      horizontal=True, key="map_metric")
    with mapc4: map_wk_mode = st.radio("Period", ["Full Year", "MYtD"],
                                       horizontal=True, key="map_wk_mode")

    map_df = df[df["marketing_year"] == map_year].copy()
    if map_rr != "All":
        map_df = map_df[map_df["railroad"] == map_rr]

    if map_wk_mode == "MYtD":
        cur_wk = int(df[df["marketing_year"] == current_my]["my_week"].max()) \
                 if map_year == current_my else \
                 int(df[df["marketing_year"] == map_year]["my_week"].max())
        map_df = map_df[map_df["my_week"] <= cur_wk]

    metric_col = "est_bushels" if map_metric == "Est. Bushels" else "carloads"
    state_totals = map_df.groupby("state")[metric_col].sum().reset_index()

    fig_map = px.choropleth(
        state_totals, locations="state", locationmode="USA-states",
        color=metric_col, scope="usa",
        color_continuous_scale=[[0, "#dbeafe"], [0.3, "#60a5fa"],
                                 [0.7, "#0693e3"], [1, "#1d4ed8"]],
        labels={metric_col: map_metric},
        title=f"{map_metric} by State — {map_year}  ({map_wk_mode})",
    )
    fig_map.update_layout(
        geo_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#32373c", family="Inter, sans-serif", size=11),
        margin=dict(t=40, b=0, l=0, r=0),
        images=[_LOGO_IMG],
    )
    st.plotly_chart(fig_map, width='stretch')

    # State breakdown table
    state_totals_sorted = state_totals.sort_values(metric_col, ascending=False)
    state_totals_sorted = state_totals_sorted.rename(columns={
        "state": "State",
        metric_col: map_metric,
    })
    if map_metric == "Est. Bushels":
        state_totals_sorted[map_metric] = state_totals_sorted[map_metric].apply(fmt_bu)
    else:
        state_totals_sorted[map_metric] = state_totals_sorted[map_metric].apply(fmt_cars)

    with st.expander("📋 State detail table"):
        st.dataframe(state_totals_sorted, width='stretch', hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — WEEKLY BY YEAR
# ══════════════════════════════════════════════════════════════════════════════
with tab_weekly:
    wc1, wc2, wc3 = st.columns(3)
    with wc1: w_rr    = st.selectbox("Railroad", ["All"] + all_rrs, key="w_rr")
    with wc2: w_state = st.selectbox("State", ["All"] + all_states, key="w_state")
    with wc3: w_years = st.multiselect(
        "Marketing Years", all_years,
        default=all_years[:min(6, len(all_years))],
        key="w_years",
    )

    w_df = df.copy()
    if w_rr    != "All": w_df = w_df[w_df["railroad"] == w_rr]
    if w_state != "All": w_df = w_df[w_df["state"]    == w_state]

    sel_years_w = w_years if w_years else all_years[:6]
    weekly = (
        w_df[w_df["marketing_year"].isin(sel_years_w)]
        .groupby(["marketing_year", "my_week"])["est_bushels"]
        .sum().reset_index()
    )

    fig_wk = px.line(
        weekly, x="my_week", y="est_bushels", color="marketing_year",
        labels={"est_bushels": "Est. Bushels", "my_week": "MY Week",
                "marketing_year": "Marketing Year"},
        title="Weekly Grain Rail Shipments by Marketing Year",
    )
    fig_wk.update_layout(**_lax(height=420))
    st.plotly_chart(fig_wk, width='stretch')

    # Cumulative
    weekly_cum = weekly.copy().sort_values(["marketing_year", "my_week"])
    weekly_cum["cumulative"] = weekly_cum.groupby("marketing_year")["est_bushels"].cumsum()

    fig_cum = px.line(
        weekly_cum, x="my_week", y="cumulative", color="marketing_year",
        labels={"cumulative": "Cumulative Est. Bushels", "my_week": "MY Week",
                "marketing_year": "Marketing Year"},
        title="Cumulative Shipments by Marketing Year",
    )
    fig_cum.update_layout(**_lax(height=420))
    st.plotly_chart(fig_cum, width='stretch')


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — YEARLY BY RAILROAD
# ══════════════════════════════════════════════════════════════════════════════
with tab_yearly:
    yc1, yc2, yc3 = st.columns(3)
    with yc1: y_state = st.selectbox("State", ["All"] + all_states, key="y_state")
    with yc2: y_dest  = st.selectbox(
        "Destination", ["All"] + sorted(df["destination"].unique()), key="y_dest"
    )
    with yc3: y_view  = st.radio("View", ["Stacked", "Grouped"],
                                 horizontal=True, key="y_view")

    y_df = df.copy()
    if y_state != "All": y_df = y_df[y_df["state"]       == y_state]
    if y_dest  != "All": y_df = y_df[y_df["destination"]  == y_dest]

    yearly = (
        y_df.groupby(["marketing_year", "railroad"])["est_bushels"]
        .sum().reset_index()
        .sort_values("marketing_year")
    )

    fig_y = px.bar(
        yearly, x="marketing_year", y="est_bushels", color="railroad",
        color_discrete_map=RR_COLORS,
        barmode="stack" if y_view == "Stacked" else "group",
        labels={"est_bushels": "Est. Bushels", "marketing_year": "Marketing Year",
                "railroad": "Railroad"},
        title="Annual Grain Rail Shipments by Railroad",
    )
    fig_y.update_layout(**_lax(height=450))
    st.plotly_chart(fig_y, width='stretch')

    # Pivot table
    pivot_y = (
        yearly.pivot_table(index="railroad", columns="marketing_year",
                           values="est_bushels", fill_value=0)
        .reset_index()
        .rename(columns={"railroad": "Railroad"})
    )
    pivot_y.columns.name = None

    fmt_y = pivot_y.copy()
    for col in fmt_y.columns:
        if col != "Railroad":
            fmt_y[col] = fmt_y[col].apply(fmt_bu)

    st.dataframe(fmt_y, width='stretch', hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
with tab_summary:
    cur_df  = df[df["marketing_year"] == current_my]
    max_wk_s = int(cur_df["my_week"].max()) if len(cur_df) else 0
    cur_wk_df = cur_df[cur_df["my_week"] <= max_wk_s]

    total_bu_s   = int(cur_wk_df["est_bushels"].sum())
    total_cars_s = int(cur_wk_df["carloads"].sum())

    ly_s   = comp_yrs[-1] if comp_yrs else None
    ly_bu_s = int(
        df[(df["marketing_year"] == ly_s) & (df["my_week"] <= max_wk_s)]["est_bushels"].sum()
    ) if ly_s else 0

    delta_str = (
        f"{fmt_bu(total_bu_s - ly_bu_s)} vs {ly_s}" if ly_bu_s else None
    )

    sm1, sm2, sm3, sm4 = st.columns(4)
    sm1.metric("Current Marketing Year", current_my)
    sm2.metric("MYtD Est. Bushels", fmt_bu(total_bu_s), delta=delta_str)
    sm3.metric("MYtD Carloads",     fmt_cars(total_cars_s))
    sm4.metric("Weeks Reported",    str(max_wk_s))

    st.divider()

    col_dest, col_rr = st.columns(2)

    with col_dest:
        dest_tot = (
            cur_wk_df.groupby("destination")["est_bushels"]
            .sum().reset_index()
            .sort_values("est_bushels", ascending=False)
        )
        fig_dest = px.pie(
            dest_tot, names="destination", values="est_bushels",
            color="destination", color_discrete_map=DEST_COLORS,
            title=f"MYtD by Destination — {current_my}",
        )
        fig_dest.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#32373c", family="Inter, sans-serif", size=11),
            legend=dict(bgcolor="rgba(0,0,0,0)"),
            images=[_LOGO_IMG],
        )
        st.plotly_chart(fig_dest, width='stretch')

    with col_rr:
        rr_tot = (
            cur_wk_df.groupby("railroad")["est_bushels"]
            .sum().reset_index()
            .sort_values("est_bushels", ascending=False)
        )
        fig_rr_s = px.bar(
            rr_tot, x="railroad", y="est_bushels",
            color="railroad", color_discrete_map=RR_COLORS,
            labels={"est_bushels": "Est. Bushels", "railroad": "Railroad"},
            title=f"MYtD by Railroad — {current_my}",
        )
        fig_rr_s.update_layout(**_lax(showlegend=False, height=380))
        st.plotly_chart(fig_rr_s, width='stretch')

    st.divider()

    # Year-over-year total
    yoy = (
        df[df["marketing_year"].isin(comp_yrs + [current_my])]
        .groupby("marketing_year")["est_bushels"]
        .sum().reset_index()
        .sort_values("marketing_year")
    )
    fig_yoy = px.bar(
        yoy, x="marketing_year", y="est_bushels",
        labels={"est_bushels": "Est. Bushels", "marketing_year": "Marketing Year"},
        title="Full-Year Grain Rail Shipments — All Railroads",
    )
    fig_yoy.update_traces(marker_color="#0693e3")
    fig_yoy.update_layout(**_lax(height=380))
    st.plotly_chart(fig_yoy, width='stretch')

st.markdown(
    f'<div style="font-family:inherit;margin-top:40px;padding:14px 20px;border-top:1px solid #e2e8f0;'
    f'color:#6b7280;font-size:inherit;line-height:1.6;">'
    f'Trading commodity futures, options on futures, cash commodities, and over-the-counter '
    f'derivative products involves substantial risk of loss and may not be suitable for all investors. '
    f'This communication is provided for informational purposes only and does not constitute investment '
    f'advice, a recommendation, or an offer or solicitation to buy or sell any futures, options, cash '
    f'commodities, or derivative products. John Stewart &amp; Associates, Inc. does not accept orders '
    f'to buy or sell any financial instruments via email. The information contained herein has been '
    f'obtained from sources believed to be reliable; however, its accuracy and completeness are not '
    f'guaranteed. Any opinions expressed are solely those of the author, are subject to change without '
    f'notice, and should not be relied upon as a basis for investment decisions. Past performance is '
    f'not indicative of future results. This message may contain confidential or proprietary '
    f'information intended solely for the use of the designated recipient. '
    f'&copy; John Stewart &amp; Associates, Inc. {pd.Timestamp.now().year}'
    f'</div>',
    unsafe_allow_html=True,
)
