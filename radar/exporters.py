"""Excel / CSV export and Google Sheets sync (Apps Script webhook or service account)."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, Iterable

import requests

from .settings import env, resolve_path
from .textutil import clean_cell

# (db key, header, width)
COLUMNS = [
    ("title", "Title", 45), ("company", "Company", 24), ("source", "Source", 22), ("url", "URL", 40),
    ("category", "Category", 16), ("location", "Location", 22), ("opp_type", "Opportunity Type", 16),
    ("remote_type", "Remote", 10), ("found_at", "Date Found", 18), ("score", "Match Score", 12),
    ("reasons", "Match Reasons", 50), ("status", "Status", 12), ("notes", "Notes", 30),
]


def _value(row: dict, key: str):
    value = row.get(key)
    if key == "reasons":
        try:
            return " | ".join(json.loads(value or "[]"))
        except ValueError:
            return value or ""
    if key in ("found_at", "posted_at") and value:
        return str(value)[:16].replace("T", " ")
    return value if value is not None else ""


def export_xlsx(path: Path, sheets: Dict[str, Iterable]) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    header_fill = PatternFill("solid", fgColor="4F46E5")
    good = PatternFill("solid", fgColor="DCFCE7")
    mid = PatternFill("solid", fgColor="FEF3C7")
    score_col = [k for k, _, _ in COLUMNS].index("score") + 1
    url_col = [k for k, _, _ in COLUMNS].index("url") + 1

    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(title=name[:31])
        ws.append([h for _, h, _ in COLUMNS])
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = header_fill
            cell.alignment = Alignment(vertical="center")
        for raw in rows:
            row = dict(raw)
            ws.append([row.get("score") or 0 if key == "score" else clean_cell(_value(row, key))
                       for key, _, _ in COLUMNS])
            r = ws.max_row
            if row.get("url"):
                link = ws.cell(row=r, column=url_col)
                link.hyperlink = row["url"]
                link.style = "Hyperlink"
            score = row.get("score") or 0
            if score >= 70:
                ws.cell(row=r, column=score_col).fill = good
            elif score >= 50:
                ws.cell(row=r, column=score_col).fill = mid
        for idx, (_, _, width) in enumerate(COLUMNS, start=1):
            ws.column_dimensions[get_column_letter(idx)].width = width
        ws.freeze_panes = "B2"
        ws.auto_filter.ref = ws.dimensions
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def export_csv(path: Path, rows: Iterable) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow([h for _, h, _ in COLUMNS])
        for raw in rows:
            row = dict(raw)
            writer.writerow([_value(row, key) for key, _, _ in COLUMNS])
    return path


# ---------------------------------------------------------------- Google Sheets
SHEET_HEADER = ["ID", "Date Found", "Match Score", "Title", "Company", "Location", "Category", "Opportunity Type",
                "Remote", "Source", "Status", "Notes", "Match Reasons", "Link"]


def sheet_mode() -> str:
    if env("GOOGLE_SHEET_WEBHOOK_URL"):
        return "webhook"
    if env("GOOGLE_SHEET_ID") and (env("GOOGLE_SERVICE_ACCOUNT_JSON") or env("GOOGLE_SERVICE_ACCOUNT_FILE")):
        return "service_account"
    return ""


def sheet_configured() -> bool:
    return bool(sheet_mode())


def _safe(value) -> str:
    text = clean_cell(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


def _sheet_row(row) -> list:
    d = dict(row)
    url = (d.get("url") or "").replace('"', '""')
    return [
        d["uid"][:16], _value(d, "found_at"), d.get("score") or 0, _safe(d.get("title")), _safe(d.get("company")),
        _safe(d.get("location")), d.get("category") or "", d.get("opp_type") or "", d.get("remote_type") or "",
        _safe(d.get("source")), d.get("status") or "", _safe(d.get("notes")), _safe(_value(d, "reasons")),
        f'=HYPERLINK("{url}","Open")' if url else "",
    ]


def sync_google_sheet(con, min_score: int) -> str:
    """Append new opportunities (score >= min_score). Rows you edit in the sheet are never overwritten."""
    mode = sheet_mode()
    if not mode:
        return "skipped (not configured)"
    threshold = int(env("SHEET_MIN_SCORE") or min_score)
    rows = con.execute(
        "SELECT * FROM opportunities WHERE synced=0 AND score>=? ORDER BY score DESC LIMIT 500", (threshold,)
    ).fetchall()
    if not rows:
        return "sent (0 rows)"
    values = [_sheet_row(r) for r in rows]

    if mode == "webhook":
        resp = requests.post(env("GOOGLE_SHEET_WEBHOOK_URL"), timeout=60, json={
            "secret": env("GOOGLE_SHEET_WEBHOOK_SECRET"), "header": SHEET_HEADER,
            "sheet": env("GOOGLE_SHEET_TAB", "Opportunities"), "rows": values,
        })
        resp.raise_for_status()
        try:
            result = resp.json()
        except ValueError:
            raise RuntimeError("Apps Script did not return JSON — check the Web App deployment (Anyone access)")
        if not result.get("ok"):
            raise RuntimeError(f"Apps Script: {result.get('error')}")
        added = result.get("added", len(values))
    else:
        import gspread

        info = env("GOOGLE_SERVICE_ACCOUNT_JSON")
        client = (gspread.service_account_from_dict(json.loads(info)) if info else
                  gspread.service_account(filename=str(resolve_path(env("GOOGLE_SERVICE_ACCOUNT_FILE")))))
        book = client.open_by_key(env("GOOGLE_SHEET_ID"))
        tab = env("GOOGLE_SHEET_TAB", "Opportunities")
        try:
            ws = book.worksheet(tab)
        except gspread.WorksheetNotFound:
            ws = book.add_worksheet(title=tab, rows=1000, cols=len(SHEET_HEADER))
        existing = ws.col_values(1)
        if not existing:
            ws.append_row(SHEET_HEADER, value_input_option="RAW")
        known = set(existing)
        fresh = [v for v in values if v[0] not in known]
        if fresh:
            ws.append_rows(fresh, value_input_option="USER_ENTERED")
        added = len(fresh)

    con.executemany("UPDATE opportunities SET synced=1 WHERE id=?", [(r["id"],) for r in rows])
    con.commit()
    return f"sent ({added} rows)"
