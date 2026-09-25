"""Serves the artifact dashboard (dashboard/radar-app.html) on the Mac with a tiny `window.claude` shim.

The page talks to the same document paths it uses inside claude.ai (feed, status/<id>, config/*),
backed here by the local SQLite database, so both versions look and behave the same.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, Response, abort, jsonify, request

from . import db as dbm
from .feed import item as feed_item
from .settings import ROOT
from .tiers import Classifier

bp = Blueprint("localapp", __name__)
PAGE = ROOT / "dashboard" / "radar-app.html"
_SAFE = re.compile(r"^[A-Za-z0-9_\-.:@+/]{1,200}$")

SHIM = """<script>
(function () {
  function get(u) { return fetch(u, { cache: "no-store" }).then(function (r) { if (!r.ok) throw { code: "http_" + r.status }; return r.json(); }); }
  function poll(url, map, cb, err) {
    var last = null, stop = false;
    function tick() {
      if (stop) return;
      get(url).then(function (d) { var s = JSON.stringify(d); if (s !== last) { last = s; cb(map(d)); } })
        .catch(function (e) { if (err && last === null) err(e); }).then(function () { setTimeout(tick, 8000); });
    }
    tick();
    return function () { stop = true; };
  }
  var DB = {
    collection: function (name) {
      return { onSnapshot: function (cb, err) {
        return poll("/api/kv/col/" + name, function (d) { return { docs: d.docs.map(function (x) { return { id: x.id, data: function () { return x.data; } }; }) }; }, cb, err);
      } };
    },
    doc: function (path) {
      return {
        onSnapshot: function (cb, err) { return poll("/api/kv/doc/" + path, function (d) { return { exists: d.exists, data: function () { return d.data; } }; }, cb, err); },
        set: function (data) {
          return fetch("/api/kv/doc/" + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) })
            .then(function (r) { if (!r.ok) throw { code: "http_" + r.status }; });
        }
      };
    }
  };
  var MCP = { local: true, listTools: function () { return Promise.resolve(null); },
    callTool: function (server, tool) {
      if (tool !== "fire_trigger") return Promise.reject({ code: "not_in_manifest" });
      return fetch("/api/scan", { method: "POST" }).then(function (r) { if (!r.ok) throw { code: "tool_error" }; return { payload: {} }; });
    } };
  window.claude = { use: function (name) { return Promise.resolve(name === "db" ? DB : name === "mcp" ? MCP : null); } };
})();
</script>
"""


def _kv_get(con, path: str):
    raw = dbm.get_setting(con, "kv:" + path, "")
    return json.loads(raw) if raw else None


def _rules(con):
    return _kv_get(con, "config/rules")


@bp.route("/app")
def app_page():
    html = PAGE.read_text(encoding="utf-8")
    return Response(html.replace("<script>", SHIM + "<script>", 1), mimetype="text/html")


@bp.route("/api/kv/col/<name>")
def kv_collection(name: str):
    with dbm.get_db() as con:
        if name == "feed":
            rules = _rules(con) or {}
            days = int(rules.get("days") or 7)
            floor = (datetime.now(timezone.utc) - timedelta(days=days + 1)).isoformat(timespec="seconds")
            clf = Classifier(rules)
            rows = con.execute("SELECT * FROM opportunities WHERE found_at > ? ORDER BY found_at", (floor,)).fetchall()
            items = [i for i in (feed_item(r, clf) for r in rows) if i["tier"] != "drop"]
            docs = [{"id": f"local-{n}", "data": {"items": items[n:n + 200]}} for n in range(0, len(items), 200)]
            return jsonify({"docs": docs})
        if name == "status":
            rows = con.execute("SELECT key, value FROM settings WHERE key LIKE 'kv:status/%'").fetchall()
            return jsonify({"docs": [{"id": r[0][len("kv:status/"):], "data": json.loads(r[1])} for r in rows]})
    return jsonify({"docs": []})


@bp.route("/api/kv/doc/<path:path>", methods=["GET", "POST"])
def kv_doc(path: str):
    if not _SAFE.match(path) or ".." in path:
        abort(400)
    with dbm.get_db() as con:
        if request.method == "GET":
            if path == "config/meta":
                last = con.execute("SELECT finished_at, started_at, fetched FROM scans ORDER BY id DESC LIMIT 1").fetchone()
                data = {"lastRun": (last[0] or last[1]) if last else None, "newItems": last[2] if last else 0}
                return jsonify({"exists": bool(last), "data": data})
            data = _kv_get(con, path)
            return jsonify({"exists": data is not None, "data": data})
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            abort(400)
        dbm.set_setting(con, "kv:" + path, json.dumps(data, ensure_ascii=False))
        if path.startswith("status/"):
            uid = path.split("/", 1)[1]
            con.execute("UPDATE opportunities SET status=?, notes=?, updated_at=datetime('now') WHERE substr(uid,1,16)=?",
                        (data.get("status") or "New", data.get("notes") or "", uid))
            con.commit()
    if path == "config/sources":
        from .remote_config import apply_sources

        apply_sources(data)
    return jsonify({"ok": True})


@bp.post("/api/scan")
def api_scan():
    from .scanner import run_scan
    from .web import run_background

    started = run_background("اسکن از داشبورد", run_scan)
    return jsonify({"started": bool(started)})
