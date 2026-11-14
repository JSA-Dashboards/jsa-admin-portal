"""Microsoft sign-in (shared/signin.py), the access list (shared/access_store.py) and the way shared/auth.py uses them.

The pure rules are tested directly; the gate is driven headless with streamlit's AppTest, with the identity provider and
Snowflake replaced by stand-ins (st.user cannot be signed in without a real provider, so `signin.current_user` is faked)."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from shared import access_store, signin  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402


@pytest.fixture(autouse=True)
def _pristine_modules():
    """The gate harness replaces functions on the REAL shared modules; put them back after every test."""
    yield
    import importlib
    importlib.reload(access_store)
    importlib.reload(signin)


# ── pure rules ────────────────────────────────────────────────────────────────

def test_normalize_email():
    assert access_store.normalize_email("  Jane.Doe@Example.COM ") == "jane.doe@example.com"
    for bad in ("", "nope", "a@b", "a b@c.com", "a@b.com, c@d.com", None, 5, "<x@y.com>"):
        assert access_store.normalize_email(bad) == "", bad


def test_parse_emails_splits_dedupes_and_reports_rejects():
    good, bad = access_store.parse_emails("A@x.com, b@y.org;  a@x.com\nJane <J@Z.com> junk")
    assert good == ["a@x.com", "b@y.org", "j@z.com"]
    assert bad == ["Jane", "junk"]
    assert access_store.parse_emails(None) == ([], [])


def test_claim_email_prefers_email_then_username_then_emails_list():
    assert signin.claim_email({"email": "A@B.com", "preferred_username": "x@y.com"}) == "a@b.com"
    assert signin.claim_email({"preferred_username": "U@Y.com"}) == "u@y.com"
    assert signin.claim_email({"emails": ["not-an-email", "e@z.com"]}) == "e@z.com"
    assert signin.claim_email({"email": "garbage", "preferred_username": "p@q.com"}) == "p@q.com"
    assert signin.claim_email({"name": "No Email"}) == ""
    assert signin.claim_email(None) == ""


def test_settings_complete_needs_every_key_and_no_placeholders():
    full = {k: "v" for k in signin.REQUIRED_AUTH_KEYS}
    assert signin.settings_complete(full)
    assert not signin.settings_complete(None)
    assert not signin.settings_complete({})
    for k in signin.REQUIRED_AUTH_KEYS:
        assert not signin.settings_complete({**full, k: ""}), k
        assert not signin.settings_complete({**full, k: "   "}), k
        assert not signin.settings_complete({**full, k: "<paste here>"}), k
        assert not signin.settings_complete({kk: v for kk, v in full.items() if kk != k}), k


def test_bootstrap_emails_accepts_a_list_or_text():
    assert signin.bootstrap_emails(["A@x.com", "b@y.com"]) == ["a@x.com", "b@y.com"]
    assert signin.bootstrap_emails("a@x.com, b@y.com\nc@z.com") == ["a@x.com", "b@y.com", "c@z.com"]
    assert signin.bootstrap_emails(None) == []
    assert signin.bootstrap_emails(5) == []


ROWS = [
    {"EMAIL": "client@acme.com", "ROLE": "client", "ACTIVE": True},
    {"EMAIL": "off@acme.com", "ROLE": "client", "ACTIVE": False},
    {"EMAIL": "boss@jpsi.com", "ROLE": "staff", "ACTIVE": True},
]


def test_decide_rules():
    d = signin.decide
    assert d("client@acme.com", ROWS) == signin.Decision(True, role="client")
    assert d("CLIENT@ACME.COM", ROWS).ok                              # case does not matter
    assert d("stranger@acme.com", ROWS).reason == "not_listed"
    assert d("off@acme.com", ROWS).reason == "inactive"
    assert d("", ROWS).reason == "no_email"
    assert d("boss@jpsi.com", ROWS).ok                                # staff may open the client portal
    assert d("client@acme.com", ROWS, need="staff").reason == "wrong_role"
    assert d("boss@jpsi.com", ROWS, need="staff").ok
    assert not d("client@acme.com", []).ok
    assert not d("client@acme.com", None).ok


def test_decide_reads_snowflake_style_keys_and_values():
    rows = [{"email": "a@b.com", "role": " Client ", "active": "true"}]
    assert signin.decide("a@b.com", rows).ok
    assert signin.decide("a@b.com", [{"EMAIL": "a@b.com", "ROLE": "client", "ACTIVE": 0}]).reason == "inactive"
    assert signin.decide("a@b.com", [{"EMAIL": "a@b.com", "ROLE": "admin", "ACTIVE": True}]).reason == "wrong_role"


def test_a_row_for_someone_else_never_admits_a_prefix_or_suffix_match():
    rows = [{"EMAIL": "ann@acme.com", "ROLE": "client", "ACTIVE": True}]
    for other in ("nn@acme.com", "joann@acme.com", "ann@acme.com.evil.io", "ann@acme.co"):
        assert not signin.decide(other, rows).ok, other


# ── the gate, headless ────────────────────────────────────────────────────────

HARNESS = r'''
import sys
sys.path.insert(0, {root!r})
import streamlit as st
st.cache_data.clear()
import importlib
from shared import signin, access_store, auth
importlib.reload(access_store)       # undo every stand-in a previous run put on the real modules
importlib.reload(signin)
if {enabled!r}:
    signin.is_enabled = lambda: True
signin.current_user = lambda: signin.Who({logged!r}, {email!r}, "Test Person")
_S = {secrets!r}
signin._secret = lambda n, d=None: _S.get(n, d)
_ROWS = {rows!r}
def _read(email):
    if _ROWS is None:
        raise RuntimeError("snowflake down")
    return [r for r in _ROWS if r["EMAIL"] == email]
access_store.read_for_email = _read
for k, v in {state!r}.items():
    st.session_state[k] = v
auth.require_client_login()
signin.render_account_bar()
st.write("INSIDE THE PORTAL")
'''


def run(*, logged=False, email="", rows=ROWS, secrets=None, enabled=True, state=None, password=None):
    code = HARNESS.format(root=str(ROOT), enabled=enabled, logged=logged, email=email, secrets=secrets or {},
                          rows=rows, state=state or {})
    at = AppTest.from_string(code, default_timeout=30)
    if password is not None:
        at.secrets["CLIENT_PASSWORD"] = password
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    return at


def inside(at):
    return any("INSIDE THE PORTAL" in str(m.value) for m in at.markdown)


def text(at):
    return " ".join(str(x.value) for x in list(at.markdown) + list(at.error) + list(at.caption) + list(at.info))


def button_labels(at):
    return [b.label for b in at.button]


def test_signed_out_sees_only_the_sign_in_button():
    at = run()
    assert not inside(at)
    assert "Sign in" in button_labels(at)
    assert not at.text_input                                   # no password box unless the fallback is on


def test_listed_person_gets_in_and_sees_who_they_are():
    at = run(logged=True, email="client@acme.com")
    assert inside(at)
    assert at.session_state["_jsa_signin_email"] == "client@acme.com"
    assert "client@acme.com" in text(at)                       # the account bar
    assert "Sign out" in button_labels(at)


def test_unlisted_person_is_stopped_and_told_which_address():
    at = run(logged=True, email="stranger@acme.com")
    assert not inside(at)
    assert "stranger@acme.com is not on the access list" in text(at)
    assert "Sign out" in button_labels(at)


def test_switched_off_person_is_stopped():
    at = run(logged=True, email="off@acme.com")
    assert not inside(at)
    assert "no longer has access" in text(at)


def test_sign_in_without_an_email_is_stopped():
    at = run(logged=True, email="")
    assert not inside(at)
    assert "did not include an email address" in text(at)


def test_an_unreadable_access_list_fails_closed_and_says_so():
    at = run(logged=True, email="client@acme.com", rows=None)
    assert not inside(at)
    assert "could not check the access list" in text(at)
    assert "not on the access list" not in text(at)            # not mislabelled as 'not listed'


def test_the_bootstrap_secret_still_admits_when_the_list_cannot_be_read():
    at = run(logged=True, email="first@acme.com", rows=None, secrets={"SIGNIN_ALLOWED_EMAILS": "first@acme.com"})
    assert inside(at)
    at = run(logged=True, email="first@acme.com", rows=[], secrets={"SIGNIN_ALLOWED_EMAILS": ["First@acme.com"]})
    assert inside(at)
    at = run(logged=True, email="other@acme.com", rows=None, secrets={"SIGNIN_ALLOWED_EMAILS": "first@acme.com"})
    assert not inside(at)


def test_removing_someone_stops_an_open_session():
    # the session was admitted earlier (its flag is set), then the row was removed: the next run must not trust the flag
    at = run(logged=True, email="client@acme.com", rows=[],
             state={"_jsa_signin_email": "client@acme.com", "_jsa_client_authed": True})
    assert not inside(at)
    assert "_jsa_signin_email" not in at.session_state


def test_the_shared_password_opens_nothing_once_sign_in_is_on_unless_the_fallback_is():
    at = run(state={"_jsa_client_authed": True}, password="pw")
    assert not inside(at)                                      # fallback off: a leftover password session is ignored
    at = run(state={"_jsa_client_authed": True}, password="pw", secrets={"SIGNIN_PASSWORD_FALLBACK": "true"})
    assert inside(at)
    assert "_jsa_signin_email" not in at.session_state and "Sign out" not in button_labels(at)


def test_fallback_password_box_accepts_the_right_password_and_refuses_a_wrong_one():
    secrets = {"SIGNIN_PASSWORD_FALLBACK": "true"}
    at = run(secrets=secrets, password="s3cret")
    assert at.text_input and not inside(at)
    at.text_input[0].input("wrong").run()
    assert not inside(at) and "Incorrect password." in text(at)
    at.text_input[0].input("s3cret").run()
    assert inside(at)


def test_without_an_auth_block_the_old_password_gate_is_unchanged():
    at = run(enabled=False, password="pw")
    assert not inside(at)
    assert at.text_input and "Sign in" not in button_labels(at)
    at.text_input[0].input("pw").run()
    assert inside(at)
    closed = run(enabled=False)                                # no password either: still closed
    assert not inside(closed) and "not configured" in text(closed)


def test_a_microsoft_session_is_not_waved_through_by_the_password_flag():
    # logged in with Microsoft but NOT on the list, and a stale password flag: the list wins
    at = run(logged=True, email="stranger@acme.com", state={"_jsa_client_authed": True},
             secrets={"SIGNIN_PASSWORD_FALLBACK": "true"}, password="pw")
    assert not inside(at)


def test_is_enabled_reads_the_real_auth_secrets():
    code = (f"import sys; sys.path.insert(0, {str(ROOT)!r})\n"
            "import streamlit as st\nfrom shared import signin\n"
            "st.write('ENABLED=' + str(signin.is_enabled()))\n")
    full = {k: "v" for k in signin.REQUIRED_AUTH_KEYS}

    def enabled(auth):
        at = AppTest.from_string(code, default_timeout=30)
        if auth is not None:
            at.secrets["auth"] = auth
        at.run()
        assert not at.exception
        return "ENABLED=True" in " ".join(str(m.value) for m in at.markdown)

    assert enabled(full)
    assert not enabled(None)
    assert not enabled({**full, "client_secret": ""})
    assert not enabled({**full, "client_id": "<paste the Application (client) ID>"})


# ── the staff page and the store ──────────────────────────────────────────────

def test_the_access_page_refuses_to_run_in_the_client_view(monkeypatch):
    monkeypatch.setenv("JSA_PORTAL_VIEW", "client")
    called = []
    monkeypatch.setattr(access_store, "read_all", lambda: called.append("read") or [])
    at = AppTest.from_file(str(ROOT / "admin_pages" / "portal_access.py"), default_timeout=30)
    at.run()
    assert not at.exception
    assert any("for JSA staff" in str(e.value) for e in at.error)
    assert not called                                          # it stopped before touching the list


class FakeConn:
    def __init__(self):
        self.calls = []
        self.closed = False

    def cursor(self):
        return self

    def execute(self, sql, params=()):
        self.calls.append((sql, params))

    def close(self):
        self.closed = True


def test_add_users_binds_values_and_never_puts_an_address_in_the_sql(monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr(access_store, "_connect", lambda: conn)
    n = access_store.add_users(["A@x.com", "bad", "b@y.com"], "client", name="N", note="Acme", by="page")
    assert n == 2
    assert conn.closed and len(conn.calls) == 2
    for sql, params in conn.calls:
        assert "@" not in sql and "Acme" not in sql
        assert sql.count("%s") == len(params) == 5
    assert conn.calls[0][1][0] == "a@x.com"


def test_add_users_rejects_an_unknown_role_and_writes_nothing_for_junk(monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr(access_store, "_connect", lambda: conn)
    with pytest.raises(ValueError):
        access_store.add_users(["a@x.com"], "admin")
    assert access_store.add_users(["junk"], "client") == 0
    assert not conn.calls


def test_set_active_and_remove_bind_the_address(monkeypatch):
    conn = FakeConn()
    monkeypatch.setattr(access_store, "_connect", lambda: conn)
    access_store.set_active("A@X.com", False)
    access_store.remove("a@x.com'; DROP TABLE x;--")           # not an address: nothing runs
    assert len(conn.calls) == 1
    sql, params = conn.calls[0]
    assert "a@x.com" not in sql and params == (False, "a@x.com")


def test_read_for_email_asks_for_one_normalized_address(monkeypatch):
    seen = []
    monkeypatch.setattr(access_store, "_rows", lambda sql, params=(): seen.append((sql, params)) or [])
    assert access_store.read_for_email("  A@X.com ") == []
    assert seen and seen[0][1] == ("a@x.com",) and "WHERE" in seen[0][0]
    seen.clear()
    assert access_store.read_for_email("not an address") == [] and not seen   # no query for junk


def test_a_client_view_never_imports_the_writing_functions():
    # the client gate only needs read_for_email; the writers are used by the staff page alone
    src = (ROOT / "shared" / "signin.py").read_text(encoding="utf-8")
    for fn in ("add_users", "set_active", "remove(", "read_all"):
        assert fn not in src, fn
