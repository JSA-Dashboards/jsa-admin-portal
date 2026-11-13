"""Guards for the client portal's default-deny list (Home.py CLIENT_PAGES)."""
import ast
from pathlib import Path

SRC = (Path(__file__).parent / "Home.py").read_text(encoding="utf-8")
TREE = ast.parse(SRC)


def literal(name):
    for n in TREE.body:
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == name:
            return ast.literal_eval(n.value)
    raise AssertionError(f"{name} not found in Home.py")


def tiles():
    for n in TREE.body:
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "LIVE_DASHBOARDS":
            return [{k.value: ast.literal_eval(v) for k, v in zip(d.keys, d.values)} for d in n.value.elts]


STAFF_ONLY = {"cso-risk-analyzer", "rma-map", "teams-broadcast", "financial-wire", "grain-desk-status", "ask-ai", "ask-ai",
              "weekly-cattle-reports", "cattle-market-board"}


def test_staff_only_pages_are_never_in_the_client_list():
    assert STAFF_ONLY.isdisjoint(literal("CLIENT_PAGES"))


def test_every_client_page_is_a_real_tile():
    paths = {t["url_path"] for t in tiles()}
    assert literal("CLIENT_PAGES") <= paths


def test_the_staff_only_set_is_exactly_what_is_not_offered():
    paths = {t["url_path"] for t in tiles()}
    assert paths - literal("CLIENT_PAGES") == STAFF_ONLY       # a new tile must be added to one list or the other


def test_cso_is_a_coming_soon_tile_for_clients():
    assert "CSO & Spread Risk Analyzer" in literal("CLIENT_COMING_SOON")


def test_the_survey_sits_under_cash_grain_for_clients():
    assert literal("CLIENT_CATEGORY")["farmer-selling-survey"] == "Cash Grain"


def test_the_broker_logins_are_the_two_links_clients_asked_for():
    links = literal("BROKER_LINKS")
    assert [(label, url) for label, url, _logo in links] == [("MyStoneX", "https://my.stonex.com/"),
                                                              ("Plus500", "https://client-portal.plus500.com/")]


def test_a_broker_logo_file_that_is_named_exists_or_falls_back_to_a_text_button():
    # Missing logo = text button (Home.py checks), so this only documents which logos are on disk.
    present = {logo for _l, _u, logo in literal("BROKER_LINKS") if (Path(__file__).parent / "assets" / logo).exists()}
    assert "logo-stonex.png" in present
    assert "logo-plus500.png" in present


def test_the_broker_buttons_are_labelled_access_to_client_portals():
    assert literal("BROKER_HEADING") == "Access to Client Portals"


def test_client_tile_text_never_mentions_admin_or_internal_pages():
    for url_path, text in literal("CLIENT_DESC").items():
        assert url_path in literal("CLIENT_PAGES")
        assert "admin" not in text.lower() and "entry" not in text.lower() and "strip trial" not in text.lower()


def test_client_only_tiles_are_offered_to_clients():
    only = {t["url_path"] for t in tiles() if t.get("client_only")}
    assert only == {"crop-conditions"}                  # staff left it off on 11-03; add here only on purpose
    assert only <= literal("CLIENT_PAGES")              # a client-only tile nobody can see would be dead weight


def test_legacy_apps_are_unique_jpsi_com_links():
    legacy = literal("LEGACY_APPS")
    urls = [u for _t, u, _d in legacy]
    assert len(urls) == len(set(urls)) == 7
    assert all(u.startswith("https://www.jpsi.com/") and u.endswith("-dashboard/") for u in urls)
    assert all(t and d for t, _u, d in legacy)
