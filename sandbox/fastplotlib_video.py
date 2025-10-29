import sys
from PyQt6 import QtWidgets, QtCore
import fastplotlib as fpl
import imageio.v3 as iio

app = QtWidgets.QApplication(sys.argv)
fpl.loop._app = app

# Read video using imageio
video = iio.imread("imageio:cockatoo.mp4")
n_frames, video_h, video_w, *_ = video.shape

fig = fpl.Figure()
fig[0, 0].add_image(video[0], name="video")

# create a QMainWindow
class MainWindow(QtWidgets.QMainWindow):
    def closeEvent(self, ev):
        fpl.loop.stop()
        super().closeEvent(ev)

main_window = MainWindow()

def update_frame(ix):
    fig[0, 0]["video"].data = video[ix]

# Create slider
slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
slider.setRange(0, n_frames - 1)
slider.valueChanged.connect(update_frame)
dock = QtWidgets.QDockWidget()
dock.setWidget(slider)
main_window.addDockWidget(
    QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, 
    dock
)

canvas_widget = fig.show()
main_window.setCentralWidget(canvas_widget)
main_window.show()

app.processEvents()
dock_h = dock.sizeHint().height()
main_window.resize(video_w, video_h + dock_h)

sys.exit(app.exec())

