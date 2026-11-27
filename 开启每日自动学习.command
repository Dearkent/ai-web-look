#!/bin/bash
# 双击：每天凌晨 3:17 自动学习一次（电脑开着时）。再双击一次可以选择关掉。
BRAIN="$(cd "$(dirname "$0")" && pwd)"
cd "$BRAIN" || exit 1
PY="$HOME/.aisite/venv/bin/python3"; [ -x "$PY" ] || PY="python3"
if [ -f "$HOME/Library/LaunchAgents/com.aisite.autolearn.plist" ]; then
  read -r -p "已经开着每日自动学习。要关掉吗？(y/N) " a
  if [ "$a" = "y" ] || [ "$a" = "Y" ]; then "$PY" brain.py autolearn --uninstall-schedule; fi
else
  "$PY" brain.py autolearn --install-schedule --at 03:17
fi
read -r -p "按回车关闭窗口" _
