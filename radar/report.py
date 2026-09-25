"""Daily report: collect matches, render e-mail / Telegram text and deliver."""
from __future__ import annotations

import html
import smtplib
import ssl
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Dict, List, Optional

import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import db as dbm
from .exporters import export_xlsx, sheet_configured, sync_google_sheet
from .profile import load_profile
from .settings import REPORT_DIR, env, env_bool

_jinja = Environment(
    loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
    autoescape=select_autoescape(["html"]),
)


def channel_status() -> Dict[str, bool]:
    return {
        "email": bool(env("SMTP_USER") and env("SMTP_PASSWORD") and env("REPORT_EMAIL_TO")),
        "telegram": bool(env("TELEGRAM_BOT_TOKEN") and env("TELEGRAM_CHAT_ID")),
        "sheet": sheet_configured(),
    }


def collect_report(con, profile, include_reported: bool = False) -> dict:
    today = date.today().isoformat()
    where = "score >= ? AND status NOT IN (?,?)"
    if not include_reported:
        where += " AND reported = 0"
    rows = con.execute(
        f"SELECT * FROM opportunities WHERE {where} ORDER BY score DESC, found_at DESC LIMIT 500",
        (profile.min_score, *dbm.CLOSED),
    ).fetchall()
    scans = con.execute(
        "SELECT COALESCE(SUM(fetched),0), COALESCE(SUM(new),0), COUNT(*) FROM scans WHERE substr(started_at,1,10)=?",
        (today,),
    ).fetchone()
    stale = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(timespec="seconds")
    followups = con.execute(
        "SELECT * FROM opportunities WHERE status IN ('Contacted','Applied') AND updated_at < ? "
        "ORDER BY updated_at LIMIT 5",
        (stale,),
    ).fetchall()
    pipeline = {r[0]: r[1] for r in con.execute("SELECT status, COUNT(*) FROM opportunities GROUP BY status")}
    sheet_id = env("GOOGLE_SHEET_ID")
    return {
        "date": today,
        "name": profile.name,
        "min_score": profile.min_score,
        "top_n": profile.report_top_n,
        "scanned": scans[0],
        "new": scans[1],
        "scan_runs": scans[2],
        "items": [dbm.opp_dict(r) for r in rows],
        "followups": [dbm.opp_dict(r) for r in followups],
        "pipeline": pipeline,
        "statuses": dbm.STATUSES,
        "status_fa": dbm.STATUS_FA,
        "sheet_url": f"https://docs.google.com/spreadsheets/d/{sheet_id}" if sheet_id else "",
    }


def render_email(rep: dict) -> str:
    return _jinja.get_template("email_report.html").render(rep=rep)


def render_text(rep: dict) -> str:
    lines = [
        f"رادار فرصت — {rep['date']}",
        f"امروز {rep['scanned']} فرصت بررسی شد · {rep['new']} جدید · {len(rep['items'])} فرصت مناسب (امتیاز ≥ {rep['min_score']})",
        "",
    ]
    if not rep["items"]:
        lines.append("امروز فرصت جدیدِ مناسبی پیدا نشد.")
    for i, o in enumerate(rep["items"][: rep["top_n"]], 1):
        lines += [
            f"{i}. {o['title']} — {o['company']} ({o['location']})",
            f"   Score: {o['score']}%   {'  '.join(o['reasons_list'][:6])}",
            f"   {o['url']}",
        ]
    if rep["followups"]:
        lines += ["", "یادآوری پیگیری:"] + [f"- {o['title']} — {o['company']} ({o['status']})" for o in rep["followups"]]
    return "\n".join(lines)


def render_telegram(rep: dict) -> str:
    esc = html.escape
    parts = [
        f"📡 <b>رادار فرصت</b> — {rep['date']}",
        f"امروز {rep['scanned']} فرصت بررسی شد · {rep['new']} جدید · <b>{len(rep['items'])}</b> مناسب",
        "",
    ]
    if not rep["items"]:
        parts.append("امروز فرصت جدیدِ مناسبی پیدا نشد.")
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
    user = env("SMTP_USER")
    password = env("SMTP_PASSWORD")
    if "gmail" in host:
        password = password.replace(" ", "")  # Gmail app passwords are shown with spaces
    recipients = [x.strip() for x in env("REPORT_EMAIL_TO").split(",") if x.strip()]

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = env("REPORT_EMAIL_FROM") or user
    msg["To"] = ", ".join(recipients)
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    for path in attachments:
        msg.add_attachment(
            Path(path).read_bytes(),
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=Path(path).name,
        )
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
    resp = requests.post(
        f"https://api.telegram.org/bot{env('TELEGRAM_BOT_TOKEN')}/sendMessage",
        json={"chat_id": env("TELEGRAM_CHAT_ID"), "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=20,
    )
    resp.raise_for_status()
    return "sent"


def _attempt(fn, *args) -> str:
    try:
        return fn(*args)
    except Exception as exc:
        return f"error: {type(exc).__name__}: {exc}"[:300]


def deliver_report(mark: bool = True, include_reported: bool = False, sheet: bool = True) -> dict:
    profile = load_profile()
    with dbm.get_db() as con:
        rep = collect_report(con, profile, include_reported)
        xlsx = REPORT_DIR / f"radar-{rep['date']}.xlsx"
        all_rows = con.execute("SELECT * FROM opportunities WHERE score > 0 ORDER BY score DESC LIMIT 3000").fetchall()
        export_xlsx(xlsx, {"Today": rep["items"], "All": all_rows})

        results: Dict[str, str] = {}
        if rep["items"] or env_bool("REPORT_SEND_EMPTY", True):
            subject = f"رادار فرصت | {len(rep['items'])} فرصت مناسب | {rep['date']}"
            results["email"] = _attempt(send_email, subject, render_email(rep), render_text(rep), [xlsx])
            results["telegram"] = _attempt(send_telegram, render_telegram(rep))
        if sheet:
            results["sheet"] = _attempt(sync_google_sheet, con, profile.min_score)

        delivered = any(results.get(k) == "sent" for k in ("email", "telegram"))
        if mark and delivered and rep["items"]:
            con.executemany("UPDATE opportunities SET reported=1 WHERE id=?", [(o["id"],) for o in rep["items"]])
            con.commit()
    return {"matches": len(rep["items"]), "xlsx": str(xlsx), "results": results}


def preview(include_reported: bool = True) -> Optional[str]:
    with dbm.get_db() as con:
        return render_email(collect_report(con, load_profile(), include_reported))
