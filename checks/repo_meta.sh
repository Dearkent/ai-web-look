#!/bin/bash
# usage: meta.sh CATEGORY owner/repo  -> prints TSV line
cat="$1"; r="$2"; base=${META_DIR:-/home/claude/meta}; d="$base/$(echo $r | tr '/' '__')"
if [ ! -d "$d" ]; then timeout 120 git clone -q --depth 1 --filter=blob:none --no-checkout "https://github.com/$r.git" "$d" >/dev/null 2>&1 || { printf "%s\t%s\tFAIL\t\t\t\n" "$cat" "$r"; exit 0; }; fi
date=$(git -C "$d" log -1 --format=%cs 2>/dev/null)
lf=$(git -C "$d" ls-tree --name-only HEAD | grep -iE '^(licen[cs]e|copying)(\.md|\.txt)?$' | head -1)
t=""; [ -n "$lf" ] && t=$(timeout 60 git -C "$d" show "HEAD:$lf" 2>/dev/null | head -c 3000 | tr '\n' ' ' | tr -s ' ')
l="?"
case "$t" in
 *"Commons Clause"*) l="MIT+Commons Clause";;
 *"Functional Source"*) l="FSL";;
 *"Business Source"*) l="BUSL";;
 *"Elastic License"*) l="Elastic-2.0";;
 *"Sustainable Use"*) l="Sustainable Use";;
 *"Portions of this software"*|*"ee/"*) case "$t" in *"MIT"*|*"Permission is hereby granted"*) l="MIT(含ee)";; *"Apache"*) l="Apache-2.0(含ee)";; *) l="混合";; esac;;
 *"GNU AFFERO"*) l="AGPL-3.0";;
 *"GNU LESSER"*) l="LGPL";;
 *"GNU GENERAL PUBLIC"*) l="GPL";;
 *"Mozilla Public License"*) l="MPL-2.0";;
 *"Apache License"*) l="Apache-2.0";;
 *"MIT License"*|*"Permission is hereby granted, free of charge"*) l="MIT";;
 *"BSD"*|*"Redistribution and use in source and binary forms"*) l="BSD";;
 *"Creative Commons"*|*"CC0"*|*"CC-BY"*|*"CC BY"*) l="CC";;
 *"tldraw license"*|*"tldraw"*) l="tldraw许可";;
 "") l="无LICENSE文件";;
 *) l="其他";;
esac
rf=$(git -C "$d" ls-tree --name-only HEAD | grep -iE '^readme(\.md)?$' | head -1)
desc=""; [ -n "$rf" ] && desc=$(timeout 60 git -C "$d" show "HEAD:$rf" 2>/dev/null | grep -v '^\s*$' | grep -vE '!\[|<img|<p|</p|<a |shield|badge|<br|<div|</div|<h[1-6]|</h|<source|<picture|^\[|^---|<!--|^>|^\|' | sed 's/^#* *//' | head -3 | tr '\n' ' ' | cut -c1-220 | tr '\t' ' ')
printf "%s\t%s\tOK\t%s\t%s\t%s\n" "$cat" "$r" "$date" "$l" "$desc"
