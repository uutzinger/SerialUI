############################################################################################################################################
# QT Chart Helper
#
# Display data in either
#  - PyQtGraph 
#  - fastplotlib
#
# This code is maintained by Urs Utzinger
############################################################################################################################################
#
# ==============================================================================
# Configuration
# ==============================================================================
from config import ( MAX_ROWS, MAX_COLS, MAX_ROWS_LINEDATA,
                     USE_FASTPLOTLIB, CACHE_FILE,
                     DEBUGCHART, PROFILEME, DEBUG_LEVEL, DEBUGFASTPLOTLIB,
                     COLORS, AXIS_FONT_COLOR, AXIS_COLOR, GRID_COLOR, GRID_MINOR_COLOR,
                     FRAME_PLANE_COLOR, FRAME_TITLE_COLOR, LEGEND_FONT_COLOR,
                     GRID_ALPHA, TICK_COLOR, POINT_COLOR, 
                     CHART_BACKGROUND_COLOR, LEGEND_BACKGROUND_COLOR,
                     MAJOR_TICKS, MINOR_TICKS,
                     LINEWIDTH, AXIS_LINEWIDTH,
                     PARSE_OPTIONS, PARSE_DEFAULT_NAME, PARSE_OPTIONS_INV,
                     UPDATE_INTERVAL,
                     CAMERA_PAD, SMALLEST, REL_TOL)
# ==============================================================================
# Imports
# ==============================================================================
#
# General Imports
# ----------------------------------------
import logging
import time
import re
import textwrap
import sys
from math import pi, floor, ceil, isfinite, floor, log10, isclose
from typing import Optional
import numpy as np
# Accelerator
try:
    from numba import njit
    hasNUMBA = True
except Exception:
    njit = None
    hasNUMBA = False
# Provide a no‑op decorator if numba not available (so @njit(...) won’t crash)
if njit is None:
    def njit(*_args, **_kwargs):
        def _wrap(func):
            return func
        return _wrap    
#
# QT Libraries
# ----------------------------------------
try:
    from PyQt6.QtCore import (
        Qt, QObject, QTimer, QThread, pyqtSlot, QStandardPaths, pyqtSignal, 
        QCoreApplication, 
    )
    from PyQt6.QtWidgets import (
        QLineEdit, QSlider,QTabWidget, QWidget, QVBoxLayout, 
    )
    from PyQt6.QtGui import ( QBrush, QColor, QGuiApplication,
                              QOpenGLContext
    )
    PreciseTimerType = Qt.TimerType.PreciseTimer
    DOCUMENTS = QStandardPaths.StandardLocation.DocumentsLocation
#
except Exception:
    from PyQt5.QtCore import (
        Qt, QObject, QTimer, QThread, pyqtSlot, QStandardPaths, pyqtSignal, 
        QCoreApplication,
    )
    from PyQt5.QtWidgets import (
        QLineEdit, QSlider, QTabWidget, QWidget, QVBoxLayout, 
    )
    from PyQt5.QtGui import ( QBrush, QColor, QGuiApplication,
                              QOpenGLContext
    )
    PreciseTimerType = QTimer.PreciseTimer
    DOCUMENTS = QStandardPaths.DocumentsLocation
#
# Fastplotlib
# ----------------------------------------
if USE_FASTPLOTLIB:
    if DEBUGFASTPLOTLIB:
        tic = time.perf_counter()
    try:
        import fastplotlib as fpl
        from   fastplotlib.legends import Legend
        import pygfx
    except Exception:
        USE_FASTPLOTLIB = False
    if DEBUGFASTPLOTLIB:
        print(f"Loading fastplotlib took {time.perf_counter()-tic} seconds")
#
# QtGraph
# ----------------------------------------
if not USE_FASTPLOTLIB:
    tic = time.perf_counter()
    import pyqtgraph                               as     pg
    from   pyqtgraph                               import PlotWidget
    import pyqtgraph.exporters                     as     pgxr
    from   pyqtgraph.graphicsItems.PlotDataItem    import PlotDataItem
    from    pyqtgraph.graphicsItems.GraphicsObject import GraphicsObject
    VALID_PG_LEGENDITEM = (PlotDataItem, GraphicsObject)
    print(f"Loading pyqtgraph took {time.perf_counter()-tic} seconds")
else:
    # Ensure symbol exists so pg_updateLegend doesn't NameError if accidentally called
    VALID_PG_LEGENDITEM = tuple()
#
# Line Parsers
# ----------------------------------------
#  - python implementation, slow and legacy
#  - c implementation, fast, requires user to run setup.py to compile the code once
try:
    from line_parsers import simple_parser
    from line_parsers import header_parser
    hasFastParser = True
except Exception:
    hasFastParser = False
#
from helpers.Circular_Buffer import CircularBuffer
#
from helpers.General_helper import (clip_value, rotate, color_to_rgba, rgbafloat_to_rgbaint,
                                    select_file, confirm_overwrite_append, is_widget_gl_free,
                                    connect, disconnect)
#
# Profiling
# ----------------------------------------
try:
    profile                                                                    # provided by kernprof at runtime
except NameError:
    def profile(func):                                                         # no-op when not profiling
        return func

# ==============================================================================
# Helpers
# ==============================================================================

def nice_step(span, n_major):
    # Compute major tick spacing
    # (0, 0.01, 4)  -> (0.002, 3)
    # (0, 1, 5)     -> (0.2, 1)
    # (0, 10, 5)    -> (2, 0)
    # (0, 100, 5)   -> (20, 0)
    # (0, 1000, 5)  -> (200, 0)
    rough = span / n_major
    e = floor(log10(rough))
    f = rough / (10.0 ** e)
    if   f <= 1.5: base = 1.0
    elif f <= 2.5: base = 2.0
    elif f <= 4.0: base = 2.5
    elif f <= 7.5: base = 5.0
    else:          base = 10.0
    major = base * (10.0 ** e)
    decimals = max(0, -floor(log10(major))) if major < 1.0 else 0
    return major, decimals

def nudgeup_ticks(major, min_major):
    """Adjust the major tick size upwards to be at least min_major."""
    ratio = min_major / max(major, SMALLEST)
    r_exp = floor(log10(ratio))
    r_base = ratio / (10**r_exp)
    if   r_base <= 1.5: mult = 1.0
    elif r_base <= 2.5: mult = 2.0
    elif r_base <= 4.0: mult = 2.5
    elif r_base <= 7.5: mult = 5.0
    else:               mult = 10.0
    return major * mult * (10.0 ** r_exp)

def nudgedown_ticks(major, max_major):
    """Adjust the major tick size downwards to be at most max_major."""
    ratio = major / max(max_major, SMALLEST)
    r_exp  = floor(log10(ratio))
    r_base = ratio / (10**r_exp)
    if   r_base <= 2.0: div = 1.0                                              # small adjustment
    elif r_base <= 4.0: div = 2.0
    elif r_base <= 7.5: div = 2.5
    else:               div = 5.0
    return max(max_major, (major / div) / (10**r_exp))

# ==============================================================================
# QChart
# ==============================================================================

