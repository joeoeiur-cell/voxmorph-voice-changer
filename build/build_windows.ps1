<#
.SYNOPSIS
    Local Windows build: VoxMorph.exe + installer.

.EXAMPLE
    .\build\build_windows.ps1                 # DSP-only build (fast, ~180 MB)
    .\build\build_windows.ps1 -WithGPU        # bundles torch + RVC (~2.5 GB)
    .\build\build_windows.ps1 -Version 1.2.0
#>
param(
    [string]$Version = "",
    [switch]$WithGPU,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "=== VoxMorph Windows build ===" -ForegroundColor Cyan

if (-not $Version) {
    $Version = (Select-String -Path voxmorph/__init__.py -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
}
Write-Host "Version: $Version"

# ---------------------------------------------------------------- venv
if (-not (Test-Path .venv)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    py -3.10 -m venv .venv
}
& .\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip wheel | Out-Null
Write-Host "Installing dependencies..." -ForegroundColor Yellow
pip install -r requirements.txt
pip install pyinstaller==6.11.1

if ($WithGPU) {
    Write-Host "Installing CUDA torch + RVC (this is a large download)..." -ForegroundColor Yellow
    pip install torch==2.4.1+cu121 torchaudio==2.4.1+cu121 --index-url https://download.pytorch.org/whl/cu121
    pip install -r requirements-gpu.txt
}

# ---------------------------------------------------------------- icon
if (-not (Test-Path assets/voxmorph.ico)) {
    New-Item -ItemType Directory -Force -Path assets | Out-Null
    python tools/make_icon.py
}

# ---------------------------------------------------------------- tests
Write-Host "Running tests..." -ForegroundColor Yellow
python tests/test_integration.py
if ($LASTEXITCODE -ne 0) { throw "Tests failed - aborting build." }

# ---------------------------------------------------------------- build
Write-Host "Running PyInstaller..." -ForegroundColor Yellow
Remove-Item -Recurse -Force build/__pycache__, dist -ErrorAction SilentlyContinue
pyinstaller build/voxmorph.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

Write-Host "Smoke testing..." -ForegroundColor Yellow
& dist\VoxMorph\VoxMorph-cli.exe --version
& dist\VoxMorph\VoxMorph-cli.exe doctor

$size = "{0:N0}" -f ((Get-ChildItem dist/VoxMorph -Recurse | Measure-Object Length -Sum).Sum / 1MB)
Write-Host "Build size: $size MB"

# ------------------------------------------------------------ installer
if (-not $SkipInstaller) {
    $iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if (Test-Path $iscc) {
        Write-Host "Building installer..." -ForegroundColor Yellow
        & $iscc "/DMyAppVersion=$Version" build\installer.iss
        $setup = Get-ChildItem dist/installer/*.exe | Select-Object -First 1
        $hash = (Get-FileHash $setup.FullName -Algorithm SHA256).Hash.ToLower()
        Write-Host ""
        Write-Host "Installer: $($setup.FullName)" -ForegroundColor Green
        Write-Host "sha256:    $hash" -ForegroundColor Green
        Write-Host ""
        Write-Host "Publish this hash in the GitHub release body so the" -ForegroundColor Cyan
        Write-Host "auto-updater can verify it." -ForegroundColor Cyan
    } else {
        Write-Warning "Inno Setup 6 not found - skipping installer."
        Write-Warning "Install from https://jrsoftware.org/isdl.php"
    }
}

Write-Host "=== Done ===" -ForegroundColor Cyan
