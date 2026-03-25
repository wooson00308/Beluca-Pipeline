#!/usr/bin/env bash
# ============================================
# BPE Nuke 연동 설치 (macOS / Linux)
# ============================================
# bpe 패키지를 ~/.nuke/ 에 symlink 하고
# menu.py 에 hook 을 추가합니다.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NUKE_DIR="$HOME/.nuke"
HOOK_MARKER="# BPE_HOOK_START"

# bpe 패키지 소스 탐색
if [ -f "$SCRIPT_DIR/../src/bpe/__init__.py" ]; then
    BPE_SRC="$(cd "$SCRIPT_DIR/../src/bpe" && pwd)"
elif [ -f "$SCRIPT_DIR/bpe/__init__.py" ]; then
    BPE_SRC="$(cd "$SCRIPT_DIR/bpe" && pwd)"
else
    echo "[오류] bpe 패키지를 찾을 수 없습니다."
    echo "프로젝트 루트의 scripts 폴더에서 실행하거나,"
    echo "배포 폴더에 bpe 디렉터리가 있는지 확인하세요."
    exit 1
fi

echo "============================================"
echo "BPE Nuke 연동 설치"
echo "============================================"

mkdir -p "$NUKE_DIR"

# bpe 패키지를 symlink
echo "[1/2] bpe 패키지를 $NUKE_DIR/bpe 로 symlink 합니다..."
if [ -e "$NUKE_DIR/bpe" ] || [ -L "$NUKE_DIR/bpe" ]; then
    rm -rf "$NUKE_DIR/bpe"
fi
ln -s "$BPE_SRC" "$NUKE_DIR/bpe"
echo "      $BPE_SRC -> $NUKE_DIR/bpe"

# menu.py 에 BPE hook 추가
echo "[2/2] menu.py 에 BPE hook 을 추가합니다..."
MENU_PY="$NUKE_DIR/menu.py"

if [ -f "$MENU_PY" ] && grep -qF "$HOOK_MARKER" "$MENU_PY"; then
    echo "      menu.py 에 이미 BPE hook 이 있습니다. 건너뜁니다."
else
    cat >> "$MENU_PY" << 'HOOK_EOF'

# BPE_HOOK_START
try:
    from bpe.nuke_plugin.menu_setup import add_setup_pro_menu
    add_setup_pro_menu()
    from bpe.nuke_plugin.tool_hooks import reload_tool_hooks
    reload_tool_hooks()
except Exception as _bpe_err:
    import nuke
    nuke.tprint("[BPE] menu.py hook 로드 실패: " + str(_bpe_err))
# BPE_HOOK_END
HOOK_EOF
fi

echo ""
echo "[완료] 설치 경로:"
echo "  $NUKE_DIR/bpe -> $BPE_SRC"
echo "  $MENU_PY"
echo ""
echo "Nuke 를 재시작하면 상단에 setup_pro 메뉴가 나타납니다."
