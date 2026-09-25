"""HTTP helpers with a browser-like User-Agent (several boards block bare clients)."""
from __future__ import annotations

import requests

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 PersonalOpportunityRadar/1.0"
)
TIMEOUT = 25


def _get(url: str, params=None, accept: str = "*/*") -> requests.Response:
    resp = requests.get(
        url,
        params=params,
        timeout=TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept": accept, "Accept-Language": "en-US,en;q=0.9"},
    )
    resp.raise_for_status()
    return resp


def get_json(url: str, params=None):
    return _get(url, params, "application/json").json()


def get_text(url: str, params=None) -> str:
    return _get(url, params, "text/html,application/xhtml+xml,*/*;q=0.8").text


def get_bytes(url: str, params=None) -> bytes:
    return _get(url, params, "application/rss+xml,application/atom+xml,application/xml,text/xml,*/*;q=0.8").content
