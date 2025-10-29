############################################################################################################################################
# General Support Functions
#
#  clip_value, rotate
#  Signals: disconnectconnect, connect, disconnect, wait_for_signal, object_alive
#  Colors: color_to_rgba, rgbafloat_to_rgbaint, rgba_tuple_to_qt
#  Dialog: select_file, confirm_overwrite_append
#  Qt: WidgetVisibilityWatcher
#  Qt Window: sanitize_main_window_flags, window_flags
#  OS environment: setup_graphics_env, probe_qt_gl_vendor
#
# Maintainer: Urs Utzinger
############################################################################################################################################
#
import time, re, os, platform
from math import cos, sin, isfinite, floor, log10, isclose
from pathlib import Path
from typing import Optional, Sequence
#
try:
    import sip                                                                 # PyQt
except Exception:
    sip = None
#
try:
    from PyQt6.QtCore import (QEventLoop, pyqtSignal, QTimer, pyqtSlot, QStandardPaths, 
                              QObject, Qt, QEvent)
    from PyQt6.QtGui import QColor, QOpenGLContext, QSurfaceFormat, QOffscreenSurface
    from PyQt6.QtWidgets import (QFileDialog, QDialogButtonBox, QMessageBox, QApplication, 
                                 QWidget, QMainWindow, QGraphicsView)
    ConnectionType= Qt.ConnectionType
    WindowType    = Qt.WindowType
    DOCUMENTS     = QStandardPaths.StandardLocation.DocumentsLocation
    BUTTON_SAVE   = QDialogButtonBox.StandardButton.Save
    BUTTON_CANCEL = QDialogButtonBox.StandardButton.Cancel
    FILEDIALOG_ACCEPTSAVE = QFileDialog.AcceptMode.AcceptSave
    FILEDIALOG_DONT_USE_NATIVE_DIALOG = QFileDialog.Option.DontUseNativeDialog
    FILEDIALOG_DONT_CONFIRM_OVERWRITE = QFileDialog.Option.DontConfirmOverwrite
    MESSAGEBOX_ICON_WARNING = QMessageBox.Icon.Warning
    MESSAGEBOX_STANDARD_BUTTON = QMessageBox.StandardButton
    EV_TYPE        = QEvent.Type
    EV_SHOW        = QEvent.Type.Show
    EV_PARENTCHG   = QEvent.Type.ParentChange
    EV_RESIZE      = QEvent.Type.Resize
    EV_MOVE        = getattr(QEvent.Type, "Move", None)
    EV_EXPOSE      = getattr(QEvent.Type, "Expose", None)
except Exception:
    from PyQt5.QtCore import (QEventLoop, pyqtSignal, QTimer, pyqtSlot, QStandardPaths, 
                              QObject, Qt, QEvent)
    from PyQt5.QtGui import QColor
    from PyQt5.QtWidgets import (QFileDialog, QDialogButtonBox, QMessageBox, QApplication,
                                 QWidget, QMainWindow, QGraphicsView)
    ConnectionType= Qt
    WindowType    = Qt
    DOCUMENTS     = QStandardPaths.DocumentsLocation
    BUTTON_SAVE   = QDialogButtonBox.Save
    BUTTON_CANCEL = QDialogButtonBox.Cancel
    FILEDIALOG_ACCEPTSAVE = QFileDialog.AcceptSave
    FILEDIALOG_DONT_USE_NATIVE_DIALOG = QFileDialog.DontUseNativeDialog
    FILEDIALOG_DONT_CONFIRM_OVERWRITE = QFileDialog.DontConfirmOverwrite
    MESSAGEBOX_ICON_WARNING = QMessageBox.Warning
    MESSAGEBOX_STANDARD_BUTTON = QMessageBox
    EV_SHOW        = getattr(QEvent, "Show", None)
    EV_PARENTCHG   = getattr(QEvent, "ParentChange", None)
    EV_RESIZE      = getattr(QEvent, "Resize", None)
    EV_MOVE        = getattr(QEvent, "Move", None)
    EV_EXPOSE      = getattr(QEvent, "Expose", None)
#
WATCH_EVENTS = tuple(ev for ev in (EV_SHOW, EV_PARENTCHG, EV_RESIZE, EV_MOVE, EV_EXPOSE) if ev is not None)
#

# ==============================================================================
# General Helper Functions
# ==============================================================================

