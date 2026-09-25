#!/bin/bash
# پشتیبان‌گیری از دیتابیس و تنظیمات در پوشه‌ی backups/
cd "$(dirname "$0")/.."
STAMP="$(date +%Y%m%d-%H%M)"
mkdir -p backups
tar -czf "backups/radar-backup-$STAMP.tar.gz" data/radar.db config .env 2>/dev/null || tar -czf "backups/radar-backup-$STAMP.tar.gz" data/radar.db config
echo "✓ backups/radar-backup-$STAMP.tar.gz"
