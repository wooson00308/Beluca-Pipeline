#!/usr/bin/env bash
# ============================================
# BPE Nuke 연동 설치 (macOS / Linux)
# ============================================
# bpe.core.nuke_plugin_install 로 ~/.nuke/bpe 슬림 동기화

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -f "$SCRIPT_DIR/../src/bpe/__init__.py" ]; then
    export PYTHONPATH="$SCRIPT_DIR/../src${PYTHONPATH:+:$PYTHONPATH}"
elif [ -f "$SCRIPT_DIR/bpe/__init__.py" ]; then
    export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"
else
    echo "[오류] bpe 패키지를 찾을 수 없습니다."
    exit 1
fi

echo "============================================"
echo "BPE Nuke 연동 설치"
echo "============================================"

python3 -c "from bpe.core.nuke_plugin_install import ensure_nuke_plugin; r=ensure_nuke_plugin(force=True); print(r); raise SystemExit(0 if not r.get('error') else 1)"

echo ""
echo "[완료] $HOME/.nuke/bpe"
echo "Nuke 를 재시작하면 상단에 BPE 메뉴가 나타납니다."
