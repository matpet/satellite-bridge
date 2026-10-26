# Rebuild with: python build_macos_app.py (PyInstaller 6.22.3).
from pathlib import Path

project = Path(SPECPATH).parent
a = Analysis(
    [str(project / 'bridge_app.py')],
    pathex=[str(project)],
    binaries=[],
    datas=[(str(project / 'bridge-settings.json'), '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='Satellite Bridge',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch='x86_64',
    # None selects PyInstaller's default ad-hoc signing without enabling
    # hardened-runtime library validation (which requires an Apple Team ID).
    codesign_identity=None,
    entitlements_file=str(project / 'packaging' / 'entitlements.plist'),
)
collection = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Satellite Bridge')
app = BUNDLE(
    collection,
    name='Satellite Bridge.app',
    icon=str(project / 'packaging' / 'SatelliteBridge.icns'),
    bundle_identifier='local.satellitebridge.IC9700',
    version='1.0.6',
    info_plist={
        'CFBundleDisplayName': 'Satellite Bridge',
        'CFBundleName': 'Satellite Bridge',
        'CFBundleShortVersionString': '1.0.6',
        'CFBundleVersion': '10',
        'LSMinimumSystemVersion': '10.15.4',
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': True,
    },
)
