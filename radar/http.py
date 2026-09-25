"""HTTP helpers: browser-like User-Agent, small retry on 429/5xx."""
from __future__ import annotations

import random
import time

import requests

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
TIMEOUT = 25
SLOW_TIMEOUT = 45  # Iranian sites are often slow (and very slow behind a VPN)
SLOW_HOSTS = (".ir/", ".ir?", "karlancer.com", "parscoders.com", "e-estekhdam.com", "kardix.com", "karpishe.com")
_RETRY_STATUS = {429, 500, 502, 503, 504}


def request(method: str, url: str, *, params=None, json=None, data=None, headers=None,
            accept: str = "*/*", retries: int = 2) -> requests.Response:
    hdrs = {"User-Agent": USER_AGENT, "Accept": accept, "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7"}
    hdrs.update(headers or {})
    slow = any(h in url + "/" for h in SLOW_HOSTS)
    for attempt in range(retries + 1):
        try:
            resp = requests.request(method, url, params=params, json=json, data=data, headers=hdrs,
                                    timeout=(15, SLOW_TIMEOUT if slow else TIMEOUT))
        except (requests.Timeout, requests.ConnectionError):
            if attempt < min(retries, 1):
                time.sleep(3)
                continue
            raise
        if resp.status_code in _RETRY_STATUS and attempt < retries:
            time.sleep(4 * (2 ** attempt) + random.uniform(0, 2))
            continue
        resp.raise_for_status()
        return resp
    return resp  # pragma: no cover


def get_json(url: str, params=None, headers=None):
    return request("GET", url, params=params, headers=headers, accept="application/json").json()


def post_json(url: str, payload, headers=None):
    return request("POST", url, json=payload, headers=headers, accept="application/json").json()


def get_text(url: str, params=None, headers=None) -> str:
    return request("GET", url, params=params, headers=headers,
                   accept="text/html,application/xhtml+xml,*/*;q=0.8").text


def get_bytes(url: str, params=None) -> bytes:
    return request("GET", url, params=params,
                   accept="application/rss+xml,application/atom+xml,application/xml,text/xml,*/*;q=0.8").content


def pause(seconds: float = 1.5) -> None:
    """Polite delay between requests to the same site."""
    time.sleep(seconds + random.uniform(0, seconds / 2))
