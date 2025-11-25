# Add folders you want to bundle
import os
from PyInstaller.building.build_main import Analysis, PYZ, EXE, COLLECT, Tree

block_cipher = None

# Path to project root (where this spec file lives)
proj_root = os.path.abspath(os.getcwd())

# Entry point of your app:
entry_script = os.path.join(proj_root, "SerialUI.py")


a = Analysis(
    [entry_script],
    pathex=[proj_root],
    binaries=[],
    datas = [
        Tree('assets',  prefix='assets'),
        Tree('docs',    prefix='docs'),
        Tree('helpers', prefix='helpers'),
    ],
    hiddenimports=[
        # Add any modules here that PyInstaller might miss, e.g.:
        # "pkg_resources.py2_warn",
        # "some_dynamic_imported_module",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher,
)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SerialUI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # set False if you want a pure GUI app (no console window)
    icon=os.path.join("SerialUI", "assets", "icon_96.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="SerialUI",
)