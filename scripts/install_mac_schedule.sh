#!/bin/bash
# اجرای خودکار ساعتی روی مک (launchd) — حتی وقتی داشبورد بسته است.
# هر ساعت: دریافت نتایج GitHub → اسکن منابع ایرانی موعددار → ارسال به GitHub.
#   نصب:  ./scripts/install_mac_schedule.sh
#   حذف:  ./scripts/install_mac_schedule.sh uninstall
set -e
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
LABEL="com.opportunity-radar.tick"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ "$1" = "uninstall" ]; then
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "✓ اجرای خودکار حذف شد."
  exit 0
fi

PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || python3 -m venv .venv
"$PY" -m pip install -q -r requirements.txt
mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/data"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>ProgramArguments</key>
  <array><string>$PY</string><string>-m</string><string>radar</string><string>tick</string></array>
  <key>StartInterval</key><integer>3600</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$ROOT/data/tick.log</string>
  <key>StandardErrorPath</key><string>$ROOT/data/tick.log</string>
</dict>
</plist>
PLIST

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "✓ هر ساعت اجرا می‌شود. لاگ: $ROOT/data/tick.log"
