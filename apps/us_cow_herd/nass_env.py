"""
One-line environment fix that every NASS-cache reader on this page needs.

nass_cache_client reads the private-key passphrase from SNOWFLAKE_PRIVATE_KEY_PWD
-- the name Streamlit Cloud's secrets use. Everywhere else on this machine it is
SNOWFLAKE_PRIVATE_KEY_PASSPHRASE, and without the bridge the connector fails with
"Password was not given but private key is encrypted", which reaches the reader
as a panel that simply is not there.

snowflake_db.py accepts either name; nass_cache_client accepts only one and is
vendored byte-for-byte across four repos, so it is not ours to edit.

This lives in its own module rather than being repeated in each reader: a subtle
fix copied twice is a fix that gets half-removed later. Import it before
nass_cache_client and the ordering does the work.
"""
import os


def bridge_passphrase():
    """Mirror the passphrase onto the name nass_cache_client reads. Idempotent."""
    if not os.environ.get("SNOWFLAKE_PRIVATE_KEY_PWD"):
        pp = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE")
        if pp:
            os.environ["SNOWFLAKE_PRIVATE_KEY_PWD"] = pp


bridge_passphrase()
