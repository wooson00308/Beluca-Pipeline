# BPE — Beluca Pipeline Engine

VFX 프로덕션 파이프라인 도구. Nuke(합성)와 ShotGrid(프로젝트 관리)를 연결하는 데스크톱 앱.

## 기능

| 탭 | 설명 |
|---|---|
| Preset Manager | Nuke 프로젝트 세팅(FPS, 해상도, OCIO, Write) 프리셋 저장/로드 |
| Shot Builder | 샷 이름 → 폴더 구조 + NK 파일 자동 생성 |
| My Tasks | ShotGrid 담당 샷 조회, 썸네일, 노트, NK 열기 |
| Publish | MOV 드래그 드롭 → ShotGrid Version 생성 + 업로드 |
| Tools | Nuke QC Checker, Post-Render Viewer 토글 |

## 설치

### 바이너리 (권장)

[Releases](https://github.com/wooson00308/Beluca-Pipeline/releases)에서 OS별 zip 다운로드.

- Windows: `BPE-Windows.zip` → 압축 해제 → `BPE.exe` 실행
- macOS: `BPE-macOS.zip` → 압축 해제 → `xattr -cr BPE.app` → 실행

### 소스에서 실행

```bash
git clone https://github.com/wooson00308/Beluca-Pipeline.git
cd Beluca-Pipeline
pip install -e ".[dev]"
python -m bpe
```

## 개발

### 구조

```
src/bpe/
├── core/          # 순수 로직 (GUI 무관, 표준 라이브러리만)
├── shotgrid/      # ShotGrid API 래퍼
├── gui/           # PySide6 GUI
└── nuke_plugin/   # Nuke 내부 플러그인 (PySide6 금지)
```

핵심 규칙: `core/`는 어디서든 import 가능하지만, `gui/`와 `nuke_plugin/`은 서로 import 금지.

### 테스트

```bash
python -m pytest tests/ -v
```

### 린트

```bash
ruff check src/ tests/
ruff format src/ tests/
```

### 배포

```bash
# CI 통과 확인 후
git tag v0.x.x
git push origin v0.x.x
# GitHub Actions가 mac/win 바이너리를 자동 빌드 + Release
```

## 설정 파일

`~/.setup_pro/` 디렉토리에 저장됨:

| 파일 | 용도 |
|---|---|
| `settings.json` | 앱 설정 (tools, shotgrid, presets_dir) |
| `presets.json` | 프리셋 데이터 |
| `shot_builder.json` | Shot Builder 상태 |
| `cache/` | Nuke 포맷/컬러스페이스 캐시 |

### ShotGrid 연결

`shotgrid_studio.json`을 `~/.setup_pro/` 또는 EXE 옆에 배치:

```json
{
  "base_url": "https://YOUR_STUDIO.shotgrid.autodesk.com",
  "script_name": "YOUR_SCRIPT_NAME",
  "script_key": "YOUR_SCRIPT_KEY"
}
```

환경변수로도 가능: `BPE_SHOTGRID_BASE_URL`, `BPE_SHOTGRID_SCRIPT_NAME`, `BPE_SHOTGRID_SCRIPT_KEY`

## Nuke 플러그인 설치

- Windows: `scripts/install_to_nuke.bat` 실행
- macOS: `scripts/install_to_nuke.sh` 실행

## 기술 스택

- GUI: PySide6 (Qt)
- ShotGrid API: shotgun_api3
- 빌드: PyInstaller + GitHub Actions
- 테스트: pytest
- 린트: ruff
