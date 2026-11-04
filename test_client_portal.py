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


STAFF_ONLY = {"cso-risk-analyzer", "rma-map", "teams-broadcast", "financial-wire", "grain-desk-status",
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