def clip_value(value, min_value, max_value):
    """ 
    Clip a value to a specified range.
    """
    return max(min_value, min(value, max_value))

def rotate(angle, axis_x, axis_y, axis_z):
    """
    Quaternion representing rotation around the given axis by the given angle.
    """
    a2 = angle/2.0
    c = cos(a2)
    s = sin(a2)
    return (axis_x * s, axis_y * s, axis_z * s, c)

def changed(a, b, rel_tol=1e-6, abs_tol=1e-9):
    if a is None or b is None:
        return True
    return abs(a - b) > max(abs_tol, rel_tol * max(abs(a), abs(b)))
    # isclose function in math is 10 times faster

# ==============================================================================
# Signal/Slot Helpers
# ==============================================================================

def disconnectconnect(signal: pyqtSignal, slot: pyqtSlot, previous_slot: pyqtSlot = None, unique: bool = True)-> bool:
    try:
        if previous_slot is None:
            signal.disconnect()
        else:
            signal.disconnect(previous_slot)
    except TypeError:
        pass
    try:
        signal.connect(slot, type=ConnectionType.UniqueConnection if unique else ConnectionType.AutoConnection)
        return True
    except TypeError:
        return False

def connect(signal: pyqtSignal, slot: pyqtSlot, unique: bool = True)-> bool:
    try:
        signal.connect(slot, type=ConnectionType.UniqueConnection if unique else ConnectionType.AutoConnection)
        return True
    except TypeError:
        return False

def disconnect(signal: pyqtSignal, slot: pyqtSlot = None)-> bool:
    try:
        if slot is None:
            signal.disconnect()
        else:
            signal.disconnect(slot)
        return True
    except TypeError:
        return False

def wait_for_signal(signal, timeout_ms: int = None, sender=None)-> tuple[bool, tuple, str]:
    """
    Block the current thread with a local event loop until `signal` fires or timeout elapses.

    Returns (ok, args, reason), where:
      ok     -> True if signal received, False otherwise
      args   -> tuple of signal arguments (empty tuple if none)
      reason -> "signal" | "timeout" | "destroyed"

    sender (optional): the QObject that owns `signal`. If provided, we also quit
    the loop when the sender is destroyed to avoid waiting the full timeout.
    """
    loop = QEventLoop()
    data = {"args": (), "ok": False, "reason": "timeout"}

    def on_signal(*args):
        data["args"] = args
        data["ok"] = True
        data["reason"] = "signal"
        loop.quit()

    # connect one shot handler
    signal.connect(on_signal)

    timer = None
    if timeout_ms is not None:
        timer = QTimer(loop)
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(timeout_ms)

    # If we know the sender, quit when it’s destroyed (queued to this thread)
    stopper = None
    if sender is not None:
        class _LoopStopper(QObject):
            @pyqtSlot()
            def stop(self):
                data["reason"] = "destroyed"
                loop.quit()
        stopper = _LoopStopper()
        try:
            # QueuedConnection ensures thread-safe invocation into this thread
            sender.destroyed.connect(stopper.stop, type=ConnectionType.QueuedConnection)
        except Exception: 
            try:
                sender.destroyed.connect(stopper.stop)
            except Exception:
                stopper = None                                                 # give up gracefully

    # Qt5 uses exec_(), Qt6 uses exec()
    if hasattr(loop, "exec_"):
        loop.exec_()
    else:
        loop.exec()

    # Clean up connections safely
    try:
        signal.disconnect(on_signal)
    except Exception:
        pass

    if sender is not None and stopper is not None:
        try:
            sender.destroyed.disconnect(stopper.stop)
        except Exception:
            pass

        try:
            stopper.deleteLater()
        except Exception:
            pass

    if timer is not None and timer.isActive():
        try:
            timer.stop()
        except Exception:
            pass

    return data["ok"], data["args"], data["reason"]

def qobject_alive(obj) -> bool:
    """Return True if Qt wrapper still refers to a live C++ object."""
    if obj is None:
        return False
    # Prefer sip on PyQt
    if sip is not None:
        try:
            return not sip.isdeleted(obj)
        except Exception:
            return False
    # Last resort: touch a cheap Qt method; will raise if dead
    try:
        _ = obj.metaObject()
        return True
    except Exception:
        return False

# ==============================================================================
# Color Helpers
# ==============================================================================

