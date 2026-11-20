#!/bin/bash
# Set up the paper-trading bot on macOS: virtualenv, API key, and a launchd schedule.
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"   # .../ashare_quant
LABEL="com.ashare-quant.daily"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "需要 Python 3.10 或更高版本。请先安装: brew install python"; exit 1
fi

echo "[1/4] 创建虚拟环境并安装依赖 ($PY)"
"$PY" -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install -q --upgrade pip
"$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"

echo "[2/4] 配置 API key"
if [ ! -f "$DIR/.env" ]; then
  read -r -s -p "粘贴你的 Anthropic API key (输入不会显示): " KEY; echo
  ( umask 077; printf 'ANTHROPIC_API_KEY=%s\n' "$KEY" > "$DIR/.env" )
else
  echo "已存在 $DIR/.env, 跳过"
fi

echo "[3/4] 安装定时任务"
# 15:40 Beijing time expressed in this Mac's local time zone.
read -r HOUR MINUTE < <("$DIR/.venv/bin/python" - <<'PYEOF'
import datetime as dt
from zoneinfo import ZoneInfo
t = dt.datetime.now(ZoneInfo("Asia/Shanghai")).replace(hour=15, minute=40).astimezone()
print(t.hour, t.minute)
PYEOF
)
DAYS=""
for d in 1 2 3 4 5 6 7; do  # every day: the bot itself skips non-trading days, and time zones shift weekdays
  DAYS="$DAYS<dict><key>Weekday</key><integer>$d</integer><key>Hour</key><integer>$HOUR</integer><key>Minute</key><integer>$MINUTE</integer></dict>"
done
mkdir -p "$HOME/Library/LaunchAgents" "$DIR/logs"
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$DIR/mac/run_daily.sh</string></array>
  <key>StartCalendarInterval</key><array>$DAYS</array>
  <key>StandardOutPath</key><string>$DIR/logs/launchd.log</string>
  <key>StandardErrorPath</key><string>$DIR/logs/launchd.log</string>
</dict></plist>
PLISTEOF
launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
printf '已安装: 每天本机时间 %02d:%02d (北京时间 15:40) 运行\n' "$HOUR" "$MINUTE"

echo "[4/4] 立即运行一次"
bash "$DIR/mac/run_daily.sh"
tail -n 5 "$DIR/logs/run.log"
echo "日报: $DIR/report.md    日志: $DIR/logs/run.log"
