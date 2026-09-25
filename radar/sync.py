"""Mac ⇄ GitHub sync through the GitHub REST API (no git needed on the Mac).

Branch `radar-data` (configurable) holds two exchange files:
  inbox/local-latest.json  ← written by the Mac   (Iranian sources + your status changes)
  inbox/cloud-latest.json  ← written by Actions   (international sources)
Config files (config/*.yaml) are pushed to the default branch so GitHub Actions
uses the same profile / sources / settings as the dashboard.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from . import db as dbm
from .config_store import load_settings
from .settings import CONFIG_DIR, env, runner

API = "https://api.github.com"


def repo() -> str:
    return env("GITHUB_REPO") or env("GITHUB_REPOSITORY")


def configured() -> bool:
    return bool(env("GITHUB_TOKEN") and repo())


def _headers(raw: bool = False) -> dict:
    return {
        "Authorization": f"Bearer {env('GITHUB_TOKEN')}",
        "Accept": "application/vnd.github.raw+json" if raw else "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _branch() -> str:
    return load_settings()["sync"].get("data_branch") or "radar-data"


def _default_branch() -> str:
    resp = requests.get(f"{API}/repos/{repo()}", headers=_headers(), timeout=20)
    resp.raise_for_status()
    return resp.json().get("default_branch") or "main"


def _ensure_branch(branch: str) -> None:
    resp = requests.get(f"{API}/repos/{repo()}/branches/{branch}", headers=_headers(), timeout=20)
    if resp.status_code == 200:
        return
    base = _default_branch()
    ref = requests.get(f"{API}/repos/{repo()}/git/ref/heads/{base}", headers=_headers(), timeout=20)
    ref.raise_for_status()
    created = requests.post(f"{API}/repos/{repo()}/git/refs", headers=_headers(), timeout=20,
                            json={"ref": f"refs/heads/{branch}", "sha": ref.json()["object"]["sha"]})
    if created.status_code not in (201, 422):  # 422 = created concurrently
        created.raise_for_status()


def _sha(path: str, branch: str) -> Optional[str]:
    resp = requests.get(f"{API}/repos/{repo()}/contents/{path}", params={"ref": branch}, headers=_headers(), timeout=20)
    return resp.json().get("sha") if resp.status_code == 200 else None


def put_file(path: str, content: bytes, message: str, branch: Optional[str] = None) -> None:
    branch = branch or _branch()
    if branch == _branch():
        _ensure_branch(branch)
    body = {"message": message, "content": base64.b64encode(content).decode(), "branch": branch}
    sha = _sha(path, branch)
    if sha:
        body["sha"] = sha
    resp = requests.put(f"{API}/repos/{repo()}/contents/{path}", headers=_headers(), json=body, timeout=30)
    resp.raise_for_status()


def get_file(path: str, branch: Optional[str] = None) -> Optional[bytes]:
    resp = requests.get(f"{API}/repos/{repo()}/contents/{path}", params={"ref": branch or _branch()},
                        headers=_headers(raw=True), timeout=30)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.content


# ---------------------------------------------------------------- exchange
def _since(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def push_items() -> str:
    """Upload what this machine found (last 7 days) + status changes (last 30 days)."""
    if not configured():
        return "skipped (GitHub sync not configured)"
    side = runner()
    with dbm.get_db() as con:
        payload = {
            "runner": side,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "items": dbm.export_items(con, _since(7), origin=side),
            "status_updates": dbm.export_status_updates(con, _since(30)) if side == "local" else {},
        }
    path = f"inbox/{side}-latest.json"
    try:
        current = json.loads((get_file(path) or b"{}").decode("utf-8"))
    except ValueError:
        current = {}
    if current.get("items") == payload["items"] and current.get("status_updates") == payload["status_updates"]:
        return "unchanged"
    put_file(path, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
             f"radar: {side} results ({len(payload['items'])} items)")
    return f"sent ({len(payload['items'])} items)"


def pull_items() -> str:
    """Import what the other side found."""
    if not configured():
        return "skipped (GitHub sync not configured)"
    other = "cloud" if runner() == "local" else "local"
    raw = get_file(f"inbox/{other}-latest.json")
    if not raw:
        return "nothing to import yet"
    payload = json.loads(raw.decode("utf-8"))
    from .profile import load_profile
    from .scoring import score_item
    from .sources.base import Item

    profile = load_profile()
    new = updated = 0
    with dbm.get_db() as con:
        for row in payload.get("items") or []:
            item = Item(**{k: row.get(k) for k in ("title", "url", "company", "location", "description", "posted_at",
                                                    "job_type", "salary", "source", "source_type")},
                        tags=row.get("tags") or [])
            if not item.title:
                continue
            kind, _ = dbm.upsert_opportunity(con, item, score_item(item, profile), source_id=row.get("source_id", ""),
                                             origin=other, uid=row.get("uid"))
            new += kind == "new"
            updated += kind == "updated"
        con.commit()
        changed = dbm.apply_status_updates(con, payload.get("status_updates") or {})
    return f"imported {new} new, {updated} updated, {changed} status changes"


def push_config() -> str:
    """Push config/*.yaml to the default branch so GitHub Actions uses the same settings."""
    if not configured():
        return "skipped (GitHub sync not configured)"
    base = _default_branch()
    pushed = []
    for name in ("profile.yaml", "sources.yaml", "settings.yaml"):
        path = CONFIG_DIR / name
        if not path.exists():
            continue
        content = path.read_bytes()
        remote = get_file(f"config/{name}", branch=base)
        if remote == content:
            continue
        put_file(f"config/{name}", content, f"radar: update {name} from dashboard", branch=base)
        pushed.append(name)
    return f"pushed {', '.join(pushed)}" if pushed else "already up to date"


def pull_config() -> str:
    if not configured():
        return "skipped (GitHub sync not configured)"
    base = _default_branch()
    pulled = []
    for name in ("profile.yaml", "sources.yaml", "settings.yaml"):
        remote = get_file(f"config/{name}", branch=base)
        if remote and (not (CONFIG_DIR / name).exists() or (CONFIG_DIR / name).read_bytes() != remote):
            (CONFIG_DIR / name).write_bytes(remote)
            pulled.append(name)
    return f"pulled {', '.join(pulled)}" if pulled else "already up to date"
