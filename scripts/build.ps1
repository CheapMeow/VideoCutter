$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if ([string]::IsNullOrWhiteSpace($env:VIDEOCUTTER_PYTHON)) {
    throw "VIDEOCUTTER_PYTHON is not set. Point it at the python.exe used to build VideoCutter."
}

& $env:VIDEOCUTTER_PYTHON -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "VIDEOCUTTER_PYTHON must be Python 3.11 or newer"
}

& $env:VIDEOCUTTER_PYTHON -c "import PySide6, cv2, PyInstaller, av"
if ($LASTEXITCODE -ne 0) {
    throw "VIDEOCUTTER_PYTHON is missing PySide6, opencv-python, PyInstaller, or av"
}

& $env:VIDEOCUTTER_PYTHON -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name VideoCutter `
    --paths src `
    --distpath dist `
    --workpath build `
    --specpath build `
    --collect-submodules videocutter `
    --collect-all PySide6 `
    --collect-all cv2 `
    --collect-all av `
    src\videocutter\__main__.py

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}
