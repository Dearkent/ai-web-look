#!/bin/sh
# macOS / Linux：双击或在终端运行 sh start.sh
cd "$(dirname "$0")" && exec python3 product/app/start.py --setup "$@"
