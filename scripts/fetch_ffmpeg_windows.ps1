#requires -Version 5.1
<#
.SYNOPSIS
  gyan.dev ffmpeg-release-essentials.zip 에서 ffmpeg.exe / ffprobe.exe 만 추출해 installer/ffmpeg-bin 에 둔다.
  PyInstaller onefile 번들에 포함되며, 런타임에는 sys._MEIPASS 에서 찾는다 (bpe.core.ffmpeg_paths).
#>
param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

if ($env:OS -ne 'Windows_NT') {
    Write-Host 'fetch_ffmpeg_windows: Windows 가 아니면 건너뜁니다.'
    exit 0
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$DestDir = Join-Path $RepoRoot 'installer\ffmpeg-bin'
$FfOut = Join-Path $DestDir 'ffmpeg.exe'
$FpOut = Join-Path $DestDir 'ffprobe.exe'

New-Item -ItemType Directory -Force -Path $DestDir | Out-Null

if ((-not $Force) -and (Test-Path -LiteralPath $FfOut) -and (Test-Path -LiteralPath $FpOut)) {
    Write-Host "FFmpeg 이미 있음: $DestDir"
    exit 0
}

$Url = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
$TmpRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('bpe-ff-' + [guid]::NewGuid().ToString('n'))
$ZipPath = Join-Path $TmpRoot 'ffmpeg-essentials.zip'

New-Item -ItemType Directory -Force -Path $TmpRoot | Out-Null
try {
    Write-Host "다운로드: $Url"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $Url -OutFile $ZipPath -UseBasicParsing

    Write-Host '압축 해제...'
    Expand-Archive -LiteralPath $ZipPath -DestinationPath $TmpRoot -Force

    $FfSrc = Get-ChildItem -Path $TmpRoot -Filter ffmpeg.exe -Recurse -File -ErrorAction SilentlyContinue |
        Select-Object -First 1
    $FpSrc = Get-ChildItem -Path $TmpRoot -Filter ffprobe.exe -Recurse -File -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $FfSrc -or -not $FpSrc) {
        throw '압축 안에서 ffmpeg.exe / ffprobe.exe 를 찾지 못했습니다.'
    }

    Copy-Item -LiteralPath $FfSrc.FullName -Destination $FfOut -Force
    Copy-Item -LiteralPath $FpSrc.FullName -Destination $FpOut -Force
    Write-Host "복사 완료: $FfOut"
}
finally {
    Remove-Item -LiteralPath $TmpRoot -Recurse -Force -ErrorAction SilentlyContinue
}
