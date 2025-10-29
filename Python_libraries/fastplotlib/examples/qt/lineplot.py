"""
Lineplot
========

Complex example for lineplot in PyQt that displays 3 traces.
The plot is black on white with a legend on the right.

For testing purpose we plot in a tabbed widget.

We defer figure creation until the QT UI is visible.
The animation starts when the user selects the plot tab.
"""
import sys
import numpy as np
import time
from math import pi, cos, sin, log10, floor, isfinite, ceil

RENDERING_HARDWARE = "NVIDIA"    # will likely use Vulkan backend
#RENDERING_HARDWARE = "Radeon"   # AMD GPU, will likely use Vulkan backend
#RENDERING_HARDWARE = "CPU"      # will use CPU/LLVM backend (slow)
#RENDERING_HARDWARE = "OPENGL"   # will likely use CPU integrated GPU using OpenGL backend

try:
    from PyQt6.QtWidgets import (
        QApplication, QWidget, QVBoxLayout, QMainWindow,
        QLabel, QTabWidget, QSizePolicy, QWIDGETSIZE_MAX
    )
    from PyQt6.QtCore import QTimer, Qt, QSize, QEvent

except ImportError:
    from PyQt5.QtWidgets import (
        QApplication, QWidget, QVBoxLayout, QMainWindow,
        QLabel, QTabWidget, QSizePolicy, QWIDGETSIZE_MAX
    )
    from PyQt5.QtCore import QTimer, Qt, QSize, QEvent

import fastplotlib as fpl
from fastplotlib.legends import Legend
import pygfx, wgpu

print("pygfx", pygfx.__version__, "wgpu", wgpu.__version__)
print("fastplotlib:", getattr(fpl, "__version__", "local-build"))
print('file=', fpl.__file__);
print('version=', getattr(fpl,'__version__','?'))
import importlib.metadata as im
print("dist-info version       =", im.version("fastplotlib"))

def rotate(angle, axis_x, axis_y, axis_z):
    """
    Quaternion representing rotation around the given axis by the given angle.
    Useful to rotate text labels.
    """
    a2 = angle/2.0
    c = cos(a2)
    s = sin(a2)
    return (axis_x * s, axis_y * s, axis_z * s, c)

