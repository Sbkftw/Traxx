from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


# PyInstaller does not guarantee __file__ inside spec execution.
# Use the current working directory, which our build script sets to repo root.
project_root = Path.cwd()
hiddenimports = collect_submodules("yt_dlp")

datas = []
for relative_path in ("README.md", ".env.example", "traxx-hero.svg"):
    source = project_root / relative_path
    if source.exists():
        datas.append((str(source), "."))

icon_path = project_root / "assets" / "traxx.ico"


a = Analysis(
    ["traxx.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="traxx",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    icon=str(icon_path) if icon_path.exists() else None,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
