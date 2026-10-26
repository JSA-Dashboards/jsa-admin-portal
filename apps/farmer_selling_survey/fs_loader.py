"""Parse the analyst's Farmer Selling Survey workbook into tidy tables."""
import pandas as pd
import openpyxl

# All Data block label -> (commodity, marketing-year start month)
BLOCKS = {"YC": ("Corn", 9), "YSB": ("Soybeans", 9), "SRW": ("SRW wheat", 6),
          "HRW": ("HRW wheat", 6), "HRS": ("HRS wheat", 9)}
# Summary title keyword -> commodity
SUMMARY = {"Corn": "Corn", "Soybean": "Soybeans", "HRW": "HRW wheat",
           "SRW": "SRW wheat", "HRS": "HRS wheat"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def parse_all_data(ws) -> pd.DataFrame:
    """Survey-date series: commodity, crop_year, date, pct (0-100)."""
    rows = list(ws.iter_rows(values_only=True))
    out = []
    i = 0
    while i < len(rows):
        label = rows[i][0]
        if label in BLOCKS:
            commodity, _ = BLOCKS[label]
            dates, prev = [], None
            for d in rows[i][1:]:
                if hasattr(d, "year") and prev is not None and (d - prev).days > 180:
                    d = d.replace(year=prev.year)  # hand-typed year slip in the sheet
                if hasattr(d, "year"):
                    prev = d
                dates.append(d if hasattr(d, "year") else None)
            j = i + 1
            while j < len(rows) and rows[j][0]:
                cy = str(rows[j][0])
                for d, v in zip(dates, rows[j][1:]):
                    if d is not None and _num(v) is not None:
                        out.append((commodity, cy, pd.Timestamp(d), _num(v) * 100))
                j += 1
            i = j
        i += 1
    df = pd.DataFrame(out, columns=["commodity", "crop_year", "date", "pct"])
    return df.sort_values(["commodity", "crop_year", "date"]).reset_index(drop=True)


def parse_summary(ws) -> pd.DataFrame:
    """Monthly table: commodity, kind (current/new), crop_year, month, pct (0-100)."""
    rows = list(ws.iter_rows(values_only=True))
    out = []
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            if not (isinstance(cell, str) and "Sales (%)" in cell):
                continue
            kind = "new" if cell.startswith("New Crop") else "current"
            commodity = next(v for k, v in SUMMARY.items() if k in cell)
            years = []
            c2 = c + 1
            while c2 < len(rows[r + 1]) and rows[r + 1][c2]:
                years.append(rows[r + 1][c2]); c2 += 1
            rr, seen = r + 2, set()
            while rr < len(rows) and rows[rr][c] in MONTHS:
                m = rows[rr][c]
                if m in seen:  # wheat tables repeat the first month as the year-end close
                    m += " close"
                seen.add(m)
                for k, cy in enumerate(years):
                    v = _num(rows[rr][c + 1 + k])
                    if v is not None:
                        out.append((commodity, kind, str(cy), m, v))
                rr += 1
    return pd.DataFrame(out, columns=["commodity", "kind", "crop_year", "month", "pct"])


def load_workbook_tables(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    return parse_all_data(wb["All Data"]), parse_summary(wb["Summary"])
