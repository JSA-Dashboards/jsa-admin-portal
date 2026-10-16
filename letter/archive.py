"""
Keep every letter that was published, exactly as it went out.

WHY THIS EXISTS. Until 2026-09-24 nothing kept them. out/ is gitignored, the
build overwrites a render with the same date and session, and on the deployed
app out/ is wiped by every reboot. The rendered 9/15 and 9/22 letters were
already gone by the time anyone asked. Clients have them; JSA did not.

RE-RENDERING IS NOT ARCHIVING, and this is the whole argument for storing bytes
rather than inputs. Rebuilding 9/23's morning brief on the 24th produces
different futures (the AM session fix), a settlement date line that did not
exist that morning, and no intro paragraph. Every one of those changes was
correct, and every one of them makes the rebuilt letter a different document
from the one clients read. The data cache is a record of what was fetched; only
the HTML and PDF are a record of what was sent.

A GIT REPO, NOT A FOLDER, AND THAT DOES THE VERSIONING. Publishing a corrected
letter for a date that already has one overwrites the file and commits it, so
`git log -- <path>` in the archive gives every version that ever went out, with
the earlier bytes intact. Nothing here needs to invent -v2 filenames.

WHERE IT GOES. A separate PRIVATE repo. These are letters paying clients
receive, and livestock-portal is public -- committing them beside the code
would publish the product. The path is LETTER_ARCHIVE_DIR, defaulting to a
sibling checkout, so on Streamlit Cloud -- no clone, no push credentials -- the
directory is simply absent and every call here becomes a no-op with a reason
rather than a traceback in the middle of a letter.

NOTHING IS ARCHIVED AUTOMATICALLY. "Published" means Ross sent it, and only he
knows when that happened; a hook on every build would commit a dozen drafts a
day and bury the one that matters. It is a flag on the CLI and a button on the
authoring page.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

# A sibling of the portal checkout: projects/livestock-portal ->
# projects/jsa-letter-archive. Override with LETTER_ARCHIVE_DIR.
DEFAULT_DIR = Path(__file__).resolve().parents[2] / "jsa-letter-archive"

INDEX_NAME = "index.json"


def archive_dir() -> Path:
    return Path(os.environ.get("LETTER_ARCHIVE_DIR") or DEFAULT_DIR)


def available() -> tuple[bool, str]:
    """
    (usable, why not). Checked before offering the button, so the page can say
    what is missing instead of failing when it is pressed.
    """
    d = archive_dir()
    if not d.exists():
        return False, f"no archive checkout at {d}"
    if not (d / ".git").exists():
        return False, f"{d} is not a git repo -- clone jsa-letter-archive there"
    return True, ""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def stem_for(issue: date, session: str) -> str:
    """
    "2026-09-23-am".

    DATE AND SESSION ONLY. There are exactly two letters a day, so that is
    already unique, and the weekday is derivable from the date -- putting it in
    the name too invites the two disagreeing after a manual rename. The weekday
    and the format kind are both recorded in the index, where they can be read
    without parsing a filename.
    """
    return f"{issue.isoformat()}-{str(session).strip().lower()}"


def paths_for(issue: date, session: str, root: Path = None) -> dict:
    """Year/month folders: a flat directory stops being browsable in a year."""
    root = Path(root or archive_dir())
    folder = root / f"{issue.year:04d}" / f"{issue.month:02d}"
    stem = stem_for(issue, session)
    return {"folder": folder,
            "html": folder / f"{stem}.html",
            "pdf": folder / f"{stem}.pdf"}


def load_index(root: Path = None) -> dict:
    p = Path(root or archive_dir()) / INDEX_NAME
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_index(index: dict, root: Path = None) -> None:
    p = Path(root or archive_dir()) / INDEX_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _git(root: Path, *args) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", *args], cwd=str(root), capture_output=True,
                           text=True, timeout=120)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, f"{type(e).__name__}: {e}"


def publish(issue: date, session: str, html_path=None, pdf_path=None,
            kind: str = "", title: str = "", push: bool = True,
            root: Path = None) -> dict:
    """
    Copy one published letter into the archive, commit it, and push.

    Returns {"ok", "reason", "files", "changed", "pushed"}. Never raises: this
    runs at the end of a letter, and losing the archive step must not cost the
    letter.

    `changed` is False when the bytes already match what is archived -- pressing
    the button twice is harmless and makes no commit.
    """
    root = Path(root or archive_dir())
    ok, why = available() if root == archive_dir() else (root.exists(), f"no archive at {root}")
    if not ok:
        return {"ok": False, "reason": why, "files": [], "changed": False, "pushed": False}

    dest = paths_for(issue, session, root)
    dest["folder"].mkdir(parents=True, exist_ok=True)

    copied, changed = [], False
    for key, src in (("html", html_path), ("pdf", pdf_path)):
        if not src:
            continue
        src = Path(src)
        if not src.exists():
            continue
        target = dest[key]
        if target.exists() and _sha(target) == _sha(src):
            copied.append(target)
            continue
        shutil.copy2(src, target)
        copied.append(target)
        changed = True

    if not copied:
        return {"ok": False, "reason": "nothing to archive -- no rendered file found",
                "files": [], "changed": False, "pushed": False}

    # The index is a manifest for reading the archive without walking it, not
    # the archive itself. The files are the archive.
    index = load_index(root)
    key = stem_for(issue, session)
    entry = {
        "issue_date": issue.isoformat(),
        "session": str(session).strip().lower(),
        "kind": kind,
        "title": title,
        "weekday": issue.strftime("%A").lower(),
        "archived_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": {k: str(dest[k].relative_to(root)).replace("\\", "/")
                  for k in ("html", "pdf") if dest[k].exists()},
        "sha256": {k: _sha(dest[k]) for k in ("html", "pdf") if dest[k].exists()},
    }
    if index.get(key, {}).get("sha256") != entry["sha256"]:
        changed = True
    # Keep the first archived_at: it says when this letter was first published,
    # which a re-publish should not rewrite.
    if key in index and index[key].get("sha256") == entry["sha256"]:
        entry["archived_at"] = index[key].get("archived_at", entry["archived_at"])
    index[key] = entry
    save_index(index, root)

    if not changed:
        return {"ok": True, "reason": "already archived, unchanged",
                "files": [str(p) for p in copied], "changed": False, "pushed": False}

    _git(root, "add", "-A")
    rc, out = _git(root, "commit", "-m",
                   f"{title or 'Letter'} -- {issue.isoformat()} {str(session).upper()}")
    if rc != 0 and "nothing to commit" not in out:
        return {"ok": False, "reason": f"commit failed: {out[:200]}",
                "files": [str(p) for p in copied], "changed": True, "pushed": False}

    pushed = False
    if push:
        rc, out = _git(root, "push")
        pushed = (rc == 0)
        if not pushed:
            return {"ok": True, "reason": f"committed locally; push failed: {out[:200]}",
                    "files": [str(p) for p in copied], "changed": True, "pushed": False}

    return {"ok": True, "reason": "", "files": [str(p) for p in copied],
            "changed": True, "pushed": pushed}
