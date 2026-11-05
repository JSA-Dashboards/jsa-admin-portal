"""Ask AI (Admin): questions about any JSA Snowflake data, oversight findings, and what changed in the latest WASDE.

A hand-written portal page (not a synced mirror). This repo is public: no keys, account or user names here.
Everything comes from secrets. SQL runs through a role that can only read (AG_DQ_READER), and the code also
refuses anything but a single SELECT / WITH / SHOW / DESCRIBE.
"""
import json
import os
import re

import pandas as pd
import streamlit as st

MODEL = "claude-sonnet-5-5"
READ_ROLE = "AG_DQ_READER"
MAX_ROWS = 200
MAX_TOOL_ROUNDS = 8

if os.environ.get("JSA_PORTAL_VIEW") == "client":
    st.error("This page is for JSA staff.")
    st.stop()


def _secret(name: str, default: str = "") -> str:
    try:
        v = st.secrets.get(name, "")
    except Exception:
        v = ""
    return str(v or os.environ.get(name, default) or default)


def _private_key_der():
    from cryptography.hazmat.primitives import serialization
    pem, path = _secret("SNOWFLAKE_PRIVATE_KEY"), _secret("SNOWFLAKE_PRIVATE_KEY_PATH")
    if not pem.strip() and not path:
        return None
    data = open(path, "rb").read() if path else pem.replace("\\n", "\n").encode()
    pwd = _secret("SNOWFLAKE_PRIVATE_KEY_PWD") or None
    key = serialization.load_pem_private_key(data, password=pwd.encode() if pwd else None)
    return key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


@st.cache_resource(ttl=3600, show_spinner=False)
def _conn():
    import snowflake.connector as sc
    return sc.connect(
        account=_secret("SNOWFLAKE_ACCOUNT"), user=_secret("SNOWFLAKE_USER"), private_key=_private_key_der(),
        role=READ_ROLE, warehouse=_secret("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        session_parameters={"STATEMENT_TIMEOUT_IN_SECONDS": 60, "QUERY_TAG": "portal_ask_ai"},
        login_timeout=30, network_timeout=60)


_READ_ONLY = re.compile(r"^\s*(select|with|show|describe|desc)\b", re.I)


def run_sql(sql: str) -> pd.DataFrame:
    """One read-only statement. The role is the real guard; this is a second one."""
    body = sql.strip().rstrip(";")
    if ";" in body or not _READ_ONLY.match(body):
        raise ValueError("Only a single SELECT, WITH, SHOW or DESCRIBE statement is allowed.")
    cur = _conn().cursor()
    try:
        cur.execute(body)
        cols = [d[0] for d in cur.description]
        return pd.DataFrame(cur.fetchmany(MAX_ROWS), columns=cols)
    finally:
        cur.close()


@st.cache_data(ttl=300, show_spinner=False)
def _q(sql: str) -> pd.DataFrame:
    return run_sql(sql)


SYSTEM = f"""You are the data analyst for John Stewart & Associates (JSA), an agricultural commodity brokerage.
You answer questions about JSA's Snowflake data (grain basis and bids, river and rail FOB, WASDE and USDA PSD,
NASS, CFTC COT, exports, cattle and beef, crush margins and more) using the run_sql tool, which is read-only.

How to work:
- Explore before you query: SHOW SCHEMAS IN DATABASE JSA, SHOW TABLES IN SCHEMA JSA.WASDE, DESCRIBE TABLE ... .
  Other databases: EXPORTS, FIN_WIRE, GRAIN_MARKETING, RIVER_FOB, YIELD_REPORTS. Use fully qualified names.
- Keep queries small (aggregate, filter by date, LIMIT). At most {MAX_ROWS} rows come back.
- JSA.WASDE.REVISIONS holds each release's value, prior release value and the revision (RELEASE_YM like 202610).
  JSA.OVERSIGHT.FINDINGS lists data-quality issues the overseer bots logged (open ones are status = 'open').
- State the numbers you used and which tables they came from. If data looks stale, empty or odd, say so plainly,
  and never guess a number you did not query. Units: WASDE US values are usually million bushels or 1,000 units,
  check the attribute and table before quoting.
- Be concise: lead with the answer, then the supporting figures."""

TOOLS = [{
    "name": "run_sql",
    "description": "Run one read-only Snowflake SQL statement (SELECT / WITH / SHOW / DESCRIBE). Returns up to "
                   f"{MAX_ROWS} rows as JSON.",
    "input_schema": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]},
}]


def ask(question: str, history: list[dict]):
    """Tool-use loop. Returns (answer text, [sql statements run])."""
    import anthropic
    client = anthropic.Anthropic(api_key=_secret("ANTHROPIC_API_KEY"))
    msgs = [{"role": m["role"], "content": m["content"]} for m in history] + [{"role": "user", "content": question}]
    used = []
    for _ in range(MAX_TOOL_ROUNDS):
        resp = client.messages.create(model=MODEL, max_tokens=2000, system=SYSTEM, tools=TOOLS, messages=msgs)
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text"), used
        msgs.append({"role": "assistant", "content": resp.content})
        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            sql = b.input.get("sql", "")
            used.append(sql)
            try:
                out = run_sql(sql).to_json(orient="records", date_format="iso", default_handler=str)
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": out[:30000]})
            except Exception as e:
                results.append({"type": "tool_result", "tool_use_id": b.id, "is_error": True, "content": str(e)[:500]})
        msgs.append({"role": "user", "content": results})
    return "I ran out of steps before finishing. Try a narrower question.", used


