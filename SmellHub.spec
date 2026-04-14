# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


def _existing_data_entries():
    entries = []
    names = [
        "api",
        "analyzers",
        "core",
        "models",
        "utils",
        "web",
        "smell_ai",
        "SE_Emotion_PTM-3589",
        "DPy",
        "DPy_WINDOWS",
        "DPy_MACOS",
        "requirements.txt",
        "pronoun_paradigms_coling2022.txt",
    ]
    for name in names:
        path = PROJECT_ROOT / name
        if path.exists():
            entries.append((str(path), name))
    return entries


a = Analysis(
    [str(PROJECT_ROOT / "launcher.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=_existing_data_entries(),
    hiddenimports=[
        "api.main",
        "fastapi.middleware.cors",
        "fastapi.staticfiles",
        "fastapi.responses",
        "uvicorn",
        "torch",
        "transformers",
    ],
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
    [],
    exclude_binaries=True,
    name="SmellHub",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="SmellHub",
)
