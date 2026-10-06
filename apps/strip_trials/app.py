"""Yield Observations — the Iowa Soybean Association's on-farm strip trials, each field's
yield beside its county's NASS yield.

The yield portal's Strip trials page (JSA-Dashboards/yield-portal,
app_pages/strip_trials.py), bundled here; keep the two in step. The table is
loaded by that repo, so nothing here writes.
"""
import datetime
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

# st.navigation runs this file from Home.py's directory, so its own folder isn't on
# sys.path unless added (the same shim as the other bundled apps)
sys.path.insert(0, str(Path(__file__).parent))
import isa_strip_data as data  # noqa: E402

FIELD_INK = "#0693e3"
COUNTY_INK = "#1baf7a"
STATE_INK = "#9aa0a6"
SERIES = ["Strip-trial fields", "Their counties (NASS)", "Iowa (NASS)"]
SCALE = alt.Scale(domain=SERIES, range=[FIELD_INK, COUNTY_INK, STATE_INK])

st.title("Yield Observations")
st.caption("The Iowa Soybean Association's replicated on-farm strip trials, 2005 onward: "
           "farmers comparing two or more practices across a whole field, so each trial "
           "is one real field's yield, read against its county's NASS yield.")

try:
    trials = data.load_trials()
except Exception as exc:
    if "not authorized" in str(exc).lower() or "does not exist" in str(exc).lower():
        st.error("This portal's Snowflake role can't read the strip-trial table. "
                 "`ADMIN_PORTAL_ROLE` needs SELECT on `YIELD_REPORTS.PUBLIC` "
                 "(see CLAUDE.md).", icon=":material/lock:")
    else:
        st.error(f"Couldn't read the strip-trial table: {exc}", icon=":material/cloud_off:")
    st.stop()
if trials.empty:
    st.info("The strip-trial table is empty. The yield portal's loader fills it "
            "(`python load_isa.py load --target snowflake`).", icon=":material/database:")
    st.stop()

try:
    county, state = data.load_nass(datetime.date.today().year)
except Exception:                             # the trials still stand on their own
    county = pd.DataFrame(columns=["crop", "year", "county", "yield"])
    state = pd.DataFrame(columns=["crop", "year", "final"])
trials = data.with_nass(trials, county, state)
HAVE_NASS = not county.empty


