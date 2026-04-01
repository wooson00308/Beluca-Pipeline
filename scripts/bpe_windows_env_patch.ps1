# BPE Windows 환경 패치 (BPE 실행 파일과 별도)
#
# 하는 일:
#   - 사용자 계정에 영구 환경 변수를 설정해, 다음 실행부터 BPE가 읽습니다.
#   - BPE_NUKEX_EXE  : NK 열기(NukeX) — 자동 탐색 실패·비표준 설치 경로 대응
#   - BPE_SERVER_ROOT: My Tasks 등에서 서버 루트 자동 탐색이 안 될 때 (예: W:\vfx\project_2026)
#
# 안전 (서버·다른 PC에 영향 없음):
#   - 네트워크 서버의 파일/폴더를 만들거나 지우지 않고, 서버 설정을 바꾸지 않습니다.
#   - 이 PC의 "현재 로그인 사용자"에만 적용되며, 관리자 권한이 없어도 됩니다.
#   - 다른 사용자 계정이나 다른 컴퓨터에는 영향이 없습니다.
#   - 잘못된 값을 넣으면 BPE에서만 경로가 어긋날 수 있으니, 그때는 아래 "되돌리기"로 변수를 지우면 됩니다.
#
# 한계:
#   - 이미 켜져 있는 BPE에는 반영되지 않습니다. 패치 후 BPE를 완전히 종료했다가 다시 실행하세요.
#   - 탐색기/URL 자체가 막히는 보안 정책 등은 이 스크립트로 고칠 수 없습니다 (서버 경로·Nuke 경로 문제 위주).
#
#Requires -Version 5.1
$ErrorActionPreference = 'Stop'

function Write-Utf8Line {
    param([string]$Message)
    [Console]::WriteLine($Message)
}

function Get-NukexCandidates {
    $list = New-Object System.Collections.Generic.List[string]
    foreach ($root in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if ([string]::IsNullOrWhiteSpace($root)) { continue }
        if (-not (Test-Path -LiteralPath $root)) { continue }
        $nukeDirs = @(Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -like 'Nuke*' })
        foreach ($dir in $nukeDirs) {
            $nukeDir = $dir.FullName
            $low = $nukeDir.ToLowerInvariant()
            if ($low -match 'studio|hiero|indie') { continue }
            $exes = @(Get-ChildItem -LiteralPath $nukeDir -Filter 'nukex*.exe' -File -ErrorAction SilentlyContinue)
            foreach ($exe in $exes) {
                [void]$list.Add($exe.FullName)
            }
        }
    }
    return ,$list.ToArray()
}

function Set-UserEnv {
    param(
        [string]$Name,
        [string]$Value
    )
    [Environment]::SetEnvironmentVariable($Name, $Value, 'User')
}

Write-Utf8Line ''
Write-Utf8Line '=== BPE Windows 환경 패치 ==='
Write-Utf8Line ''
Write-Utf8Line '[안전] 서버 파일·서버 설정은 변경하지 않습니다. 이 Windows 사용자에게만 BPE용 변수가 저장됩니다.'
Write-Utf8Line ''

$prevNukex = [Environment]::GetEnvironmentVariable('BPE_NUKEX_EXE', 'User')
$prevRoot = [Environment]::GetEnvironmentVariable('BPE_SERVER_ROOT', 'User')
if ($prevNukex) { Write-Utf8Line ("(기존) BPE_NUKEX_EXE = {0}" -f $prevNukex) }
else { Write-Utf8Line '(기존) BPE_NUKEX_EXE = (없음)' }
if ($prevRoot) { Write-Utf8Line ("(기존) BPE_SERVER_ROOT = {0}" -f $prevRoot) }
else { Write-Utf8Line '(기존) BPE_SERVER_ROOT = (없음)' }
Write-Utf8Line ''

$nukexPath = $null
$cands = @(Get-NukexCandidates)