class QChart(QObject):
    """
    Chart Interface for QT

    The chart displays data traces in a plot.
    The data received from the serial port is organized in a ring buffer.
    A data track is a column in the buffer.
    The plot can be zoomed in by selecting how far back in time to display the data.
    The horizontal axis is the sample number.
    The vertical axis is auto scaled to the max and minimum values of the data.

    Slots (functions available to respond to external signals)
        on_pushButton_ChartStartStop
        on_pushButton_ChartPause
        on_pushButton_ChartClear
        on_pushButton_ChartSave
        on_pushButton_ChartSaveFigure
        on_ZoomSliderChanged(int)
        on_ZoomLineEditChanged(str)
        on_receivedLines(list)
        on_comboBox_DataSeparator selects data separation method
        on_mtocRequest() emits profiling mtoc message
        on_pg_viewBox_changed(vb, ranges, axes) called when user zooms or pans the plot (inspection mode)
        on_fpl_user_interaction() called when users zooms or pans the plot (inspection mode)
        on_throughputTimer() reports points per second drawn on chart

    Functions
        updatePlot() the main chart update function called by timer 
        process_lines_header() python text to data parser with header
        process_lines_simple() python text to data parser without header
        fast_process_lines_header() C accelerated text to data parser with header
        fast_process_lines_simple() C accelerated text to data parser without header
    """

    # Signals
    # ==========================================================================
    throughputUpdate = pyqtSignal(float, float, str)                           # report rx/tx to main ("chart")
    plottingRunning  = pyqtSignal(bool)                                        # emit True if plotting wants serial receiver running
    logSignal        = pyqtSignal(int, str)                                    # Logging

    # Init
    # ==========================================================================
    def __init__(self, parent=None, ui=None):

        super().__init__(parent)

        self.thread_id = int(QThread.currentThreadId()) if QThread.currentThreadId() else -1
        self.instance_name = self.objectName() if self.objectName() else self.__class__.__name__

        # For debugging initialization
        self.logger = logging.getLogger(self.instance_name[:10])
        self.logger.setLevel(DEBUG_LEVEL)
        if not self.logger.handlers:
            sh = logging.StreamHandler()
            fmt = "[%(levelname)-8s] [%(name)-10s] %(message)s"
            sh.setFormatter(logging.Formatter(fmt))
            self.logger.addHandler(sh)
        self.logger.propagate = False

        # Initialize profiling variables
        self.mtoc_updatePlot = 0.
        self.mtoc_process_lines_simple = 0.
        self.mtoc_process_lines_header = 0.

        # Making sure we have access to the User Interface, Serial and Serial Worker
        if ui is None:
            self.logger.log(
                logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Need to have access to User Interface"
            )
            raise ValueError("User Interface (ui) is required but was not provided.")
        self.ui = ui

        # Delegate encoding if parent has one
        if parent and hasattr(parent, "encoding"):
            self.encoding = parent.encoding
        else:
            self.encoding = "utf-8"

        self.maxPoints = 1024                                                  # initial maximum number of points to show in a plot from now to the past
        self.x_max     = 0.                                                    # initial max
        self.x_min     = self.x_max - self.maxPoints + 1                       # initial min
        self.x_base    = np.arange(- self.maxPoints + 1, 1, dtype=np.float64)  # base x values for the plot (to create x axis we will add latest sample number to this vector)
        self.x_view    = np.empty_like(self.x_base)                            # x values, pre allocation
        self.y_min = -1.0
        self.y_max =  1.0
        # self._x_realign_count = 0                                              # count how many times we have realigned x axis without changing span

        # ─── Replace the GraphicsView widget in the User Interface (ui) with the pyqtgraph plot
        self.tabWidget    = self.ui.findChild(QTabWidget,     "tabWidget_MainWindow")
        self.plotterPage  = self.ui.findChild(QWidget,        "Plotter") 
        self.monitorPage  = self.ui.findChild(QWidget,        "Monitor") 
        self.chartView    = self.ui.findChild(QWidget,        "chartView")

        self.chartFPLInitialized = False                                       # flag to indicate if the chart has been initialized
        self.chartPGInitialized  = False                                       # flag to indicate if the chart has been initialized
        
        self.legend = None                                                     # handle to the legend in the plot
        self.legend_entries = []                                               # handles to the legend entries in the plot

        # Data traces
        self.data_traces = []                                                  # handles to the data traces in the plot
        self.data_traces_writeidx = []                                         # point to next free location in the data_traces array
        self.data_trace_capacity = self.maxPoints                              # current capacity of each data trace (all traces have same capacity)

        # Initialize the circular buffer to store the incoming data
        self.buffer = CircularBuffer(MAX_ROWS, MAX_COLS, dtype=np.float64)     # to match the GPU vertex buffer
        _, newest_sample = self.buffer.counter
        self.previous_newest_sample = newest_sample                            # no samples yet

        # Initialize the data array that will be used to store result when parsing lines
        #   data_array will be pushed to circular buffer when parsing is completed.
        self.data_array = np.full((MAX_ROWS_LINEDATA, MAX_COLS), np.nan)

        self.sample_number = 0                                                 # A counter indicating current sample number which is also the x position in the plot
        self.channel_names = []                                                # list of channel names created from self.channel_names_dict
        self.channel_names_dict = {}                                           # stores the variable names and their column index in a dictionary
        self.prev_channel_names_dict = {}                                      # detect if channel names or their order changed

        # Initialize the horizontal slider
        self.horizontalSlider = self.ui.findChild(QSlider, "horizontalSlider_Zoom")
        self.horizontalSlider.setMinimum(8)
        self.horizontalSlider.setMaximum(MAX_ROWS)
        self.horizontalSlider.setValue(int(self.maxPoints))
        self.lineEdit = self.ui.findChild(QLineEdit, "lineEdit_Horizontal_Zoom")
        self.lineEdit.setText(str(self.maxPoints))
        
        self.textDataSeparator = PARSE_DEFAULT_NAME                            # default data separator
        # self.ui.comboBoxDropDown_DataSeparator.blockSignals(True)
        # index = self.ui.comboBoxDropDown_DataSeparator.findText(self.textDataSeparator) # find default data separator in drop down
        # self.ui.comboBoxDropDown_DataSeparator.setCurrentIndex(index)        # update data separator combobox
        # self.ui.comboBoxDropDown_DataSeparator.blockSignals(False)

        self.ui.pushButton_ChartStartStop.setText("Start")

        self.ui.pushButton_ChartPause.setText("N.A.")
        self.ui.pushButton_ChartPause.setEnabled(False)

        # Set up timer for Plot update
        self.ChartTimer = QTimer(self)
        self.ChartTimer.setTimerType(PreciseTimerType)
        self.ChartTimer.setInterval(UPDATE_INTERVAL)
        self.ChartTimer.timeout.connect(self.updatePlot)

        # Throughput computation
        # setup the throughput measurement timer
        self.throughputTimer = QTimer(self)
        self.throughputTimer.setInterval(1000)                                 # every second
        self.throughputTimer.timeout.connect(self.on_throughputTimer)
        self.points_uploaded = 0

        # Zoom slider throttle
        self.zoomGate = True
        self.zoomGate_interval_ms = 100                                        # default interval in milliseconds
        self.zoomGate_timer = QTimer(self)
        self.zoomGate_timer.setSingleShot(True)
        self.zoomGate_timer.timeout.connect(lambda: setattr(self, "zoomGate", True))

        # Tick update throttle
        self.tickGate = True
        self.tickGate_interval_ms = 100                                        # default interval in milliseconds
        self.tickGate_timer = QTimer(self)
        self.tickGate_timer.setSingleShot(True)
        self.tickGate_timer.timeout.connect(lambda: setattr(self, "tickGate", True))

        self.warning = True                                                    # flag to only warn once about binary data with separator
        
        self.logger.log(
            logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: QChart initialized."
        )

    @pyqtSlot()
    def pg_figure_init(self):
        """
        Initialize the pyqtgraph figure after the UI is fully set up.
        """

        if not getattr(self, "chartPGInitialized", False):

            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Attempting to initialize PyQtGraph."
            )

            if self.initChartPG():
                self.logSignal.emit(logging.INFO, 
                    f"[{self.instance_name[:15]:<15}]: PyQtGraph Initialization successful."
                )
                self.ui.statusBar().showMessage('Chart set to PyQtGraph.', 2000)
            else:
                self.logSignal.emit(logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: PyQtGraph Initialization failed, retrying."
                )
        else:
            self.logSignal.emit(logging.WARNING, 
                    f"[{self.instance_name[:15]:<15}]: chartPG already initialized."
                )

    @pyqtSlot()
    def fpl_figure_init(self):
        """
        Initialize the FastPlotLib figure after the UI is fully set up.

        Loading fastplotlib and initializing the GPU needs time with noticeable delay for user.
        """
        if not getattr(self, "chartFPLInitialized", False):

            if DEBUGFASTPLOTLIB:
                self.logSignal.emit(logging.DEBUG, f"[{self.instance_name[:15]:<15}]: Widget visible={self.chartView.isVisible()}")
                self.logSignal.emit(logging.DEBUG, f"[{self.instance_name[:15]:<15}]: Widget size={self.chartView.size()}")
                self.logSignal.emit(logging.DEBUG, f"[{self.instance_name[:15]:<15}]: Window active={self.chartView.window().isActiveWindow()}")

            # Ensure chartView has a real size; temporarily show the plotter tab if needed

            chartView    = getattr(self, "chartView", None)
            tab_widget   = getattr(self, "tabWidget", None)
            plotter_page = getattr(self, "plotterPage", None)

            prev_tab_index = tab_widget.currentIndex() if tab_widget else None
            plotter_index  = tab_widget.indexOf(plotter_page) if (tab_widget and plotter_page) else -1

            chartView_invalid = (
                chartView is None
                or chartView.size().width() <= 100
                or chartView.size().height() <= 100
            )

            if chartView_invalid and plotter_index != -1:
                # ChartView is not established.
                # Switch to the plotter tab temporarily

                self.logSignal.emit(logging.INFO, 
                    f"[{self.instance_name[:15]:<15}]: Switching to plotter tab."
                )

                if tab_widget.currentIndex() != plotter_index:
                    tab_widget.setCurrentIndex(plotter_index)
                    QCoreApplication.processEvents()

                if chartView is not None:
                    size = chartView.size()
                    chartView_invalid = size.width() <= 100 or size.height() <= 100
                else:
                    chartView_invalid = True

                # Switch back
                if tab_widget.currentIndex() != prev_tab_index and prev_tab_index is not None:
                    tab_widget.setCurrentIndex(prev_tab_index)

                self.logSignal.emit(logging.INFO, 
                    f"[{self.instance_name[:15]:<15}]: Switching tab back."
                )

            if chartView_invalid:
                # still not valid chartView
                QTimer.singleShot(100, self.fpl_figure_init)
                return

            self.logSignal.emit(logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Attempting to initialize FastPlotLib."
            )

            if self.initChartFPL():
                self.logSignal.emit(logging.INFO, 
                    f"[{self.instance_name[:15]:<15}]: FastPlotLib initialization successful."
                )
                self.ui.statusBar().showMessage('Chart set to FastPlotLib.', 2000)
            else:
                self.logSignal.emit(logging.ERROR, 
                    f"[{self.instance_name[:15]:<15}]: FastPlotLib initialization failed, switching to PyQtGraph."
                )
                QTimer.singleShot(500, self.fpl_figure_init)

        else:
            self.logSignal.emit(logging.WARNING, 
                    f"[{self.instance_name[:15]:<15}]: chartFPL already initialized."
                )

    # ==========================================================================
    # pyqtgraph functions
    # ==========================================================================

    def initChartPG(self) -> bool:
        """
        Initialize the pyqtgraph chart. 
        We want to do this after the UI is fully set up.
        """

        if getattr(self, "chartPGInitialized", False):
            return True

        self.ui.radioButton_useFPL.setChecked(False)
        self.ui.radioButton_useFPL.setEnabled(False)
        self.ui.pushButton_ChartSaveFigure.setText("Save Figure SVG")
        
        fg_rgba = rgbafloat_to_rgbaint(AXIS_FONT_COLOR)
        pg.setConfigOptions(
            antialias = False,
            foreground = QColor(*fg_rgba)
        )

        try:
            tic = time.perf_counter()
            
            # Embed the pyQtGraph Widget into the first page:
            layoutPG = self.chartView.layout()
            if layoutPG is None:
                layoutPG = QVBoxLayout(self.chartView)
                layoutPG.setContentsMargins(0, 0, 0, 0)
                layoutPG.setSpacing(0)

            # Create the pyqtgraph chart
            self.chartWidgetPG   = PlotWidget()
            layoutPG.addWidget(self.chartWidgetPG)

            # Setting the pyQtGraph Widget features
            self.chartWidgetPG.setBackground(rgbafloat_to_rgbaint(CHART_BACKGROUND_COLOR))
            self.chartWidgetPG.showGrid(x=True, y=True, alpha=GRID_ALPHA)
            self.chartWidgetPG.setLabel("left", "Signal", units="")
            self.chartWidgetPG.setLabel("bottom", "Sample", units="")
            self.chartWidgetPG.setTitle("Chart")

            # Obtain the ViewBox 
            # and set passing, autorange and mouse interaction
            self.viewBox = self.chartWidgetPG.getViewBox()
            self.viewBox.setDefaultPadding(0)                                  # no padding when auto ranging
            self.viewBox.disableAutoRange(pg.ViewBox.XAxis)                    # disable auto ranging
            self.viewBox.disableAutoRange(pg.ViewBox.YAxis)                    # disable auto ranging
            self.viewBox.setMouseEnabled(x=True, y=True)                       # enable mouse interaction
            # Initialize the plot axis ranges
            self.chartWidgetPG.setXRange(self.x_min, self.x_max)
            self.chartWidgetPG.setYRange(self.y_min, self.y_max)

            connect(self.viewBox.sigRangeChanged, self.on_pg_viewBox_changed, unique=True) # When plot is idle we allow zoom and pan

            # Trace Colors
            self.pensPG = [pg.mkPen(color, width=LINEWIDTH) for color in COLORS]

            # Create legend once (styled) so it’s ready before first update
            self.legend = self.pg_createLegend()
            self.legend_entries = []

            # Tick marks and grid
            # self.pg_updateAxesTicks(axis="x",n_major=MAJOR_TICKS, n_minor=MINOR_TICKS)
            # self.pg_updateAxesTicks(axis="y",n_major=MAJOR_TICKS, n_minor=MINOR_TICKS)

            self.logSignal.emit(
                logging.INFO, 
                f"[{self.instance_name[:15]:<15}]: Created PyQtGraph figure in {time.perf_counter() - tic:.2f} seconds"
            )

            self.chartPGInitialized = True

            return True
        
        except Exception as e:
            self.logSignal.emit(
                logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Failed to create PyQtGraph figure: {e}"
            )
            return False

    def pg_createLegend(self):
        """Create a styled PyQtGraph legend once."""
        bg_rgba  = rgbafloat_to_rgbaint(LEGEND_BACKGROUND_COLOR)
        font_rgba = rgbafloat_to_rgbaint(LEGEND_FONT_COLOR)
        bg_qc    = QColor(*bg_rgba)
        font_qc  = QColor(*font_rgba)
        # Try to set style at creation (newer pyqtgraph supports labelTextColor)
        try:
            legend = self.chartWidgetPG.addLegend(
                offset=(10, 10),
                brush=QBrush(bg_qc),
                pen=pg.mkPen(bg_qc),
                labelTextColor=font_qc,
            )
        except Exception:
            legend = self.chartWidgetPG.addLegend(offset=(10, 10))
            try:
                legend.setBrush(QBrush(bg_qc))
                legend.setPen(pg.mkPen(bg_qc))
            except Exception:
                pass
            # Will color labels in pg_updateLegend if global option not supported
        
        # Cache last applied style so we can avoid redundant work
        self._pg_legend_style = {"bg": tuple(bg_rgba), "font": tuple(font_rgba)}
        return legend

    def pg_clearLegend(self):
        """
        Clear legend of chart
        """
        legend = getattr(self, "legend", None)
        if legend is None:
            return                                                             # nothing to update when we dont have a legend

        legend.clear()
        self.legend_entries = []

    @profile
    def pg_updateLegend(self, lines, labels ):
        """
        Update legend of chart
        """

        legend = getattr(self, "legend", None)
        if legend is None:
            return
        self.pg_clearLegend()

        if labels is None:
            labels = []

        # Set global label text color once
        font_rgba = rgbafloat_to_rgbaint(LEGEND_FONT_COLOR)
        font_qc   = QColor(*font_rgba)
        
        if hasattr(legend, "setLabelTextColor"):
            try:
                legend.setLabelTextColor(font_qc)
            except Exception:
                pass

        for i, data_trace in enumerate(lines or []):
            label = labels[i] if i < len(labels) and labels[i] else f"Trace {i}"

            if VALID_PG_LEGENDITEM and not isinstance(data_trace, VALID_PG_LEGENDITEM):
                self.logSignal.emit(
                    logging.DEBUG,
                    f"[{self.instance_name[:15]:<15}]: Legend skip non-pg item type={type(data_trace)} label={label}"
                )
                continue

            # Set the display name on the item if supported
            if hasattr(data_trace, "setName"):
                data_trace.setName(label)
            else:
                try:
                    # Some pg versions accept name= in setData without needing x/y again
                    data_trace.setData(name=label)
                except Exception:
                    # Fallback: update the opts dict
                    try:
                        data_trace.opts["name"] = label
                    except Exception:
                        pass

            # Add to legend with explicit text (ensures 1:1 mapping regardless of opts)
            legend.addItem(data_trace, label)

        # If global label color wasn’t applied, set per-label once here
        if not hasattr(legend, "setLabelTextColor"):
            try:
                for _, lbl in getattr(legend, "items", []):
                    try:
                        text = lbl.textItem.toPlainText() if hasattr(lbl, "textItem") else getattr(lbl, "text", "")
                        lbl.setText(text, color=font_qc)
                    except Exception:
                        pass
            except Exception:
                pass

        # Resize legend box if supported
        try:
            legend.updateSize()
        except Exception:
            pass

    # @profile
    def pg_updateAxesTicks(self, 
                    axis="x", 
                    lo=None, 
                    hi=None, 
                    n_major=MAJOR_TICKS, 
                    n_minor=MINOR_TICKS
        ):
        """
        Update tick spacing on the given axis if needed.
        axis: "x" or "y"
        lo, hi: data range to consider; if None, use current ViewBox range
        n_major: desired number of major ticks
        n_minor: desired number of minor ticks per major interval
        """

        if self.chartWidgetPG is None:
            return

        if self.viewBox is None:
            return

        ax_item = self.chartWidgetPG.getAxis('bottom' if axis == 'x' else 'left')
        if ax_item is None:
            return

        # If lo/hi not provided, use current view range
        if lo is None or hi is None:
            try:
                (x_lo, x_hi), (y_lo, y_hi) = self.viewBox.viewRange()
                lo, hi = (x_lo, x_hi) if axis == "x" else (y_lo, y_hi)
            except Exception:
                return

        if hi < lo: 
            lo, hi = hi, lo                                                    # handle reversed ranges

        span = hi - lo
        if span <= 0:
            return

        major, decimals = nice_step(span, n_major)
        minor_div = max(int(n_minor), 1)
        minor = major / minor_div

        # Make sure tick spacing is not too sparse or crowded if window size is changed

        if axis == "x":
            px = max(1, int(self.viewBox.width()))
        else:
            px = max(1, int(self.viewBox.height()))
        dpp = (hi - lo) / px

        # Spacing should be larger than min_major_px in screen space
        MIN_MAJOR_PX = 80                                                      # desired distance in pixels between major ticks (prevent crowding if uses reduced application window size)
        MIN_MINOR_PX = MIN_MAJOR_PX / 5                                        # desired distance in pixels between minor ticks
        min_major = max(dpp * MIN_MAJOR_PX, span / max(int(n_major), 1))
        max_major = min_major * 5

        # Nudge major toward pixel target if too dense
        if major < min_major:
            major = nudgeup_ticks(major, min_major)
            minor = major / minor_div
        elif major > max_major:
            major = nudgedown_ticks(major, max_major)
            minor = major / minor_div

        # Enforce minimum pixels between minor ticks
        minor_px = minor / max(dpp, SMALLEST)
        if minor_px < MIN_MINOR_PX:
            k = max(1, int(round(MIN_MINOR_PX / minor_px)))
            minor = major / max(1, minor_div // k)

        # Subplot cache to avoid churn 
        if not hasattr(self, "axisTickState"):
            self.axisTickState = {"x": {"major":None,"minor":None},
                                  "y": {"major":None,"minor":None}}
        prev_state = self.axisTickState[axis]
        prev_major = prev_state["major"]
        prev_minor = prev_state["minor"]

        # Only apply if meaningfully changed
        changed = (
            prev_major is None or
            not isclose(major, prev_major, rel_tol=REL_TOL, abs_tol=0.0) or
            not isclose(minor, prev_minor, rel_tol=REL_TOL, abs_tol=0.0)
        )

        if not changed:
            return

        try:
            ax_item.setTickSpacing(major=major, minor=minor)
        except TypeError:
            ax_item.setTickSpacing(levels=[(major, minor)])

        try:
            ax_item.setTickSpacing(major=major, minor=minor)
        except TypeError:
            # levels expects [(spacing, offset), ...] ordered from most detailed to least
            ax_item.setTickSpacing(levels=[(minor, 0), (major, 0)])

        # update cache
        prev_state["major"] = major
        prev_state["minor"] = minor

        # ticks = [(v, f"{v:.{decimals}f}") for v in np.arange(lo, hi+major, major)]
        # ax_item.setTicks([ticks])

    @pyqtSlot(object, object, object)
    @profile
    def on_pg_viewBox_changed(self, vb, rng, axis_changed) -> None:
        """
        Handle viewBox range changes and update ticks accordingly.
        rng: list of lists [[x_min, x_max], [y_min, y_max]]
        axis_changed: list of boolean [x_changed: bool, y_changed: bool]
        """

        if not self.tickGate:
            # Prevent tick update until gate is released (throttling)
            return

        if rng is None:
            self.logSignal.emit(
                logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Range is None."
            )
            return

        try:
            (x_lo, x_hi), (y_lo, y_hi) = rng
        except Exception:
            self.logSignal.emit(
                logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Failed to unpack viewBox range: {rng}. Should be list of lists [[x_min, x_max], [y_min, y_max]]"
            )
            return  

        if not np.isfinite([x_lo, x_hi, y_lo, y_hi]).all():
            self.logSignal.emit(
                logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: Range is not finite: {rng}."
            )
            return

        if axis_changed is None:
            self.logSignal.emit(
                logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: axis changes is None."
            )
            return

            
        if  not isinstance(axis_changed, (list, tuple)):
            self.logSignal.emit(
                logging.ERROR, 
                f"[{self.instance_name[:15]:<15}]: axis changed is not a list or tuple."
            )
            return


        self.tickGate = False
        self.tickGate_timer.start(self.tickGate_interval_ms)

        # Default: assume both axes changed if info missing
        x_range_changed, y_range_changed = axis_changed

        if x_range_changed:
            self.pg_updateAxesTicks("x", x_lo, x_hi, n_major=MAJOR_TICKS, n_minor=MINOR_TICKS)
        if y_range_changed:
            self.pg_updateAxesTicks("y", y_lo, y_hi, n_major=MAJOR_TICKS, n_minor=MINOR_TICKS)

    # ==========================================================================
    # fastplotlib functions
    # ==========================================================================

    def initChartFPL(self) -> bool:
        """
        Initialize the FastPlotLib chart after the UI is fully set up.
        """

        if getattr(self, "chartFPLInitialized", False):
            return True

        self.ui.radioButton_useFPL.setChecked(True)
        self.ui.radioButton_useFPL.setEnabled(False)
        self.ui.pushButton_ChartSaveFigure.setText("Save Figure PNG")

        if DEBUGFASTPLOTLIB:
            self.logSignal.emit(logging.DEBUG, f"[{self.instance_name[:15]:<15}]: Thread={QThread.currentThread()}, GUI Thread={QCoreApplication.instance().thread() if QCoreApplication.instance() else None}")

        # ─── Loading FastPlotLib ────────────────────────────────────────────────
        # Fastplotlib figure creation requires a visible user interface window.
        #
        # If the UI window uses discreteGPU or OpenGL, fastplotlib will need to use
        # the same adapter and can not switch to Vulkan or dedicated GPU.
        # Since its possible that user initializes fastplotlib on "wrong" adapter 
        # we need to assure that system does not panic and make sure the adapters 
        # is compatible with the widget that will enclose it.
        # The main issue arises if OpenGL context is present in the UI, as that
        # requires fastplotlib to use an OpenGL compatible adapter.

        adapters = fpl.enumerate_adapters()
        if adapters:
            self.logger.log(logging.INFO,f"[{self.instance_name[:15]:<15}]: Available adapters={len(adapters)}")
            for idx, adapter in enumerate(adapters):
                self.logger.log(logging.INFO,f"[{self.instance_name[:15]:<15}]: Adapter {idx}: {adapter.summary}")
        else:
            self.logger.log(logging.INFO,f"[{self.instance_name[:15]:<15}]: No WGPU adapter available; using pyqtgraph.")
            USE_FASTPLOTLIB = False
            return False

        # Identify platform and OS
        platform   = QGuiApplication.platformName()                            # 'xcb', 'wayland', 'windows', 'cocoa'
        if sys.platform.startswith("linux"):
            self.logger.log(logging.INFO, f"[{self.instance_name[:15]:<15}]: Linux Qt platform={platform}")
        elif sys.platform.startswith("win"):
            self.logger.log(logging.INFO, f"[{self.instance_name[:15]:<15}]: Windows Qt platform={platform}")
        elif sys.platform.startswith("darwin"):
            self.logger.log(logging.INFO, f"[{self.instance_name[:15]:<15}]: MacOS Qt platform={platform}")
        else:
            self.logger.log(logging.INFO, f"[{self.instance_name[:15]:<15}]: Unknown Qt platform={platform}")

        # Probe if OpenGL Widgets are present
        useOPENGL = False
        #Is GL active?
        if QOpenGLContext.currentContext() is not None:
            self.logger.log(logging.INFO, f"[{self.instance_name[:15]:<15}]: Qt OpenGL context active")
            useOPENGL = True
        # Are there other OpenGL widgets in the User Interface?
        elif not is_widget_gl_free(self.chartView):
            self.logger.log(logging.INFO, f"[{self.instance_name[:15]:<15}]: Qt OpenGL context active")
            useOPENGL = True

        # If we have OpenGL in the User Interface we need to make sure fastplotlib use an OpenGL adapter
        # otherwise we can let it auto select the best adapter
        if useOPENGL:
            gl_adapters = []
            for a in adapters:
                if hasattr(a, "info"):  info = a.info
                if isinstance(a, dict): info = a
                if info.get("backend_type","").lower() in ("opengl","gl","glx"):
                    gl_adapters.append(a)

            if gl_adapters:
                fpl.select_adapter(gl_adapters[0])                             # select first OpenGL adapter
                self.logger.log(logging.INFO, f"[{self.instance_name[:15]:<15}]: Selected OpenGL adapter: {gl_adapters[0].summary}")
            else:
                USE_FASTPLOTLIB = False
                return False

        self.logger.log(logging.INFO, f"[{self.instance_name[:15]:<15}]: Creating FastPlotLib figure, takes a few seconds...")

        # ─── Read pipeline cache ────────────────────────────────────────────────
        # This is not yet supported by wgpu, but might be in the future.
        # It would speed up the startup time when creating the FastPlotLib figure.
        #
        # initial_cache_data = None
        # if os.path.exists(CACHE_FILE):
        #     try:
        #         with open(CACHE_FILE, "rb") as f:
        #             initial_cache_data = f.read()
        #             self.logger.log(logging.INFO, 
        #                 f"[{self.instance_name[:15]:<15}]: Loaded pipeline cache: {len(initial_cache_data)} bytes from {CACHE_FILE}"
        #             )
        #     except Exception as e:
        #         self.logger.log(logging.ERROR, 
        #             f"[{self.instance_name[:15]:<15}]: Failed to read cache: {e}"
        #         )
        #
        # Once loading cache configuration is supported we would load it like this:
        # adapter.request_device_sync(pipeline_cache=initial_cache_data)

        tic = time.perf_counter()
    
        layoutFPL = self.chartView.layout()
        if layoutFPL is None:
            layoutFPL = QVBoxLayout(self.chartView)
            layoutFPL.setContentsMargins(0, 0, 0, 0)
            layoutFPL.setSpacing(0)
        
        # ─────── Create the fastplotlib figure ────────────────
        
        # Figure and Layout
        #   this takes a couple of seconds
        self.fpl_fig = fpl.Figure(
            shape=(1,1), 
            names=[["Line Plots"]],
            canvas_kwargs={"parent": self.chartView},
            size=(self.chartView.size().width(), self.chartView.size().height()),
            show_tooltips=True
        )
        self.fpl_canvas = self.fpl_fig.show(autoscale=True, maintain_aspect=True)
        self.fpl_canvas.setContentsMargins(0, 0, 0, 0)
        layoutFPL.addWidget(self.fpl_canvas)

        # Create the Fastplotlib subplot
        self.fpl_subplot = self.fpl_fig[0, 0]
        self.fpl_subplot.axes.visible = True
        self.fpl_subplot.background_color = pygfx.Color(CHART_BACKGROUND_COLOR)

        # Camera for the subplot
        self.fpl_camera = self.fpl_subplot.camera

        # Set figure background color (affects title bar and figure tools background)
        self.fpl_subplot.frame.plane.material.color = pygfx.Color(FRAME_PLANE_COLOR)
        pc = getattr(self.fpl_subplot.frame, "plane_color", None)
        if pc is not None:
            def _mod(col, f):
                r, g, b, a = (col + (1.0,))[:4]
                return (min(r * f, 1.0), min(g * f, 1.0), min(b * f, 1.0), a)
            idle_color      = _mod(FRAME_PLANE_COLOR, 0.85)
            highlight_color = _mod(FRAME_PLANE_COLOR, 1.00)
            action_color    = _mod(FRAME_PLANE_COLOR, 1.15)
            if hasattr(pc, "_replace") and hasattr(pc, "idle") and hasattr(pc, "highlight"):
                self.fpl_subplot.frame.plane_color = pc._replace(
                    idle      = pygfx.Color(idle_color),
                    highlight = pygfx.Color(highlight_color),
                    action    = pygfx.Color(action_color)
                )
            else:
                # Attribute style fallback
                for attr_name, clr in (
                    ("idle",      idle_color),
                    ("highlight", highlight_color),
                    ("action",    action_color),
                    ("normal",    FRAME_PLANE_COLOR),
                    ("base",      FRAME_PLANE_COLOR),
                    ("hover",     highlight_color),
                ):
                    if hasattr(pc, attr_name):
                        setattr(pc, attr_name, pygfx.Color(clr))

        # Create pens for line plots
        self.pensFPL = [color_to_rgba(color) for color in COLORS]

        # Title

        self.fpl_subplot.title = "Line Plots"
        self.fpl_subplot.title.face_color    = pygfx.Color(FRAME_TITLE_COLOR)
        self.fpl_subplot.title.outline_color = pygfx.Color(FRAME_TITLE_COLOR)

        # X label left → right

        self.fpl_subplot.docks["bottom"].size = 30
        self.fpl_subplot.docks["bottom"].add_text(
            "Sample",
            font_size=16,
            face_color=pygfx.Color(AXIS_FONT_COLOR),
            anchor="middle-center",
            offset=(0, 0, 0),
        )
        self.fpl_subplot.docks["bottom"].background_color = pygfx.Color(CHART_BACKGROUND_COLOR)

        # Y label bottom → top
        
        q = rotate(pi/2.0, 0., 0., 1.)                                         # rotate 90 deg around z-axis
        self.fpl_subplot.docks["left"].size = 30
        self.fpl_subplot.docks["left"].add_text(
            "Signal",
            font_size=16,
            face_color=pygfx.Color(AXIS_FONT_COLOR),
            anchor="middle-center",
            offset=(0, 0, 0),
            rotation=q,
        )
        self.fpl_subplot.docks["left"].background_color = pygfx.Color(CHART_BACKGROUND_COLOR)

        # Axes
        ax = self.fpl_subplot.axes

        def set_color(obj, value):
            if not obj:
                return
            c = pygfx.Color(value)
            # common cases
            if hasattr(obj, "material"):
                if hasattr(obj.material, "color"):
                    obj.material.color = c
                if hasattr(obj.material, "outline_color"):
                    obj.material.outline_color = c
                if hasattr(obj.material, "edge_color"):
                    obj.material.edge_color = c

            if hasattr(obj, "color"):
                try:
                    obj.color = c
                except Exception:
                    pass

        # X axis properties
        ax.x.line.material.thickness = AXIS_LINEWIDTH
        set_color(ax.x.line,   AXIS_COLOR)
        set_color(getattr(ax.x, "ticks",       None), TICK_COLOR)
        set_color(getattr(ax.x, "minor_ticks", None), GRID_MINOR_COLOR)
        set_color(getattr(ax.x, "points",      None), POINT_COLOR)
        set_color(getattr(ax.x, "text",        None), AXIS_FONT_COLOR)

        # Y axis properties
        ax.y.line.material.thickness = AXIS_LINEWIDTH
        set_color(ax.y.line,   AXIS_COLOR)
        set_color(getattr(ax.y, "ticks",       None), TICK_COLOR)
        set_color(getattr(ax.y, "minor_ticks", None), GRID_MINOR_COLOR)
        set_color(getattr(ax.y, "points",      None), POINT_COLOR)
        set_color(getattr(ax.y, "text",        None), AXIS_FONT_COLOR)

        # Grid
        ax.grids.xy.visible = True
        if hasattr(ax.grids.xy, "material"):
            ax.grids.xy.material.major_color     = pygfx.Color(GRID_COLOR)
            ax.grids.xy.material.minor_color     = pygfx.Color(GRID_MINOR_COLOR)
            ax.grids.xy.material.major_thickness = AXIS_LINEWIDTH
            ax.grids.xy.material.minor_thickness = AXIS_LINEWIDTH / 2

        # Legend
        self.legend=self.fpl_createLegend()

        # ─── Controller and Events ──────────────────────────────────────
        self.fpl_controller = getattr(self.fpl_subplot, "controller", None) or getattr(self.fpl_fig, "controller", None)
        if hasattr(self.fpl_controller, "enabled"):     self.fpl_controller.enabled     = True
        if hasattr(self.fpl_controller, "auto_update"): self.fpl_controller.auto_update = True
        if hasattr(self.fpl_controller, "pause"):       self.fpl_controller.pause       = False

        # connect mouse and resize events to camera change handler
        self.fpl_fig.renderer.add_event_handler(self.on_fpl_user_interaction, "wheel", "pointer_move", "resize")

        # ─── Show ────────────────────────────────────────────────────────

        x_min = self.x_min
        y_min = self.y_min
        x_max = self.x_max
        y_max = self.y_max

        # Location of x-axis in scene
        ax.x.start_value = x_min
        # Location of y-axis in scene
        ax.y.start_value = y_min
        # # Axis limits
        # ax.x_limits = (x_min, x_max)
        # ax.y_limits = (y_min, y_max)

        # Camera
        x_span = x_max - x_min
        y_span = y_max - y_min
        x_center = 0.5 * (x_max + x_min)
        y_center = 0.5 * (y_max + y_min)
        self.fpl_camera.set_state({
            "width": x_span * CAMERA_PAD,
            "height": y_span * CAMERA_PAD,
            "position": (x_center, y_center, 1.0),                             # z>0 so data at z=0 is in front
            "maintain_aspect": False,                                          # optional; set True if you want locked aspect
        })

        # Axis ticks
        self.fpl_subplot.axes.update_using_camera()
        # self.fpl_subplot.axes.update(self.fpl_camera, self.fpl_subplot.viewport.logical_size)
        self.fpl_subplot.axes.auto_grid = False                                # allow for custom grid
        self.fpl_updateAxesTicks(lo=(x_min, y_min), hi=(x_max, y_max), n_major=MAJOR_TICKS, n_minor=MINOR_TICKS)
        self.fpl_subplot.center_scene()

        # Request graphics update
        self.fpl_fig.canvas.request_draw()

        self.chartFPLInitialized = True

        self.logSignal.emit(
            logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: Created FastPlotLib figure in {time.perf_counter() - tic:.2f} seconds"
        )
        return True

    def fpl_resizeTraceCapacity(self, new_capacity: int):
        """
        Resize per-trace fixed capacity for fastplotlib lines.
        Recreate each line graphic with (new_capacity, 3) buffer, preserving existing data.
        """
        new_capacity = max(16, int(new_capacity))

        if new_capacity == self.data_trace_capacity:
            return                                                             # no change

        self.logSignal.emit(
            logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Resizing trace capacity {self.data_trace_capacity} -> {new_capacity}"
        )

        self.x_min =  np.inf
        self.x_max = -np.inf
        self.y_min =  np.inf
        self.y_max = -np.inf
        x_min_finite = False
        x_max_finite = False
        y_min_finite = False
        y_max_finite = False

        for i, line in enumerate(list(self.data_traces)):
            new_arr = np.full((new_capacity, 3), np.nan, dtype=np.float32)
            new_arr[:, 2] = 0.0                                                # (z)

            # robust capacity read across versions
            old_feature  = self.data_traces[i].data
            try:
                old_capacity = int(len(old_feature))
            except Exception:
                old_capacity = int(old_feature.value.shape[0])
            end       = min(self.data_traces_writeidx[i], old_capacity)
            copy_len  = min(end, new_capacity)
            if copy_len > 0:
                src = old_feature.value
                src_head = src[end - copy_len:end, :2]                         # copy x,y only; keep z=0
                new_arr[0:copy_len, :2] = src_head

                # Update ranges only with finite values

                with np.errstate(invalid="ignore"):
                    _x_min = float(np.nanmin(src_head[:, 0]))
                    _x_max = float(np.nanmax(src_head[:, 0]))
                    _y_min = float(np.nanmin(src_head[:, 1]))
                    _y_max = float(np.nanmax(src_head[:, 1]))

                _x_min_finite = np.isfinite(_x_min)
                _x_max_finite = np.isfinite(_x_max)
                _y_min_finite = np.isfinite(_y_min)
                _y_max_finite = np.isfinite(_y_max)

                if _x_min_finite and _x_min < self.x_min:
                    self.x_min = _x_min
                if _x_max_finite and _x_max > self.x_max:
                    self.x_max = _x_max
                if _y_min_finite and _y_min < self.y_min:
                    self.y_min = _y_min
                if _y_max_finite and _y_max > self.y_max:
                    self.y_max = _y_max

                x_min_finite = x_min_finite or _x_min_finite
                x_max_finite = x_max_finite or _x_max_finite
                y_min_finite = y_min_finite or _y_min_finite
                y_max_finite = y_max_finite or _y_max_finite

            self.data_traces_writeidx[i] = copy_len

            # Recreate line graphic with new capacity

            try:
                self.fpl_subplot.delete_graphic(line)
            except Exception: 
                pass
            color = self.pensFPL[i % len(self.pensFPL)] if hasattr(self, "pensFPL") else (1, 1, 1, 1)
            new_line = self.fpl_subplot.add_line(
                new_arr,
                isolated_buffer=False,
                colors=pygfx.Color(color),
                thickness=LINEWIDTH
            )
            self.data_traces[i] = new_line
        
        self.data_trace_capacity = new_capacity

        # If no finite data was found, fallback to previous or safe defaults
        if not (x_min_finite and x_max_finite and y_min_finite and y_max_finite):
            prev = getattr(self, "fpl_last_ranges", None)
            if prev:
                x_min, x_max = prev["x"][0], prev["x"][1]
                y_min, y_max = prev["y"][0], prev["y"][1]
            else:
                x_min, x_max = float(-self.maxPoints + 1.), 0.0
                y_min, y_max = -1.0, 1.0
        else:
            x_min, x_max = self.x_min, self.x_max
            y_min, y_max = self.y_min, self.y_max

        # Re-evaluate finiteness after fallback
        x_min_finite = np.isfinite(x_min)
        x_max_finite = np.isfinite(x_max)
        y_min_finite = np.isfinite(y_min)
        y_max_finite = np.isfinite(y_max)
        x_finite = x_min_finite and x_max_finite
        y_finite = y_min_finite and y_max_finite

        x_span = max(SMALLEST, x_max - x_min)                                  # Camera width
        y_span = max(SMALLEST, y_max - y_min)                                  # Camera height
        x_center = 0.5 * (x_min + x_max)                                       # Camera view center
        y_center = 0.5 * (y_min + y_max)                                       # Camera view center
        x_span_finite   = np.isfinite(x_span)
        x_center_finite = np.isfinite(x_center)
        y_span_finite   = np.isfinite(y_span)
        y_center_finite = np.isfinite(y_center)

        # Adjust ranges

        # if x_finite:
        #     x_major = None
        #     if hasattr(self, "axisTickState"):
        #         x_major = self.axisTickState.get("x", {}).get("major")
        #     if x_major is None:
        #         x_major = max(x_span / max(MAJOR_TICKS, 1), 1.0)
        #     x_limits_lo = floor(x_min / x_major) * x_major
        #     x_limits_hi = ceil (x_max / x_major) * x_major
        #     self.fpl_subplot.axes.x_limits = (x_limits_lo, x_limits_hi)
        # if y_finite:
        #     y_major = None
        #     if hasattr(self, "axisTickState"):
        #         y_major = self.axisTickState.get("y", {}).get("major")
        #     if y_major is None:
        #         y_major = max(y_span / max(MAJOR_TICKS, 1), 1.0)
        #     y_limits_lo = floor(y_min / y_major) * y_major
        #     y_limits_hi = ceil (y_max / y_major) * y_major
        #     self.fpl_subplot.axes.y_limits = (y_limits_lo, y_limits_hi)

        # Adjust camera

        x_camera_finite = x_span_finite and x_center_finite
        y_camera_finite = y_span_finite and y_center_finite
        if x_camera_finite and y_camera_finite:
            self.fpl_camera.set_state({
                "width": x_span * CAMERA_PAD,
                "height": y_span * CAMERA_PAD,
                "position": (x_center, y_center, 1.0),                         # z>0 so data at z=0 is in front
                "maintain_aspect": False,                                      # optional; set True if you want locked aspect
            })

        # Adjust axes
        self.fpl_subplot.axes.x.start_value = x_min
        self.fpl_subplot.axes.y.start_value = y_min

        # self.fpl_subplot.axes.update(self.fpl_camera, self.fpl_subplot.viewport.logical_size)
        self.fpl_subplot.axes.update_using_camera()

        # Update Ticks
        if x_finite and y_finite:
            self.fpl_updateAxesTicks(lo=(x_min, y_min), hi=(x_max, y_max), n_major=MAJOR_TICKS, n_minor=MINOR_TICKS)

            self.x_min, self.x_max = x_min, x_max
            self.y_min, self.y_max = y_min, y_max

        self.fpl_subplot.center_scene()

        # Store ranges
        if x_finite and y_finite and x_camera_finite and y_camera_finite:
            self.fpl_last_ranges = {
                # "x": (x_min, x_max, x_span, x_center, x_limits_lo, x_limits_hi), 
                # "y": (y_min, y_max, y_span, y_center, y_limits_lo, y_limits_hi)}
                "x": (x_min, x_max, x_span, x_center), 
                "y": (y_min, y_max, y_span, y_center)}
        else:
            # Keep previous ranges if camera update not possible
            pass
        
        # Rebuild legend if present

        labels = self.channel_names if getattr(self, "channel_names", None) else []
        if self.legend is not None and labels:
            try:
                self.fpl_updateLegend(self.data_traces, labels)
                self.legend_entries = list(labels)
            except Exception:
                pass

    def fpl_createLegend(self):
        fpl_subplot = getattr(self, "fpl_subplot", None)
        if fpl_subplot is None:
            return                                                             # can not crete legend if there is no axis

        legend_dock = self.fpl_subplot.docks["right"]                          # options are right, left, top, bottom
        legend_dock.background_color = pygfx.Color(LEGEND_BACKGROUND_COLOR)
        legend_dock.size = 80                                                  # if top/bottom dock that is the height of dock in pixels, 
                                                                               # if left/right dock that is the width of the dock in pixels,
        return Legend(
            plot_area=legend_dock,                                             # the plot area to attach the legend to
            max_rows = 5,                                                      # how many items per column before wrapping
            background_color = pygfx.Color(LEGEND_BACKGROUND_COLOR),           # optional: the background color of the legend
            label_color      = pygfx.Color(LEGEND_FONT_COLOR),
        )

    @profile
    def fpl_updateLegend(self, lines, labels ):
        """
        Update legend of chart
        """
        legend = getattr(self, "legend", None)
        if legend is None:
            return                                                             # nothing to update when we dont have a legend
        self.fpl_clearLegend()                                                 # Clear the legend before updating
        for line, label in zip(lines, labels):
            self.legend.add_graphic(line, label, label_color = pygfx.Color(LEGEND_FONT_COLOR))
        self.legend.update_using_camera()

    def fpl_clearLegend(self):
        """
        Clear legend, do not remove the legend object itself
        """
        legend = getattr(self, "legend", None)
        if legend is None:
            return                                                             # nothing to update when we dont have a legend

        remover = None
        if hasattr(legend, "remove_graphic"):
            remover = getattr(legend, "remove_graphic")
        elif hasattr(legend, "delete_graphic"):
            remover = getattr(legend, "delete_graphic")

        # Remove each item
        for g in legend.graphics:
            remover(g)
        self.legend_entries = []

    @profile
    def fpl_updateAxesTicks(
        self,
        lo: Optional[tuple[float, float]] = None,
        hi: Optional[tuple[float, float]] = None,
        n_major: int = MAJOR_TICKS,
        n_minor: int = MINOR_TICKS,
    ):
        """
        Update the tick marks of the x and y axis.
        """

        if self.fpl_subplot is None:
            return

        ax = self.fpl_subplot.axes
        if ax is None:
            return

        n_minor  = max(n_minor, 1)
        n_major  = max(n_major, 1)

        # Spacing should be larger than min_major_px in screen space
        MIN_MAJOR_PX = 80                                                      # desired distance in pixels between major ticks (prevent crowding if uses reduced application window size)
        MIN_MINOR_PX = MIN_MAJOR_PX / 5                                        # desired distance in pixels between minor ticks

        # If lo/hi not provided, grab world‐space extent from the rulers
        if lo is None or hi is None:

            state = self.fpl_camera.get_state()
            w2 = 0.5 * state.get("width")  / CAMERA_PAD
            h2 = 0.5 * state.get("height") / CAMERA_PAD
            cx, cy, cz = state.get("position", (0,0,0))
            x_lo = cx - w2
            x_hi = cx + w2
            y_lo = cy - h2
            y_hi = cy + h2

            # (x_lo, x_hi) = ax.x_limits
            # (y_lo, y_hi) = ax.y_limits
            # if x_lo is None or x_hi is None or y_lo is None or y_hi is None:
            #     (x_lo, x_hi) = (ax.x.start_value, ax.x.end_value)
            #     (y_lo, y_hi) = (ax.y.start_value, ax.y.end_value)
            x_span = abs(x_hi - x_lo)
            y_span = abs(y_hi - y_lo)
        else:
            x_lo, y_lo = lo
            x_hi, y_hi = hi
            x_span = abs(x_hi - x_lo)
            y_span = abs(y_hi - y_lo)

        x_major, x_decimals = nice_step(x_span, n_major)
        y_major, y_decimals = nice_step(y_span, n_major)
        x_minor = x_major / n_minor
        y_minor = y_major / n_minor

        # Make sure tick spacing is not too sparse or crowded if window size is changed

        # Data units per pixel
        width_px, height_px = self.fpl_fig.canvas.get_logical_size()
        x_dpp = x_span / width_px
        y_dpp = y_span / height_px

        x_min_major    = x_dpp * MIN_MAJOR_PX
        x_max_major    = x_min_major * 10
        y_min_major    = y_dpp * MIN_MAJOR_PX
        y_max_major    = y_min_major * 10

        if x_major < x_min_major:
            # Nudge major toward pixel target if too dense
            x_major = nudgeup_ticks(x_major, x_min_major)
            x_minor = x_major / n_minor
        elif x_major > x_max_major:
            # If far sparse, gently downscale toward min screen spacing target
            x_major = nudgedown_ticks(x_major, x_max_major)
            x_minor = x_major / n_minor

        if y_major < y_min_major:
            y_major = nudgeup_ticks(y_major, y_min_major)
            y_minor = y_major / n_minor
        elif y_major > y_max_major:
            y_major = nudgedown_ticks(y_major, y_max_major)
            y_minor = y_major / n_minor

        # Enforce minimum pixels between minor ticks
        x_minor_px = x_minor / x_dpp
        y_minor_px = y_minor / y_dpp
        if x_minor_px < MIN_MINOR_PX:
            k = max(1, int(round(MIN_MINOR_PX / x_minor_px)))
            x_minor = x_major / max(1, n_minor // k)
        if y_minor_px < MIN_MINOR_PX:
            k = max(1, int(round(MIN_MINOR_PX / y_minor_px)))
            y_minor = y_major / max(1, n_minor // k)

        # Subplot cache to avoid churn 
        if not hasattr(self, "axisTickState"):
            self.axisTickState = {"x": {"major":None},
                                  "y": {"major":None}}

        x_major_prev = self.axisTickState["x"]["major"]
        y_major_prev = self.axisTickState["y"]["major"]

        # Only apply if meaningfully changed
        changed = (
            x_major_prev is None or y_major_prev is None or
            not isclose(x_major, x_major_prev, rel_tol=REL_TOL, abs_tol=0.0) or
            not isclose(y_major, y_major_prev, rel_tol=REL_TOL, abs_tol=0.0)
        )

        if not changed:
            return

        try:
            ax.grids.xy.major_step = (x_major, y_major)
            ax.grids.xy.minor_step = (x_minor, y_minor)
        except Exception:
            pass

        if DEBUGCHART:
            self.logger.log(logging.INFO,
                f"[{self.instance_name[:15]:<15}]: x_major={x_major} y_major={y_major}"
            )

        # update cache
        self.axisTickState["x"]["major"] = x_major
        self.axisTickState["y"]["major"] = y_major

        # Some FPL versions support tick_format; keep safe
        try:
            ax.x.tick_format = f".{x_decimals}f"
            ax.y.tick_format = f".{y_decimals}f"
        except Exception:
            pass

    def fpl_save_pipeline_cache(self):
        """
        Save the GPU pipeline cache to a file.
        
        This is not yet exposed by wgpu
        A precompiled gpu pipeline would improve startup time
        """
        try:
            cache_blob = None

            # Try common locations across versions
            cache_blob = getattr(self.fpl_fig, "cache", None)
            if not cache_blob:
                renderer = getattr(self.fpl_fig, "renderer", None)
                for attr in ("pipeline_cache", "shader_cache", "cache"):
                    val = getattr(renderer, attr, None) if renderer else None
                    if hasattr(val, "get_data"):
                        cache_blob = val.get_data()
                        break
                    if isinstance(val, (bytes, bytearray)):
                        cache_blob = val
                        break

            if cache_blob:
                with open(CACHE_FILE, "wb") as f:
                    f.write(bytes(cache_blob))
                self.logSignal.emit(logging.INFO,
                    f"[{self.instance_name[:15]:<15}]: Saved pipeline cache to {CACHE_FILE}."
                )
            else:
                self.logSignal.emit(logging.INFO,
                    f"[{self.instance_name[:15]:<15}]: No pipeline cache available on this backend/version."
                )
        except Exception as e:
            self.logSignal.emit(logging.WARNING,
                f"[{self.instance_name[:15]:<15}]: Pipeline cache save not supported: {e}"
            )

    @pyqtSlot()
    def on_fpl_user_interaction(self, ev):
        if ev.type == "pointer_move" and not getattr(ev, "buttons", ()):
            return                                                             # ignore mere hovers

        # Defer tick work so the controller finishes applying pan/zoom first.
        # Use existing throttled gate.
        if self.tickGate:
            self.tickGate = False
            self.tickGate_timer.start(self.tickGate_interval_ms)
            # schedule the actual tick refresh after controller has updated camera
            QTimer.singleShot(10, self.refresh_ticks_from_camera)

    @pyqtSlot()
    @profile
    def refresh_ticks_from_camera(self):
        """ Update Tick Marks and Redraw when Camera view changes. """
        # self.fpl_subplot.axes.update(self.fpl_camera, self.fpl_subplot.viewport.logical_size)
        self.fpl_subplot.axes.update_using_camera()
        self.fpl_updateAxesTicks(n_major=MAJOR_TICKS, n_minor=MINOR_TICKS)     # without specifying lo,hi, camera status is used
        self.fpl_subplot.center_scene()
        self.fpl_fig.canvas.request_draw()

    ########################################################################################################################################
    # Main Function
    ########################################################################################################################################

    @pyqtSlot()
    @profile
    def updatePlot(self) -> None:
        """
        Update the chart plot.

        - Plots data.
        - Ensures that number of traces matches number of data columns.
        - Sets the horizontal range to show the newest data up to maxPoints.
        - Sets vertical range dynamically based on min/max values of all data traces.
        - Updates the legend.

        - Handles both pyqtgraph and fastplotlib plotting libraries.
        """

        tic = time.perf_counter()

        # Retrieve and prepare the data 
        # ----------------------------------------

        oldest_sample, newest_sample = self.buffer.counter                     # sample numbers
        delta_samples = newest_sample - self.previous_newest_sample
        if delta_samples <= 0:                                                 # no new data
            # Early exit if nothing new
            #    Optionally create code that adjusts axes/legend if UI size changed (skip here for speed)
            return
        self.previous_newest_sample = newest_sample

        if delta_samples >= self.maxPoints:
            delta_samples = self.maxPoints                                     # too much new data, only take the last maxPoints and skip the rest 

        if not USE_FASTPLOTLIB:
            # PyQtGraph does not support sliced data update
            # Need to obtain full display range of data
            data = self.buffer.last(self.maxPoints)
        else:
            # FastPlotLib supports sliced data update
            # Need to obtain only the new data
            data = self.buffer.last(delta_samples)

        num_rows, num_cols = data.shape

        # Adjust number of data traces on chart if needed
        # ----------------------------------------
        # Grow or Shrink

        num_traces        = len(self.data_traces)
        delta_data_traces = num_cols - num_traces                              # How many traces do we need to add/remove?

        if delta_data_traces > 0:

            # ─── Grow numbers of data traces ─────────────

            for idx in range(delta_data_traces):
                if not USE_FASTPLOTLIB:
                    # PyQtGraph ─────────────────────────────────
                    new_data_trace = self.chartWidgetPG.plot(
                        [], 
                        [], 
                        pen=self.pensPG[(idx+num_traces) % len(self.pensPG)], 
                        name=f"Trace {idx}",
                        antialias=False,                                       # AA is expensive; keep it off for streams
                        clipToView=True,                                       # do less work: only process visible vertices
                        autoDownsample=True,                                   # let pg decimate when dense on screen
                        downsampleMethod='peak',                               # preserves spikes; good for signals
                        connect='finite',                                      # cheap segmentation around NaNs
                    )
                else:
                    # FastPlotLib ─────────────────────────────────
                    #   uses 3D points (x,y,z), for 2D plots we set z=0
                    new_arr = np.full((self.data_trace_capacity, 3), np.nan, dtype=np.float32)
                    new_arr[:, 2] = 0.0                                        # (z) value is zero everywhere
                    new_data_trace = self.fpl_subplot.add_line(
                        new_arr, 
                        isolated_buffer=False,                                 # since we already allocated the buffer above, we use shared buffers for better performance
                        colors=pygfx.Color(self.pensFPL[(idx+num_traces) % len(self.pensFPL)]), # color for the line
                        thickness=LINEWIDTH                                    # line width
                    )
                self.data_traces.append(new_data_trace)
                self.data_traces_writeidx.append(0)

        elif delta_data_traces < 0:

            # ──── Shrink number of data traces ─────────────

            for _ in range(-delta_data_traces):
                # Remove oldest trace
                old_data_trace = self.data_traces.pop()
                _ = self.data_traces_writeidx.pop()
                if not USE_FASTPLOTLIB:
                    self.chartWidgetPG.removeItem(old_data_trace)
                else:
                    self.fpl_subplot.delete_graphic(old_data_trace)

        #                 
        # Plot data
        # ----------------------------------------

        # Compute x/y values and their ranges

        # ─── X values ─────────────
        if num_rows > 0:
            # To speed up we reuse preallocated x base
            #   add offset and store results in x_view
            base_tail = self.x_base[-num_rows:]
            np.add(base_tail, newest_sample, out=self.x_view[:num_rows])
            x_vals = self.x_view[:num_rows]                                    # Current x values for plotting
        else:
            x_vals = self.x_view[:0]                                           # keep same
        num_samples = num_rows

        # ─── Y values ─────────────
        y_vals = data                                                          # Y-Axis values are the data values

        # Throughput counter for this update, we keep track of total points uploaded at the end of this function
        total_points_uploaded = 0

        # Compute axis ranges

        # X Range, length remains fixed to user selected history length: maxPoints
        self.x_min = float(newest_sample - self.maxPoints + 1)                 # left edge of x axis
        self.x_max = float(newest_sample)                                      # right edge of x axis

        # Y Range:
        # ----------------------------------------
        # - PG updated full window (we can calculate min/max of display window directly here
        # - FPL updates with latest data only and need to calculate min/max from visible buffers at later time in the code below)
        if not USE_FASTPLOTLIB:
            # calculate here
            self.y_min = float(np.nanmin(y_vals))                              # 4%
            self.y_max = float(np.nanmax(y_vals))                              # 2% 
                    
            if not isfinite(self.y_min):
                self.y_min = -1.0

            if not isfinite(self.y_max):
                self.y_max = 1.0
        else:
            # calculate later in the code because we need to calculate it from the full data traces
            pass

        # Plot
        # ----------------------------------------

        if not USE_FASTPLOTLIB:
            # PyQtGraph

            for i in range(num_cols):
                self.data_traces[i].setData(x_vals,y_vals[:, i])               # 40%
                total_points_uploaded += num_samples

        else:
            # FastPlotLib ─────────────────────────────────

            # We use partial updates
            # Since fastplotlib requires a fixed size buffer, unused data points are NaN
            # Unused data points are at the end of the data trace
            # We use NaN filtering when adding new data to the buffer
            #   if we were to keep NaNs they break the plot lines in fastplotlib 
            #   this will result in data traces with different lengths of valid data
            #   we keep track of valid data in the data trace with write_idx
            # Therefore we implement for each data trace:
            #  - trimming old data from buffer (anything older than newest_sample - maxPoints)
            #  - appending new data to buffer at write index
            #  - computing y min/max from the data trace (not just the added data)
            #  - updating write index

            mask = np.isfinite(y_vals)                                         # mask of valid (non-NaN) data points

            for i in range(num_cols):

                # Trim Data
                # ----------------------------------------

                # Need to trim data in chart that is older than requested history (newest_sample - maxPoints)
                # And move the remaining data to the beginning of data trace
                line      = self.data_traces[i].data                           # make code more readable
                write_idx = self.data_traces_writeidx[i]                       # make code more readable
                capacity  = self.data_trace_capacity                           # make code more readable

                if write_idx > 0:
                    # trim only traces with data
                    xmin_allowed = newest_sample - self.maxPoints + 1
                    filled_x = line.value[:write_idx, 0]
                    trim_mask = np.isfinite(filled_x) & (filled_x < xmin_allowed)
                    trim_len = int(trim_mask.sum())
                    if trim_len > 0:
                        # we need to trim
                        keep_start = trim_len
                        keep_end   = write_idx
                        keep_len   = keep_end - keep_start
                        if keep_len > 0:
                            # partial replace, shift valid data to left
                            line[0:keep_len, 0:2] = line.value[keep_start:keep_end,0:2] # only copy x,y, z is zero everywhere
                            # clear tail
                            line[keep_len:keep_end, 0:2] = np.nan
                            write_idx = keep_len
                        else:
                            # full replace, clear entire buffer
                            line[:write_idx,0:2] = np.nan
                            write_idx = 0

                # Append new data
                # ----------------------------------------
                # GPU vertex buffer is float32, python float is float64

                col_mask  = mask[:, i]
                x = x_vals[col_mask].astype(np.float32)                        # convert to float32 for GPU vertex rendering
                y = y_vals[col_mask, i].astype(np.float32)                     # convert to float32 for GPU vertex rendering
                num_valid_samples = int(x.size)

                if num_valid_samples == 0:
                    continue

                # Check for buffer overrun
                room = capacity - write_idx

                if num_valid_samples > capacity:
                    # Incoming batch alone exceeds the whole buffer:
                    # keep only the newest `capacity` and overwrite from 0.
                    x = x[-capacity:]
                    y = y[-capacity:]
                    dropped = num_valid_samples - capacity
                    num_valid_samples = capacity
                    write_idx = 0
                    # line[:capacity, 0:2] = np.nan                           # clear before overwrite (optional)
                    # self.logger.log(logging.WARNING,
                    #     f"[{self.instance_name[:15]:<15}]: Data trace {i} buffer full, dropped {dropped} samples"
                    # )

                elif num_valid_samples > room:
                    # Not enough room to append new data, need to drop oldest samples
                    shift = num_valid_samples - room
                    keep = max(0, write_idx - shift)
                    if keep > 0:
                        # Move newest existing samples to beginning of buffer
                        line[0:keep, 0:2] = line.value[shift:shift + keep, 0:2]
                    if write_idx > keep:
                        line[keep:write_idx, 0:2] = np.nan
                    write_idx = keep
                    # self.logger.log(logging.WARNING,
                    #     f"[{self.instance_name[:15]:<15}]: Data trace {i} buffer full, dropped {shift} samples"
                    # )

                # Add new data
                end = write_idx + num_valid_samples
                line[write_idx:end, 0] = x
                line[write_idx:end, 1] = y
                # line[write_idx:end, 2] = np.float32(0.0) # z value was set to zero previously
                write_idx = end

                self.data_traces_writeidx[i] = write_idx
                total_points_uploaded += num_valid_samples

            # Compute Y range from data traces (not just the appended data)

            ymins = np.full((num_cols, 1), np.nan, dtype=np.float32)
            ymaxs = np.full((num_cols, 1), np.nan, dtype=np.float32)
            for i in range(num_cols):
                write_idx = self.data_traces_writeidx[i]
                if write_idx > 0:
                    with np.errstate(invalid='ignore', all='ignore'):
                        seg = self.data_traces[i].data.value[:write_idx, 1]    # y value
                        if seg.size > 0:
                            ymins[i] = np.min(seg)                             # should not contain NaNs
                            ymaxs[i] = np.max(seg)                             # should not contain NaNs
            self.y_min = float(np.nanmin(ymins))
            self.y_max = float(np.nanmax(ymaxs))
            if not isfinite(self.y_min):
                self.y_min = -1.0
            if not isfinite(self.y_max):
                self.y_max = 1.0    
 
        # Adjust X and Y ranges, Tick marks, Camera View
        # ----------------------------------------

        if not USE_FASTPLOTLIB:
            # PyQtGraph ─────────────────────────────────

            x_min, x_max = self.x_min, self.x_max
            y_min, y_max = self.y_min, self.y_max
            x_span = max(SMALLEST, x_max - x_min)
            y_span = max(SMALLEST, y_max - y_min)

            # Avoid redundant setRange and setTick calls by comparing to previous values
            prev = getattr(self, "pg_last_ranges", None)
            if not prev:
                # First time run, seed ranges once
                self.viewBox.setXRange(self.x_min, x_max)
                self.viewBox.setYRange(self.y_min, y_max)
                self.pg_updateAxesTicks("x", x_min, x_max, n_major=MAJOR_TICKS, n_minor=MINOR_TICKS)
                self.pg_updateAxesTicks("y", y_min, y_max, n_major=MAJOR_TICKS, n_minor=MINOR_TICKS)
                self.pg_last_ranges = {"x": (x_min, x_max, x_span), 
                                        "y": (y_min, y_max, y_span)}
            else:
                # Previous values
                x_min_prev, x_max_prev, x_span_prev = prev.get("x", (None, None, None))
                y_min_prev, y_max_prev, y_span_prev = prev.get("y", (None, None, None))

                x_limits_changed = False
                x_span_changed   = False
                y_limits_changed = False
                y_span_changed   = False

                # ─── X range ─────────────
                if x_min_prev is None or x_max_prev is None:
                    # No previous values
                    x_limits_changed  = True
                    x_span_changed    = True
                else:
                    # compare with previous values
                    if (x_min_prev, x_max_prev) != (self.x_min, self.x_max):
                        x_limits_changed = True
                        if x_span != x_span_prev:
                            x_span_changed = True

                # ──── Y range ─────────────
                if y_min_prev is None or y_max_prev is None:
                    # no previous values
                    y_limits_changed  = True
                    y_span_changed    = True
                    y_center_changed  = True
                else:
                    #  expand or shrink with hysteresis
                    if not (isclose(y_min, y_min_prev, rel_tol=REL_TOL, abs_tol=0) or
                            isclose(y_max, y_max_prev, rel_tol=REL_TOL, abs_tol=0)):
                        y_limits_changed = True
                        if not isclose(y_span, y_span_prev, rel_tol=REL_TOL, abs_tol=0):
                            y_span_changed = True

                if x_limits_changed:
                    # set new range and update ticks
                    self.viewBox.setXRange(x_min, x_max)
                    x_min_prev, x_max_prev = x_min, x_max

                if y_limits_changed:
                    # set new range and update ticks
                    self.viewBox.setYRange(y_min, y_max)
                    y_min_prev, y_max_prev = y_min, y_max

                if x_span_changed:
                    self.pg_updateAxesTicks("x", x_min, x_max, n_major=MAJOR_TICKS, n_minor=MINOR_TICKS)
                    x_span_prev = x_span

                if y_span_changed:
                    self.pg_updateAxesTicks("y", y_min, y_max, n_major=MAJOR_TICKS, n_minor=MINOR_TICKS)
                    y_span_prev = y_span

                # TranslateBy is actually less efficient
                #   left over code
                # dxr          = self.x_max - x_max_prev
                # dxl          = self.x_min - x_min_prev
                # if x_span_prev == x_span and dxr == dxl:
                #     # translate view, no tick update needed
                #     # self.viewBox.translateBy(x=dxr, y=0.0) # 38% 970
                #     # self._x_realign_count += 1 
                #     # if self._x_realign_count >= 120:
                #     #    self.viewBox.setXRange(self.x_min, self.x_max) # 32% 830
                #     #    self._x_realign_count = 0
                # else:
                #     # set new range and update ticks
                #     self.viewBox.setXRange(self.x_min, self.x_max)
                #     if x_span != x_span_prev:
                #         self.pg_updateAxesTicks("x", self.x_min, self.x_max, n_major=MAJOR_TICKS, n_minor=MINOR_TICKS)

                # Store current values for next comparison
                self.pg_last_ranges = {
                    "x": (x_min_prev, x_max_prev, x_span_prev), 
                    "y": (y_min_prev, y_max_prev, y_span_prev)}

        else:
            # FastPlotLib ─────────────────────────────────

            # 1) set data limits on the axes
            # 2) set camera position, width and height
            # 3) updated axes using camera
            # 4) update axes ticks

            x_min, x_max = self.x_min, self.x_max
            y_min, y_max = self.y_min, self.y_max
            x_span = max(SMALLEST, x_max - x_min)
            y_span = max(SMALLEST, y_max - y_min)
            x_center = 0.5 * (x_min + x_max)                                   # Camera view x center
            y_center = 0.5 * (y_min + y_max)                                   # Camera view y center

            # Avoid redundant limits, ticks, camera calls by comparing to previous values
            prev_ranges = getattr(self, "fpl_last_ranges", None)
            if not prev_ranges:
                # First time run, no previous values
                # ----------------------------------------

                # # X limits
                # # get the tick mark major increment
                # x_major = None
                # if hasattr(self, "axisTickState"):
                #     x_major = self.axisTickState.get("x", {}).get("major")
                # if x_major is None:
                #     x_major = max(x_span / max(MAJOR_TICKS, 1), 1.0)
                # # for stable tick marks, limit the axis range to multiples of major tick
                # x_limits_lo = floor(x_min / x_major) * x_major # floor to make it smaller if needed
                # x_limits_hi = ceil (x_max / x_major) * x_major # ceil to make it larger if needed
                # self.fpl_subplot.axes.x_limits = (x_limits_lo, x_limits_hi)
                # # now the axis limits include the full range of data and are padded to multiple of major tickmark interval

                # # repeat the same for y
                # y_major = None
                # if hasattr(self, "axisTickState"):
                #     y_major = self.axisTickState.get("y", {}).get("major")
                # if y_major is None:
                #     y_major = max(y_span / max(MAJOR_TICKS, 1), 1.0)
                # y_limits_lo = floor(y_min / y_major) * y_major
                # y_limits_hi = ceil (y_max / y_major) * y_major
                # self.fpl_subplot.axes.y_limits = (y_limits_lo, y_limits_hi)

                # Now set the camera state, 
                # we need to update it each iteration as x values increase each update
                self.fpl_camera.set_state({
                    "width": x_span * CAMERA_PAD,
                    "height": y_span * CAMERA_PAD,
                    "position": (x_center, y_center, 1.0),                     # z>0 so data at z=0 is in front of camera
                    "maintain_aspect": False,                                  # optional; set True if you want locked aspect
                })

                # Adjust axes
                self.fpl_subplot.axes.x.start_value = x_min
                self.fpl_subplot.axes.y.start_value = y_min

                # Adjust axes to camera view
                # self.fpl_subplot.axes.update(self.fpl_camera, self.fpl_subplot.viewport.logical_size)
                self.fpl_subplot.axes.update_using_camera()

                # Update the axes ticks
                self.fpl_updateAxesTicks(lo=(x_min, y_min), hi=(x_max,y_max), n_major=MAJOR_TICKS, n_minor=MINOR_TICKS)

                # is redundant
                # self.fpl_subplot.center_scene()

                self.fpl_last_ranges = {
                    "x": (x_min, x_max, x_span, x_center), 
                    "y": (y_min, y_max, y_span, y_center)}
            else:
                # Previous values
                # ----------------------------------------
                x_min_prev, x_max_prev, x_span_prev, x_center_prev = prev_ranges.get("x", (None, None, None, None))
                y_min_prev, y_max_prev, y_span_prev, y_center_prev = prev_ranges.get("y", (None, None, None, None))
                x_limits_changed = False
                x_span_changed   = False
                x_center_changed = False
                y_limits_changed = False
                y_span_changed   = False
                y_center_changed = False

                # ─── X range & position ─────────────
                if x_min_prev is None or x_max_prev is None:
                    # No previous values
                    x_limits_changed  = True
                    x_span_changed    = True
                    x_center_changed  = True
                else:
                    # Compare with previous values
                    if (x_min_prev, x_max_prev) != (self.x_min, self.x_max):   # fastest to detect any change
                        x_limits_changed = True
                        if x_span != x_span_prev:
                            x_span_changed = True
                        if x_center != x_center_prev:
                            x_center_changed = True

                # ──── Y range & position─────────────
                if y_min_prev is None or y_max_prev is None:
                    # no previous values
                    y_limits_changed  = True
                    y_span_changed    = True
                    y_center_changed  = True
                else:
                    #  expand or shrink with hysteresis
                    if not (isclose(y_min, y_min_prev, rel_tol=REL_TOL, abs_tol=0) or
                            isclose(y_max, y_max_prev, rel_tol=REL_TOL, abs_tol=0)):
                        y_limits_changed = True
                        if y_span != y_span_prev:
                            y_span_changed = True
                        if y_center != y_center_prev:
                            y_center_changed = True

                # # adjust data ranges and axis position in scene
                # if x_limits_changed:
                #     x_major = None
                #     if hasattr(self, "axisTickState"):
                #         x_major = self.axisTickState.get("x", {}).get("major")
                #     if x_major is None:
                #         x_major = max(x_span / max(MAJOR_TICKS, 1), 1.0)
                #     x_limits_lo = floor(x_min / x_major) * x_major
                #     x_limits_hi = ceil (x_max / x_major) * x_major
                #     if (x_limits_lo, x_limits_hi) != (x_limits_lo_prev, x_limits_hi_prev):
                #         self.fpl_subplot.axes.x_limits = (x_limits_lo, x_limits_hi)
                #         x_limits_lo_prev, x_limits_hi_prev = x_limits_lo, x_limits_hi
                #     x_min_prev, x_max_prev = x_min, x_max

                # if y_limits_changed:
                #     y_major = None
                #     if hasattr(self, "axisTickState"):
                #         y_major = self.axisTickState.get("y", {}).get("major")
                #     if y_major is None:
                #         y_major = max(y_span / max(MAJOR_TICKS, 1), 1.0)
                #     y_limits_lo = floor(y_min / y_major) * y_major
                #     y_limits_hi = ceil (y_max / y_major) * y_major
                #     if (y_limits_lo, y_limits_hi) != (y_limits_lo_prev, y_limits_hi_prev):
                #         self.fpl_subplot.axes.y_limits = (y_limits_lo, y_limits_hi)
                #         y_limits_lo_prev, y_limits_hi_prev = y_limits_lo, y_limits_hi
                #     y_min_prev, y_max_prev = y_min, y_max

                # update Camera
                camera_changed = (x_center_changed or y_center_changed or
                                  x_span_changed or y_span_changed)
                if camera_changed:
                    self.fpl_camera.set_state({
                        "width":  x_span * CAMERA_PAD,
                        "height": y_span * CAMERA_PAD,
                        "position": (x_center, y_center, 1.0),                 # z>0 so data at z=0 is in front
                        "maintain_aspect": False,                              # optional; set True if you want locked aspect
                    })
                    x_span_prev = x_span
                    y_span_prev = y_span
                    x_center_prev = x_center
                    y_center_prev = y_center

                if x_limits_changed:
                    self.fpl_subplot.axes.x.start_value = x_min
                if y_limits_changed:
                    self.fpl_subplot.axes.y.start_value = y_min

                if camera_changed or x_limits_changed or y_limits_changed:
                    # self.fpl_subplot.axes.update(self.fpl_camera, self.fpl_subplot.viewport.logical_size)
                    self.fpl_subplot.axes.update_using_camera()

                if x_span_changed or y_span_changed:
                    self.fpl_updateAxesTicks(lo=(x_min, y_min), hi=(x_max,y_max), n_major=MAJOR_TICKS, n_minor=MINOR_TICKS)

                # Store values for next update
                self.fpl_last_ranges = {
                    "x": (x_min_prev, x_max_prev, x_span_prev, x_center_prev), 
                    "y": (y_min_prev, y_max_prev, y_span_prev, y_center_prev)}

        # Adjust legend
        # ----------------------------------------
                
        # Make channel names consistent
        if (self.channel_names_dict != self.prev_channel_names_dict):
            # Channel names changed
            self.prev_channel_names_dict = dict(self.channel_names_dict)       # Store a copy of channel_names(dict makes shallow copy)
            # Variables sorted from dictionary
            sorted_vars = sorted(self.channel_names_dict.items(), key=lambda x: x[1])
            self.channel_names = [name for name, _ in sorted_vars]

        if self.legend is None:
            # No legend, need to initialize and create the legend
            if not USE_FASTPLOTLIB:
                self.legend = self.pg_createLegend()                           # consolidated creation & styling
                self.pg_updateLegend(self.data_traces, self.channel_names)
            else:
                # Should not happen as we create legend at init time
                self.legend = self.fpl_createLegend()
                self.fpl_updateLegend(self.data_traces, self.channel_names)
            self.legend_entries = list(self.channel_names)

        else:
            # Legend exists
            current = getattr(self, "legend_entries", [])
            if current != self.channel_names:
                # Update legend, since channel names changed
                if not USE_FASTPLOTLIB:
                    self.pg_updateLegend(self.data_traces, self.channel_names)
                else:
                    self.fpl_updateLegend(self.data_traces, self.channel_names)
                self.legend_entries = list(self.channel_names)

        if USE_FASTPLOTLIB:
            self.fpl_fig.canvas.request_draw()

        self.points_uploaded += total_points_uploaded

        if DEBUGCHART:
            toc = time.perf_counter()
            self.logSignal.emit(
                logging.DEBUG,
                f"[{self.instance_name[:15]:<15}]: Uploaded pts={total_points_uploaded}"
            )
            self.logSignal.emit(
                logging.DEBUG,
                f"[{self.instance_name[:15]:<15}]: Plot updated in {1000 * (toc - tic):.2f} ms"
            )

        if PROFILEME:
            toc = time.perf_counter()
            self.mtoc_updatePlot = max ((toc - tic), self.mtoc_updatePlot)

    # ==========================================================================
    # Slots
    # ==========================================================================

    @pyqtSlot()
    def on_throughputTimer(self) -> None:
        """
        Report throughput numbers
        """
        pps = self.points_uploaded                                             # points per second
        self.points_uploaded = 0                                               # restart counting
        self.throughputUpdate.emit(0.0, float(pps), "chart")                   # announce throughput

    @pyqtSlot()
    def on_mtocRequest(self) -> None:
        """
        Report the profiling information.
        """
        log_message = textwrap.dedent(f"""
            Chart UI Profiling
            =============================================================
            mtoc_updatePlot         took {self.mtoc_updatePlot*1000:.2f} ms
            mtoc_process_lines_hdr  took {self.mtoc_process_lines_header*1000:.2f} ms
            mtoc_process_lines_smpl took {self.mtoc_process_lines_simple*1000:.2f} ms
        """)
        self.logSignal.emit(-1, log_message)
        self.mtoc_updatePlot = 0.
        self.mtoc_process_lines_header = 0.
        self.mtoc_process_lines_simple = 0.

    @pyqtSlot()
    def cleanup(self) -> None:
        """
        Cleanup the chart UI.

        - Stops the chart update timer.
        - Disconnects the updatePlot function from the timer.
        - Clears the plot data and legend.
        - Resets the plot axis ranges.
        """
        # Stop Chart Timer
        if hasattr(self.ChartTimer, "isActive") and self.ChartTimer.isActive():
            self.ChartTimer.stop()
            try:
                self.ChartTimer.timeout.disconnect()
            except Exception:
                self.logSignal.emit(logging.ERROR, f"[{self.instance_name[:15]:<15}]: Failed to disconnect ChartTimer timeout")

        # Remove Traces
        if getattr(self, "data_traces", None):
            # Remove each trace from the chart before clearing the list
            for data_trace in self.data_traces:
                if not USE_FASTPLOTLIB:
                    self.chartWidgetPG.removeItem(data_trace)
                else:
                    self.fpl_subplot.delete_graphic(data_trace)
            self.data_traces.clear()
        
        # Legend
        if getattr(self, "legend", None) is not None:
            if not USE_FASTPLOTLIB:
                # PyQtGraph
                self.pg_clearLegend()
            else:
                # FastPlotLib
                self.fpl_clearLegend()
            self.legend = None

        # Clear plot/figure (choose the active backend) ----
        if not USE_FASTPLOTLIB:
            if getattr(self, "chartPGInitialized", False):
                self.chartWidgetPG.clear()
        else:
            if getattr(self, "chartFPLInitialized", False):
                self.fpl_subplot.clear()
                self.fpl_fig.clear()

        self.logSignal.emit(
            logging.INFO, 
            f"[{self.instance_name[:15]:<15}]: Cleaned up."
        )

    # ==========================================================================
    # Process Lines Function without Headers
    # ==========================================================================

    @staticmethod
    @njit(cache=True)
    def ensure_capacity(arr, rows, cols, rows_needed, cols_needed):
        """
        Nopython‐compatible growth logic for a 2D float64 array.
        Returns (new_arr, new_rows, new_cols).
        """

        if rows_needed > rows:
            rows_to_add = rows_needed - rows + 1
            half       = rows // 2
            if half > rows_to_add:
                rows_to_add = half
        else:
            rows_to_add = 0

        if cols_needed + 1 > cols:
            cols_to_add = cols_needed - cols + 1
            half        = cols // 2
            if half > cols_to_add:
                cols_to_add = half
        else:
            cols_to_add = 0

        if rows_to_add or cols_to_add:
            new_rows = rows + rows_to_add
            new_cols = cols + cols_to_add
            new_arr  = np.empty((new_rows, new_cols), dtype=arr.dtype)
            new_arr[:] = np.nan
            new_arr[:rows, :cols] = arr
            return new_arr, new_rows, new_cols
        else:
            return arr, rows, cols

    # - Split data into segments
    #
    # "1 2 3 4, 4 5 6 7"      > ["1 2 3 4", " 4 5 6 7"] 
    # " , 1 2 3 4, 4 5 6 7, " > [' ', ' 1 2 3 4', ' 4 5 6 7', ' ']
    SEG_SPLIT = lambda s: s.split(',')

    # Python implementation 
    @profile
    def process_lines_simple(self, lines, encoding="utf-8") -> None:
        """
        Processing of data without headers. Python version.

        A list of text lines is provided.
        Each line contains numbers, spaces or commas.
        We convert each line to numbers so that we can place them into a numpy array.
        A column in the data array is a data channel.
        Numbers separated by a space belong to the same channel.
        A comma separates data into channels.
        A line containing numbers separated by spaces or commas is organized so that
           numbers separated by space belong to the same channel and the comma introduces a new channel.
        Some lines might contain more channels than others, in that case the channels without new data
           are assigned NaNs and the location for the next data insert point is increased.
        The next new data insert location is set for all channels to be the same and is incremented 
           after each line by the largest number of data points found for any channel in that line.
        Unassigned numbers in a channel remain NaN which is the initialization value of the data array.
        """

        if PROFILEME:
            tic = time.perf_counter()

        # Acceleration
        data_array = self.data_array
        push       = self.buffer.push
        thread_id  = self.thread_id
        seg_split  = self.SEG_SPLIT
        ensure_capacity = self.ensure_capacity
        
        row = 0                                                                # Tracks row position in data_array
        max_len_segment = 0                                                    # Track longest segment
        num_columns = 0                                                        # Track maximum column index
        new_samples = 0                                                        # Track number of new samples
        rows, cols = data_array.shape                                          # Size of temporary array to organize data

        for line in lines:
            # Decode the line if it's a byte object
            if isinstance(line, (bytes, bytearray)):
                decoded_line = line.decode(encoding, errors='replace')         # Decode bytes to str, replace errors
            else:
                decoded_line = line

            segments = seg_split(decoded_line)

            max_len_segment = 0

            # Convert segments to NumPy arrays
            for i, seg in enumerate(segments):
                segment = seg.strip()                                          # Remove leading/trailing whitespace

                if segment == '':
                    segment_data = np.array([np.nan], dtype=np.float64)
                else:
                    segment_data = np.fromstring(segment, dtype=np.float64, sep=' ')
                    if segment_data.size == 0:
                        # parser failed, treat as NaN
                        segment_data = np.array([np.nan], dtype=np.float64)
                        self.logSignal.emit(
                            logging.WARNING,
                            f"[{thread_id}]: Could not parse '{seg}' on line '{decoded_line}'"
                        )

                len_segment = len(segment_data)
                row_end     = row + len_segment
                max_len_segment = max(max_len_segment, len_segment)

                data_array, rows, cols = ensure_capacity(
                    data_array, rows, cols, row_end, i
                )
                
                # Store the values in `data_array`
                data_array[row:row_end, i] = segment_data
                max_len_segment = max(max_len_segment, segment_data.size)

            new_samples += max_len_segment
            row += max_len_segment  

            num_columns = max(len(segments), num_columns)                      # keep track of columns used

        # Update variable names
        self.channel_names_dict = {str(i + 1): i for i in range(num_columns)}

        # Push only the valid portion of data_array to the buffer
        push(data_array[:new_samples, :num_columns])

        # Clear only the used portion of `data_array`
        data_array[:new_samples, :num_columns] = np.nan
        # For next time
        self.data_array = data_array

        if PROFILEME:
            toc = time.perf_counter()
            self.mtoc_process_lines_simple = max((toc - tic), self.mtoc_process_lines_simple)

    # C accelerated implementation, is about 10 time faster than the python implementation
    @profile
    def fast_process_lines_simple(self, lines, encoding="utf-8") -> None:
        """
        Fast processing of data without headers, via our pybind11 parser.
        """
        if PROFILEME:
            tic = time.perf_counter()

        # 1) Decode any bytes → str
        # decoded = [
        #     l.decode(encoding, errors='replace') if isinstance(l, (bytes, bytearray)) else l
        #     for l in lines
        # ]

        # 2) Call the C++ parser: returns a trimmed np.ndarray
        # 36% of time spent here
        data, shape, channel_names_dict  = simple_parser.parse_lines(lines, channel_names=self.channel_names_dict, strict=False, gil_release=True) # 54% 61

        # 3) Push the array into the buffer
        # 28% of time spent here
        self.buffer.push(data)                                                 # 39%, 43

        # 4) Update channel_names
        self.channel_names_dict = channel_names_dict

        if PROFILEME:
            toc = time.perf_counter()
            # record the worst-case time
            self.mtoc_process_lines_simple = max((toc - tic),  self.mtoc_process_lines_simple)

    # ==========================================================================
    # Process Lines Function with Headers
    # ==========================================================================

    # - Split data into segments
    #
    # "1 2 3 4, 4 5 6 7"      > ["1 2 3 4", " 4 5 6 7"] 
    # " , 1 2 3 4, 4 5 6 7, " > [' ', ' 1 2 3 4', ' 4 5 6 7', ' ']
    SEG_SPLIT = lambda s: s.split(',')

    # - Separate headers from data
    #
    # "Power: 1 2 3 4"                          > "Power" , "1 2 3 4"
    # "Power: 1 2 3 4; 4 5 6 7"                 > "Power" , "1 2 3 4; 4 5 6 7"
    # "Power: 1 2 3 4, 4 5 6 7"                 > "Power" , "1 2 3 4, 4 5 6 7"
    # "Speed: 1 2 3 4, Power: 1 2 3 4"          > "Speed", "1 2 3 4, ", "Power" , "1 2 3 4"
    # "Speed: 1 2 3 4, 5 6 7 8, Power: 1 2 3 4" > "Speed", "1 2 3 4, 5 6 7 8,", "Power" , "1 2 3 4"
    #
    HEADER_REGEX = re.compile(
        r'([A-Za-z][\w ]*):\s*'                                                #  <header>: starts with a letter, then any combination of word-chars (\w = letters, digits, underscore) or spaces
        r'(.*?)'                                                               #  <data> (non-greedy)
        r'(?=\s*[A-Za-z][\w ]*:\s*|$)'                                         #  up to next <header>: or end
    )
    HEADER_SPLIT = HEADER_REGEX.findall
    # NAMED_SEGMENT_REGEX = re.compile(r'([A-Za-z ]+):([\d\s;,]+)')
    # NAMED_SEGMENT_REGEX = re.compile(r'(\w+):([\d\s;,]+)')         # No spaces in variable names allowed, will truncate the name
    # NAMED_SEGMENT_REGEX = re.compile(r'\s*,?(\w+):\s*([\d\s;,]+)')
    # NAMED_SEGMENT_REGEX = re.compile(r'(\w+):([\d\s;,]+?)(?=\s*\w+:|$)')

    # Python implementation
    @profile
    def process_lines_header(self, lines, encoding="utf-8") -> None:
        """
        Processing of data with headers.

        A list of text lines is provided.
        Each line can contain headers and data.

        Headers are separated by a colon and data is separated by spaces and commas, the same way as in the simple parser.
        In the simple parser a comma is used to separate data into channels.
        A header is a variable name and the data that follows belongs to that variable.
        A line can contain multiple headers and data segments.
        A line can be empty or contain empty data segments as well as data without headers. 
        When a header is followed by data separated by commas, 
          the data is split into channels and each channel is assigned the variable name 
          plus an underscore followed by a number indicating the sub channel.
        When data is missing a header, the variable name is the channel number.
        """
    
        # Line 1: "Power: 1 2 3 4, Speed: 5 6 7 8"
        # Line 2: "Power: 4 3 2 1, Speed: 8 7 6 5"
        # Result:
        #   Variable index: {"Power:0, "Speed":1}
        #   Data: [[1,5],
        #          [2,6],
        #          [3,7],
        #          [4,8],
        #          [4,8],
        #          [3,7],
        #          [2,6],
        #          [1,5]] 
        #
        # Line 1: "Power: 1, 2, 3, 4 Speed: 5, 6, 7, 8"
        # Line 2: "Power: 4, 3, 2, 1 Speed: 8, 7, 6, 5"
        # Result:
        #   Variable index: {"Power_1":0, "Power_2":1, "Power_3":2, "Power_4":3, "Speed_1":4, "Speed_2":5, "Speed_3":6, "Speed_4":7}
        #   Data: [[1,2,3,4,5,6,7,8],
        #          [4,3,2,1,8,7,6,5]] 
        #
        # Line 1: "Power: 1 2 3 4, 5 6 7 8 Speed:  9 10 11 12, 13 14 15 16" 
        # Line 2: "Power: 4 3 2 1, 8 7 6 5 Speed: 12 11 10  9, 16 15 14 13"
        # Result:
        #   Variable index {"Power_1":0, "Power_2":1, "Speed_1":2, "Speed_2":3
        #   Data: [[1,5, 9,13],
        #          [2,6,10,14],
        #          [3,7,11,15],
        #          [4,8,12,16],
        #          [4,8,12,16],
        #          [3,7,11,15],
        #          [2,6,10,14],
        #          [1,5, 9,13]]
        #
        # Line 1: "Sound: 1 2 3 4"
        # Line 2: "Sound: 5 6 7 Blood Pressure: 121"
        # Line 3: "Sound: 8 9 10 11 12"
        # Line 4: "Sound: 13 14 Sound: 15 16, Oxygenation: 99"
        # Result:
        #   Variable index: {"Sound}":0, "Blood Pressure":1, "Oxygenation":2}
        #   Data: 
        #   [[  1.  nan  nan]
        #   [   2.  nan  nan]
        #   [   3.  nan  nan]
        #   [   4.  nan  nan]
        #   [   5. 121.  nan]
        #   [   6.  nan  nan]
        #   [   7.  nan  nan]
        #   [   8.  nan  nan]
        #   [   9.  nan  nan]
        #   [  10.  nan  nan]
        #   [  11.  nan  nan]
        #   [  12.  nan  nan]
        #   [  13.  nan  nan]
        #   [  14.  nan  nan]
        #   [  15.  nan  99.]  # Moved to new row before inserting second "Sound"
        #   [  16.  nan  nan]]

        if PROFILEME:
            tic = time.perf_counter()

        # Acceleration
        data_array = self.data_array
        push       = self.buffer.push
        thread_id  = self.thread_id
        seg_split = self.SEG_SPLIT
        ensure_capacity = self.ensure_capacity
        header_split = self.HEADER_SPLIT
        
        channel_names_dict = self.channel_names_dict
        name_cache = {}

        row = 0                                                                # time axis into data array
        num_columns = 0                                                        # Track maximum column index
        new_samples = 0                                                        # Track number of new samples
        rows, cols = data_array.shape                                          # Size of temporary array to organize data

        for line in lines:
            # Decode the line if it's a byte object
            if isinstance(line, (bytes, bytearray)):
                decoded_line = line.decode(encoding, errors='replace')
            else:
                decoded_line = line

            # Extract list of header and data segments (e.g., "Power: 1 2 3 4")
            named_segments = header_split(decoded_line)

            # handle a headerless prefix if nobody matched
            if not named_segments:
                named_segments = [("", decoded_line)]

            name_counts = {}
            prev_block_length = 0

            # For each header data segment pair:
            for name, data in named_segments:

                # track repeats of the same header in this line
                cnt = name_counts[name] = name_counts.get(name, 0) + 1

                # if repeated, we advance time by the previous block length
                if cnt > 1:
                    row         += prev_block_length
                    new_samples += prev_block_length
                    prev_block_length = 0

                # Split data by comma for multiple components
                segments = seg_split(data)

                # Convert segments to NumPy arrays
                for i, seg in enumerate(segments):
                    segment = seg.strip()                                      # Remove leading/trailing whitespace 

                    if segment == '':
                        segment_data = np.array([np.nan], dtype=np.float64)
                    else:
                        segment_data = np.fromstring(segment, dtype=np.float64, sep=' ')
                        if segment_data.size == 0:
                            # parser failed, treat as NaN
                            segment_data = np.array([np.nan], dtype=np.float64)
                            self.logSignal.emit(
                                logging.WARNING,
                                f"[{thread_id}]: Could not parse '{seg}' on line '{segment}'"
                            )

                    len_segment = segment_data.size
                    row_end = row + len_segment
                    prev_block_length = max(prev_block_length, len_segment)

                    # Pick column name: add _1, _2 if multiple parts
                    base_name = name.strip() or str(i)                         # fallback to channel-index string
                    col_name = (
                        f"{base_name}_{i+1}"
                        if len(segments) > 1
                        else base_name
                    )
                    
                    if col_name in name_cache:
                        # If we have seen this name before, we use the cached index
                        col = name_cache[col_name]
                    else:
                        # Assign column index
                        col = channel_names_dict.setdefault(col_name, len(channel_names_dict))
                        name_cache[col_name] = col

                    # check capacity
                    data_array, rows, cols = ensure_capacity(
                        data_array, rows, cols, row_end, col
                    )

                    # Store the values in `data_array`
                    data_array[row:row_end, col] = segment_data

            new_samples += prev_block_length
            row         += prev_block_length

        # Update buffer and variable index
        num_columns = max(channel_names_dict.values(), default=0) + 1

        # Push only the valid portion of `data_array`
        push(data_array[:new_samples, :num_columns])

        # Clear only the used portion of `data_array`
        data_array[:new_samples, :num_columns] = np.nan  
        self.data_array = data_array
        self.channel_names_dict = channel_names_dict

        if PROFILEME:
            toc = time.perf_counter()
            self.mtoc_process_lines_header = max ((toc - tic), self.mtoc_process_lines_header)

    # C accelerated implementation, is about 10 time faster than the python implementation
    @profile
    def fast_process_lines_header(self, lines, encoding="utf-8") -> None:
        """
        Fast processing of data with headers, via our pybind11 compiled parser.
        """
        if PROFILEME:
            tic = time.perf_counter()

        # 1) Decode any bytes → str
        # decoded = [
        #     l.decode(encoding, errors='replace') if isinstance(l, (bytes, bytearray)) else l
        #     for l in lines
        # ]

        # 2) Call the C++ parser: returns an np.ndarray
        data, shape, channel_names_dict  = header_parser.parse_lines(lines, channel_names=self.channel_names_dict, strict=False, gil_release=True)

        # 3) Push the array into the buffer
        self.buffer.push(data)

        # 4) Update channel_names
        self.channel_names_dict = channel_names_dict

        if PROFILEME:
            toc = time.perf_counter()
            # record the worst-case time
            self.mtoc_process_lines_header = max((toc - tic), self.mtoc_process_lines_header)

    # ==========================================================================
    # Response Functions to User Interface Signals
    # ==========================================================================
        
    @pyqtSlot(list)
    @profile
    def on_receivedLines(self, lines: list) -> None:
        """
        Parse a list of lines for data and add it to the circular buffer
        """

        if DEBUGCHART:
            tic = time.perf_counter()

        # Make a copy of the lines
        # lines_copy = [item[:] for item in lines]

        if self.textDataSeparator == 'simple':
            if hasFastParser:
                self.fast_process_lines_simple(lines, encoding = self.encoding)
            else:
                self.process_lines_simple(     lines, encoding = self.encoding)

        elif self.textDataSeparator == 'header':
            if hasFastParser:
                self.fast_process_lines_header(lines, encoding = self.encoding)
            else:
                self.process_lines_header(     lines, encoding = self.encoding)
        elif self.textDataSeparator == 'binary':
            self.logSignal.emit(
                logging.WARNING,
                f"[{self.instance_name[:15]:<15}]: Data separator {repr(self.textDataSeparator)} not compatible with line processing."
            )
        else:
            self.logSignal.emit(
                logging.ERROR,
                f"[{self.instance_name[:15]:<15}]: Data separator {repr(self.textDataSeparator)} not available."
            )

        if DEBUGCHART:
            toc = time.perf_counter()
            self.logSignal.emit(
                logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Data points received: parsing took {1000 * (toc - tic)} ms"
            )        

    @pyqtSlot(bytearray)
    @profile
    def on_receivedData(self, byte_array: bytearray) -> None:
        if self.warning:
            self.logSignal.emit(
                logging.WARNING,
                f"[{self.instance_name[:15]:<15}]: Data separator {repr(self.textDataSeparator)} with binary receiver is not supported yet."
            )
            self.warning = False
        
        # will need to implement binary data parsing here
        # will use codec helper
        # should be able to process a wide variety of data types
        
    @pyqtSlot()
    def on_comboBox_DataSeparator(self)-> None:
        ''' user wants to change the data separator '''
        label = self.ui.comboBoxDropDown_DataSeparator.currentText()
        separator  = PARSE_OPTIONS.get(label, PARSE_DEFAULT_NAME)

        self.textDataSeparator = separator

        # Log both the friendly label and the raw bytes for clarity
        hr = PARSE_OPTIONS_INV.get(separator, repr(separator))
        self.logSignal.emit(
            logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Data separator -> {hr} ({repr(separator)})"
        )

        self.ui.statusBar().showMessage("Data separator changed.", 2000)

    @pyqtSlot()
    def on_pushButton_ChartStartStop(self) -> None:
        """
        Start/Stop plotting

        Connect serial receiver new data received
        Start timer
        """
        if self.ui.pushButton_ChartStartStop.text() == "Start":

            # ─── We want to start plotting ─────────────

            # Enter Live Mode

            self.ui.pushButton_ChartPause.setText("Pause")
            self.ui.pushButton_ChartPause.setEnabled(True)
            self.throughputTimer.start()

            if not USE_FASTPLOTLIB:
                # PyqtGraph ─────────────────────────────────

                # Make sure the charts are initialized before we render them
                if not self.chartPGInitialized:
                    self.chartPGInitialized = self.initChartPG()

                # Clear existing data traces if any
                if not self.ChartTimer.isActive():
                    for data_trace in self.data_traces:
                        self.chartWidgetPG.removeItem(data_trace) 
                    self.data_traces.clear()
                    self.pg_clearLegend()
                    self.chartWidgetPG.clear()

                # Disable mouse pan/zoom mode
                # Disable auto ranging
                if self.viewBox:
                    self.viewBox.setMouseEnabled(x=False, y=False)
                    self.viewBox.disableAutoRange(pg.ViewBox.XAxis)            # disable autorange, we will set view in updatePlot
                    self.viewBox.disableAutoRange(pg.ViewBox.YAxis)            # disable autorange, we will set view in updatePlot

                    disconnect(self.viewBox.sigRangeChanged, self.on_pg_viewBox_changed)

                    self.viewBox.setLimits(
                        xMin      = None, 
                        xMax      = None,
                        yMin      = None,
                        yMax      = None,
                        minXRange = None,
                        maxXRange = None,
                        minYRange = None, 
                        maxYRange = None
                    )
                self.pg_last_ranges = None                                     # need to reset because after mouse zoom and pan we need to start fresh

            else:
                # FastPlotLib ─────────────────────────────────

                # Make sure the charts are initialized before we render them
                if not self.chartFPLInitialized:
                    self.chartFPLInitialized = self.initChartFPL()

                # Clear existing data traces if any
                if not self.ChartTimer.isActive():
                    # Remove only existing line graphics, preserve axes/docks styling
                    for data_trace in self.data_traces:
                        self.fpl_subplot.delete_graphic(data_trace)
                    self.data_traces.clear()
                    if self.legend is not None:
                        self.fpl_clearLegend()

                    # Disable mouse zoom/pan interaction
                    if hasattr(self.fpl_controller, "enabled"):     self.fpl_controller.enabled     = False
                    if hasattr(self.fpl_controller, "auto_update"): self.fpl_controller.auto_update = False
                    if hasattr(self.fpl_controller, "pause"):       self.fpl_controller.pause       = True

                    # Disconnect mouse and resize events from camera change handler
                    self.fpl_fig.renderer.remove_event_handler(self.on_fpl_user_interaction, "wheel", "pointer_move", "resize")

                self.fpl_last_ranges = None                                    # need to reset because after mouse zoom and pan we need to start fresh

            # Finish up start plotting
            self.plottingRunning.emit(True)                                    # We need the receiver running
            self.ChartTimer.start()
            self.logSignal.emit(
                logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Start plotting"
            )
            self.ui.statusBar().showMessage("Chart update started.", 2000)

        else:
            # ─── We want to stop plotting ─────────────

            # Enter Inspection Mode

            self.ui.pushButton_ChartPause.setText("N.A.")
            self.ui.pushButton_ChartPause.setEnabled(False)
            self.throughputTimer.stop()
            self.throughputUpdate.emit(0.0, 0.0, "chart")

            # Enable mouse pan/zoom mode
            if not USE_FASTPLOTLIB:
                # PyQtGraph chart ─────────────────────────────────

                if self.viewBox:
                    self.viewBox.setMouseEnabled(x=True, y=True)
                    self.viewBox.enableAutoRange(pg.ViewBox.YAxis)             # one shot auto range, when user zooms viewbox remains until new data is added to the plot
                    connect(self.viewBox.sigRangeChanged, self.on_pg_viewBox_changed, unique=True)

                    # Compute current data extents and min/max spans
                    x_span = max(1.0,   float(self.x_max - self.x_min))
                    y_span = max(SMALLEST, float(self.y_max - self.y_min))
                    min_frac = 0.01                                            # don’t allow zooming in beyond 1% of data span
                    max_frac = 4.00                                            # don’t allow zooming out so data < 25% of the view
                    minXRange = x_span * min_frac                              # **multiply**, not divide
                    maxXRange = x_span * max_frac                              # 4× data span → data is 25% of view
                    minYRange = y_span * min_frac
                    maxYRange = y_span * max_frac

                    pad_frac = 0.5                                             # 50% padding around data
                    x_pad = x_span * pad_frac
                    y_pad = y_span * pad_frac
                    self.viewBox.setLimits(
                        xMin      = self.x_min - x_pad,
                        xMax      = self.x_max + x_pad,
                        yMin      = self.y_min - y_pad,
                        yMax      = self.y_max + y_pad,
                        minXRange = minXRange,
                        maxXRange = maxXRange,
                        minYRange = minYRange,
                        maxYRange = maxYRange,
                    )

            else:
                # FastPlotLib ─────────────────────────────────

                if hasattr(self.fpl_controller, "enabled"):     self.fpl_controller.enabled     = True
                if hasattr(self.fpl_controller, "auto_update"): self.fpl_controller.auto_update = True
                if hasattr(self.fpl_controller, "pause"):       self.fpl_controller.pause       = False

                # self.fpl_subplot.axes.x_limits = (self.x_min - x_pad, self.x_max + x_pad)
                # self.fpl_subplot.axes.y_limits = (self.y_min - y_pad, self.y_max + y_pad)

                self.fpl_subplot.axes.x.start_value = self.x_min
                self.fpl_subplot.axes.y.start_value = self.y_min

                # set pan/zoom limits

                # Allow panning beyond data range of up to ±50% of data range
                x_span = max(1.0, float(self.x_max - self.x_min))
                y_span = max(SMALLEST, float(self.y_max - self.y_min))
                pad_frac = 0.5
                x_pad = x_span * pad_frac
                y_pad = y_span * pad_frac

                # Allow 100x to 0.25x zoom
                min_frac = 0.01                                                # don’t allow zooming in beyond 1% of data span
                max_frac = 4.00                                                # don’t allow zooming out so data < 25% of the view
                minXRange = x_span * min_frac                                  # 1% of data span → max zoom in
                maxXRange = x_span * max_frac                                  # 4× data span → data is 25% of view
                minYRange = y_span * min_frac
                maxYRange = y_span * max_frac            
                for name, val in [
                    ("x_min_range", minXRange), ("x_max_range", maxXRange),
                    ("y_min_range", minYRange), ("y_max_range", maxYRange),
                ]:
                    if hasattr(self.fpl_subplot.axes, name):
                        setattr(self.fpl_subplot.axes, name, val)

                # connect mouse and resize events to camera change handler
                self.fpl_fig.renderer.add_event_handler(self.on_fpl_user_interaction, "wheel", "pointer_move", "resize")

            # Finish up stop plotting
            self.ChartTimer.stop()
            self.plottingRunning.emit(False)                                   # we do not require the receiver
            self.logSignal.emit(
                logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Stopped plotting"
            )
            self.ui.statusBar().showMessage("Chart update stopped.", 2000)

    @pyqtSlot()
    def on_pushButton_ChartPause(self) -> None:
        """
        Pause plotting

        Incoming data is still received and stored in the buffer
        """
        if self.ui.pushButton_ChartPause.text() == "Pause":
            # ─── We want to pause plotting ─────────────

            self.ui.pushButton_ChartPause.setText("Resume")

            # We want to stop plotting and enable mouse pan/zoom mode
            self.ChartTimer.stop()
            self.throughputTimer.stop()
            self.throughputUpdate.emit(0.0, 0.0, "chart")

            
            # Enable mouse pan/zoom mode
            if not USE_FASTPLOTLIB:
                # PyQtGraph ─────────────────────────────────

                if self.viewBox:
                    self.viewBox.setMouseEnabled(x=True, y=True)
                    self.viewBox.enableAutoRange(pg.ViewBox.YAxis)             # one shot auto range, viewbox will not change until new data is added to the plot
                    connect(self.viewBox.sigRangeChanged, self.on_pg_viewBox_changed, unique=True)

                    # Compute current data extents and min/max spans
                    x_span = max(1.0,   float(self.x_max - self.x_min))
                    y_span = max(SMALLEST, float(self.y_max - self.y_min))
                    min_frac = 0.01                                            # don’t allow zooming in beyond 1% of data span
                    max_frac = 4.00                                            # don’t allow zooming out so data < 25% of the view
                    minXRange = x_span * min_frac                              # **multiply**, not divide
                    maxXRange = x_span * max_frac                              # 4× data span → data is 25% of view
                    minYRange = y_span * min_frac
                    maxYRange = y_span * max_frac

                    pad_frac = 0.5                                             # 50% padding around data
                    x_pad = x_span * pad_frac
                    y_pad = y_span * pad_frac
                    self.viewBox.setLimits(
                        xMin      = self.x_min - x_pad,
                        xMax      = self.x_max + x_pad,
                        yMin      = self.y_min - y_pad,
                        yMax      = self.y_max + y_pad,
                        minXRange = minXRange,
                        maxXRange = maxXRange,
                        minYRange = minYRange,
                        maxYRange = maxYRange,
                    )

            else:
                # FastPlotLib ─────────────────────────────────

                if hasattr(self.fpl_controller, "enabled"):     self.fpl_controller.enabled     = True
                if hasattr(self.fpl_controller, "auto_update"): self.fpl_controller.auto_update = True
                if hasattr(self.fpl_controller, "pause"):       self.fpl_controller.pause       = False

                # self.fpl_subplot.axes.x_limits = (self.x_min - x_pad, self.x_max + x_pad)
                # self.fpl_subplot.axes.y_limits = (self.y_min - y_pad, self.y_max + y_pad)

                self.fpl_subplot.axes.x.start_value = self.x_min
                self.fpl_subplot.axes.y.start_value = self.y_min

                # Set pan and zoom limits

                # Allow panning beyond data range of up to ±50% of data range
                x_span = max(1.0, float(self.x_max - self.x_min))
                y_span = max(SMALLEST, float(self.y_max - self.y_min))
                pad_frac = 0.5
                x_pad = x_span * pad_frac
                y_pad = y_span * pad_frac

                # Allow 100x to 0.25x zoom
                min_frac = 0.01                                                # don’t allow zooming in beyond 1% of data span
                max_frac = 4.00                                                # don’t allow zooming out so data < 25% of the view
                minXRange = x_span * min_frac                                  # 1% of data span → max zoom in
                maxXRange = x_span * max_frac                                  # 4× data span → data is 25% of view
                minYRange = y_span * min_frac
                maxYRange = y_span * max_frac            
                for name, val in [
                    ("x_min_range", minXRange), ("x_max_range", maxXRange),
                    ("y_min_range", minYRange), ("y_max_range", maxYRange),
                ]:
                    if hasattr(self.fpl_subplot.axes, name):
                        setattr(self.fpl_subplot.axes, name, val)

                # connect mouse and resize events to camera change handler
                self.fpl_fig.renderer.add_event_handler(self.on_fpl_user_interaction, "wheel", "pointer_move", "resize")

                if DEBUGCHART:
                    # To help figure out issues
                    for i, data_trace in enumerate(self.data_traces):
                        seg = data_trace.data.value
                        write_idx = int(self.data_traces_writeidx[i])
                        window = seg[:write_idx, :2]
                        finite_mask = np.isfinite(window)
                        finite_count = int(np.count_nonzero(finite_mask))
                        total_count = window.size
                        has_nan = finite_count != total_count
                        x_min = float(np.nanmin(window[:, 0])) if write_idx else float("nan")
                        x_max = float(np.nanmax(window[:, 0])) if write_idx else float("nan")
                        y_min = float(np.nanmin(window[:, 1])) if write_idx else float("nan")
                        y_max = float(np.nanmax(window[:, 1])) if write_idx else float("nan")

                        self.logSignal.emit(
                            logging.INFO,
                            (f"[{self.instance_name[:15]:<15}]: Trace {i} "
                             f"write_idx={write_idx} finite={finite_count}/{total_count} "
                             f"has_nan={has_nan} "
                             f"x=[{x_min}, {x_max}] y=[{y_min}, {y_max}]")
                        )

            self.logSignal.emit(
                logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Plotting paused"
            )
            self.ui.statusBar().showMessage("Chart update paused.", 2000)


        else:
            # ─── We want to resume plotting ─────────────
            self.ui.pushButton_ChartPause.setText("Pause")

            # Clear existing data traces if any
            if not USE_FASTPLOTLIB:
                # PyQtGraph ─────────────────────────────────

                # Disable mouse pan/zoom mode
                # Disable auto ranging
                if self.viewBox:
                    self.viewBox.setMouseEnabled(x=False, y=False)
                    self.viewBox.disableAutoRange(pg.ViewBox.XAxis)            # disable autorange, we will set view in updatePlot
                    self.viewBox.disableAutoRange(pg.ViewBox.YAxis)            # disable autorange, we will set view in updatePlot
                    disconnect(self.viewBox.sigRangeChanged, self.on_pg_viewBox_changed)
                    self.viewBox.setLimits(
                        xMin      = None, 
                        xMax      = None,
                        yMin      = None,
                        yMax      = None,
                        minXRange = None,
                        maxXRange = None,
                        minYRange = None, 
                        maxYRange = None
                    )

                self.pg_last_ranges = None                                     # need to reset previous view because after mouse zoom and pan we need to start fresh

            else:
                # FastPlotLib ─────────────────────────────────

                # Disable mouse zoom/pan interaction
                if hasattr(self.fpl_controller, "enabled"):     self.fpl_controller.enabled     = False
                if hasattr(self.fpl_controller, "auto_update"): self.fpl_controller.auto_update = False
                if hasattr(self.fpl_controller, "pause"):       self.fpl_controller.pause       = True

                # Disconnect mouse and resize events from camera change handler
                self.fpl_fig.renderer.remove_event_handler(self.on_fpl_user_interaction, "wheel", "pointer_move", "resize")

                self.fpl_last_ranges = None                                    # need to reset previous view because after mouse zoom and pan we need to start fresh

            # Restart timer
            self.ChartTimer.start()
            self.throughputTimer.start()

            self.logSignal.emit(
                logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Plotting resumed"
            )
            self.ui.statusBar().showMessage("Chart update resumed.", 2000)

    @pyqtSlot()
    def on_pushButton_ChartClear(self) -> None:
        """
        Clear Plot

        Clear data buffer then update plot
        """
        # clear buffer
        self.buffer.clear()
        _, newest_sample = self.buffer.counter
        self.previous_newest_sample = newest_sample

        self.sample_number = 0
        self.channel_names = []
        self.channel_names_dict = {}
        self.prev_channel_names_dict = {}

        if not USE_FASTPLOTLIB:
            # PyQtGraph ─────────────────────────────────

            for data_trace in self.data_traces:
                self.chartWidgetPG.removeItem(data_trace)
            self.data_traces.clear()
            self.pg_clearLegend()
            if self.legend is None:
                self.legend = self.pg_createLegend()
            self.data_traces_writeidx = []

        else:
            # FastPlotLib ─────────────────────────────────

            for data_trace in self.data_traces:
                # self.fpl_canvas.removeItem(data_trace)
                self.fpl_subplot.delete_graphic(data_trace)
            self.data_traces.clear()
            self.fpl_clearLegend()
            self.data_traces_writeidx = []

        self.logSignal.emit(
            logging.INFO,
            f"[{self.instance_name[:15]:<15}]: Cleared plotted data."
        )
        self.ui.statusBar().showMessage("Chart cleared.", 2000)

    @pyqtSlot()
    def on_pushButton_ChartSave(self) -> None:
        """
        Save data into Text File
        """
        # Suggest a default location/name
        stdFileName = (
            QStandardPaths.writableLocation(DOCUMENTS)
            + "/Data.csv"
        )

        file_path = select_file(
            stdFileName = stdFileName,
            do_text= "Save",
            cancel_text="Cancel",
            filter="CSV (*.csv);;Text (*.txt)",
            suffix="csv",
            parent=self
        )

        # If the dialog was cancelled
        if not file_path:
            self.logSignal.emit(
                logging.WARNING,
                f"[{self.instance_name[:15]:<15}]: No file selected for saving."
            )
            return

        if file_path.exists():                                                 # Check if file already exists
            mode = confirm_overwrite_append(offer_append=False, parent=self)
            if mode == "c":
                return

        # Choose delimiter from extension
        ext = file_path.suffix.lower()
        delimiter = "," if ext == ".csv" else "\t"

        # Optional: create parent folder if user typed a new path
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass                                                               # Non-fatal; OS will error on write if invalid

        # Prepare data (adjust this to your actual data source)
        data = getattr(self.buffer, "data", None)
        if data is None:
            self.logSignal.emit(
                logging.ERROR,
                f"[{self.instance_name[:15]:<15}]: Save failed: no data."
            )
            return

        # Optional header: write channel names if you have them
        header = ""
        names = getattr(self, "channel_names", None)
        if isinstance(names, (list, tuple)) and len(names) == data.shape[1]:
            header = ",".join(map(str, names)) if delimiter == "," else "\t".join(map(str, names))

        # Write file
        try:
            np.savetxt(str(file_path), data, delimiter=delimiter, header=header, comments="")
            self.ui.statusBar().showMessage(f"Chart data saved: {file_path.name}", 2000)
            self.logSignal.emit(
                logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Saved plotted data to {file_path.name}."
            )
        except Exception as e:
            self.logSignal.emit(
                logging.ERROR,
                f"[{self.instance_name[:15]:<15}]: Save failed: {e}"
            )

    @pyqtSlot()
    def on_pushButton_ChartSaveFigure(self) -> None:
        """
        Save current chart to disk.
        - Fastplotlib → raster (.png, .jpg, .tiff)
        - PyQtGraph   → vector (.svg) or raster
        """
        doc_dir = QStandardPaths.writableLocation(DOCUMENTS)
        if not USE_FASTPLOTLIB:
            # PyQtGraph: offer vector (.svg) or raster
            default_ext    = ".svg"
            file_filter    = "SVG Files (*.svg);;PNG Files (*.png)"
        else:
            # FastPlotLib: only raster formats
            default_ext    = ".png"
            file_filter    = "PNG Files (*.png);;JPEG Files (*.jpg);;TIFF Files (*.tiff)"
        stdFileName   = f"{doc_dir}/chart{default_ext}"

        file_path = select_file(
            stdFileName = stdFileName,
            do_text= "Save",
            cancel_text="Cancel",
            filter=file_filter,
            suffix=default_ext.lstrip("."),
            parent=self
        )

        if not file_path:
            return

        if file_path.exists():                                                 # Check if file already exists
            mode = confirm_overwrite_append(offer_append=False, parent=self)
            if mode == "c":
                return
        
        was_running = self.ChartTimer.isActive()
        if was_running:
            self.ChartTimer.stop()                                             # Can not update plot while its saved

        try:
            if not USE_FASTPLOTLIB:
                # PyQtGraph: choose vector vs raster exporter
                ext = file_path.suffix.lower()
                if ext == ".svg":
                    exporter = pgxr.SVGExporter(self.chartWidgetPG.getPlotItem())
                else:
                    exporter = pgxr.ImageExporter(self.chartWidgetPG.getPlotItem())
                exporter.export(str(file_path))
            else:
                # Use FastPlotLib exporter, needs imageio
                #  only support ".png", ".jpg", ".tiff"
                self.fpl_fig.export(str(file_path))
            
            self.logSignal.emit(
                logging.INFO,
                f"[{self.instance_name[:15]:<15}]: Chart saved as {file_path}."
            )
            self.ui.statusBar().showMessage(f"Chart saved as {file_path}.", 2000)

        except Exception as e:
            self.logSignal.emit(
                logging.ERROR,
                f"[{self.instance_name[:15]:<15}]: Error saving chart."
            )
            self.ui.statusBar().showMessage(f"Error saving chart: {str(e)}", 3000)

        finally:
            # Restart timer if it was previously running
            if was_running:
                self.ChartTimer.start()

    @pyqtSlot(int)
    def on_ZoomSliderChanged(self, value) -> None:
        """
        Serial Plotter Horizontal Slider Moving
        """
        # Throttle rapid zoom changes
        if not self.zoomGate:
            return
        self.zoomGate = False                                                  # lock
        self.zoomGate_timer.start(self.zoomGate_interval_ms)                   # schedule release
        self.on_ZoomSlider(value)

    @pyqtSlot()
    def on_ZoomSliderReleased(self) -> None:
        """
        Serial Plotter Horizontal Slider Release
        """
        # update right away
        self.on_ZoomSlider(self.horizontalSlider.value())

    def on_ZoomSlider(self, value) -> None:
        """
        Serial Plotter Horizontal Slider Handling
        This sets the maximum number of points back in history shown on the plot
        """

        # Set limits and updated maxPoints and tick marks
        new_value = int(clip_value(value, 16, MAX_ROWS))
        self.maxPoints = new_value
        
        self.x_base = np.arange(-self.maxPoints+1, 1, dtype=np.float64)
        self.x_view = np.empty_like(self.x_base)                               # x values adjusted for current view (sample numbers)

        # Update line edit with value of the slider position
        self.lineEdit.blockSignals(True)
        self.lineEdit.setText(str(new_value))
        self.lineEdit.blockSignals(False)

        # Update horizontal slider with adjusted value
        self.horizontalSlider.blockSignals(True)
        self.horizontalSlider.setValue(new_value)
        self.horizontalSlider.blockSignals(False)

        if not USE_FASTPLOTLIB:
            # PyQtGraph

            self.updatePlot()
            self.pg_updateAxesTicks("x", self.x_min, self.x_max, n_major=MAJOR_TICKS, n_minor=MINOR_TICKS)
        else:
            # FastPlotLib
            self.fpl_resizeTraceCapacity(int(new_value))
            self.updatePlot()
            self.fpl_subplot.canvas.request_draw()

        if DEBUGCHART:
            self.logSignal.emit(
                logging.DEBUG,
                f"[{self.instance_name[:15]:<15}]: Horizontal zoom set to {value}."
            )

    @pyqtSlot()
    def on_ZoomLineEditChanged(self) -> None:
        """
        Serial Plotter Horizontal Line Edit Handling
        Updates the slider and the history range when text is entered manually and user presses Enter or Return
        """

        try:
            value = int(self.lineEdit.text().strip())                          # Strip spaces to prevent errors
        except ValueError:
            self.logSignal.emit(logging.WARNING, f"[{self.instance_name[:15]:<15}]: Invalid input in Zoom Lines box.")
            return                                                             # Exit without applying changes if input is invalid

        # Set limits and updated maxPoints and tick marks
        new_value = int(clip_value(value, 16, MAX_ROWS))
        self.maxPoints = new_value
        
        self.x_base = np.arange(-self.maxPoints+1, 1, dtype=np.float64)
        self.x_view = np.empty_like(self.x_base)                               # x values adjusted for current view (sample numbers)

        # Update line edit with value of the slider position
        self.lineEdit.blockSignals(True)
        self.lineEdit.setText(str(new_value))
        self.lineEdit.blockSignals(False)

        # Update horizontal slider with adjusted value
        self.horizontalSlider.blockSignals(True)
        self.horizontalSlider.setValue(new_value)
        self.horizontalSlider.blockSignals(False)

        if not USE_FASTPLOTLIB:
            # PyQtGraph
            self.updatePlot()
            self.pg_updateAxesTicks("x", self.x_min, self.x_max, n_major=MAJOR_TICKS, n_minor=MINOR_TICKS)
        else:
            # FastPlotLib
            self.fpl_resizeTraceCapacity(int(new_value))
            self.updatePlot()
            self.fpl_subplot.canvas.request_draw()

        if DEBUGCHART:
            self.logSignal.emit(
                logging.DEBUG,
                f"[{self.instance_name[:15]:<15}]: Horizontal zoom set to {value}."
            )

############################################################################################################################################
# Testing
############################################################################################################################################

if __name__ == "__main__":
    # not implemented
    pass
