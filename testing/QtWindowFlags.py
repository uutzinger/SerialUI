import os, sys, platform

# ---- Qt5/Qt6 compatibility shim -------------------------------------------
try:
    from PyQt6.QtWidgets import QApplication, QMainWindow
    from PyQt6.QtCore import Qt, QT_VERSION_STR
    from PyQt6.QtGui import QGuiApplication
    IS_QT6 = True
except Exception:
    from PyQt5.QtWidgets import QApplication, QMainWindow
    from PyQt5.QtCore import Qt, QT_VERSION_STR
    from PyQt5.QtGui import QGuiApplication
    IS_QT6 = False

WT = Qt.WindowType if IS_QT6 else Qt
MASK = int(WT.WindowType_Mask)

def flag_is_set(win, flag) -> bool:
    return bool(int(win.windowFlags()) & int(flag))

# ---- Runtime probe ---------------------------------------------------------
print("=== Qt runtime probe ===")
print("OS:                         ", platform.platform())
print("Qt version:                 ", QT_VERSION_STR)
print("Qt platform plugin:         ", QGuiApplication.platformName())  # 'xcb', 'wayland', ...
print("Env: QT_WAYLAND_DISABLE_WINDOWDECORATION =", os.getenv("QT_WAYLAND_DISABLE_WINDOWDECORATION"))
print("Env: QT_QPA_PLATFORMTHEME              =", os.getenv("QT_QPA_PLATFORMTHEME"))

# ---- App + window ----------------------------------------------------------
app = QApplication(sys.argv)
win = QMainWindow()
win.resize(800, 500)

# ---- Before
print("=== Qt before ===")

flags_before = int(win.windowFlags())
print("Window flags (hex):         ", hex(flags_before))

base = flags_before & MASK
print("Base type (masked):         ", hex(base))

print("FramelessWindowHint?        ", flag_is_set(win, WT.FramelessWindowHint) if hasattr(WT, "FramelessWindowHint") else False)
print("CustomizeWindowHint?        ", flag_is_set(win, WT.CustomizeWindowHint) if hasattr(WT, "CustomizeWindowHint") else False)
print("BypassWindowManagerHint?    ", flag_is_set(win, WT.BypassWindowManagerHint) if hasattr(WT, "BypassWindowManagerHint") else False)
print("NoDropShadowWindowHint?     ", flag_is_set(win, WT.NoDropShadowWindowHint) if hasattr(WT, "NoDropShadowWindowHint") else False)

# List a few notable flags that are set
CANDIDATES = [
    "Window", "Dialog", "Tool", "Popup", "SubWindow", "SplashScreen", "Desktop",
    "FramelessWindowHint", "CustomizeWindowHint", "BypassWindowManagerHint",
    "NoDropShadowWindowHint", "WindowTitleHint", "WindowSystemMenuHint",
    "WindowMinMaxButtonsHint", "WindowCloseButtonHint", "WindowStaysOnTopHint",
    "WindowStaysOnBottomHint"
]
print("Flags set:")
for name in CANDIDATES:
    if hasattr(WT, name):
        val = int(getattr(WT, name))
        if flags_before & val:
            print(f"  {name} (0x{val:x})")

# ---- Set Flags

# Normalize to a standard decorated window (good for WM shadows on X11)
win.setWindowFlags(WT.Window)
for bad in ("FramelessWindowHint", "CustomizeWindowHint", "Tool",
            "Popup", "SubWindow", "BypassWindowManagerHint"):
    if hasattr(WT, bad):
        win.setWindowFlag(getattr(WT, bad), False)

# Optional: ensure common titlebar buttons
for good in ("WindowTitleHint", "WindowSystemMenuHint",
             "WindowMinMaxButtonsHint", "WindowCloseButtonHint"):
    if hasattr(WT, good):
        win.setWindowFlag(getattr(WT, good), True)

# ---- After
print("=== Qt after ===")

flags_after = int(win.windowFlags())
print("Window flags (hex):         ", hex(flags_after))

base = flags_after & MASK
print("Base type (masked):         ", hex(base))

print("FramelessWindowHint?        ", flag_is_set(win, WT.FramelessWindowHint) if hasattr(WT, "FramelessWindowHint") else False)
print("CustomizeWindowHint?        ", flag_is_set(win, WT.CustomizeWindowHint) if hasattr(WT, "CustomizeWindowHint") else False)
print("BypassWindowManagerHint?    ", flag_is_set(win, WT.BypassWindowManagerHint) if hasattr(WT, "BypassWindowManagerHint") else False)
print("NoDropShadowWindowHint?     ", flag_is_set(win, WT.NoDropShadowWindowHint) if hasattr(WT, "NoDropShadowWindowHint") else False)

# List a few notable flags that are set
CANDIDATES = [
    "Window", "Dialog", "Tool", "Popup", "SubWindow", "SplashScreen", "Desktop",
    "FramelessWindowHint", "CustomizeWindowHint", "BypassWindowManagerHint",
    "NoDropShadowWindowHint", "WindowTitleHint", "WindowSystemMenuHint",
    "WindowMinMaxButtonsHint", "WindowCloseButtonHint", "WindowStaysOnTopHint",
    "WindowStaysOnBottomHint"
]
print("Flags set:")
for name in CANDIDATES:
    if hasattr(WT, name):
        val = int(getattr(WT, name))
        if flags_after & val:
            print(f"  {name} (0x{val:x})")

# Show the window last (after flags are finalized)
win.show()
sys.exit(app.exec())
