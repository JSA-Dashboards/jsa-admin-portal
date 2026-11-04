"""
WCMD Licensed Grain Warehouse scraper.
Downloads state-summary (WH Sum Map) and warehouse-detail (WH Heat Map) sheets
from the USDA FSA WCMD Tableau dashboard, then builds the county-level estimate CSV.
Run manually or via scheduled task to refresh monthly.
"""
import os
import sys
import pathlib
import datetime
import pandas as pd

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

DASHBOARD_URL = (
    "https://publicdashboards.dl.usda.gov/t/MRP_PUB/views/WCMDDashboard/Maps"
    "?:embed=y&:showDownloadButton=yes"
)
DATA_DIR = pathlib.Path(__file__).parent / "data"
STATE_FILE   = DATA_DIR / "wcmd_warehouses.csv"
HEATMAP_FILE = DATA_DIR / "wcmd_heatmap.csv"
COUNTY_FILE  = DATA_DIR / "wcmd_county.csv"


def _download_sheet(page, frame, sheet_index: int, save_path: pathlib.Path) -> bool:
    """Open the Crosstab dialog, pick sheet by index, select CSV, and download."""
    try:
        frame.locator('[data-tb-test-id="viz-viewer-toolbar-button-download"]').click()
        page.wait_for_timeout(1500)
        frame.locator('[data-tb-test-id="download-flyout-download-crosstab-MenuItem"]').click()
        page.wait_for_timeout(4000)

        sheets = frame.locator('.thumbnail-wrapper_farv7f0').all()
        if sheet_index >= len(sheets):
            print(f"  Sheet index {sheet_index} out of range ({len(sheets)} sheets)")
            return False
        sheets[sheet_index].click()
        page.wait_for_timeout(800)

        frame.locator('[data-tb-test-id="crosstab-options-dialog-radio-csv-Label"]').click()
        page.wait_for_timeout(500)

        with page.expect_download(timeout=60_000) as dl_info:
            frame.locator('.fc9tep5').click()
        dl = dl_info.value
        save_path.parent.mkdir(parents=True, exist_ok=True)
        dl.save_as(str(save_path))
        print(f"  Saved {save_path.name}  ({save_path.stat().st_size:,} bytes)")
        return True
    except PWTimeout as e:
        print(f"  Timeout: {e}")
        return False
    except Exception as e:
        print(f"  Error: {e}")
        return False


def scrape() -> bool:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1400, "height": 900},
            accept_downloads=True,
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = ctx.new_page()

        print(f"Loading {DASHBOARD_URL} ...")
        try:
            page.goto(DASHBOARD_URL, timeout=90_000, wait_until="load")
        except PWTimeout:
            print("Page load timed out — continuing anyway.")
        page.wait_for_timeout(14_000)

        # Find download button frame
        frame = None
        for f in page.frames:
            btn = f.locator('[data-tb-test-id="viz-viewer-toolbar-button-download"]')
            if btn.count() > 0:
                frame = f
                print(f"Download button found in frame: {f.url[:80]}")
                break

        if frame is None:
            print("Download button not found in any frame.")
            browser.close()
            return False

        # Sheet indices: 0=Laptop, 1=Masthead 2, 2=WH Heat Map, 3=WH Sum Map
        print("Downloading WH Sum Map (state totals) ...")
        ok1 = _download_sheet(page, frame, sheet_index=3, save_path=STATE_FILE)

        print("Downloading WH Heat Map (warehouse locations) ...")
        ok2 = _download_sheet(page, frame, sheet_index=2, save_path=HEATMAP_FILE)

        browser.close()

    if ok1 and ok2:
        _build_county_file()
        stamp = DATA_DIR / "wcmd_last_updated.txt"
        stamp.write_text(datetime.datetime.now().isoformat())
        print(f"Done. Timestamp: {stamp.read_text()}")
    return ok1


def _build_county_file():
    """Derive county-level estimated capacity from the heat map + state totals."""
    print("Building county estimates ...")

    # State totals
    raw = pd.read_csv(STATE_FILE, encoding="utf-16", sep="\t")
    grain = raw[raw["Commodity*"].str.strip() == "Grain"]
    state_cap = grain[grain["Unnamed: 6"].str.strip() == "Capacity*"][["State", "Grain"]].copy()
    state_cap.columns = ["state", "state_capacity_bu"]
    state_cap["state_capacity_bu"] = (
        state_cap["state_capacity_bu"].astype(str).str.replace(",", "")
        .apply(pd.to_numeric, errors="coerce")
    )

    # Heat map — long form
    raw_hm = pd.read_csv(HEATMAP_FILE, encoding="utf-16", sep="\t", header=None, dtype=str)
    data = raw_hm.iloc[2:].reset_index(drop=True)
    data.columns = range(len(data.columns))
    df = data[[7, 8, 9, 11]].copy()
    df.columns = ["commodity", "county", "func_units", "state"]
    df_grain = df[df["commodity"].str.strip() == "Grain"].copy()
    df_grain["func_units"] = pd.to_numeric(df_grain["func_units"], errors="coerce").fillna(0)

    county = df_grain.groupby(["state", "county"]).agg(
        locations=("func_units", "count"),
        func_units=("func_units", "sum"),
    ).reset_index()
    state_funcs = county.groupby("state")["func_units"].sum().reset_index()
    state_funcs.columns = ["state", "state_func_total"]
    county = county.merge(state_funcs, on="state").merge(state_cap, on="state")
    county["est_capacity_bu"] = (
        (county["func_units"] / county["state_func_total"] * county["state_capacity_bu"])
        .round(0).astype("Int64")
    )
    county.to_csv(COUNTY_FILE, index=False)
    print(f"  Saved {COUNTY_FILE.name}: {len(county)} county rows")


if __name__ == "__main__":
    ok = scrape()
    sys.exit(0 if ok else 1)
