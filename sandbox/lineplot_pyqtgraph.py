"""
Lineplot Qt
===========

Complex example for lineplot in PyQt that displays 3 traces.
The plot is a standard black on white with a legend on the right.

CPU 12% (maxed out), GPU: 0%,  6,150,000 sps should be 9,375,000
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
    DATAPOINTS = 50000
    INTERVAL   = 16  # ms

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
        self.plot.addLegend(offset=(10, 10))

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
        self.num_segs = 0

        timer = QTimer(self)
        timer.timeout.connect(self.update)
        timer.start(self.INTERVAL)


    def update(self):
        # advance phases
        self.phase1 += 0.01 * self.INTERVAL
        self.phase2 += 0.0101 * self.INTERVAL

        # compute y-data
        np.sin(self.t + self.phase1, out=self.y1)
        self.y2[:] = np.random.rand(self.DATAPOINTS).astype(np.float32) + 1.0
        np.sin(self.t + self.phase2, out=self.y3)
        self.y3 -= 1.0

        # update curves
        self.curve1.setData(self.t, self.y1)
        self.curve2.setData(self.t, self.y2)
        self.curve3.setData(self.t, self.y3)

        # benchmark
        self.num_segs += 3 * self.DATAPOINTS
        now = time.perf_counter()
        if now - self.last_time >= 1.0:
            fps = 1000 / self.INTERVAL
            print(f"Segments/s: {self.num_segs}, Segs/frame: {3*self.DATAPOINTS}, FPS: {fps:.2f}")
            self.last_time = now
            self.num_segs = 0


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = PGPlotMain()
    win.show()
    sys.exit(app.exec())
