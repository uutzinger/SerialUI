# Add folders you want to bundle
import os
from PyInstaller.building.build_main import Analysis, PYZ, EXE, COLLECT, Tree
from config import USE_FASTPLOTLIB, USE_BLE

block_cipher = None
console_mode = os.environ.get("SERIALUI_CONSOLE", "").strip().lower() in ("1", "true", "yes", "on")

# Path to project root (where this spec file lives)
proj_root = os.path.abspath(os.getcwd())

# Entry point of your app:
entry_script = os.path.join(proj_root, "SerialUI.py")

datas = [
    ("assets", "assets"),
    ("README.md", "."),
]

excludes = [
    # Ensure only PyQt6 is collected. The source contains PyQt5 fallback imports,
    # but frozen builds should ship exactly one Qt binding.
    "PyQt5",
    "PyQt5.sip",
    "PySide2",
    "PySide6",
    # Exclude GUI stacks not used by this Qt app.
    "IPython",
    "ipykernel",
    "gi",
    "gi.repository",
    "tkinter",
    "PIL.ImageTk",
    # Avoid GTK/Tk backend pull-in from matplotlib in frozen Qt app.
    "matplotlib",
    "matplotlib.backends.backend_gtk3",
    "matplotlib.backends.backend_gtk3agg",
    "matplotlib.backends.backend_gtk3cairo",
    "matplotlib.backends.backend_gtk4",
    "matplotlib.backends.backend_gtk4agg",
    "matplotlib.backends.backend_gtk4cairo",
    "matplotlib.backends.backend_tkagg",
    "matplotlib.backends.backend_tkcairo",
    # Debug helper is guarded out in frozen mode; avoid bundling it.
    "debugpy",
]

# In default config we do not use fastplotlib. Exclude its heavy dependency stack
# to prevent multi-GB Linux bundles from optional CUDA/OpenCV/media packages.
if not USE_FASTPLOTLIB:
    excludes += [
        "fastplotlib",
        "pygfx",
        "wgpu",
        "rendercanvas",
        "imgui_bundle",
        "cv2",
        "imageio",
        "imageio_ffmpeg",
        "av",
        "uharfbuzz",
        "wx",
        "vtk",
        "pandas",
        "dask",
        "zarr",
        "numcodecs",
        "h5py",
        "botocore",
        "sphinx",
        "pytest",
    ]

# BLE stack is optional in app config.
if not USE_BLE:
    excludes += [
        "bleak",
        "bleak.backends",
    ]

a = Analysis(
    [entry_script],
    pathex=[proj_root],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # Add any modules here that PyInstaller might miss, e.g.:
        # "pkg_resources.py2_warn",
        # "some_dynamic_imported_module",
    ],
    hookspath=[],
    hooksconfig={
        # Prevent matplotlib hook from selecting GTK/Tk backends on Linux.
        "matplotlib": {"backends": "QtAgg"},
        # If Gtk is pulled in indirectly, do not recurse through /usr/share/icons and themes.
        "gi": {"icons": [], "themes": [], "languages": []},
    },
    runtime_hooks=[],
    excludes=excludes,
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
    # Stripping/UPX can corrupt some native extension dependencies
    # (notably OpenBLAS/Numpy libs on Linux), causing runtime loader errors.
    strip=False,
    upx=False,
    console=console_mode,
    icon=os.path.join("assets", "icon_96.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SerialUI",
)