def color_to_rgba(name: str) -> tuple[float, float, float, float]:
    """
    Given a CSS color name ("orangered", "blue", "#FF4500", etc.) return
    an (r, g, b, a) tuple of floats in [0,1].
    """
    q = QColor(name)
    # QColor will accept named colors or "#RRGGBB" or "#RRGGBBAA"
    # and default alpha to 1.0 if none provided.
    return (q.redF(), q.greenF(), q.blueF(), q.alphaF())

def rgbafloat_to_rgbaint(color: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    return tuple(int(c * 255) for c in color)

def rgba_tuple_to_qt(rgba):
    """
    Convert (r, g, b, a) floats in 0–1 range into 'rgba(R,G,B,A)' for Qt stylesheets.
    """
    r, g, b, a = rgba
    
# ==============================================================================
# File Dialog Helpers
# ==============================================================================

def select_file(
        stdFileName: str, 
        filter: str="Text files (*.txt)", 
        suffix: str | Sequence[str] = "txt", 
        do_text: str = "Save", 
        cancel_text: str = "Cancel", 
        parent=None) -> Optional[Path]:
    """
    Open a file dialog to select a file.
    Allows custom button text. Uses Qt dialog not OS native.
    - filter: standard Qt name filter string, e.g. "Text (*.txt *.csv);;Binary (*.bin *.dat)"
    - suffix: default suffix or list of defaults; first entry is used if user omits extension.
    Returns Path or None on cancel.
    """
    # Normalize default suffix for setDefaultSuffix (single token, no dot)
    def _norm_one_sfx(s: str) -> str:
        return str(s).strip().lstrip(".").split(".")[-1] if s else ""

    if isinstance(suffix, (list, tuple)):
        default_sfx = _norm_one_sfx(suffix[0] if suffix else "")
    else:
        default_sfx = _norm_one_sfx(suffix)

    parent_widget = parent if isinstance(parent, QWidget) else (QApplication.activeWindow() or None)

    dialog = QFileDialog(parent_widget)
    dialog.setWindowTitle(f"{do_text} as")
    dialog.selectFile(stdFileName)
    dialog.setNameFilter(filter)
    if default_sfx:
        dialog.setDefaultSuffix(default_sfx)
    dialog.setAcceptMode(FILEDIALOG_ACCEPTSAVE)
    dialog.setOption(FILEDIALOG_DONT_USE_NATIVE_DIALOG, True)
    dialog.setOption(FILEDIALOG_DONT_CONFIRM_OVERWRITE, True)

    button_box = dialog.findChild(QDialogButtonBox)
    if button_box:
        save_button   = button_box.button(BUTTON_SAVE)
        cancel_button = button_box.button(BUTTON_CANCEL)
        if save_button:
            save_button.setText(do_text)
        if cancel_button:
            cancel_button.setText(cancel_text)
    try:
        accepted = dialog.exec() == QFileDialog.DialogCode.Accepted
    except AttributeError:
        accepted = dialog.exec_() == QFileDialog.Accepted
    if not accepted:
        return None

    files = dialog.selectedFiles() or []
    if not files:
        return None
    file_path = Path(files[0])

    # Extract allowed suffixes from the selected name filter, e.g. "*.txt *.csv"
    sel_filter = getattr(dialog, "selectedNameFilter", lambda: "")() or ""
    allowed = [m.lower() for m in re.findall(r"\*\.(\w+)", sel_filter)]
    if not allowed:
        # Fallback to provided suffix argument
        if isinstance(suffix, (list, tuple)):
            allowed = [_norm_one_sfx(s) for s in suffix if _norm_one_sfx(s)]
        else:
            s = _norm_one_sfx(suffix)
            allowed = [s] if s else []

    # Apply/adjust extension to match the chosen filter
    current = file_path.suffix.lstrip(".").lower()
    if not current:
        if allowed:
            file_path = file_path.with_suffix("." + allowed[0])
    elif allowed and current not in allowed:
        # Coerce to the first allowed suffix from the selected filter
        file_path = file_path.with_suffix("." + allowed[0])
 
    return file_path

def confirm_overwrite_append(offer_append: bool = True, parent=None) -> str:
    """
    Shows a confirmation dialog for overwriting or appending an existing file.
    """
    parent_widget = parent if isinstance(parent, QWidget) else (QApplication.activeWindow() or None)
    dialog = QMessageBox(parent_widget)
    dialog.setWindowTitle("Confirm Overwrite")
    dialog.setText(
        "The file already exists. Do you want to overwrite it?"
        if not offer_append else
        "The file already exists. Overwrite or append?"
    )    
    dialog.setIcon(MESSAGEBOX_ICON_WARNING)
    if offer_append:
        dialog.setStandardButtons(
            MESSAGEBOX_STANDARD_BUTTON.Yes
            | MESSAGEBOX_STANDARD_BUTTON.No
            | MESSAGEBOX_STANDARD_BUTTON.Cancel
        )
    else:
        dialog.setStandardButtons(
            MESSAGEBOX_STANDARD_BUTTON.Yes
            | MESSAGEBOX_STANDARD_BUTTON.Cancel
        )
    yes_btn = dialog.button(MESSAGEBOX_STANDARD_BUTTON.Yes)
    if yes_btn:
        yes_btn.setText("Overwrite")
    cancel_btn = dialog.button(MESSAGEBOX_STANDARD_BUTTON.Cancel)
    if cancel_btn:
        cancel_btn.setText("Cancel")
    if offer_append:
        append_btn = dialog.button(MESSAGEBOX_STANDARD_BUTTON.No)
        if append_btn:
            append_btn.setText("Append")
    else:
        append_btn = None
    dialog.setDefaultButton(MESSAGEBOX_STANDARD_BUTTON.Cancel)

    try:
        res = dialog.exec()
    except AttributeError:
        res = dialog.exec_()

    if res == MESSAGEBOX_STANDARD_BUTTON.Yes:
        mode = "w"                                                             # Overwrite
    elif offer_append and res == MESSAGEBOX_STANDARD_BUTTON.No:
        mode = "a"                                                             # Append
    else:
        mode = "c"

    return mode


# ==============================================================================
# Widget Visibility Watcher
# ==============================================================================

class WidgetVisibilityWatcher(QObject):
    """
    Watches a QWidget and emits:
      becameVisible -> when widget (and parents) become visible
      becameExposed -> when underlying QWindow is exposed
      timedOut      -> when timeout_ms elapsed before required condition

    Parameters:
    widget                  -> The QWidget to watch.
    parent                  -> Optional QObject parent.
    require_exposed         -> If True (default), requires QWindow to be exposed.
    timeout_ms              -> Timeout duration in milliseconds.
    poll_interval_ms        -> Polling interval in milliseconds.
    one_shot                -> If True (default), stops watching after first successful condition.
    """
    becameVisible = pyqtSignal()
    becameExposed = pyqtSignal()
    timedOut      = pyqtSignal()

    def __init__(self, widget, parent=None, require_exposed=True,
                 timeout_ms: int | None = None, poll_interval_ms: int = 120,
                 one_shot: bool = True):
        super().__init__(parent)
        self._w = widget
        self._require_exposed = require_exposed
        self._timeout_ms = timeout_ms
        self._poll_ms = max(15, poll_interval_ms)
        self._one_shot = one_shot
        self._start_time = time.perf_counter()
        self._timed_out = False
        self._visible_emitted = False
        self._exposed_emitted = False
        widget.installEventFilter(self)

        # Initial check next loop
        QTimer.singleShot(0, self._check)
        if self._timeout_ms is not None:
            QTimer.singleShot(self._poll_ms, self._poll_loop)

    def eventFilter(self, obj, ev):
        if obj is self._w and ev.type() in WATCH_EVENTS:
            self._check()
        return False

    def _emit_visible(self):
        if not self._visible_emitted:
            self._visible_emitted = True
            self.becameVisible.emit()

    def _emit_exposed(self):
        if not self._exposed_emitted:
            self._exposed_emitted = True
            self.becameExposed.emit()

    def _finalize_if_one_shot(self):
        if self._one_shot and (self._visible_emitted and
                               (not self._require_exposed or self._exposed_emitted)):
            try:
                self._w.removeEventFilter(self)
            except Exception:
                pass

    def _check(self):
        if self._timed_out:
            return
        if not self._w.isVisible():
            return

        if self._require_exposed:
            wh = self._w.windowHandle()
            if wh is None:
                return
            if not wh.isExposed():
                # connect to exposed just once
                try:
                    wh.exposed.disconnect(self._on_exposed)
                except Exception:
                    pass
                wh.exposed.connect(self._on_exposed)
                # still emit becameVisible? Only if not requiring exposure (so skip here)
                return
            # Already exposed
            self._emit_visible()
            self._emit_exposed()
        else:
            self._emit_visible()

        self._finalize_if_one_shot()

    def _on_exposed(self):
        wh = self._w.windowHandle()
        if wh and wh.isExposed():
            # ensure visible signal first (some platforms dispatch exposed before a Show resize)
            if self._w.isVisible():
                self._emit_visible()
            self._emit_exposed()
            self._finalize_if_one_shot()

    def _poll_loop(self):
        if self._timed_out:
            return
        # Condition satisfied → nothing further (check already emitted)
        if (self._visible_emitted and
            (not self._require_exposed or self._exposed_emitted)):
            return
        elapsed_ms = (time.perf_counter() - self._start_time) * 1000.0
        if self._timeout_ms is not None and elapsed_ms >= self._timeout_ms:
            self._timed_out = True
            self.timedOut.emit()
            self._finalize_if_one_shot()
            return
        QTimer.singleShot(self._poll_ms, self._poll_loop)

# ==============================================================================
# Window Flag Helpers
# ==============================================================================

# Written to debug the window appearance under different desktop managers
def window_flags(win: QWidget)->tuple[list[str], list[str]]:
    """
    Human-readable inspector that avoids false positives.
    """
    flags = win.windowFlags()

    type_names = [
        "Window", "Dialog", "Sheet", "Drawer", "Popup", "Tool", "ToolTip",
        "SplashScreen", "Desktop", "ForeignWindow", "CoverWindow", "SubWindow",
    ]
    hint_names = [
        "WindowTitleHint", "WindowSystemMenuHint",
        "WindowMinimizeButtonHint", "WindowMaximizeButtonHint",
        "WindowMinMaxButtonsHint", "WindowCloseButtonHint",
        "FramelessWindowHint", "CustomizeWindowHint",
        "BypassWindowManagerHint", "NoDropShadowWindowHint",
    ]

    set_type  = [n for n in type_names if getattr(WindowType, n, None) and (flags & getattr(WindowType, n))]
    set_hints = [n for n in hint_names if getattr(WindowType, n, None) and (flags & getattr(WindowType, n))]
    return set_type, set_hints

def sanitize_main_window_flags(win: QMainWindow) -> None:
    """
    Ensure a normal top-level window:
      - Type = Window
      - Good hints on (title, system menu, min/max/close)
      - Known-problematic flags cleared
    Works in Qt5/Qt6
    """
    flags = win.windowFlags()
    try:
        mask = WindowType.WindowType_Mask
    except AttributeError:
        mask = None 

    # 1) Clear any existing *type* bits, then set Window
    if mask is not None:
        flags &= ~mask
    else:
        # Fallback if mask isn’t available: clear by OR-ing known types
        type_bits = (  getattr(WindowType, "Window", 0)
                     | getattr(WindowType, "Dialog", 0)
                     | getattr(WindowType, "Sheet", 0)
                     | getattr(WindowType, "Drawer", 0)
                     | getattr(WindowType, "Popup", 0)
                     | getattr(WindowType, "Tool", 0)
                     | getattr(WindowType, "ToolTip", 0)
                     | getattr(WindowType, "SplashScreen", 0)
                     | getattr(WindowType, "Desktop", 0)
                     | getattr(WindowType, "ForeignWindow", 0)
                     | getattr(WindowType, "CoverWindow", 0)
                     | getattr(WindowType, "SubWindow", 0))
        flags &= ~type_bits

    flags |= getattr(WindowType, "Window")

    # 2) Remove problematic flags (existence-checked for Qt5/Qt6)
    for name in (
        "FramelessWindowHint",
        "CustomizeWindowHint",
        "Tool",
        "Popup",
        "SubWindow",
        "BypassWindowManagerHint",
        "NoDropShadowWindowHint",
    ):
        val = getattr(WindowType, name, None)
        if val and (flags & val):
            flags &= ~val

    # 3) Ensure standard hints are present
    for name in (
        "WindowTitleHint",
        "WindowSystemMenuHint",
        "WindowMinMaxButtonsHint",
        "WindowCloseButtonHint",
    ):
        val = getattr(WindowType, name, None)
        if val:
            flags |= val

    was_visible = win.isVisible()
    win.setWindowFlags(flags)
    if was_visible:
        win.show()                                                             # must re-show after changing flags
 
# ==============================================================================
# Graphics Environment Setup
# ==============================================================================

def setup_graphics_env(
    prefer_discrete_gpu: bool = True,
    force_backend: str | None = None,                                          # "vulkan" | "dx12" | "metal" | "gl" | None(auto)
    wayland_ok: bool = True,
    verbose_logs: bool = False,
):
    """
    Set up environment variables to steer graphics backends on Linux, Windows, macOS.
    This should be run before importing any Qt, wgpu, pygfx, fastplotlib, pyqtgraph modules.

    prefer_discrete_gpu: 
        if True, bias to dGPU if available; else bias to iGPU.
    force_backend: 
        "Vulkan" | "WebGPU" | "D3D11" | "D3D12" | "Metal" | "OpenGL" | "OpenGLES"| None(auto)
    wayland_ok: 
        if False, forces X11 on Linux even if Wayland session.
    verbose_logs: 
        if True, enables RUST_LOG for wgpu logs if not already set
    """
    sys = platform.system()

    # Common: 
    #   make wgpu logs visible if you need them
    #   make Qt plugin loading verbose
    if verbose_logs and "RUST_LOG" not in os.environ:
        os.environ["RUST_LOG"] = "wgpu_core=info,wgpu_hal=info,wgpu_native=info,naga=warn"
        os.environ["QT_DEBUG_PLUGINS"] = "1"
    else:
        os.environ["RUST_LOG"] = "error" 
        os.environ["QT_DEBUG_PLUGINS"] = "0"

    if sys == "Linux":
        # Detect session
        sess = os.environ.get("XDG_SESSION_TYPE", "").lower()
        if not sess:
            if os.environ.get("WAYLAND_DISPLAY"): 
                sess = "wayland"
            elif os.environ.get("DISPLAY"):       
                sess = "x11"

        # Choose Qt platform
        if sess == "wayland" and wayland_ok:
            os.environ.setdefault("QT_QPA_PLATFORM", "wayland")
            # Better portals on Wayland (file dialogs/screen share)
            os.environ.setdefault("QT_QPA_PLATFORMTHEME", "xdgdesktopportal")
            # Qt Quick (if used) -> Vulkan to match wgpu
            os.environ.setdefault("QSG_RHI_BACKEND", "Vulkan")
        else:
            # Force X11 (safer for GLX and also fine for Vulkan)
            os.environ["QT_QPA_PLATFORM"] = "xcb"
            # If GL ever gets used, prefer GLX over EGL to avoid EGL_BAD_ACCESS
            os.environ.setdefault("QT_XCB_GL_INTEGRATION", "xcb_glx")
            # Keep Qt Quick on Vulkan (or set to 'software' for debugging)
            os.environ.setdefault("QSG_RHI_BACKEND", "vulkan")

        # Pick wgpu backend (default Vulkan)
        backend = (force_backend or "Vulkan")
        os.environ["WGPU_BACKEND_TYPE"] = backend

        # Power preference steers adapter choice
        os.environ["WGPU_POWER_PREFERENCE"] = (
            "high-performance" if prefer_discrete_gpu else "low-power"
        )

        # Hybrid NVIDIA laptops: if you want dGPU, you typically launch with `prime-run`.
        # If not using prime-run, these hints can help (ignored on non-NVIDIA setups):
        if prefer_discrete_gpu:
            os.environ.setdefault("__NV_PRIME_RENDER_OFFLOAD", "1")
            os.environ.setdefault("__GLX_VENDOR_LIBRARY_NAME", "nvidia")
            # Vulkan ICD hint (usually not needed if prime-run is available)
            # os.environ.setdefault("VK_ICD_FILENAMES", "/usr/share/vulkan/icd.d/nvidia_icd.json")

        # If you *must* force OpenGL instead of Vulkan on X11, avoid EGL:
        if backend == "OpenGL":
            os.environ.setdefault("WGPU_GL_BACKEND", "OpenGL")

    elif sys == "Windows":
        # Direct3D 12 is the native path
        os.environ["WGPU_BACKEND_TYPE"] = (force_backend or "D3D12")
        os.environ["WGPU_POWER_PREFERENCE"] = (
            "HighPerformance" if prefer_discrete_gpu else "LowPower"
        )
        # Qt Quick RHI to D3D12 (or leave default which may be D3D11/D3D12)
        os.environ.setdefault("QSG_RHI_BACKEND", "d3d12")
        # Qt platform is 'windows' by default; no change needed.

        # Optional: request high-performance GPU on Windows via DXGI preference env
        # (Windows also has per-app “Graphics performance preference” in Settings)
        os.environ.setdefault("QT_OPENGL", "desktop")                          # if you ever use Qt/GL, prefer desktop GL

    elif sys == "Darwin":                                                      # macOS
        # Metal is the only real choice
        os.environ["WGPU_BACKEND_TYPE"] = (force_backend or "Metal")
        os.environ["WGPU_POWER_PREFERENCE"] = (
            "HighPerformance" if prefer_discrete_gpu else "LowPower"
        )
        # Qt Quick on Metal
        os.environ.setdefault("QSG_RHI_BACKEND", "metal")
        # Qt platform is 'cocoa' by default; no change needed.

def probe_qt_gl_vendor(widget=None):
    """
    Offscreen GL probe on the same screen; empty dict if GL not available.
    What adapter would GL use on this screen?
    """
    try:
        from PyQt6.QtGui import QOpenGLContext, QSurfaceFormat, QOffscreenSurface, QGuiApplication
        from OpenGL import GL
        screen = None
        if widget is not None:
            win = getattr(widget, "windowHandle", None)
            win = win() if callable(win) else win
            if win: 
                screen = win.screen()
        if screen is None:
            screen = QGuiApplication.primaryScreen()

        fmt = QSurfaceFormat()
        ctx = QOpenGLContext() 
        ctx.setFormat(fmt)
        if screen: 
            ctx.setScreen(screen)
        if not ctx.create(): 
            return {}
        surf = QOffscreenSurface(screen)
        surf.setFormat(fmt)
        surf.create()
        if not ctx.makeCurrent(surf): 
            return {}
        info = {
            "vendor":   (GL.glGetString(GL.GL_VENDOR)   or b"").decode(errors="ignore"),
            "renderer": (GL.glGetString(GL.GL_RENDERER) or b"").decode(errors="ignore"),
            "version":  (GL.glGetString(GL.GL_VERSION)  or b"").decode(errors="ignore"),
        }
        ctx.doneCurrent()
        return info
    except Exception:
        return {}

def find_gl_consumers(root: QWidget):
    """
    Return a dict listing widgets that would create/use OpenGL (or GPU RHI).

    If your app has loaded OpenGL contexts already,
    you should not use a non-GL interface for pygfx/wgpu, otherwise your app will panic.
    """
    hits = {
        "QOpenGLWidget": [],
        "QQuick*": [],
        "QWebEngine*": [],
        "QGraphicsView_with_GL_viewport": [],
    }

    stack = [root]
    while stack:
        w = stack.pop()
        stack.extend(w.findChildren(QWidget))

        # 1) OpenGL widgets (Qt5 legacy + Qt6)
        try:
            from PyQt6.QtOpenGLWidgets import QOpenGLWidget                    # Qt6 module
        except Exception:
            QOpenGLWidget = None
        if QOpenGLWidget and isinstance(w, QOpenGLWidget):
            hits["QOpenGLWidget"].append(w)

        # 2) Qt Quick
        try:
            from PyQt6.QtQuickWidgets import QQuickWidget
            if isinstance(w, QQuickWidget):
                hits["QQuick*"].append(w)
        except Exception:
            pass

        # 3) WebEngine (Chromium)
        try:
            from PyQt6.QtWebEngineWidgets import QWebEngineView
            if isinstance(w, QWebEngineView):
                hits["QWebEngine*"].append(w)
        except Exception:
            pass

        # 4) QGraphicsView using an OpenGL viewport
        if isinstance(w, QGraphicsView):
            vp = w.viewport()
            if QOpenGLWidget and isinstance(vp, QOpenGLWidget):
                hits["QGraphicsView_with_GL_viewport"].append(w)

    return {k: v for k, v in hits.items() if v}                                # prune empties

def is_widget_gl_free(root: QWidget) -> bool:
    """True if no known GL-using components are found under root."""
    return not find_gl_consumers(root)

def has_current_gl_context_gui_thread() -> bool:
    """True if there is a current OpenGL context in the current (GUI) thread."""
    return QOpenGLContext.currentContext() is not None
