"""Daily report: collect matches → Excel → e-mail / Telegram → EmailLogs."""
from __future__ import annotations

import html
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Dict, List

import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import db as dbm
from .config_store import load_settings
from .exporters import export_xlsx, sheet_configured
from .profile import load_profile
from .settings import REPORT_DIR, env
from .textutil import now_iso

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

_jinja = Environment(loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
                     autoescape=select_autoescape(["html"]))
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def local_now() -> datetime:
    tz = load_settings().get("timezone") or "Asia/Tehran"
    try:
        return datetime.now(ZoneInfo(tz)) if ZoneInfo else datetime.now()
    except Exception:
        return datetime.now()


def email_to() -> List[str]:
    raw = load_settings()["report"].get("email_to") or env("REPORT_EMAIL_TO")
    return [x.strip() for x in str(raw).split(",") if x.strip()]


def channel_status() -> Dict[str, bool]:
    return {
        "email": bool(env("SMTP_USER") and env("SMTP_PASSWORD") and email_to()),
        "telegram": bool(env("TELEGRAM_BOT_TOKEN") and env("TELEGRAM_CHAT_ID")),
        "sheet": sheet_configured(),
    }


def report_due(con, now_local: datetime = None) -> bool:
    cfg = load_settings()["report"]
    freq = str(cfg.get("frequency") or "daily").lower()
    if freq == "off":
        return False
    now_local = now_local or local_now()
    try:
        hh, mm = [int(x) for x in str(cfg.get("time") or "09:30").split(":")[:2]]
    except ValueError:
        hh, mm = 9, 30
    if (now_local.hour, now_local.minute) < (hh, mm):
        return False
    if freq == "weekly" and WEEKDAYS[now_local.weekday()] != str(cfg.get("weekly_day") or "sat")[:3].lower():
        return False
    last = con.execute("SELECT MAX(local_date) FROM email_logs WHERE status='sent'").fetchone()[0]
    return last != now_local.date().isoformat()


def collect_report(con, profile, include_reported: bool = False) -> dict:
    where = "score >= ? AND status NOT IN (?,?)"
    if not include_reported:
        where += " AND reported = 0"
    rows = con.execute(
        f"SELECT * FROM opportunities WHERE {where} ORDER BY score DESC, found_at DESC LIMIT 500",
        (profile.min_score, *dbm.CLOSED),
    ).fetchall()
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
    scans = con.execute("SELECT COALESCE(SUM(fetched),0), COALESCE(SUM(new),0) FROM scans WHERE started_at >= ?",
                        (since,)).fetchone()
    stale = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(timespec="seconds")
    followups = con.execute(
        "SELECT * FROM opportunities WHERE status IN ('Contacted','Applied') AND updated_at < ? ORDER BY updated_at LIMIT 5",
        (stale,),
    ).fetchall()
    pipeline = {r[0]: r[1] for r in con.execute("SELECT status, COUNT(*) FROM opportunities GROUP BY status")}
    sheet_id = env("GOOGLE_SHEET_ID")
    return {
        "date": local_now().date().isoformat(),
        "name": profile.name,
        "min_score": profile.min_score,
        "top_n": profile.report_top_n,
        "scanned": scans[0],
        "new": scans[1],
        "items": [dbm.opp_dict(r) for r in rows],
        "followups": [dbm.opp_dict(r) for r in followups],
        "pipeline": pipeline,
        "statuses": dbm.STATUSES,
        "status_fa": dbm.STATUS_FA,
        "sheet_url": env("GOOGLE_SHEET_URL") or (f"https://docs.google.com/spreadsheets/d/{sheet_id}" if sheet_id else ""),
    }


def render_email(rep: dict) -> str:
    return _jinja.get_template("email_report.html").render(rep=rep)


def render_text(rep: dict) -> str:
    lines = [f"Daily Opportunity Radar Report — {rep['date']}",
             f"Today: {rep['scanned']} opportunities scanned · {rep['new']} new · {len(rep['items'])} strong matches", ""]
    if not rep["items"]:
        lines.append("امروز فرصت جدیدِ مناسبی پیدا نشد.")
    lines.append("Top matches:")
    for i, o in enumerate(rep["items"][: rep["top_n"]], 1):
        lines += [f"{i}. {o['title']}", f"   Score: {o['score']}%", f"   Company: {o['company']}",
                  f"   Why: {'  '.join(o['reasons_list'][:6])}", f"   Link: {o['url']}", ""]
    if rep["followups"]:
        lines += ["یادآوری پیگیری:"] + [f"- {o['title']} — {o['company']} ({o['status']})" for o in rep["followups"]]
    return "\n".join(lines)