st.title("Ask AI")
st.caption("Ask anything about JSA's data. Answers come from live Snowflake queries through a read-only role.")

if not _secret("ANTHROPIC_API_KEY"):
    st.warning("Add `ANTHROPIC_API_KEY` to this app's secrets to turn on the chat. Findings and WASDE changes below still work.")

tab_ask, tab_findings, tab_wasde = st.tabs(
    ["Ask", "Oversight findings", "WASDE changes"], on_change="rerun", default="Ask")

if tab_ask.open:
    st.session_state.setdefault("ask_ai_msgs", [])
    for m in st.session_state.ask_ai_msgs:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m.get("sql"):
                with st.expander("SQL used"):
                    st.code("\n\n".join(m["sql"]), language="sql")
    q = st.chat_input("Ask about basis, WASDE, exports, cattle, data freshness...",
                      disabled=not _secret("ANTHROPIC_API_KEY"))
    if st.session_state.ask_ai_msgs:
        if st.button("Clear chat", icon=":material/delete:"):
            st.session_state.ask_ai_msgs = []
            st.rerun()
    if q:
        hist = [{"role": m["role"], "content": m["content"]} for m in st.session_state.ask_ai_msgs]
        st.session_state.ask_ai_msgs.append({"role": "user", "content": q})
        with st.chat_message("user"):
            st.markdown(q)
        with st.chat_message("assistant"):
            with st.spinner("Querying Snowflake..."):
                try:
                    answer, sqls = ask(q, hist)
                except Exception as e:
                    answer, sqls = f"Something went wrong: {e}", []
            st.markdown(answer)
            if sqls:
                with st.expander("SQL used"):
                    st.code("\n\n".join(sqls), language="sql")
        st.session_state.ask_ai_msgs.append({"role": "assistant", "content": answer, "sql": sqls})

if tab_findings.open:
    try:
        f = _q("""select created_at::timestamp_ntz as logged, severity, category, object_name, summary,
                         recommended_action, reported_by, status
                  from JSA.OVERSIGHT.FINDINGS
                  order by iff(status = 'open', 0, 1), decode(severity, 'critical', 0, 'warning', 1, 2), created_at desc
                  limit 200""")
        if f.empty:
            st.info("No findings logged yet.")
        else:
            c1, c2, c3 = st.columns(3)
            is_open = f["STATUS"] == "open"
            c1.metric("Open", int(is_open.sum()))
            c2.metric("Open critical", int((is_open & (f["SEVERITY"] == "critical")).sum()))
            c3.metric("Logged (latest 200)", len(f))
            show_open = st.toggle("Open only", value=True)
            st.dataframe(f[is_open] if show_open else f, hide_index=True, width="stretch")
    except Exception as e:
        st.error(f"Could not read findings: {e}")

if tab_wasde.open:
    try:
        rel = _q("select max(release_ym) as r from JSA.WASDE.REVISIONS")
        ym = int(rel["R"].iloc[0])
        st.caption(f"Latest release in the data: {ym // 100}-{ym % 100:02d}. Revision = this release minus the prior one.")
        crops = _q("select distinct commodity from JSA.WASDE.REVISIONS order by 1")["COMMODITY"].tolist()
        c1, c2 = st.columns(2)
        pick = c1.multiselect("Commodity", crops, default=[c for c in ("Corn", "Soybeans", "Wheat") if c in crops])
        scope = c2.segmented_control("Scope", ["US", "World"], default="US")
        where = "country_code = 'US'" if scope == "US" else "country_code <> 'US'"
        com = ("and commodity in (" + ",".join("'" + c.replace("'", "''") + "'" for c in pick) + ")") if pick else ""
        w = _q(f"""select commodity, country_name as country, market_year as my, attribute_name as item,
                          prev_value as prior, value as this_release, revision,
                          round(100 * revision / nullif(abs(prev_value), 0), 1) as pct
                   from JSA.WASDE.REVISIONS
                   where release_ym = {ym} and revision <> 0 and {where} {com}
                   order by abs(revision) / nullif(abs(prev_value), 0) desc nulls last limit 100""")
        if w.empty:
            st.info("No revisions for that selection.")
        else:
            st.dataframe(w, hide_index=True, width="stretch")
            if _secret("ANTHROPIC_API_KEY") and st.button("Explain these changes", icon=":material/auto_awesome:"):
                with st.spinner("Reading the revisions..."):
                    try:
                        txt, _ = ask("Here are the biggest revisions in the latest WASDE release (" + str(ym) +
                                     "), as JSON. Explain in plain language what changed and why a grain or livestock "
                                     "marketer would care. Group by commodity, flag the largest moves first.\n" +
                                     w.head(40).to_json(orient="records"), [])
                        st.markdown(txt)
                    except Exception as e:
                        st.error(f"Could not explain: {e}")
    except Exception as e:
        st.error(f"Could not read WASDE revisions: {e}")
