#!/bin/bash
# 双击启动 AI 建站工作台（Mac）。放在工作台文件夹（brain）里；想放桌面就给它做“替身”（右键 → 制作替身）再拖过去。
BRAIN="$(cd "$(dirname "$0")" && pwd)"
say_box() { /usr/bin/osascript -e "display dialog \"$1\" buttons {\"好\"} default button 1 with title \"建站工作台\"" >/dev/null 2>&1; }

if [ ! -f "$BRAIN/product/app/start.py" ]; then
  echo "找不到工作台：$BRAIN"
  say_box "这个文件要放在工作台文件夹（brain）里才能用。"
  read -r -p "按回车关闭窗口" _; exit 1
fi
cd "$BRAIN" || exit 1

# Mac 自带的 python3 第一次用时会提示安装“命令行开发者工具”，装完再双击一次即可
if ! /usr/bin/env python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >/dev/null 2>&1; then
  echo "这台 Mac 还没有可用的 Python 3（需要 3.9 或更新）。"
  say_box "还没有可用的 Python 3。接下来会弹出“安装命令行开发者工具”，点“安装”，装完后再双击这个图标。"
  xcode-select --install >/dev/null 2>&1
  read -r -p "装好后按回车关闭窗口，再重新双击启动" _; exit 1
fi

# 用一个独立的 Python 环境（~/.aisite/venv），不碰系统 Python，也避开 Homebrew 的“禁止安装”限制
VENV="$HOME/.aisite/venv"
if [ ! -x "$VENV/bin/python3" ]; then
  echo "第一次启动：正在准备独立环境（约半分钟）……"
  mkdir -p "$HOME/.aisite" && python3 -m venv "$VENV" || { echo "建独立环境失败"; read -r -p "按回车关闭窗口" _; exit 1; }
fi
echo "正在启动建站工作台……（第一次会自动安装两个小依赖，稍等）"
echo "用完关掉这个窗口就会停止工作台。"
"$VENV/bin/python3" product/app/start.py --setup
code=$?
if [ $code -ne 0 ]; then
  echo ""
  echo "工作台没能启动（代码 ${code}）。把上面的文字截图发给 Claude 就能排查。"
  read -r -p "按回车关闭窗口" _
fi
