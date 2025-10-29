import sys
import numpy as np

try:
    from PyQt6.QtGui import QSurfaceFormat
    fmt = QSurfaceFormat()
    fmt.setVersion(2, 1)
    # PyQt6: profile enum is nested
    profile_enum = getattr(QSurfaceFormat, "OpenGLContextProfile", QSurfaceFormat)
    fmt.setProfile(profile_enum.CoreProfile)
    QSurfaceFormat.setDefaultFormat(fmt)
except ImportError:
    from PyQt5.QtGui import QSurfaceFormat
    fmt = QSurfaceFormat()
    fmt.setVersion(2, 1)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    QSurfaceFormat.setDefaultFormat(fmt)

# Try PyQt6, fall back to PyQt5
try:
    from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout
    from PyQt6.QtCore    import QTimer
    QT_EXEC = "exec"
except ImportError:
    from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout
    from PyQt5.QtCore    import QTimer
    QT_EXEC = "exec_"

from pyqtgraph.opengl import GLViewWidget, GLLinePlotItem, GLGridItem

from OpenGL.GL import GL_DEPTH_TEST

class GLChartDemo(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GLLinePlotItem on White Background")
        self.resize(800, 600)

        # 4) Use a QWidget + QVBoxLayout to host the GLViewWidget
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 5) Create the GL canvas
        self.gl = GLViewWidget()
        # set pure white OpenGL background
        self.gl.setBackgroundColor('white')
        # top-down camera
        self.gl.setCameraPosition(elevation=90, azimuth=0, distance=8)
        layout.addWidget(self.gl)

        # 6) Add a darker gray grid (10×4 units, lines every 1 unit)
        grid = GLGridItem()
        grid.setSize(10, 4, 0)               # width in X, height in Y
        grid.setSpacing(1, 1, 0)         # grid lines every 1 unit
        grid.setColor((100, 100, 100, 255))  # medium‐gray lines
        self.gl.addItem(grid)

        # 7) Create a red sine wave (amplitude ±1, one full period)
        self.t = np.linspace(-2 * np.pi, 2 * np.pi, 10000)
        self.zs = np.full_like(self.t, 0.01)  # 0.01 units above the grid
        self.color1 = (255, 0, 0, 255)
        self.color2 = (0, 0, 0, 255)
        self.color3 = (0, 0, 255, 255)
        self.width = 2.0
        self.antialias = True

        self.phase1 = 0.0
        self.phase2 = np.pi / 2  # start at the peak

        pos = np.column_stack((self.t, np.sin(self.t + self.phase1), self.zs))
        self.line1 = GLLinePlotItem(
            pos=pos,
            color=self.color1,
            width=self.width,
            antialias=self,
        )
        self.gl.addItem(self.line1)

        pos = np.column_stack((self.t, np.random.rand(self.t.size)+1.0, self.zs))
        self.line2 = GLLinePlotItem(
            pos=pos,
            color=self.color2,
            width=self.width,
            antialias=self,
        )
        self.gl.addItem(self.line2)

        pos = np.column_stack((self.t, np.sin(self.t + self.phase2), self.zs))
        self.line3 = GLLinePlotItem(
            pos=pos,
            color=self.color3,
            width=self.width,
            antialias=self,
        )
        self.gl.addItem(self.line3)

        # 8) Animate at ~20 Hz
        timer = QTimer(self)
        timer.timeout.connect(self._update)
        timer.start(10)

    def _update(self):
        self.phase1 += 0.1
        self.phase2 += 0.15
        
        pos = np.column_stack((self.t, np.sin(self.t + self.phase1), self.zs))
        self.line1.setData(
            pos=pos,
            color=self.color1,  # normalized floats
            width=self.width,
            antialias=self.antialias,
        )

        pos = np.column_stack((self.t, np.random.rand(self.t.size)+1.0, self.zs))
        self.line2.setData(
            pos=pos,
            color=self.color2,  # normalized floats
            width=self.width,
            antialias=self.antialias,
        )

        pos = np.column_stack((self.t, np.sin(self.t + self.phase2)-1.0, self.zs))
        self.line3.setData(
            pos=pos,
            color=self.color3,  # normalized floats
            width=self.width,
            antialias=self.antialias,
        )

if __name__ == "__main__":
    app = QApplication(sys.argv)
    demo = GLChartDemo()
    demo.show()
    if QT_EXEC == "exec":
        sys.exit(app.exec())
    else:
        sys.exit(app.exec_())