# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['/Users/broke31/Desktop/tool/launcher.py'],
    pathex=['/Users/broke31/Desktop/tool'],
    binaries=[],
    datas=[('/Users/broke31/Desktop/tool/api', 'api'), ('/Users/broke31/Desktop/tool/analyzers', 'analyzers'), ('/Users/broke31/Desktop/tool/core', 'core'), ('/Users/broke31/Desktop/tool/models', 'models'), ('/Users/broke31/Desktop/tool/utils', 'utils'), ('/Users/broke31/Desktop/tool/web', 'web'), ('/Users/broke31/Desktop/tool/smell_ai', 'smell_ai'), ('/Users/broke31/Desktop/tool/SE_Emotion_PTM-3589', 'SE_Emotion_PTM-3589'), ('/Users/broke31/Desktop/tool/DPy', 'DPy'), ('/Users/broke31/Desktop/tool/requirements.txt', 'requirements.txt')],
    hiddenimports=['api.main', 'fastapi.middleware.cors', 'fastapi.staticfiles', 'fastapi.responses', 'uvicorn', 'torch', 'transformers'],
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
    name='SmellHub',
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
    name='SmellHub',
)
