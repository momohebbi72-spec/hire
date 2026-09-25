"""Local dashboard (personal CRM) — http://127.0.0.1:3000"""
from __future__ import annotations

import csv
import io
import secrets
import threading
import webbrowser
from datetime import datetime, timedelta, timezone

import yaml
from flask import Flask, abort, flash, redirect, render_template, request, send_file, url_for

from . import db as dbm
from . import sync
from .ai import get_provider
from .config_store import (FREQUENCIES, effective_runner, load_settings, load_sources, read_profile_data,
                           read_profile_text, save_settings, save_sources, slugify, write_profile_data,
                           write_profile_text)
from .exporters import export_csv, export_xlsx, sync_google_sheet
from .profile import load_profile, parse_profile
from .report import channel_status, collect_report, deliver_report, render_email
from .scanner import rescore_all, run_scan
from .scheduler import BackgroundScheduler, tick
from .scoring import CATEGORIES, OPP_TYPES, REMOTE_TYPES, score_item
from .settings import REPORT_DIR, env, runner
from .sources import FETCHERS, GROUPS, Item, SourceConfig
from .sources.websearch import backend_name

app = Flask(__name__)
app.secret_key = env("FLASK_SECRET") or secrets.token_hex(16)
scheduler = BackgroundScheduler()

_job = {"running": False, "label": "", "error": None}
_job_lock = threading.Lock()


