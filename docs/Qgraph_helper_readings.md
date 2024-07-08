# Helpful Readings:

## PyQtGraph
### [Embedding PyQtGraph Custom Widgets in a Qt App](https://www.pythonguis.com/tutorials/embed-pyqtgraph-custom-widgets-qt-app/)
This tutorial provides a step-by-step guide on how to embed custom PyQtGraph widgets in a Qt application using Qt Designer. It covers the process of creating a placeholder widget in Qt Designer, promoting it to a PyQtGraph widget, and loading the UI file in a Python script to display the custom plot.

### [PyQtGraph Documentation](https://www.pyqtgraph.org/)
The official PyQtGraph website provides comprehensive documentation, including installation instructions, examples, and API reference. It is the main resource for understanding the technical capabilities and usage of PyQtGraph for creating interactive plots in Python apps.

### [Plotting with PyQtGraph](https://www.pythonguis.com/tutorials/plotting-pyqtgraph/)
This tutorial focuses on creating interactive plots using PyQtGraph. It demonstrates how to set up a plotting widget, customize plot appearance (e.g., line color, width, style), add markers, titles, and axis labels, and manage plot legends and background grids.

### [PyQtGraph Example - Scrolling Plots](https://github.com/pyqtgraph/pyqtgraph/blob/master/pyqtgraph/examples/scrollingPlots.py)
An example script from the PyQtGraph GitHub repository that shows how to create scrolling plots, useful for understanding how to handle real-time data updates and visualize them dynamically.

### [PyQtGraph Scrolling Plots - StackOverflow](https://stackoverflow.com/questions/65332619/pyqtgraph-scrolling-plots-plot-in-chunks-show-only-latest-10s-samples-in-curre)
StackOverflow discussion that provides good reference for implementing scrolling plots with PyQtGraph. It includes code snippets and explanations for plotting data in chunks and displaying only the most recent samples.

## Example Applications
### [EKG Monitor](https://github.com/pbmanis/EKGMonitor)
This repository provides a Python-based EKG monitor using PyQtGraph. It can read input from a soundcard or an Arduino with the Olimex EKG/EMG shield. The monitor filters and amplifies the signal, displaying heart rate and variability. It includes real-time data acquisition, filtering, and saving of recorded data for further analysis.