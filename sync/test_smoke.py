"""smoke.py treats a page whose import cannot resolve as a hard failure, not a warning.

    python -m pytest sync/test_smoke.py
"""
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import smoke  # noqa: E402


def _exceptions(tmp_path, body):
    page = tmp_path / "app.py"
    page.write_text(body, encoding="utf-8")
    at = AppTest.from_file(str(page), default_timeout=60).run()
    return list(at.exception)


def test_a_module_the_portal_does_not_ship_fails_the_page(tmp_path):
    excs = _exceptions(tmp_path, "import a_module_the_portal_does_not_ship\n")
    assert excs
    assert "No module named" in excs[0].value and not smoke.HARD.search(excs[0].value)   # the bare message alone slipped through
    assert all(smoke.HARD.search(smoke.described(e)) for e in excs)


def test_a_name_that_cannot_be_imported_fails_the_page(tmp_path):
    excs = _exceptions(tmp_path, "from os import a_name_that_is_not_there\n")
    assert excs and all(smoke.HARD.search(smoke.described(e)) for e in excs)


def test_other_exceptions_keep_their_bare_message(tmp_path):
    excs = _exceptions(tmp_path, "1 / 0\n")
    assert excs and [smoke.described(e) for e in excs] == [e.value for e in excs]