def run_background(label: str, fn, *args) -> bool:
    with _job_lock:
        if _job["running"]:
            return False
        _job.update(running=True, label=label, error=None)

    def work():
        try:
            fn(*args)
        except Exception as exc:
            _job["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            _job["running"] = False

    threading.Thread(target=work, daemon=True).start()
    return True


def push_config_async() -> None:
    if sync.configured():
        threading.Thread(target=lambda: _quiet(sync.push_config), daemon=True).start()


def _quiet(fn):
    try:
        return fn()
    except Exception as exc:  # shown on the settings page via last_sync_error
        with dbm.get_db() as con:
            dbm.set_setting(con, "last_sync_error", f"{type(exc).__name__}: {exc}"[:300])


@app.context_processor
def inject_globals():
    return {"job": _job, "STATUSES": dbm.STATUSES, "STATUS_FA": dbm.STATUS_FA, "RUNNER": runner()}


@app.template_filter("fmt_dt")
def fmt_dt(value):
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(str(value)).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(value)[:16]


@app.template_filter("ago")
def ago(value):
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    mins = int((datetime.now(timezone.utc) - dt).total_seconds() // 60)
    if mins < 60:
        return f"{max(mins, 0)} دقیقه پیش"
    if mins < 1440:
        return f"{mins // 60} ساعت پیش"
    return f"{mins // 1440} روز پیش"


@app.template_filter("score_class")
def score_class(score):
    min_score = load_profile().min_score
    score = score or 0
    return "hi" if score >= min_score else "mid" if score >= min_score - 20 else "lo"


def _back(default="feed"):
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
def dashboard():
    profile = load_profile()
    with dbm.get_db() as con:
        stats = dbm.stats(con, profile.min_score)
        top = [dbm.opp_dict(r) for r in con.execute(
            "SELECT * FROM opportunities WHERE status NOT IN (?,?) AND score >= ? ORDER BY found_at DESC, score DESC LIMIT 6",
            (*dbm.CLOSED, profile.min_score))]
        last_scan = con.execute("SELECT * FROM scans ORDER BY id DESC LIMIT 1").fetchone()
        errors = con.execute("SELECT COUNT(*) FROM sources WHERE enabled=1 AND last_error IS NOT NULL").fetchone()[0]
        discovered = con.execute("SELECT COUNT(*) FROM discovered_sites WHERE dismissed=0").fetchone()[0]
        last_report = con.execute("SELECT * FROM email_logs ORDER BY id DESC LIMIT 1").fetchone()
    return render_template("dashboard.html", stats=stats, top=top, profile=profile,
                           last_scan=dict(last_scan) if last_scan else None, errors=errors,
                           discovered=discovered, last_report=dict(last_report) if last_report else None,
                           channels=channel_status(), synced=sync.configured())


@app.post("/scan")
def scan():
    ok = run_background("اسکن همه‌ی منابع فعال", lambda: run_scan(log=lambda m: None))
    flash("اسکن شروع شد؛ معمولا ۱ تا ۳ دقیقه طول می‌کشد." if ok else "یک کار در حال اجراست.", "ok" if ok else "warn")
    return redirect(request.referrer or url_for("dashboard"))


@app.post("/tick")
def tick_now():
    ok = run_background("اجرای کامل (همگام‌سازی + اسکن + گزارش)", lambda: tick(force=True, log=lambda m: None))
    flash("اجرای کامل شروع شد." if ok else "یک کار در حال اجراست.", "ok" if ok else "warn")
    return redirect(request.referrer or url_for("dashboard"))


# ------------------------------------------------------------ opportunity feed
@app.route("/opportunities")
def feed():
    profile = load_profile()
    a = request.args
    f = {
        "q": a.get("q", "").strip(), "status": a.get("status", "active"), "category": a.get("category", ""),
        "source": a.get("source", ""), "min_score": _int(a.get("min_score"), 30), "days": a.get("days", ""),
        "location": a.get("location", "").strip(), "remote": a.get("remote", ""), "type": a.get("type", ""),
        "sort": a.get("sort", "score"),
    }
    page = max(1, _int(a.get("page"), 1))
    per_page = 30

    where, params = ["score >= ?"], [f["min_score"]]
    if f["status"] == "active":
        where.append("status NOT IN (?,?)")
        params += list(dbm.CLOSED)
    elif f["status"] != "all":
        where.append("status = ?")
        params.append(f["status"])
    for key, col in (("category", "category"), ("source", "source"), ("remote", "remote_type"), ("type", "opp_type")):
        if f[key]:
            where.append(f"{col} = ?")
            params.append(f[key])
    if f["days"].isdigit():
        since = (datetime.now(timezone.utc) - timedelta(days=int(f["days"]))).isoformat(timespec="seconds")
        where.append("found_at >= ?")
        params.append(since)
    if f["location"]:
        where.append("location LIKE ?")
        params.append(f"%{f['location']}%")
    if f["q"]:
        where.append("(title LIKE ? OR company LIKE ? OR description LIKE ? OR notes LIKE ?)")
        params += [f"%{f['q']}%"] * 4
    order = "found_at DESC, score DESC" if f["sort"] == "new" else "score DESC, found_at DESC"
    clause = " AND ".join(where)

    with dbm.get_db() as con:
        total = con.execute(f"SELECT COUNT(*) FROM opportunities WHERE {clause}", params).fetchone()[0]
        rows = con.execute(f"SELECT * FROM opportunities WHERE {clause} ORDER BY {order} LIMIT ? OFFSET ?",
                           params + [per_page, (page - 1) * per_page]).fetchall()
        sources = [r[0] for r in con.execute("SELECT DISTINCT source FROM opportunities ORDER BY 1")]

    def page_url(p):
        args = request.args.to_dict()
        args["page"] = p
        return url_for("feed", **args)

    return render_template("feed.html", opps=[dbm.opp_dict(r) for r in rows], total=total, page=page,
                           pages=max(1, (total + per_page - 1) // per_page), page_url=page_url, f=f,
                           profile=profile, categories=CATEGORIES, sources=sources, remote_types=REMOTE_TYPES,
                           opp_types=OPP_TYPES)


@app.route("/opp/<int:oid>")
def detail(oid):
    profile = load_profile()
    with dbm.get_db() as con:
        row = con.execute("SELECT * FROM opportunities WHERE id=?", (oid,)).fetchone()
        if row is None:
            abort(404)
        match = con.execute("SELECT * FROM matches WHERE opportunity_id=?", (oid,)).fetchone()
        history = con.execute("SELECT * FROM status_history WHERE opportunity_id=? ORDER BY id DESC", (oid,)).fetchall()
    o = dbm.opp_dict(row)
    analysis = get_provider().analyze_opportunity(o, profile)
    return render_template("detail.html", o=o, match=dict(match) if match else None, history=history,
                           analysis=analysis)


@app.post("/opp/<int:oid>/status")
def set_status(oid):
    status = request.form.get("status")
    if status not in dbm.STATUSES:
        abort(400)
    with dbm.get_db() as con:
        dbm.set_status(con, oid, status)
    return _back()


@app.post("/opp/<int:oid>/notes")
def set_notes(oid):
    with dbm.get_db() as con:
        con.execute("UPDATE opportunities SET notes=?, updated_at=? WHERE id=?",
                    (request.form.get("notes", "").strip(), dbm.now_iso(), oid))
        con.commit()
    flash("یادداشت ذخیره شد.", "ok")
    return _back()


@app.post("/opp/<int:oid>/delete")
def delete_opp(oid):
    with dbm.get_db() as con:
        con.execute("DELETE FROM opportunities WHERE id=?", (oid,))
        con.commit()
    flash("فرصت حذف شد.", "ok")
    return redirect(url_for("feed"))


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
            title=title, company=form.get("company", "").strip(), url=form.get("url", "").strip(),
            location=form.get("location", "").strip(), job_type=form.get("job_type", "").strip(),
            salary=form.get("salary", "").strip(), description=form.get("description", "").strip(),
            posted_at=dbm.now_iso(), source=form.get("source", "").strip() or "Manual", source_type="manual",
            external_id=f"manual-{secrets.token_hex(8)}",
        )
        result = score_item(item, load_profile())
        status = form.get("status") if form.get("status") in dbm.STATUSES else "New"
        with dbm.get_db() as con:
            _, oid = dbm.upsert_opportunity(con, item, result, source_id="manual", status=status,
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
    added = merged = skipped = 0
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
            kind, _ = dbm.upsert_opportunity(con, item, score_item(item, profile), source_id="import",
                                             notes=row.get("notes", ""))
            added += kind == "new"
            merged += kind == "updated"
        con.commit()
    flash(f"{added} فرصت جدید وارد شد، {merged} تکراری ادغام شد، {skipped} ردیف نامعتبر.", "ok")
    return redirect(url_for("feed", sort="new"))


# ---------------------------------------------------------------------- sources
def _source_from_form(form, existing_id: str = "") -> SourceConfig:
    stype = form.get("type", "")
    target = form.get("target", "").strip()
    name = form.get("name", "").strip() or f"{FETCHERS[stype].label} {target}".strip()
    keywords = [k.strip() for k in form.get("keywords", "").replace("،", ",").replace("\n", ",").split(",") if k.strip()]
    return SourceConfig(
        id=existing_id or slugify(name), name=name, type=stype, target=target, keywords=keywords,
        frequency_hours=_int(form.get("frequency_hours"), 24), enabled=form.get("enabled", "1") == "1",
        runner=form.get("runner", "") if form.get("runner") in ("local", "cloud", "both") else "",
    )


@app.route("/sources", methods=["GET", "POST"])
def sources_page():
    sources = load_sources()
    if request.method == "POST":
        stype = request.form.get("type", "")
        if stype not in FETCHERS:
            flash("نوع منبع نامعتبر است.", "error")
        elif FETCHERS[stype].needs_target and not request.form.get("target", "").strip():
            flash(f"«{FETCHERS[stype].target_label}» برای این نوع منبع لازم است.", "error")
        else:
            src = _source_from_form(request.form)
            ids = {s.id for s in sources}
            while src.id in ids:
                src.id += "-2"
            sources.append(src)
            save_sources(sources)
            push_config_async()
            flash("منبع اضافه شد. با «تست» همین الان امتحانش کنید.", "ok")
        return redirect(url_for("sources_page"))

    with dbm.get_db() as con:
        dbm.sync_sources(con, sources)
        runtime = dbm.source_runtime(con)
        discovered = [dict(r) for r in con.execute(
            "SELECT * FROM discovered_sites WHERE dismissed=0 ORDER BY hits DESC, last_seen DESC LIMIT 30")]
    known = " ".join(f"{s.target} {s.type}" for s in sources).lower()
    discovered = [d for d in discovered if d["domain"].split(".")[0] not in known]
    groups = {}
    for key, st in FETCHERS.items():
        groups.setdefault(st.group, []).append(st)
    return render_template("sources.html", sources=sources, runtime=runtime, fetchers=FETCHERS, groups=groups,
                           group_names=GROUPS, frequencies=FREQUENCIES, discovered=discovered,
                           effective_runner=effective_runner, search_backend=backend_name(), synced=sync.configured())


@app.route("/sources/<sid>/edit", methods=["GET", "POST"])
def edit_source(sid):
    sources = load_sources()
    src = next((s for s in sources if s.id == sid), None)
    if src is None:
        abort(404)
    if request.method == "POST":
        if request.form.get("type") not in FETCHERS:
            abort(400)
        updated = _source_from_form(request.form, existing_id=sid)
        sources = [updated if s.id == sid else s for s in sources]
        save_sources(sources)
        push_config_async()
        flash("منبع ذخیره شد.", "ok")
        return redirect(url_for("sources_page"))
    return render_template("source_edit.html", src=src, fetchers=FETCHERS, groups=GROUPS, frequencies=FREQUENCIES)


@app.post("/sources/<sid>/toggle")
def toggle_source(sid):
    sources = load_sources()
    for s in sources:
        if s.id == sid:
            s.enabled = not s.enabled
    save_sources(sources)
    push_config_async()
    return redirect(url_for("sources_page"))


@app.post("/sources/<sid>/delete")
def delete_source(sid):
    save_sources([s for s in load_sources() if s.id != sid])
    push_config_async()
    flash("منبع حذف شد.", "ok")
    return redirect(url_for("sources_page"))


@app.post("/sources/<sid>/scan")
def scan_source(sid):
    ok = run_background("تست منبع", lambda: run_scan(source_ids=[sid], log=lambda m: None))
    flash("تست منبع شروع شد؛ چند ثانیه بعد صفحه را تازه کنید." if ok else "یک کار در حال اجراست.", "ok")
    return redirect(url_for("sources_page"))


@app.post("/discovered/<domain>/<action>")
def discovered_action(domain, action):
    with dbm.get_db() as con:
        row = con.execute("SELECT * FROM discovered_sites WHERE domain=?", (domain,)).fetchone()
        if row is None:
            abort(404)
        con.execute("UPDATE discovered_sites SET dismissed=1 WHERE domain=?", (domain,))
        con.commit()
    if action == "add":
        sources = load_sources()
        sources.append(SourceConfig(id=slugify(domain), name=domain, type="site_search", target=domain,
                                    keywords=["استخدام سئو", "SEO"], frequency_hours=24))
        save_sources(sources)
        push_config_async()
        flash(f"{domain} به‌عنوان «جستجو در سایت» اضافه شد. اگر صفحه‌ی لیست آگهی دارد، نوعش را به «هر صفحه‌ی وب» تغییر دهید.", "ok")
    return redirect(url_for("sources_page"))


# ---------------------------------------------------------------------- profile
_PROFILE_LISTS = [
    ("keywords", "کلمات کلیدی", "هر خط یک کلمه — مثل SEO، سئو، !GEO (علامت ! یعنی حساس به حروف بزرگ)"),
    ("target_roles", "عنوان‌های هدف", "اگر در عنوان آگهی باشند، امتیاز کامل کلمه‌ی کلیدی (۲۵)"),
    ("preferred_locations", "موقعیت‌ها", "Remote, Canada, USA, Europe, Iran, تهران …"),
    ("work_types", "نوع همکاری", "Remote, Freelance, Contract, Full-time, Consulting"),
    ("avoid_locations", "مناطق نامطلوب", "مثلا US citizens only"),
    ("exclude_in_title", "کلمات حذفی در عنوان", "امتیاز صفر می‌گیرند"),
    ("exclude_anywhere", "عبارت‌های حذفی در کل آگهی", "مثل unpaid"),
]


def _weighted_to_text(raw) -> str:
    lines = []
    if isinstance(raw, dict):
        for name, spec in raw.items():
            spec = spec if isinstance(spec, dict) else {"weight": spec}
            aliases = ", ".join(str(a) for a in spec.get("aliases") or [])
            lines.append(f"{name} | {spec.get('weight', 5)}" + (f" | {aliases}" if aliases else ""))
    else:
        lines = [str(x) for x in raw or []]
    return "\n".join(lines)


def _text_to_weighted(text: str, default_weight: int) -> dict:
    out = {}
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if not parts or not parts[0]:
            continue
        weight = _int(parts[1], default_weight) if len(parts) > 1 and parts[1] else default_weight
        aliases = [a.strip() for a in parts[2].split(",") if a.strip()] if len(parts) > 2 else []
        out[parts[0]] = {"weight": weight, "aliases": aliases} if aliases else {"weight": weight}
    return out


@app.route("/profile", methods=["GET", "POST"])
def profile_page():
    if request.method == "POST":
        form = request.form
        try:
            if form.get("mode") == "yaml":
                text = form.get("yaml", "")
                parse_profile(yaml.safe_load(text) or {})
                write_profile_text(text)
            else:
                data = read_profile_data()
                data.update({
                    "name": form.get("name", "").strip(),
                    "min_score": _int(form.get("min_score"), 55),
                    "report_top_n": _int(form.get("report_top_n"), 15),
                    "max_age_days": _int(form.get("max_age_days"), 30),
                    "skills": _text_to_weighted(form.get("skills", ""), 5),
                    "industries": _text_to_weighted(form.get("industries", ""), 1),
                })
                for key, _, _ in _PROFILE_LISTS:
                    data[key] = [x.strip() for x in form.get(key, "").splitlines() if x.strip()]
                parse_profile(data)
                write_profile_data(data)
        except Exception as exc:
            flash(f"خطا در پروفایل: {exc}", "error")
            return redirect(url_for("profile_page"))
        push_config_async()
        if form.get("rescore"):
            flash(f"پروفایل ذخیره شد و {rescore_all()} فرصت دوباره امتیازدهی شد.", "ok")
        else:
            flash("پروفایل ذخیره شد.", "ok")
        return redirect(url_for("profile_page"))

    data = read_profile_data()
    lists = [(key, label, hint, "\n".join(str(x) for x in data.get(key) or [])) for key, label, hint in _PROFILE_LISTS]
    return render_template("profile.html", data=data, lists=lists, skills_text=_weighted_to_text(data.get("skills")),
                           industries_text=_weighted_to_text(data.get("industries")), yaml_text=read_profile_text(),
                           profile=load_profile())


@app.post("/rescore")
def rescore():
    flash(f"{rescore_all()} فرصت دوباره امتیازدهی شد.", "ok")
    return redirect(url_for("feed"))


# --------------------------------------------------------------------- settings
@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    if request.method == "POST":
        form = request.form
        data = load_settings()
        data["timezone"] = form.get("timezone", "Asia/Tehran").strip() or "Asia/Tehran"
        rep = data["report"]
        rep["email_to"] = form.get("email_to", "").strip()
        rep["time"] = form.get("time", "09:30").strip() or "09:30"
        rep["frequency"] = form.get("frequency", "daily")
        rep["weekly_day"] = form.get("weekly_day", "sat")
        rep["sender"] = form.get("sender", "cloud")
        rep["send_empty"] = form.get("send_empty") == "1"
        save_settings(data)
        with dbm.get_db() as con:
            dbm.set_setting(con, "scheduler_enabled", "1" if form.get("scheduler_enabled") == "1" else "0")
        push_config_async()
        flash("تنظیمات ذخیره شد.", "ok")
        return redirect(url_for("settings_page"))
    with dbm.get_db() as con:
        logs = con.execute("SELECT * FROM email_logs ORDER BY id DESC LIMIT 10").fetchall()
        sched = dbm.get_setting(con, "scheduler_enabled", "1") == "1"
        sync_error = dbm.get_setting(con, "last_sync_error", "")
    return render_template("settings.html", s=load_settings(), channels=channel_status(), logs=logs,
                           scheduler_enabled=sched, synced=sync.configured(), repo=sync.repo(),
                           sync_error=sync_error, search_backend=backend_name(),
                           env_email=env("REPORT_EMAIL_TO"))


@app.post("/sync/<action>")
def sync_action(action):
    actions = {"pull": sync.pull_items, "push": sync.push_items, "config-push": sync.push_config,
               "config-pull": sync.pull_config}
    if action not in actions:
        abort(404)
    try:
        result = actions[action]()
        flash(f"GitHub: {result}", "ok")
    except Exception as exc:
        flash(f"GitHub خطا: {type(exc).__name__}: {exc}", "error")
    return redirect(url_for("settings_page"))


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
            flash(f"Google Sheet: {sync_google_sheet(con, load_profile().min_score)}", "ok")
    except Exception as exc:
        flash(f"Google Sheet خطا: {type(exc).__name__}: {exc}", "error")
    return redirect(url_for("report_page"))


@app.route("/export.<fmt>")
def export(fmt):
    with dbm.get_db() as con:
        rows = con.execute("SELECT * FROM opportunities ORDER BY score DESC").fetchall()
    if fmt == "xlsx":
        path = export_xlsx(REPORT_DIR / "opportunity_report.xlsx", {"Opportunities": rows})
    elif fmt == "csv":
        path = export_csv(REPORT_DIR / "opportunity_report.csv", rows)
    else:
        abort(404)
    return send_file(path, as_attachment=True, download_name=path.name)


def main(host: str = "127.0.0.1", port: int = 3000, open_browser: bool = True) -> None:
    dbm.init_db()
    scheduler.start()
    url = f"http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}"
    print(f"Personal Opportunity Radar → {url}")
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
