#!/bin/bash
# دابل‌کلیک روی مک: نصب (بار اول) → اجرای برنامه → باز شدن مرورگر روی http://localhost:3000
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 نصب نیست. از https://www.python.org/downloads/ نصب کنید و دوباره اجرا کنید."
  read -r -p "Enter برای بستن..." _
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "نصب اولیه (فقط بار اول، ۱-۲ دقیقه)..."
  python3 -m venv .venv || exit 1
fi
.venv/bin/python -m pip install -q --upgrade pip >/dev/null 2>&1
.venv/bin/python -m pip install -q -r requirements.txt || { echo "نصب پکیج‌ها ناموفق بود (اینترنت را چک کنید)."; read -r _; exit 1; }
[ -f .env ] || cp .env.example .env
export FLASK_SKIP_DOTENV=1 PYTHONWARNINGS=ignore
exec .venv/bin/python -m radar serve
