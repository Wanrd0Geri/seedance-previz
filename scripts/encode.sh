#!/usr/bin/env bash
# 薄封装：转调跨平台的 encode.py（用法和参数不变）。SKILL.md 直接指向 encode.py。
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
if command -v py >/dev/null 2>&1 && py -3 -c "" >/dev/null 2>&1; then PY="py -3"
elif command -v python3 >/dev/null 2>&1; then PY=python3
else PY=python; fi
exec $PY -X utf8 "$HERE/encode.py" "$@"
