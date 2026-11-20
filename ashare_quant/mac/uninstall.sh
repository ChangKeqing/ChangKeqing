#!/bin/bash
# Remove the launchd schedule. Account state and logs are kept.
LABEL="com.ashare-quant.daily"
launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "定时任务已移除"
