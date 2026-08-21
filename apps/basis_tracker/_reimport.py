import sys, io
sys.stdout=io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
from dotenv import load_dotenv; load_dotenv()
from pathlib import Path
import database as db
assert db._use_pg(), "ERROR: not connected to Postgres (DATABASE_URL missing)"
# 1) wipe existing historical rows (spreadsheet-sourced only; web data untouched)
conn=db.get_conn(); c=conn.cursor()
c.execute("DELETE FROM snapshot_rows WHERE snapshot_id IN (SELECT id FROM snapshots WHERE source='historical')")
print("deleted snapshot_rows:", c.rowcount, flush=True)
c.execute("DELETE FROM snapshots WHERE source='historical'")
print("deleted snapshots:", c.rowcount, flush=True)
conn.commit(); conn.close()
# 2) re-import both sheets fresh
f=Path("history")/"Corn basis history .xlsx"
import import_soybean_history as soy
import import_corn_history as corn
soy.run(f, apply=True, pg=True)
corn.run(f, apply=True, pg=True)
print("REIMPORT COMPLETE", flush=True)
