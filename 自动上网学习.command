#!/bin/bash
# 双击：让大脑自动上网找网站设计来学一次（缺口行业优先；最多收 12 个、跑 20 分钟）。
# 只读版面和颜色，不运行别人的代码、不留原文。学到的规律要试跑通过才会用到生成的网站上。
BRAIN="$(cd "$(dirname "$0")" && pwd)"
cd "$BRAIN" || exit 1
PY="$HOME/.aisite/venv/bin/python3"; [ -x "$PY" ] || PY="python3"
if ! command -v git >/dev/null 2>&1; then
  echo "需要 git 才能读 GitHub 上的模板。接下来会弹出“安装命令行开发者工具”，点“安装”，装完再双击一次。"
  xcode-select --install >/dev/null 2>&1
  read -r -p "按回车关闭窗口" _; exit 1
fi
echo "开始自动学习……（想看它工作：启动工作台后打开 /live 实况页）"
echo ""
"$PY" brain.py autolearn
echo ""
"$PY" brain.py autolearn --status
echo ""
read -r -p "学完了。想每天自动学一次，就双击“开启每日自动学习.command”。按回车关闭窗口" _
