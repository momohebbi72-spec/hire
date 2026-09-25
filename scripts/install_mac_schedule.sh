#!/bin/bash
# اجرای خودکار روزانه روی مک (launchd).  استفاده:  ./scripts/install_mac_schedule.sh 9 0   (ساعت ۹:۰۰)
# حذف:  launchctl unload ~/Library/LaunchAgents/com.opportunity-radar.daily.plist && rm ~/Library/LaunchAgents/com.opportunity-radar.daily.plist
set -e
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
HOUR="${1:-9}"
MINUTE="${2:-0}"
PY="$ROOT/.venv/bin/python"

if [ ! -x "$PY" ]; then
  python3 -m venv .venv
fi
"$PY" -m pip install -q -r requirements.txt

LABEL="com.opportunity-radar.daily"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/data"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>ProgramArguments</key>
  <array><string>$PY</string><string>-m</string><string>radar</string><string>daily</string></array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>$HOUR</integer><key>Minute</key><integer>$MINUTE</integer></dict>
  <key>StandardOutPath</key><string>$ROOT/data/daily.log</string>
  <key>StandardErrorPath</key><string>$ROOT/data/daily.log</string>
</dict>
</plist>
PLIST

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "✓ هر روز ساعت $HOUR:$(printf '%02d' "$MINUTE") اسکن + گزارش اجرا می‌شود. لاگ: $ROOT/data/daily.log"
