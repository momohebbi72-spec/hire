#!/bin/bash
# دابل‌کلیک روی مک: نصب (بار اول) و اجرای داشبورد روی http://127.0.0.1:3000
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "نصب اولیه..."
  python3 -m venv .venv || exit 1
fi
.venv/bin/python -m pip install -q --upgrade pip >/dev/null 2>&1
.venv/bin/python -m pip install -q -r requirements.txt || exit 1
[ -f .env ] || cp .env.example .env
exec .venv/bin/python -m radar serve
