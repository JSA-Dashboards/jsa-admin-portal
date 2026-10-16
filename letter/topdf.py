"""
HTML to PDF via headless Edge (or Chrome).

WHY A BROWSER. The alternatives all cost something this does not: WeasyPrint
needs GTK on Windows, ReportLab means laying the letter out twice, and wkhtmltopdf
is unmaintained. Edge ships with Windows 11 and already renders the print CSS in
render.py exactly as a human would see it with Ctrl+P, so the preview and the
PDF cannot disagree.

Failure here is never fatal: the HTML is already written, and the caller falls
back to telling you to print it yourself.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def find_browser() -> str | None:
    for p in CANDIDATES:
        if os.path.exists(p):
            return p
    for name in ("msedge", "chrome", "chromium"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _wrote(pdf_path: Path, wait_s: float = 6.0) -> bool:
    """
    Poll briefly for the file.

    Headless Edge returns exit 0 before the PDF is always flushed to disk, so
    checking immediately reports a false failure -- observed twice while a
    Streamlit preview had Edge busy. Poll rather than assume either way.
    """
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            return True
        time.sleep(0.25)
    return False


def html_to_pdf(html_path: Path, pdf_path: Path, timeout: int = 120,
                attempts: int = 2) -> tuple[bool, str]:
    """
    Returns (ok, message). Never raises.

    Retried once by default: the headless run intermittently exits 0 having
    written nothing when another Edge instance is busy, and a second attempt has
    always succeeded. A silent no-PDF is worse than a slow one -- this is the
    file that goes to clients.
    """
    browser = find_browser()
    if not browser:
        return False, "no Edge or Chrome found -- open the HTML and print to PDF"

    last = ""
    for attempt in range(1, attempts + 1):
        ok, last = _run_once(browser, html_path, pdf_path, timeout)
        if ok:
            return True, last
        if attempt < attempts:
            time.sleep(1.5)
    return False, f"{last} (after {attempts} attempts)"


def _run_once(browser: str, html_path: Path, pdf_path: Path,
              timeout: int) -> tuple[bool, str]:
    # Remove the previous build FIRST. _wrote() only checks that a file is
    # there, so a leftover from an earlier run would report success for a run
    # that wrote nothing -- and hand over last week's letter as this week's.
    try:
        pdf_path.unlink(missing_ok=True)
    except OSError as e:
        return False, f"could not replace {pdf_path.name}: {e}"

    # A throwaway profile: headless Chromium refuses to share the profile of a
    # running browser, and Ross has Edge open all day.
    #
    # ignore_cleanup_errors is required, not tidiness. Edge leaves its Crashpad
    # handler holding files in the profile for a moment after exit, so the
    # cleanup hits WinError 145 ("directory is not empty") -- raised from the
    # context manager's __exit__, i.e. OUTSIDE the try below, which would take
    # down a function the caller is promised never raises. The leftover lands in
    # %TEMP% and Windows clears it.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
        cmd = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile}",
            # Both spellings: Chromium renamed this flag, and the wrong one is
            # silently ignored -- which prints the timestamp and the file:// URL
            # across the top and bottom of a client letter.
            "--no-pdf-header-footer",
            "--print-to-pdf-no-header",
            f"--print-to-pdf={pdf_path}",
            html_path.resolve().as_uri(),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, f"{Path(browser).name} timed out after {timeout}s"
        except OSError as e:
            return False, f"could not launch {browser}: {e}"

    if _wrote(pdf_path):
        return True, str(pdf_path)
    err = (proc.stderr or proc.stdout or "").strip().splitlines()
    return False, err[-1] if err else f"{Path(browser).name} exited {proc.returncode} without writing a PDF"
