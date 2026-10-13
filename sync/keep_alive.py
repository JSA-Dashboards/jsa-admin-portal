"""Keep the Streamlit Cloud portal from going to sleep.

Cloud puts an app to sleep after ~12 hours with no browser connected, and the next person
waits a minute or more for it to wake. A plain HTTP GET doesn't count as a visit (only an
open websocket does), so this opens the page in a headless browser, clicks the "get this app
back up" button if it finds the sleep screen, and waits for the app to actually render.
Run by .github/workflows/keep-alive.yml every few hours; exits non-zero if the page never loads.

    python sync/keep_alive.py [url]
"""
import sys
import time

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://jsatools-corporate.streamlit.app/"
WAKE_BUTTON = "button:has-text('get this app back up')"


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
        deadline = time.time() + 240
        woke = False
        while time.time() < deadline:
            btn = page.query_selector(WAKE_BUTTON)
            if btn and not woke:
                print("app was asleep: clicking the wake button")
                btn.click()
                woke = True
            # The app lives in an iframe on Cloud; its root renders once the script has started.
            for frame in page.frames:
                if frame.query_selector("[data-testid='stApp']"):
                    time.sleep(8)  # stay connected a moment so it counts as a visit
                    print(f"app is up ({'woken' if woke else 'was already awake'})")
                    browser.close()
                    return 0
            time.sleep(3)
        print("app did not render within 4 minutes", file=sys.stderr)
        browser.close()
        return 1


if __name__ == "__main__":
    sys.exit(main())
