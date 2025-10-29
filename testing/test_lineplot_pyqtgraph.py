"""
Lineplot Qt
===========
Using pyqtgraph.

Complex example for lineplot in PyQt that displays 3 traces.
The plot is a standard black on white with a legend on the right.
"""
import sys
import numpy as np
import time
from math import pi, sin

try:
    from PyQt6.QtWidgets import QApplication, QMainWindow
    from PyQt6.QtCore import QTimer, Qt
except ImportError:
    from PyQt5.QtWidgets import QApplication, QMainWindow
    from PyQt5.QtCore import QTimer, Qt

import pyqtgraph as pg
from pyqtgraph import PlotWidget, mkPen

class PGPlotMain(QMainWindow):
    DATAPOINTS = 50_000

    def __init__(self):
        super().__init__()
        self.setWindowTitle("pyqtgraph Line Plot Test")
        self.resize(800, 600)

        # ─── PlotWidget & Appearance ────────────────────────────────────────────
        self.plotw = PlotWidget(background='w')
        self.setCentralWidget(self.plotw)
        self.plot = self.plotw.getPlotItem()
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.plot.getAxis('left').setPen('k')
        self.plot.getAxis('bottom').setPen('k')
        self.plot.setLabel('bottom', 'X')
        self.plot.setLabel('left',   'Y')
        self.plot.addLegend(offset=(600, 300))

        # ─── Data Buffers ─────────────────────────────────────────────────────────
        self.t = np.linspace(-2*np.pi, 2*np.pi, self.DATAPOINTS, dtype=np.float32)
        self.phase1 = 0.0
        self.phase2 = pi/2.0

        # Precompute empty y-arrays
        self.y1 = np.zeros_like(self.t, dtype=np.float32)
        self.y2 = np.zeros_like(self.t, dtype=np.float32)
        self.y3 = np.zeros_like(self.t, dtype=np.float32)

        # ─── PlotDataItems ────────────────────────────────────────────────────────
        self.curve1 = self.plot.plot(self.t, self.y1, pen=mkPen('r', width=1), name='sin(x)')
        self.curve2 = self.plot.plot(self.t, self.y2, pen=mkPen('k', width=1), name='rand + 1')
        self.curve3 = self.plot.plot(self.t, self.y3, pen=mkPen('b', width=1), name='sin(x + θ) - 1')

        # ─── Auto-scale once ───────────────────────────────────────────────────────
        vb = self.plot.getViewBox()
        vb.enableAutoRange()
        QTimer.singleShot(100, vb.disableAutoRange)

        # ─── Animation Timer ─────────────────────────────────────────────────────
        self.last_time = time.perf_counter()
        self.last_time_reporting = time.perf_counter()
        self.num_segments = 0
        self.generating_time = 0.0
        self.total_time = 0.0
        self.delta_avg = 0.020
        
        # How much CPU time is left for the Qt event loop
        self.cpu_start  = time.process_time()
        self.wall_start = time.perf_counter()

        self.animTimer = QTimer(self)
        self.animTimer.setTimerType(Qt.TimerType.PreciseTimer)
        self.animTimer.timeout.connect(self.update)
        self.animTimer.start(0)

    def update(self):

        tic_start = time.perf_counter()
        now_cpu  = time.thread_time()

        # compute how much time has passed since last report
        wall_elapsed = tic_start  - self.wall_start
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
        # advance phases
        self.phase1 += 0.01 * delta*1000.
        self.phase2 += 0.0101 * delta*1000.

        # compute y-data
        np.sin(self.t + self.phase1, out=self.y1)
        self.y2[:] = np.random.rand(self.t.size).astype(np.float32) + 1.0
        np.sin(self.t + self.phase2, out=self.y3)
        self.y3 -= 1.0

        self.generating_time += time.perf_counter() - tic

        # performance measurement
        tic = time.perf_counter()

        # update curves
        self.curve1.setData(self.t, self.y1)
        self.curve2.setData(self.t, self.y2)
        self.curve3.setData(self.t, self.y3)

        app.processEvents()

        # benchmark
        self.num_segments += 3 * self.t.size


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = PGPlotMain()
    win.show()
    sys.exit(app.exec())
