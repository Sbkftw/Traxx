$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $projectRoot

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    throw "Virtual environment not found at .\.venv. Create it first, then install the build dependencies."
}

& powershell -ExecutionPolicy Bypass -File .\packaging\windows\generate_icon.ps1
if ($LASTEXITCODE -ne 0) {
    throw "Icon generation failed."
}

& .\.venv\Scripts\python.exe -m pip install -e .[build]
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install build dependencies."
}

& .\.venv\Scripts\pyinstaller.exe --clean --noconfirm .\packaging\traxx.spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

Write-Host ""
Write-Host "Build complete. Binary available in dist\traxx.exe"
