#!/bin/bash
# L011 固化：对一批仓库跑许可证扫描，结束时核对条数；缺失的自动单独重跑一次。
# 用法：bash sweep.sh <克隆目录的父目录> <输出文件>
src="$1"; out="$2"; here="$(cd "$(dirname "$0")" && pwd)"
ls -d "$src"/*/ | xargs -P 12 -n 6 python3 "$here/license_scan.py" > "$out"
total=$(ls -d "$src"/*/ | wc -l)
missing=$(comm -23 <(ls -d "$src"/*/ | xargs -n1 basename | sort) <(grep -E $'\t(根目录|错误)\t' "$out" | cut -f1 | sort))
if [ -n "$missing" ]; then
  echo "首轮缺失，单独重跑：$(echo $missing | tr '\n' ' ')"
  for m in $missing; do python3 "$here/license_scan.py" "$src/$m" | grep -v '^汇总' >> "$out"; done
fi
got=$(grep -cE $'\t(根目录|错误)\t' "$out")
err=$(grep -c $'\t错误\t' "$out")
if [ "$got" -eq "$total" ]; then echo "完整：$got/$total（其中出错 $err 个）"; else echo "不完整：$got/$total"; fi
