"""CRUD for the live book (POSITIONS) plus the replace-with-history-snapshot flow used
by the import wizard. Import commits keep the original tool's "replace the whole book"
UX, but every replace now also writes an immutable JSON snapshot to POSITION_HISTORY —
the audit trail the HTML tool never had.
"""
import json
from datetime import date
from typing import List, Optional

import pandas as pd

from jsa_risk.pricing.stress import Position

from . import snowflake_client as sf


def _row_to_position(row) -> Position:
    expiry = row["EXPIRY_DATE"]
    return Position(
        id=int(row["POSITION_ID"]),
        label=row["LABEL"],
        type=row["TYPE"],
        qty=int(row["QTY"]),
        entry=float(row["ENTRY"]),
        strike=None if pd.isna(row["STRIKE"]) else float(row["STRIKE"]),
        expiry_date=None if pd.isna(expiry) else (expiry.date() if hasattr(expiry, "date") else expiry),
        iv=None if pd.isna(row["IV"]) else float(row["IV"]),
        iv_estimated=bool(row["IV_ESTIMATED"]),
        last_tick=None if pd.isna(row["LAST_TICK"]) else float(row["LAST_TICK"]),
        import_mark=None if pd.isna(row["IMPORT_MARK"]) else float(row["IMPORT_MARK"]),
    )


def load_positions() -> List[Position]:
    df = sf.query_df("SELECT * FROM POSITIONS ORDER BY POSITION_ID")
    return [_row_to_position(row) for _, row in df.iterrows()]


def update_position_field(position_id: int, field: str, value) -> None:
    """Blotter cell edits UPDATE in place. `field` must be a known column name — callers
    pass a fixed set of UI-editable columns, never raw user text, so this stays safe."""
    allowed = {
        "LABEL", "TYPE", "STRIKE", "EXPIRY_DATE", "QTY", "IV", "IV_ESTIMATED",
        "ENTRY", "LAST_TICK",
    }
    if field not in allowed:
        raise ValueError(f"'{field}' is not an editable position column")
    sf.execute(
        f"UPDATE POSITIONS SET {field} = %s, UPDATED_AT = CURRENT_TIMESTAMP() WHERE POSITION_ID = %s",
        (value, position_id),
    )


def delete_position(position_id: int) -> None:
    sf.execute("DELETE FROM POSITIONS WHERE POSITION_ID = %s", (position_id,))


def add_position(p: Position) -> int:
    sf.execute(
        """
        INSERT INTO POSITIONS (LABEL, TYPE, STRIKE, EXPIRY_DATE, QTY, IV, IV_ESTIMATED,
                                ENTRY, LAST_TICK, IMPORT_MARK)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (p.label, p.type, p.strike, p.expiry_date, p.qty, p.iv, p.iv_estimated,
         p.entry, p.last_tick, p.import_mark),
    )
    df = sf.query_df("SELECT MAX(POSITION_ID) AS ID FROM POSITIONS")
    return int(df.iloc[0]["ID"])


def replace_book(
    positions: List[Position],
    mapping: Optional[dict],
    source_filename: Optional[str],
    imported_by: str,
) -> int:
    """Deletes the current book and inserts `positions` as the new one, recording an
    IMPORT_BATCHES row and an immutable POSITION_HISTORY snapshot in the same flow."""
    conn = sf.get_connection()
    cur = conn.cursor()
    try:
        cur.execute("BEGIN")
        cur.execute(
            """
            INSERT INTO IMPORT_BATCHES (IMPORTED_BY, SOURCE_FILENAME, MAPPING_JSON, ROW_COUNT)
            SELECT %s, %s, PARSE_JSON(%s), %s
            """,
            (imported_by, source_filename, json.dumps(mapping or {}), len(positions)),
        )
        cur.execute("SELECT MAX(IMPORT_BATCH_ID) FROM IMPORT_BATCHES")
        batch_id = cur.fetchone()[0]

        cur.execute("DELETE FROM POSITIONS")
        cur.executemany(
            """
            INSERT INTO POSITIONS (LABEL, TYPE, STRIKE, EXPIRY_DATE, QTY, IV, IV_ESTIMATED,
                                    ENTRY, LAST_TICK, IMPORT_MARK, IMPORT_BATCH_ID)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (p.label, p.type, p.strike, p.expiry_date, p.qty, p.iv, p.iv_estimated,
                 p.entry, p.last_tick, p.import_mark, batch_id)
                for p in positions
            ],
        )

        snapshot = [
            {
                "label": p.label, "type": p.type, "strike": p.strike,
                "expiry_date": p.expiry_date.isoformat() if p.expiry_date else None,
                "qty": p.qty, "iv": p.iv, "iv_estimated": p.iv_estimated,
                "entry": p.entry, "last_tick": p.last_tick, "import_mark": p.import_mark,
            }
            for p in positions
        ]
        cur.execute(
            "INSERT INTO POSITION_HISTORY (IMPORT_BATCH_ID, POSITIONS_JSON) SELECT %s, PARSE_JSON(%s)",
            (batch_id, json.dumps(snapshot)),
        )
        cur.execute("COMMIT")
        return int(batch_id)
    except Exception:
        cur.execute("ROLLBACK")
        raise
    finally:
        cur.close()
