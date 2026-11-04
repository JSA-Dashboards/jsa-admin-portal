"""Keep the JSA Streamlit Cloud apps from going to sleep.

Cloud puts an app to sleep after ~12 hours with no browser connected, and the next person
waits a minute or more for it to wake. A plain HTTP GET doesn't count as a visit (only an
open websocket does), so this opens each app in a headless browser, clicks the "get this app
back up" button if it finds the sleep screen, and waits for the app to actually render.

Apps come from sync/keep_alive_apps.txt (or URLs on the command line). They run a few at a time,
and an app that doesn't render is retried: Cloud's static-file server intermittently answers a
few of a page's ~60 JavaScript files with HTTP 500 (seen 2026-11-03), which blanks the page, and
a fresh load usually gets through. Exits non-zero only if an app still failed after every try.

    python sync/keep_alive.py                  # every app in keep_alive_apps.txt
    python sync/keep_alive.py URL [URL ...]    # just these
"""
import asyncio
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

APPS_FILE = Path(__file__).with_name("keep_alive_apps.txt")
WAKE_BUTTON = "button:has-text('get this app back up')"
ATTEMPTS = 3
ATTEMPT_SECONDS = 200      # a sleeping app can take a couple of minutes to come back
CONCURRENCY = 4


def app_urls(argv: list[str]) -> list[str]:
    if argv:
        return argv
    lines = (ln.strip() for ln in APPS_FILE.read_text(encoding="utf-8").splitlines())
    return [ln for ln in lines if ln and not ln.startswith("#")]


async def rendered(page) -> bool:
    for frame in page.frames:
        try:
            if await frame.query_selector("[data-testid='stApp']"):
                return True
        except Exception:
            pass  # a frame mid-navigation
    return False


async def attempt(browser, url: str) -> str | None:
    """'awake' / 'woken' when the app rendered, else None."""
    context = await browser.new_context()
    try:
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        deadline = time.time() + ATTEMPT_SECONDS
        woke = False
        while time.time() < deadline:
            if not woke and await page.query_selector(WAKE_BUTTON):
                await page.click(WAKE_BUTTON)
                woke = True
            if await rendered(page):
                await asyncio.sleep(8)  # stay connected a moment so it counts as a visit
                return "woken" if woke else "awake"
            await asyncio.sleep(3)
        return None
    except Exception as exc:
        print(f"  {url}: {type(exc).__name__}: {str(exc)[:100]}", flush=True)
        return None
    finally:
        await context.close()


async def visit(browser, sem, url: str) -> tuple[str, str]:
    async with sem:
        for n in range(1, ATTEMPTS + 1):
            result = await attempt(browser, url)
            if result:
                print(f"ok     {url}  ({result}{'' if n == 1 else f', attempt {n}'})", flush=True)
                return url, result
            print(f"retry  {url}  (attempt {n} did not render)", flush=True)
        print(f"FAILED {url}", flush=True)
        return url, "failed"


async def main(urls: list[str]) -> int:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        sem = asyncio.Semaphore(CONCURRENCY)
        results = await asyncio.gather(*(visit(browser, sem, u) for u in urls))
        await browser.close()
    failed = [u for u, r in results if r == "failed"]
    woken = [u for u, r in results if r == "woken"]
    print(f"\n{len(results)} app(s): {len(results) - len(failed)} up, {len(woken)} woken, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(app_urls(sys.argv[1:]))))
