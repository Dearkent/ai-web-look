#!/bin/bash
# 在一个新环境里恢复验证门需要的仓库（只读学习用，不安装依赖、不运行任何仓库代码）。
# 用法：bash bootstrap.sh            # 读码笔记用到的 8 个仓库 + 元数据库
#       bash bootstrap.sh --meta-all # 另外拉取全部 157 个仓库的元数据（约 2 分钟）
set -u
here="$(cd "$(dirname "$0")" && pwd)"
fetch_full() {  # 读码笔记需要读全文：浅克隆
  [ -d "$2" ] || timeout 300 git clone -q --depth 1 "https://github.com/$1.git" "$2" && echo "已就绪 $2"
}
mkdir -p /home/claude/repos /home/claude/repos2 /home/claude/repos3 /home/claude/meta
fetch_full stackblitz-labs/bolt.diy /home/claude/repos/bolt.diy
fetch_full dyad-sh/dyad /home/claude/repos/dyad-sh_dyad
fetch_full cloudflare/vibesdk /home/claude/repos/cloudflare_vibesdk
fetch_full nextlevelbuilder/ui-ux-pro-max-skill /home/claude/repos3/nextlevelbuilder_ui-ux-pro-max-skill
# 第二轮（图纸格式）参照物：评测 E21 核对其中的代码事实
fetch_full puckeditor/puck /home/claude/repos/puckeditor_puck
fetch_full design-tokens/community-group /home/claude/repos3/design-tokens_community-group
fetch_full xyflow/xyflow /home/claude/repos3/xyflow_xyflow
fetch_full FoundationAgents/MetaGPT /home/claude/repos3/FoundationAgents_MetaGPT
# 第三轮（防死循环）参照物：OpenHands Agent SDK 只取元数据，评测 E26 按文件读取
mkdir -p /home/claude/repos4
[ -d /home/claude/repos4/OpenHands_software-agent-sdk ] || timeout 300 git clone -q --depth 1 --filter=blob:none --no-checkout https://github.com/OpenHands/software-agent-sdk.git /home/claude/repos4/OpenHands_software-agent-sdk
# 许可证评测用到的仓库：只取元数据（--no-checkout）
for r in theatre-js/theatre GrapesJS/grapesjs DwareLab/easyblocks GoogleChrome/lighthouse; do
  bash "$here/checks/repo_meta.sh" bootstrap "$r" >/dev/null && echo "元数据 $r"
done
if [ "${1:-}" = "--meta-all" ]; then
  xargs -P 24 -L 1 bash "$here/checks/repo_meta.sh" < "$here/checks/repo_list.txt" > /home/claude/meta/result.tsv
  echo "全部元数据：$(wc -l < /home/claude/meta/result.tsv) 行"
fi
echo "完成。注意：仓库内容会随上游更新变化，事实核对对不上时，先看是不是上游改了（这正是该更新笔记的信号）。"