@st.fragment
def strip_trials():
    with st.container(horizontal=True):
        crop = st.segmented_control("Crop", ["Corn", "Soybeans"], default="Corn",
                                    key="isa_crop") or "Corn"
    span = (int(trials.year.min()), int(trials.year.max()))
    lo, hi = st.slider("Seasons", span[0], span[1], span, key="isa_years")
    q = st.text_input("Search trials", placeholder="County, district, trial type or product",
                      key="isa_q", label_visibility="collapsed")
    f = trials[(trials.crop == crop) & (trials.year >= lo) & (trials.year <= hi)]
    if q:
        # a blank district comes back NULL, and one None would make the mask NaN
        hay = f[["county", "district", "trial_type", "trial_detail"]].fillna("").agg(" ".join, axis=1)
        f = f[hay.str.contains(q, case=False, regex=False)]
    read = f[f.status.isin(data.READ)]
    if read.empty:
        st.info("No trials with read yields match these filters.")
        return
    one = data.fields(read)                   # each field once

    with st.container(horizontal=True):
        st.metric("Fields read", f"{len(one):,}", border=True,
                  help=f"{len(read):,} of the {len(f):,} trials in the filter were read. ISA "
                       f"lists some fields under more than one comparison, all from one "
                       f"report, so each field counts once. The trials not read are in the "
                       f"table below, uncharted.")
        st.metric("Counties", f"{one.county.nunique()}", border=True,
                  help="Iowa counties with a read field in the filter.")
        paired = one.vs_county.dropna()
        st.metric("Field over its county", f"{paired.median():+.1%}" if len(paired) else "—",
                  border=True,
                  help="Each field's yield over its county's NASS yield that season, the "
                       "median across fields (%d paired). A county NASS didn't publish that "
                       "season has no figure." % len(paired))
        st.metric("Field over Iowa", f"{one.vs_state.median():+.1%}"
                  if one.vs_state.notna().any() else "—", border=True,
                  help="Each field's yield over Iowa's NASS yield that season, the median "
                       "across fields.")

    season = data.by_season(read)
    with st.container(border=True):
        head, toggle = st.columns([3, 1], vertical_alignment="center")
        head.markdown(f"**{crop}: strip-trial fields against NASS, by season**")
        view = toggle.segmented_control("View", ["Chart", "Table"], default="Chart",
                                        key="isa_view", label_visibility="collapsed") or "Chart"
        if view == "Chart":
            long = pd.concat([
                season[["year", "field", "fields"]].rename(columns={"field": "value"})
                .assign(series=SERIES[0]),
                season[["year", "county", "fields"]].rename(columns={"county": "value"})
                .assign(series=SERIES[1]),
                season[["year", "state", "fields"]].rename(columns={"state": "value"})
                .assign(series=SERIES[2]),
            ]).dropna(subset=["value"])
            long["year"] = long.year.astype(int)
            hover = alt.selection_point(on="pointerover", nearest=True, fields=["year"],
                                        empty=False)
            base = alt.Chart(long).encode(
                x=alt.X("year:Q", title=None, axis=alt.Axis(format="d"),
                        scale=alt.Scale(nice=False)),
                y=alt.Y("value:Q", title=f"{crop} yield (bu/acre)", scale=alt.Scale(zero=False)),
                # a legend, not end labels: the two NASS lines often finish a bushel apart
                color=alt.Color("series:N", title=None, scale=SCALE,
                                legend=alt.Legend(orient="top", symbolType="stroke")),
            )
            solid = base.transform_filter(alt.datum.series != SERIES[2]).mark_line(
                strokeWidth=2, point=alt.OverlayMarkDef(size=30))
            dashed = base.transform_filter(alt.datum.series == SERIES[2]).mark_line(
                strokeWidth=1.5, strokeDash=[4, 3])
            marks = base.mark_circle(size=90, opacity=0).add_params(hover)
            tips = base.mark_circle(size=110, stroke="#ffffff", strokeWidth=2).encode(
                opacity=alt.condition(hover, alt.value(1), alt.value(0)),
                tooltip=[alt.Tooltip("series:N", title=None),
                         alt.Tooltip("year:Q", title="Season", format="d"),
                         alt.Tooltip("value:Q", title="Yield", format=".1f"),
                         alt.Tooltip("fields:Q", title="Fields read")])
            st.altair_chart(alt.layer(solid, dashed, marks, tips).properties(height=360))
            st.caption("Mean yield of the season's read fields, and the mean NASS yield of "
                       "the counties they sat in (where NASS published the county). The "
                       "trials move from county to county every year, so read the gap "
                       "between the two lines, not the level of either.")
        else:
            shown = season.drop(columns="crop").sort_values("year", ascending=False)
            shown[["over_county", "over_state"]] *= 100
            st.dataframe(
                shown,
                hide_index=True,
                column_config={
                    "year": st.column_config.NumberColumn("Season", format="%d"),
                    "fields": st.column_config.NumberColumn("Fields read", format="%d"),
                    "field": st.column_config.NumberColumn("Mean field", format="%.1f",
                                                           help="Mean of the fields' yields."),
                    "county": st.column_config.NumberColumn(
                        "Their counties", format="%.1f",
                        help="Mean NASS yield of the fields' counties."),
                    "state": st.column_config.NumberColumn("Iowa", format="%.1f"),
                    "over_county": st.column_config.NumberColumn(
                        "Over county", format="%+.1f%%",
                        help="Median of each field's yield over its county's."),
                    "over_state": st.column_config.NumberColumn(
                        "Over Iowa", format="%+.1f%%",
                        help="Median of each field's yield over Iowa's."),
                })
        if not HAVE_NASS:
            st.caption("NASS yields couldn't be read from the fleet's cache, so only the "
                       "trials show.")

    cols = ["year", "county", "district", "trial_type", "trial_detail", "yields",
            "trial_yield", "county_final", "vs_county", "avg_response", "status", "listed_crop",
            "report_url"]
    table = f[cols].sort_values(["year", "county"], ascending=[False, True])
    table["vs_county"] *= 100
    with st.container(border=True):
        st.markdown(f"**Trials** · {len(table):,}")
        st.dataframe(
            table, hide_index=True, height=420,
            column_config={
                "year": st.column_config.NumberColumn("Season", format="%d"),
                "county": "County",
                "district": "District",
                "trial_type": "Trial type",
                "trial_detail": st.column_config.TextColumn("Compared", width="medium"),
                "yields": st.column_config.TextColumn(
                    "Treatment yields", help="Each treatment's average, as the report "
                                             "gives them."),
                "trial_yield": st.column_config.NumberColumn(
                    "Field yield", format="%.1f", help="Mean of the treatment yields."),
                "county_final": st.column_config.NumberColumn("NASS county", format="%.1f"),
                "vs_county": st.column_config.NumberColumn("Over county", format="%+.1f%%"),
                "avg_response": st.column_config.NumberColumn(
                    "ISA response", format="%+.1f",
                    help="The yield response ISA lists for the trial, which each reading "
                         "is checked against."),
                "status": st.column_config.TextColumn(
                    "Read", help="read: some pair of yields agrees with ISA's response. "
                                 "unverified: three or more treatments, exactly as many as "
                                 "ISA lists, though none agrees (ISA's response isn't one "
                                 "defined pair there). unread: no reading fits. same field: "
                                 "listed again under another comparison, with no report of "
                                 "its own. no report: not on ISA's server."),
                "listed_crop": st.column_config.TextColumn(
                    "Listed as", help="ISA's list files this trial under the other crop; the "
                                      "report's rotation line and its yields both say this "
                                      "one."),
                "report_url": st.column_config.LinkColumn("Report", display_text="PDF"),
            })
        st.download_button("Download CSV", table.to_csv(index=False),
                           file_name=f"isa_strip_trials_{crop.lower()}.csv", mime="text/csv",
                           icon=":material/download:")

    with st.expander("How these are read", icon=":material/info:"):
        st.markdown(
            """
**Source.** ISA's public strip-trial database lists every trial since 2005 with its
county and the yield response ISA measured. Each trial's yields are only in its PDF
report. The yield portal's loader keeps the text of those reports and reads each one's
summary of treatment averages. The report layout has changed several times since 2005.

**Checked against ISA.** A reading counts when the gap between two of its treatments
matches the response ISA lists for the trial. For three or more treatments, ISA's
response is sometimes the top less the bottom, sometimes another pair, and once the
LSD. So a summary with exactly as many treatments as ISA lists is also taken, marked
*unverified*. A report no reading fits stays *unread* rather than being guessed at.
One example: a "soybean" trial whose report shows corn-level yields.

**Field yield, one per field.** A field's yield is the mean of its treatment averages.
Treatments mostly move yield a few bushels, and what's compared with NASS is the
field's level. Nitrogen-rate trials are the exception: their lowest rates pull the mean
down. ISA lists some fields under two or more comparisons ("…268A" and "…268A1",
"…0035" and "…0035a"), all from one report, so the chart and figures count each field
once.

**Crop.** ISA's list files a few trials under the wrong crop, such as 2017-18 cover-crop
trials listed as corn that yielded about 60 bu. Where a report's rotation line names the
other crop, the yields decide: under 100 bu is soybeans. The "Listed as" column shows
ISA's original.

**Not a random sample.** Cooperators volunteer, often on their better-managed ground.
The trials also move between counties from year to year, and their number has fallen
from about 400 a season to under 100. Read the gap to NASS and how it shifts across
seasons; the level of the trial line says little on its own.

**Internal.** ISA states its copyright and no other terms, so the trials stay behind
passwords: this portal and the yield portal's internal pages, never a public link.
            """)


strip_trials()