def render_telegram(rep: dict) -> str:
    esc = html.escape
    parts = [f"📡 <b>Opportunity Radar</b> — {rep['date']}",
             f"امروز {rep['scanned']} فرصت بررسی شد · {rep['new']} جدید · <b>{len(rep['items'])}</b> مناسب", ""]
    for i, o in enumerate(rep["items"][:10], 1):
        link = f' · <a href="{esc(o["url"], quote=True)}">لینک</a>' if o["url"] else ""
        parts.append(f"{i}. <b>{esc(o['title'])}</b> — {esc(o['company'] or '')}\n   امتیاز: {o['score']}%{link}")
    if rep["sheet_url"]:
        parts += ["", f'<a href="{rep["sheet_url"]}">📊 Google Sheet</a>']
    text = "\n".join(parts)
    return text if len(text) < 4000 else text[:3990] + "…"


def send_email(subject: str, html_body: str, text_body: str, attachments: List[Path] = ()) -> str:
    if not channel_status()["email"]:
        return "skipped (not configured)"
    host = env("SMTP_HOST", "smtp.gmail.com")
    port = int(env("SMTP_PORT", "587"))
    user, password = env("SMTP_USER"), env("SMTP_PASSWORD")
    if "gmail" in host:
        password = password.replace(" ", "")  # Gmail app passwords are displayed with spaces
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = env("REPORT_EMAIL_FROM") or user
    msg["To"] = ", ".join(email_to())
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    for path in attachments:
        msg.add_attachment(Path(path).read_bytes(), maintype="application",
                           subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=Path(path).name)
    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls(context=context)
            smtp.login(user, password)
            smtp.send_message(msg)
    return "sent"


def send_telegram(text: str) -> str:
    if not channel_status()["telegram"]:
        return "skipped (not configured)"
    resp = requests.post(f"https://api.telegram.org/bot{env('TELEGRAM_BOT_TOKEN')}/sendMessage", timeout=20,
                         json={"chat_id": env("TELEGRAM_CHAT_ID"), "text": text, "parse_mode": "HTML",
                               "disable_web_page_preview": True})
    resp.raise_for_status()
    return "sent"


def _attempt(fn, *args) -> str:
    try:
        return fn(*args)
    except Exception as exc:
        return f"error: {type(exc).__name__}: {exc}"[:300]


def build_excel(con, rep: dict) -> Path:
    all_rows = con.execute("SELECT * FROM opportunities WHERE score > 0 ORDER BY score DESC LIMIT 3000").fetchall()
    return export_xlsx(REPORT_DIR / "opportunity_report.xlsx", {"Today": rep["items"], "All": all_rows})


def deliver_report(mark: bool = True, include_reported: bool = False) -> dict:
    profile = load_profile()
    cfg = load_settings()["report"]
    with dbm.get_db() as con:
        rep = collect_report(con, profile, include_reported)
        xlsx = build_excel(con, rep)
        results: Dict[str, str] = {}
        if rep["items"] or cfg.get("send_empty", True):
            subject = cfg.get("subject") or "Daily Opportunity Radar Report"
            subject = f"{subject} — {len(rep['items'])} matches — {rep['date']}"
            results["email"] = _attempt(send_email, subject, render_email(rep), render_text(rep), [xlsx])
            results["telegram"] = _attempt(send_telegram, render_telegram(rep))
            for channel, status in results.items():
                if status.startswith("skipped"):
                    continue
                con.execute(
                    "INSERT INTO email_logs(sent_at, local_date, channel, recipients, subject, items, status, error) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (now_iso(), local_now().date().isoformat(), channel,
                     ", ".join(email_to()) if channel == "email" else env("TELEGRAM_CHAT_ID"),
                     subject, len(rep["items"]), "sent" if status == "sent" else "error",
                     None if status == "sent" else status),
                )
            con.commit()
        delivered = any(v == "sent" for v in results.values())
        if mark and delivered and rep["items"]:
            con.executemany("UPDATE opportunities SET reported=1 WHERE id=?", [(o["id"],) for o in rep["items"]])
            con.commit()
    return {"matches": len(rep["items"]), "xlsx": str(xlsx), "results": results}
