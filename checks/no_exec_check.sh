#!/bin/bash
# L006 固化：只读学习的目录里不应该出现安装过的依赖或构建产物。
# 用法：bash no_exec_check.sh <目录> [<目录> ...]
n=0
for d in "$@"; do
  hits=$(find "$d" -maxdepth 4 -type d \( -name node_modules -o -name .venv -o -name __pypackages__ \) 2>/dev/null)
  if [ -n "$hits" ]; then echo "警告：发现已安装的依赖目录"; echo "$hits"; n=$((n+1)); fi
done
[ $n -eq 0 ] && echo "只读检查通过：没有发现已安装的依赖"
