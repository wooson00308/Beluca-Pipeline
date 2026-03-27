#requires -Version 5.1
<#
.SYNOPSIS
  로컬 PyInstaller 빌드 후 테스트용 exe를 고정 출력 폴더에 복사한다 (릴리즈/CI와 무관).

.DESCRIPTION
  - 프로젝트 루트에서 pyinstaller installer/bpe.spec 실행
  - dist\BPE.exe 를 Test_exe\BPE_dev.exe 한 개만 덮어쓰기 복사
  - 기본 출력: C:\Users\yklee\Desktop\BPE-Windows\Test_exe
  - 다른 PC/경로: 환경변수 BPE_LOCAL_TEST_EXE_DIR

.EXAMPLE
  .\scripts\build_test_exe.ps1
.EXAMPLE
  .\scripts\build_test_exe.ps1 -Check   # 빌드 전 ruff + pytest
#>
param(
    [switch]$Check,
    [string]$OutputDir = $env:BPE_LOCAL_TEST_EXE_DIR
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $OutputDir -or [string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = 'C:\Users\yklee\Desktop\BPE-Windows\Test_exe'
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

Push-Location $RepoRoot
try {
    if ($Check) {
        Write-Host '==> ruff check ...' -ForegroundColor Cyan
        python -m ruff check src/ tests/
        Write-Host '==> pytest ...' -ForegroundColor Cyan
        $env:QT_QPA_PLATFORM = 'offscreen'
        python -m pytest --tb=short -q
        Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
    }

    Write-Host '==> PySide6 (GUI 번들 필수) 확인 ...' -ForegroundColor Cyan
    python -c "import PySide6.QtCore, PySide6.QtGui, PySide6.QtWidgets; print('PySide6 OK')"
    Write-Host '==> PyInstaller (installer/bpe.spec) ...' -ForegroundColor Cyan
    python -m PyInstaller installer/bpe.spec --noconfirm

    $built = Join-Path $RepoRoot 'dist\BPE.exe'
    if (-not (Test-Path -LiteralPath $built)) {
        throw "빌드 결과가 없습니다: $built"
    }

    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    $outExe = Join-Path $OutputDir 'BPE_dev.exe'

    Copy-Item -LiteralPath $built -Destination $outExe -Force

    Write-Host ''
    Write-Host '로컬 테스트 exe 준비됨:' -ForegroundColor Green
    Write-Host "  $outExe"
}
finally {
    Pop-Location
}
