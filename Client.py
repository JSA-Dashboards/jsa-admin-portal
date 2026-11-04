"""
The CLIENT portal's main file. Same shell, same dashboards, same tiles as Home.py, narrowed to what clients
get (Home.py's CLIENT_PAGES) with a nearby-price strip on top, the shared client password in place of the
staff login, and every staff door closed.

WHY A SECOND MAIN FILE, NOT A SECRET. Streamlit Cloud takes the main file path per app, so which portal a
deployment serves is decided by how it is wired up rather than by a value somebody has to remember. A secret
would have to default to STAFF (or the existing portal would strip itself on its next reboot), and a client
deployment that lost it would then quietly serve the staff portal to clients. There is no such state here:
this file sets the view before anything renders and is the only thing that ever does. It is the same
approach as the Livestock Portal's Client.py, and its mirrored pages already honor `portal_view`.

WHY IT RUNS Home.py WITH runpy RATHER THAN IMPORTING IT. Streamlit re-executes the main script on every rerun,
and `import Home` would be a cached no-op from the second rerun on (the page would render once, then blank).

To deploy: a SECOND Streamlit Cloud app in the jsa-dashboards workspace, repo JSA-Dashboards/jsa-admin-portal,
branch master, **main file `Client.py`**. Its own Secrets: the Snowflake block (and NO SNOWFLAKE_SCHEMA),
USE_SNOWFLAKE, MASSIVE_API_KEY, NASS_API_KEY and **CLIENT_PASSWORD**. It must NOT get ADMIN_PASSWORD, the
GRAPH_* mail secrets, MARS_API_KEY or ANTHROPIC_API_KEY: nothing client-facing needs them, and leaving them off
is one more reason this deployment cannot be talked into doing staff things. See CLAUDE.md "Client portal".
"""
import os
import runpy
from pathlib import Path

import portal_view

# Before anything renders, and before Home.py's own imports pull in a page.
os.environ["JSA_PORTAL_VIEW"] = "client"
portal_view.set_client()

runpy.run_path(str(Path(__file__).with_name("Home.py")), run_name="__main__")