class FastPlotMain(QMainWindow):

    MAJOR_TICKS = 5                       # axis ticks
    MINOR_TICKS = 4                       # axis ticks
    DATAPOINTS  = 50_000                  # number of data points per line
    WHITE       = (1.0, 1.0, 1.0, 1.0)    # Some colors
    BLACK       = (0.0, 0.0, 0.0, 1.0)
    RED         = (1.0, 0.0, 0.0, 1.0)
    GREEN       = (0.0, 1.0, 0.0, 1.0)
    BLUE        = (0.0, 0.0, 1.0, 1.0)
    DARK_GRAY   = (0.2, 0.2, 0.2, 1.0)
    LIGHT_GRAY  = (0.9, 0.9, 0.9, 1.0)
    
    def __init__(self):
        super().__init__()

        # ─── Adapter ──────────────────────────────────────────────────────────────
        # This can be done automatically but for testing purpose I want to select 
        #   a specific adapter
        chosen_index = 0
        adapters = fpl.enumerate_adapters()
        for idx, adapter in enumerate(adapters):
            print(f"[{idx}] {adapter.summary}")
            if RENDERING_HARDWARE.lower() in adapter.summary.lower():
                chosen_index = idx
        print(f"Using adapter: {chosen_index}")
        fpl.select_adapter(adapters[chosen_index])

        # ─── Window ──────────────────────────────────────────────────────────────
        self.setWindowTitle("fastplotlib Line Plot Test")

        # ─── Figure & Subplot ────────────────────────────────────────────────────
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        
        # Tab 0: place holder
        # We dont need a tabbed widget, but I want to test creating a figure
        #   in a widget that resides in a tab
        self.info_tab = QWidget()
        info_layout = QVBoxLayout(self.info_tab)
        info_layout.addWidget(QLabel("Open the plot tab to see the figure."))
        self.tabs.addTab(self.info_tab, "Overview")

        # Tab 1: plot container
        # Animation will occur in this widget
        self.plot_tab = QWidget()
        self.plot_tab.setContentsMargins(0, 0, 0, 0)
        self.plot_layout = QVBoxLayout(self.plot_tab)
        self.plot_layout.setContentsMargins(0, 0, 0, 0)
        self.plot_layout.setSpacing(0)
        self.tabs.addTab(self.plot_tab, "Plot")

        # Start Stop animation when user selects tab
        self.tabs.currentChanged.connect(self.on_tab_changed)

        # ─── Data & Graphics ─────────────────────────────────────────────────────
        # Initialize data arrays

        # Time base
        t = np.linspace(-2*np.pi,2*np.pi,self.DATAPOINTS, dtype = np.float32)
        self.t = t
        self.phase1 = 0.0
        self.phase2 = pi/2.
        N = self.t.size

        # Pre-allocate three (N×2) float32 buffers:
        self.buf1 = np.empty((N, 2), dtype=np.float32)
        self.buf2 = np.empty((N, 2), dtype=np.float32)
        self.buf3 = np.empty((N, 2), dtype=np.float32)

        # Fill the x column 
        self.buf1[:, 0] = self.t 
        self.buf2[:, 0] = self.t
        self.buf3[:, 0] = self.t

        # Fill the  y column 
        np.sin(self.t + self.phase1, out=self.buf1[:, 1])
        self.buf2[:, 1] = np.random.rand(N).astype(np.float32) + 1.0
        np.sin(self.t + self.phase2, out=self.buf3[:, 1]); self.buf3[:, 1] -= 1.0

        # ─── Benchmark ──────────────────────────────────────────────────────────
        # Initialize benchmark variables

        self.last_time = time.perf_counter()
        self.last_time_reporting = time.perf_counter()
        self.num_segments = 0
        self.generating_time = 0.0
        self.total_time = 0.0
        self.delta_avg = 0.020
        # How much CPU time is left for the Qt event loop?
        self.cpu_start  = time.process_time()
        self.wall_start = time.perf_counter()

        # ───
        self.animTimer = None
        self.figure_initialized = False

    def showEvent(self, ev):
        """Qt calls this when the window is shown."""
        super().showEvent(ev)
        if not self.figure_initialized:
            QTimer.singleShot(0, self.figure_init)

    def closeEvent(self, ev):
        """Qt calls this when the window is closed."""
        if self.animTimer:
            self.animTimer.stop()
        if hasattr(fpl, "loop"):
            try:
                fpl.loop.stop()
            except Exception:
                pass
        return super().closeEvent(ev)

    def changeEvent(self, ev):
        """Handle minimize / restore without re-creating the figure."""
        if ev.type() == QEvent.Type.WindowStateChange:
            if self.windowState() & Qt.WindowState.WindowMinimized:
                # Optionally pause animation when minimized
                if self.animTimer:
                    self.animTimer.stop()
            else:
                # Restored
                if (self.animTimer
                        and not self.animTimer.isActive()
                        and self.tabs.currentWidget() is self.plot_tab):
                    self.animTimer.start(0)
        super().changeEvent(ev)

    def figure_init(self):
        """
        Initialize the fastplotlib figure and subplot.
        This is called once the Qt UI is visible.
        """

        if self.figure_initialized:
            return  # already done
        
        self.figure_initialized = True

        self.fig = fpl.Figure(
            # canvas="qt",
            canvas_kwargs={"parent": self.plot_tab},
            shape=(1,1), 
            names=[["Chart FPL"]],
            size=(800, 600),
            show_tooltips=True
        )
        self.chartWidget = self.fig.show(autoscale=False, maintain_aspect=True) # show the figure
        self.chartWidget.setContentsMargins(0, 0, 0, 0)
        self.plot_layout.addWidget(self.chartWidget)

        self.subplot = self.fig[0, 0]
        self.subplot.axes.visible = True
        self.subplot.background_color = self.WHITE

        # Title and Tool Background Color

        self.subplot.frame.plane.material.color = self.LIGHT_GRAY
        pc = getattr(self.subplot.frame, "plane_color", None)
        if pc is not None:
            idle_color      = tuple(min(c * 0.8, 1.0) for c in self.LIGHT_GRAY[:3]) # Slightly darker
            highlight_color = tuple(min(c * 1.0, 1.0) for c in self.LIGHT_GRAY[:3]) #
            action_color    = self.LIGHT_GRAY[:2] + (min(self.LIGHT_GRAY[2] * 1.2, 1.0),) #
            if hasattr(pc, "_replace") and hasattr(pc, "idle") and hasattr(pc, "highlight"):
                try:
                    self.subplot.frame.plane_color = pc._replace(
                        idle      = idle_color,
                        highlight = highlight_color,
                        action    = action_color
                    )
                except Exception:
                    pass
            else:
                # Attribute style fallback
                for attr_name, val in (
                    ("idle",      idle_color),
                    ("highlight", highlight_color),
                    ("action",    action_color),
                    ("normal",    self.LIGHT_GRAY),
                    ("base",      self.LIGHT_GRAY),
                    ("hover",     highlight_color),
                ):
                    if hasattr(pc, attr_name):
                        try:
                            setattr(pc, attr_name, val)
                        except Exception:
                            pass

        # Title

        self.subplot.title = "Line Plots"
        self.subplot.title.face_color = self.BLACK
        self.subplot.title.outline_color = self.BLACK

        # X label

        self.subplot.docks["bottom"].size = 30
        self.subplot.docks["bottom"].add_text(
            "X",
            font_size=16,
            face_color=(0, 0, 0, 1),
            anchor="middle-center",
            offset=(0, 0, 0),
        )
        self.subplot.docks["bottom"].background_color = self.WHITE

        # Y label

        q = rotate(pi/2.0, 0., 0., 1.)  # rotate 90 deg around z-axis
        self.subplot.docks["left"].size = 30
        self.subplot.docks["left"].add_text(
            "Y",
            font_size=16,
            face_color=(0, 0, 0, 1),
            anchor="middle-center",
            offset=(0, 0, 0),
            rotation=q,
        )
        self.subplot.docks["left"].background_color = self.WHITE

        # Grid

        if self.subplot.axes.grids:
            self.subplot.axes.grids.xy.visible = True
            self.subplot.axes.grids.xy.color   = self.DARK_GRAY

        # ─── Data & Graphics ─────────────────────────────────────────────────────

        # Add the lines to the plot axis
        self.line1 = self.subplot.add_line(self.buf1, colors=self.RED)
        self.line2 = self.subplot.add_line(self.buf2, colors=self.BLACK)
        self.line3 = self.subplot.add_line(self.buf3, colors=self.BLUE)

        # ─── Legend ─────────────────────────────────────────────────────────────
        
        legend_dock = self.subplot.docks["right"]  # options are right, left, top, bottom
        legend_dock.background_color = self.WHITE
        # legend_dock = self.subplot  # not working yet, no floating legend on top of plot
        legend_dock.size = 200                # if top/bottom dock that is the height of dock in pixels, 
                                              # if left/right dock that is the width of the dock in pixels,
        try:
            self.legend = Legend(
                plot_area = legend_dock,          # the plot area to attach the legend to
                background_color=self.LIGHT_GRAY, # optional: the background color of the legend
                max_rows = 5,                     # how many items per column before wrapping
                label_color = self.BLACK           # UU: default label color
            )
        except Exception:
            self.legend = Legend(
                plot_area=legend_dock,            # the plot area to attach the legend to
                max_rows = 5                      # how many items per column before wrapping
            )

        self.lines = [self.line1, self.line2, self.line3]
        self.labels = ["sin(x)", "rand + 1", "sin(x + θ) - 1"]
        for lg, label in zip(self.lines, self.labels):
            self.legend.add_graphic(lg, label, label_color=self.BLACK)  # UU: label_color

        # ─── Animation Timer ────────────────────────────────────────────────────
        self.animTimer = QTimer(self)
        self.animTimer.setTimerType(Qt.TimerType.PreciseTimer)
        self.animTimer.timeout.connect(self.animate)
        self.animTimer.stop()
     
        QTimer.singleShot(0, lambda: self.resize_for_canvas(800, 600, target=self.plot_tab))
 
    def figure_finalize(self):
        """
        Finalize the figure setup and start the animation timer.
        This is called once the Qt UI is visible and the canvas has a valid size.
        """

        if not self.figure_initialized:
            return # figure  not yet created

        # Wait until figure is visible
        if not (self.chartWidget.isVisible() and self.chartWidget.isVisibleTo(self)):
           return QTimer.singleShot(0, self.figure_finalize)  # try again later

        # Wait until canvas has a valid size
        w_log, h_log = self.fig.canvas.get_logical_size()
        dpr = self.fig.canvas.get_pixel_ratio()
        w = int(w_log * dpr)
        h = int(h_log * dpr)
        if w < 2 or h < 2:
            return QTimer.singleShot(10, self.figure_finalize)    

        # Finalize the axes, legend and start the animation
        self.subplot.auto_scale(maintain_aspect=True, zoom=0.9)
        self.updateAxesTicks(self.subplot, self.MAJOR_TICKS, self.MINOR_TICKS)
        try:
            self.subplot.axes.update_using_camera()
        except Exception:
            pass
        self.legend.update_using_camera()
        self.fig.canvas.request_draw()
        self.animTimer.start(0)

    def on_tab_changed(self, idx):
        is_plot = (self.tabs.tabText(idx) == "Plot")  # or compare by widget
        if is_plot:
            QTimer.singleShot(0, self.figure_finalize)
        else:
            self.animTimer.stop()

    def resize_for_canvas(self, width: int, height: int,
                          target: QWidget | None = None) -> None:
        """
        Resize the window so the central widget (canvas) becomes width x height.
        Set physical_pixels=True to request physical pixel size on HiDPI screens.
        """
        if target is None:
            target = getattr(self, "chartWidget", None) or self.centralWidget()

        # If targeting physical pixels, convert to Qt logical pixels using DPR
        dpr = max(1.0, self.devicePixelRatioF())
        target_w = ceil(width / dpr)
        target_h = ceil(height / dpr)

        target.setMinimumSize(target_w, target_h)
        target.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)
        target.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        # Resize the window
        self.adjustSize()

    def updateAxesTicks(self, subplot, n_major, n_minor):
        """
        Update the tick marks of the x and y axis for a given Fastplotlib subplot.
        Uses a 1 - 2 - 5 ladder to pick readable major/minor steps.
        Caches previous results to avoid unnecessary updates.
        """

        # --- helper (scalar) ---
        def nice_step(lo: float, hi: float, n: int) -> tuple[float, int]:
            """Return (major_step, decimals) for ~n ticks over [lo, hi]."""
            rng = float(hi) - float(lo)
            if not isfinite(rng) or rng <= 0.0:
                rng = 1.0
            n = int(n) if n and n > 0 else 5
            rough = rng / n
            if not isfinite(rough) or rough <= 0.0:
                rough = 1.0

            e = floor(log10(rough))
            f = rough / (10.0 ** e)
            if f <= 1.0:   base = 1.0
            elif f <= 2.0: base = 2.0
            elif f <= 5.0: base = 5.0
            else:          base = 10.0

            major = base * (10.0 ** e)
            decimals = max(0, -floor(log10(major))) if major < 1.0 else 0
            return major, decimals

        # --- axes / extents ---
        xr, yr = subplot.axes.x, subplot.axes.y

        xmin, _, _ = xr.start_pos
        xmax, _, _ = xr.end_pos
        _, ymin, _ = yr.start_pos
        _, ymax, _ = yr.end_pos

        # handle reversed ranges
        if xmax < xmin: xmin, xmax = xmax, xmin
        if ymax < ymin: ymin, ymax = ymax, ymin

        span_x = max(1e-12, xmax - xmin)
        span_y = max(1e-12, ymax - ymin)

        # --- per-subplot cache to avoid churn ---
        cache = getattr(self, "_tick_cache", None)
        if cache is None:
            cache = self._tick_cache = {}

        prev = cache.get(subplot)
        if prev:
            if (abs((span_x - prev["span_x"]) / prev["span_x"]) < 0.03 and
                abs((span_y - prev["span_y"]) / prev["span_y"]) < 0.03 and
                prev.get("n_major") == n_major and prev.get("n_minor") == n_minor):
                return  # nothing meaningful changed

        # --- compute & apply steps ---
        maj_x, dec_x = nice_step(xmin, xmax, n_major)
        maj_y, dec_y = nice_step(ymin, ymax, n_major)
        minor_div = max(int(n_minor), 1)

        xr.major_step = maj_x
        xr.minor_step = maj_x / minor_div
        yr.major_step = maj_y
        yr.minor_step = maj_y / minor_div

        # Some FPL versions support tick_format; keep safe
        try:
            xr.tick_format = f".{dec_x}f"
            yr.tick_format = f".{dec_y}f"
        except Exception:
            pass

        # update cache
        cache[subplot] = {
            "span_x": span_x, "span_y": span_y,
            "n_major": n_major, "n_minor": n_minor
        }

        # --- style once per subplot (optional) ---
        if not getattr(subplot, "_ticks_styled", False):
            xr.line.material.color = self.BLACK
            yr.line.material.color = self.BLACK

            if xr.ticks is not None:   xr.ticks.material.color = self.BLACK
            if xr.points is not None:  xr.points.material.color = self.BLACK
            if xr.text is not None:    xr.text.material.color = self.BLACK

            if yr.ticks is not None:   yr.ticks.material.color = self.BLACK
            if yr.points is not None:  yr.points.material.color = self.BLACK
            if yr.text is not None:    yr.text.material.color = self.BLACK

            if subplot.axes.grids:
                gxy = subplot.axes.grids.xy
                gxy.visible = True
                gxy.axis_color = self.BLACK
                gxy.major_color = self.BLACK
                gxy.minor_color = self.DARK_GRAY
                gxy.major_thickness = 1.0
                gxy.minor_thickness = 0.5

            subplot._ticks_styled = True

        subplot.axes.update_using_camera()

    def animate(self):
        """
        Update the data and request a redraw of the figure. 
        """

        # compute how much time has passed since last report
        tic_start = time.perf_counter()
        now_cpu   = time.thread_time()
        wall_elapsed = tic_start - self.wall_start
        cpu_elapsed  = now_cpu   - self.cpu_start

        delta = tic_start - self.last_time
        self.total_time += delta
        self.last_time = tic_start
        self.delta_avg = 0.9*self.delta_avg + 0.1*delta

        delta_reporting = tic_start - self.last_time_reporting
        if delta_reporting >= 1.0:
            cpu_pct  = cpu_elapsed / wall_elapsed * 100.0
            print(
                f"Lines/s: {int(self.num_segments/(self.total_time-self.generating_time)):,}, "
                f"Interval: {self.total_time:.3f} "
                f"Generating: {self.generating_time/self.total_time*100.:.1f}% "
                f"FPS: {1.0/self.delta_avg:.2f} "
                f"Python Main Thread usage: {cpu_pct:.1f}%"
            )                  
            # Reset the counters
            self.last_time_reporting = tic_start
            self.num_segments = 0
            self.total_time = 0.0
            self.generating_time = 0.0
            self.wall_start = tic_start
            self.cpu_start  = now_cpu

        tic = time.perf_counter()

        # Generate the data

        # Increment phases (animate plots)
        self.phase1 += 0.01  * delta*1000.
        self.phase2 += 0.0101 * delta*1000.

        #   Line 1: sin(t+phase1) in-place
        np.sin(self.t + self.phase1, out=self.buf1[:, 1])
        #   Line 2: rand+1; since rand() has no `out` kwarg, write into buf2[:,1] by slicing:
        self.buf2[:, 1] = np.random.rand(self.t.size).astype(np.float32) + 1.0
        #   Line 3: sin(t+phase2)-1 in-place
        np.sin(self.t + self.phase2, out=self.buf3[:, 1])
        self.buf3[:, 1] -= 1.0

        self.generating_time += time.perf_counter() - tic

        # Update the data in the plot lines
        self.line1.data[:, 1] = self.buf1[:, 1]
        self.line2.data[:, 1] = self.buf2[:, 1]
        self.line3.data[:, 1] = self.buf3[:, 1]

        # Schedule drawing the figure
        self.fig.canvas.request_draw()

        # Benchmark number of segments drawn per second
        self.num_segments += 3 * self.t.size 

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = FastPlotMain()
    win.show()
    sys.exit(app.exec())