if ($cands.Count -eq 0) {
    Write-Utf8Line 'Program Files에서 nukex*.exe 를 찾지 못했습니다.'
    $manual = Read-Host 'NukeX 실행 파일 전체 경로를 직접 입력하세요 (건너뛰려면 엔터)'
    $manual = $manual.Trim()
    if ($manual -ne '' -and (Test-Path -LiteralPath $manual)) {
        $nukexPath = (Resolve-Path -LiteralPath $manual).Path
    }
}
elseif ($cands.Count -eq 1) {
    $nukexPath = $cands[0]
    Write-Utf8Line ("자동 선택: {0}" -f $nukexPath)
}
else {
    Write-Utf8Line '여러 NukeX 후보가 있습니다. 번호를 고르세요.'
    for ($i = 0; $i -lt $cands.Count; $i++) {
        Write-Utf8Line ("  [{0}] {1}" -f ($i + 1), $cands[$i])
    }
    $sel = Read-Host '번호 (엔터면 목록 중 사전 정렬된 첫 번째 권장)'
    if ([string]::IsNullOrWhiteSpace($sel)) {
        $sorted = $cands | Sort-Object -Descending
        $nukexPath = $sorted[0]
    }
    else {
        $n = 0
        if (-not [int]::TryParse($sel, [ref]$n)) {
            Write-Utf8Line '잘못된 번호입니다. 종료합니다.'
            exit 1
        }
        if ($n -lt 1 -or $n -gt $cands.Count) {
            Write-Utf8Line '범위 밖 번호입니다. 종료합니다.'
            exit 1
        }
        $nukexPath = $cands[$n - 1]
    }
}

if ($null -ne $nukexPath -and $nukexPath -ne '') {
    $low = [System.IO.Path]::GetFileName($nukexPath).ToLowerInvariant()
    if (-not $low.StartsWith('nukex')) {
        Write-Utf8Line '경고: 파일 이름이 nukex로 시작하지 않습니다. BPE가 무시할 수 있습니다.'
    }
    Set-UserEnv -Name 'BPE_NUKEX_EXE' -Value $nukexPath
    Write-Utf8Line ("설정됨: BPE_NUKEX_EXE = {0}" -f $nukexPath)
}
else {
    Write-Utf8Line 'BPE_NUKEX_EXE 는 설정하지 않았습니다.'
}

Write-Utf8Line ''
Write-Utf8Line '서버 루트(프로젝트 상위, 예: W:\vfx\project_2026)를 고정하려면 입력하세요.'
Write-Utf8Line '자동 드라이브 탐색이 되는 PC는 비워 두어도 됩니다.'
$rootIn = Read-Host 'BPE_SERVER_ROOT (엔터=변경 없음)'

$rootIn = $rootIn.Trim()
if ($rootIn -ne '') {
    if (-not (Test-Path -LiteralPath $rootIn)) {
        Write-Utf8Line "경고: 해당 경로가 없습니다: $rootIn (그래도 환경 변수만 저장합니다)"
    }
    Set-UserEnv -Name 'BPE_SERVER_ROOT' -Value $rootIn
    Write-Utf8Line ("설정됨: BPE_SERVER_ROOT = {0}" -f $rootIn)
}
else {
    Write-Utf8Line 'BPE_SERVER_ROOT 는 변경하지 않았습니다.'
}

Write-Utf8Line ''
Write-Utf8Line '완료. BPE를 완전히 종료한 뒤 다시 실행해 주세요.'
Write-Utf8Line ''
Write-Utf8Line '[되돌리기] 문제가 있으면: Windows 검색에서 환경 변수 - 사용자 변수 메뉴에서'
Write-Utf8Line '  BPE_NUKEX_EXE / BPE_SERVER_ROOT 를 삭제하거나 값을 고치면 됩니다.'
Write-Utf8Line '  (서버나 다른 프로그램 설치는 건드리지 않습니다.)'
Write-Utf8Line ''
