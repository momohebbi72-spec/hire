/**
 * Personal Opportunity Radar → Google Sheet (no Google Cloud project needed)
 *
 * 1. Open your Google Sheet → Extensions → Apps Script → paste this file.
 * 2. Change SECRET below to a random string.
 * 3. Deploy → New deployment → type "Web app"
 *      Execute as: Me   ·   Who has access: Anyone
 * 4. Copy the Web app URL into GOOGLE_SHEET_WEBHOOK_URL and the secret into
 *    GOOGLE_SHEET_WEBHOOK_SECRET (.env on the Mac and GitHub Secrets).
 *
 * New rows are appended; rows already in the sheet (same ID) are skipped, so
 * the Status / Notes you type in the sheet are never overwritten.
 */
const SECRET = 'change-me';

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    if (body.secret !== SECRET) return out({ ok: false, error: 'bad secret' });
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const name = body.sheet || 'Opportunities';
    const sh = ss.getSheetByName(name) || ss.insertSheet(name);
    if (sh.getLastRow() === 0) {
      sh.appendRow(body.header);
      sh.getRange(1, 1, 1, body.header.length).setFontWeight('bold').setBackground('#4f46e5').setFontColor('#ffffff');
      sh.setFrozenRows(1);
      sh.setRightToLeft(false);
    }
    const last = sh.getLastRow();
    const ids = new Set(last > 1 ? sh.getRange(2, 1, last - 1, 1).getValues().map(r => String(r[0])) : []);
    const rows = (body.rows || []).filter(r => !ids.has(String(r[0])));
    if (rows.length) sh.getRange(sh.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows);
    return out({ ok: true, added: rows.length });
  } catch (err) {
    return out({ ok: false, error: String(err) });
  }
}

function out(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
