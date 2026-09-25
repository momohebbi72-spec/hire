"""Local web dashboard (personal CRM) — http://127.0.0.1:3000"""
from __future__ import annotations

import csv
import io
import secrets
import threading
import webbrowser
from datetime import datetime

import yaml
from flask import Flask, abort, flash, redirect, render_template, request, send_file, url_for

from . import db as dbm
from .exporters import export_csv, export_xlsx, sync_google_sheet
from .profile import load_profile, parse_profile
from .report import channel_status, collect_report, deliver_report, render_email
from .scanner import rescore_all, run_scan
from .scoring import CATEGORIES, score_item
from .settings import PROFILE_PATH, REPORT_DIR, env
from .sources import FETCHERS, Item

app = Flask(__name__)
app.secret_key = env("FLASK_SECRET") or secrets.token_hex(16)

_scan = {"running": False, "last": None, "error": None}
_scan_lock = threading.Lock()


def start_scan(source_ids=None) -> bool:
    with _scan_lock:
        if _scan["running"]:
            return False
        _scan["running"] = True

    def work():
        try:
            _scan["last"] = run_scan(source_ids=source_ids, log=lambda msg: None)
            _scan["error"] = None
        except Exception as exc:
            _scan["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            _scan["running"] = False

    threading.Thread(target=work, daemon=True).start()
    return True


@app.context_processor
def inject_globals():
    return {
        "scan_running": _scan["running"],
        "scan_error": _scan["error"],
        "STATUSES": dbm.STATUSES,
        "STATUS_FA": dbm.STATUS_FA,
    }


@app.template_filter("fmt_dt")
def fmt_dt(value):
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(str(value)).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(value)[:16]


@app.template_filter("score_class")
def score_class(score):
    min_score = load_profile().min_score
    score = score or 0
    return "hi" if score >= min_score else "mid" if score >= min_score - 20 else "lo"


def _back(default="index"):
    target = request.form.get("next") or ""
    safe = target.startswith("/") and not target.startswith("//")
    return redirect(target if safe else url_for(default))


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------------ dashboard
@app.route("/")
def index():
    profile = load_profile()
    f = {
        "q": request.args.get("q", "").strip(),
        "status": request.args.get("status", "active"),
        "category": request.args.get("category", ""),
        "source": request.args.get("source", ""),
        "min_score": _int(request.args.get("min_score"), 30),
        "sort": request.args.get("sort", "score"),
    }
    page = max(1, _int(request.args.get("page"), 1))
    per_page = 40

    where, params = ["score >= ?"], [f["min_score"]]
    if f["status"] == "active":
        where.append("status NOT IN (?,?)")
        params += list(dbm.CLOSED)
    elif f["status"] != "all":
        where.append("status = ?")
        params.append(f["status"])
    if f["category"]:
        where.append("category = ?")
        params.append(f["category"])
    if f["source"]:
        where.append("source = ?")
        params.append(f["source"])
    if f["q"]:
        where.append("(title LIKE ? OR company LIKE ? OR description LIKE ? OR notes LIKE ?)")
        params += [f"%{f['q']}%"] * 4
    order = "found_at DESC, score DESC" if f["sort"] == "new" else "score DESC, found_at DESC"
    clause = " AND ".join(where)

    with dbm.get_db() as con:
        total = con.execute(f"SELECT COUNT(*) FROM opportunities WHERE {clause}", params).fetchone()[0]
        rows = con.execute(
            f"SELECT * FROM opportunities WHERE {clause} ORDER BY {order} LIMIT ? OFFSET ?",
            params + [per_page, (page - 1) * per_page],
        ).fetchall()
        stats = dbm.stats(con, profile.min_score)
        sources = [r[0] for r in con.execute("SELECT DISTINCT source FROM opportunities ORDER BY 1")]
        last_scan = con.execute("SELECT * FROM scans ORDER BY id DESC LIMIT 1").fetchone()

    def page_url(p):
        args = request.args.to_dict()
        args["page"] = p
        return url_for("index", **args)

    return render_template(
        "index.html",
        opps=[dbm.opp_dict(r) for r in rows],
        total=total,
        page=page,
        pages=max(1, (total + per_page - 1) // per_page),
        page_url=page_url,
        f=f,
        stats=stats,
        profile=profile,
        categories=CATEGORIES,
        sources=sources,
        last_scan=dict(last_scan) if last_scan else None,
    )


@app.post("/scan")
def scan():
    if start_scan():
        flash("اسکن شروع شد؛ معمولا کمتر از یک دقیقه طول می‌کشد.", "ok")
    else:
        flash("یک اسکن در حال اجراست.", "warn")
    return redirect(url_for("index"))


@app.route("/opp/<int:oid>")
def detail(oid):
    with dbm.get_db() as con:
        row = con.execute("SELECT * FROM opportunities WHERE id=?", (oid,)).fetchone()
    if row is None:
        abort(404)
    return render_template("detail.html", o=dbm.opp_dict(row))


@app.post("/opp/<int:oid>/status")
def set_status(oid):
    status = request.form.get("status")
    if status not in dbm.STATUSES:
        abort(400)
    with dbm.get_db() as con:
        con.execute("UPDATE opportunities SET status=?, updated_at=? WHERE id=?", (status, dbm.now_iso(), oid))
        con.commit()
    return _back()


@app.post("/opp/<int:oid>/notes")
def set_notes(oid):
    with dbm.get_db() as con:
        con.execute(
            "UPDATE opportunities SET notes=?, updated_at=? WHERE id=?",
            (request.form.get("notes", "").strip(), dbm.now_iso(), oid),
        )
        con.commit()
    flash("یادداشت ذخیره شد.", "ok")
    return redirect(url_for("detail", oid=oid))


@app.post("/opp/<int:oid>/delete")
def delete_opp(oid):
    with dbm.get_db() as con:
        con.execute("DELETE FROM opportunities WHERE id=?", (oid,))
        con.commit()
    flash("فرصت حذف شد.", "ok")
    return redirect(url_for("index"))


# ------------------------------------------------------------- manual / import
@app.route("/add", methods=["GET", "POST"])
def add():
    if request.method == "POST":
        form = request.form
        title = form.get("title", "").strip()
        if not title:
            flash("عنوان لازم است.", "error")
            return render_template("add.html", form=form)
        item = Item(
            title=title,
            company=form.get("company", "").strip(),
            url=form.get("url", "").strip(),
            location=form.get("location", "").strip(),
            job_type=form.get("job_type", "").strip(),
            salary=form.get("salary", "").strip(),
            description=form.get("description", "").strip(),
            posted_at=dbm.now_iso(),
            source=form.get("source", "").strip() or "Manual",
            source_type="manual",
            external_id=f"manual-{secrets.token_hex(8)}",
        )
        result = score_item(item, load_profile())
        with dbm.get_db() as con:
            status = form.get("status") if form.get("status") in dbm.STATUSES else "New"
            oid = dbm.insert_opportunity(con, item, result, status=status,
                                         notes=form.get("notes", "").strip())
            con.commit()
        flash(f"اضافه شد — امتیاز {result.score}%", "ok")
        return redirect(url_for("detail", oid=oid))
    return render_template("add.html", form={})


@app.post("/import")
def import_csv():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        flash("فایل CSV انتخاب نشده.", "error")
        return redirect(url_for("add"))
    text = upload.read().decode("utf-8-sig", errors="replace")
    profile = load_profile()
    added = skipped = 0
    with dbm.get_db() as con:
        for raw in csv.DictReader(io.StringIO(text)):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
            if not row.get("title"):
                skipped += 1
                continue
            item = Item(
                title=row["title"], company=row.get("company", ""), url=row.get("url", ""),
                location=row.get("location", ""), description=row.get("description", ""),
                job_type=row.get("type", ""), salary=row.get("salary", ""), posted_at=dbm.now_iso(),
                source=row.get("source") or "CSV import", source_type="import",
                external_id=row.get("url") or f"{row['title']}|{row.get('company', '')}",
            )
            if dbm.insert_opportunity(con, item, score_item(item, profile), notes=row.get("notes", "")):
                added += 1
            else:
                skipped += 1
        con.commit()
    flash(f"{added} فرصت وارد شد، {skipped} مورد تکراری/نامعتبر رد شد.", "ok")
    return redirect(url_for("index", sort="new"))


# ---------------------------------------------------------------------- sources
@app.route("/sources", methods=["GET", "POST"])
def sources_page():
    with dbm.get_db() as con:
        if request.method == "POST":
            stype = request.form.get("type", "")
            if stype not in FETCHERS:
                flash("نوع منبع نامعتبر است.", "error")
            else:
                target = request.form.get("target", "").strip()
                if FETCHERS[stype].needs_target and not target:
                    flash("برای این نوع منبع، مقدار (Target) لازم است.", "error")
                else:
                    name = request.form.get("name", "").strip() or f"{FETCHERS[stype].label} — {target}"
                    con.execute("INSERT INTO sources(name, type, target, enabled) VALUES (?,?,?,1)", (name, stype, target))
                    con.commit()
                    flash("منبع اضافه شد. با دکمه‌ی «تست» همین الان امتحانش کنید.", "ok")
            return redirect(url_for("sources_page"))
        rows = [dict(r) for r in con.execute("SELECT * FROM sources ORDER BY enabled DESC, id")]
    return render_template("sources.html", sources=rows, fetchers=FETCHERS)


@app.post("/sources/<int:sid>/toggle")
def toggle_source(sid):
    with dbm.get_db() as con:
        con.execute("UPDATE sources SET enabled = 1 - enabled WHERE id=?", (sid,))
        con.commit()
    return redirect(url_for("sources_page"))


@app.post("/sources/<int:sid>/delete")
def delete_source(sid):
    with dbm.get_db() as con:
        con.execute("DELETE FROM sources WHERE id=?", (sid,))
        con.commit()
    flash("منبع حذف شد.", "ok")
    return redirect(url_for("sources_page"))


@app.post("/sources/<int:sid>/scan")
def scan_source(sid):
    flash("تست منبع شروع شد؛ چند ثانیه بعد صفحه را تازه کنید." if start_scan([sid]) else "یک اسکن در حال اجراست.",
          "ok")
    return redirect(url_for("sources_page"))


# ---------------------------------------------------------------------- profile
@app.route("/profile", methods=["GET", "POST"])
def profile_page():
    if request.method == "POST":
        text = request.form.get("yaml", "")
        try:
            parse_profile(yaml.safe_load(text) or {})
        except Exception as exc:
            flash(f"خطا در پروفایل: {exc}", "error")
            return render_template("profile.html", text=text, profile=load_profile())
        PROFILE_PATH.write_text(text, encoding="utf-8")
        if request.form.get("rescore"):
            flash(f"پروفایل ذخیره شد و {rescore_all()} فرصت دوباره امتیازدهی شد.", "ok")
        else:
            flash("پروفایل ذخیره شد.", "ok")
        return redirect(url_for("profile_page"))
    text = PROFILE_PATH.read_text(encoding="utf-8") if PROFILE_PATH.exists() else ""
    return render_template("profile.html", text=text, profile=load_profile())


@app.post("/rescore")
def rescore():
    flash(f"{rescore_all()} فرصت دوباره امتیازدهی شد.", "ok")
    return redirect(url_for("index"))


# ----------------------------------------------------------------------- report
@app.route("/report")
def report_page():
    include_all = request.args.get("all") == "1"
    with dbm.get_db() as con:
        rep = collect_report(con, load_profile(), include_reported=include_all)
    return render_template("report.html", rep=rep, email_html=render_email(rep), channels=channel_status(),
                           include_all=include_all)


@app.post("/report/send")
def report_send():
    out = deliver_report()
    parts = [f"{k}: {v}" for k, v in out["results"].items()] or ["هیچ کانالی ارسال نشد"]
    flash(f"{out['matches']} فرصت — " + " | ".join(parts), "ok")
    return redirect(url_for("report_page"))


@app.post("/report/sheet")
def report_sheet():
    try:
        with dbm.get_db() as con:
            result = sync_google_sheet(con, load_profile().min_score)
        flash(f"Google Sheet: {result}", "ok")
    except Exception as exc:
        flash(f"Google Sheet خطا: {type(exc).__name__}: {exc}", "error")
    return redirect(url_for("report_page"))


@app.route("/export.<fmt>")
def export(fmt):
    with dbm.get_db() as con:
        rows = con.execute("SELECT * FROM opportunities ORDER BY score DESC").fetchall()
    stamp = datetime.now().strftime("%Y-%m-%d")
    if fmt == "xlsx":
        path = export_xlsx(REPORT_DIR / f"opportunities-{stamp}.xlsx", {"Opportunities": rows})
    elif fmt == "csv":
        path = export_csv(REPORT_DIR / f"opportunities-{stamp}.csv", rows)
    else:
        abort(404)
    return send_file(path, as_attachment=True)


def main(host: str = "127.0.0.1", port: int = 3000, open_browser: bool = True) -> None:
    dbm.init_db()
    url = f"http://{host}:{port}"
    print(f"Personal Opportunity Radar → {url}")
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
