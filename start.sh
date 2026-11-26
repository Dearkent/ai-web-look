#!/bin/sh
# Linux：在终端运行 sh start.sh。Mac 请双击“启动建站工作台.command”（Mac 双击 .sh 只会用文本编辑打开）
cd "$(dirname "$0")" && exec python3 product/app/start.py --setup "$@"
