# Task List

## Auto select Serial Port
When program boots up and serial port finds a suitable port it should select the first non empty port automatically and not the empty item.
[Status: done]
[Implemented: when the serial port list is refreshed and no port is currently connected, the first detected real port is selected instead of the trailing None entry.]

## BLE Connection
If BLE serial device is already connected to system a scanning attempt will not find it.
[Status: done]
[Implemented: on shutdown, SerialUI now requests BLE disconnect before the BLE worker thread and event loop are torn down, so the device is cleanly disconnected when the program closes.]


## Zooming and Panning while Life Update
When charting is paused or stopped one can pan and zoom but when charting is running autoscaling is enabled and one can not zoom into the data while its updating. pyqtgraph has option to deselect plot items in the legend menu. Is it possible to autoscale only to the the items selected in the legend?
[Status: done for pyqtgraph, postponed for fastplotlib]
[Implemented: chart updates keep running while pyqtgraph mouse pan/zoom stays enabled. Manual pan/zoom suspends live x/y follow on the changed axis, and pyqtgraph View All or auto-range can re-enable live follow.]


## Label Parsing
With the data shown below received over BLEserial and displayed in terminal and with C accelerated parser enabled I get duplicate legend lables such as CH0_AVG_1 and and CH0_AVG_2 for all of the items except for "corr". The duplicates do not contain data on the chart.

CH0_AVG:836.9,CH0_RMS:120.36,CH1_AVG:827.1,CH1_RMS:0.00,lag:-15,phase_60Hz:-26.0,corr:0.06
CH0_AVG:837.4,CH0_RMS:120.35,CH1_AVG:827.1,CH1_RMS:0.00,lag:-8,phase_60Hz:-27.9,corr:0.07
CH0_AVG:837.9,CH0_RMS:120.29,CH1_AVG:827.1,CH1_RMS:0.00,lag:9,phase_60Hz:-20.1,corr:0.06

[Status: done]
[Implemented: reproduced the duplicate labels in both the Python and C++ header parsers. The root cause was a trailing comma before the next header being interpreted as an extra empty sub-channel, so labels such as CH0_AVG became CH0_AVG_1 and CH0_AVG_2. Both parsers were updated to ignore that separator-only trailing segment, and the C++ parser module was rebuilt in place.]

## Label Parsing

We have troubles parsing this:

ECG Cal [mV]: 0.000
ECG Cal [mV]: -0.000
ECG Cal [mV]: -0.000
ECG Cal [mV]: -0.000
ECG Cal [mV]: -0.001
ECG Cal [mV]: -0.001
ECG Cal [mV]: -0.001
ECG Cal [mV]: -0.001
ECG Cal [mV]: -0.001
ECG Cal [mV]: -0.001
ECG Cal [mV]: -0.002
ECG Cal [mV]: -0.002
ECG Cal [mV]: -0.001
ECG Cal [mV]: -0.001
ECG Cal [mV]: -0.001
ECG Cal [mV]: -0.002
ECG Cal [mV]: -0.002
ECG Cal [mV]: -0.002
ECG Cal [mV]: -0.002
ECG Cal [mV]: -0.002
ECG Cal [mV]: -0.003
ECG Cal [mV]: -0.002
ECG Cal [mV]: -0.003
ECG Cal [mV]: 0.001
ECG Cal [mV]: -0.001
ECG Cal [mV]: -0.009
ECG Cal [mV]: 0.017
ECG Cal [mV]: -0.024
ECG Cal [mV]: -0.002
ECG Cal [mV]: 0.303
ECG Cal [mV]: 0.527
ECG Cal [mV]: 0.483
ECG Cal [mV]: 0.463
ECG Cal [mV]: 0.478
ECG Cal [mV]: 0.459
ECG Cal [mV]: 0.455
ECG Cal [mV]: 0.450
ECG Cal [mV]: 0.443
ECG Cal [mV]: 0.438

[Status: done]
[Implemented: bracketed unit suffixes such as [mV] are now accepted in unquoted header names by both the Python and C++ header parsers. The exact ECG Cal [mV] sample now parses into a single ECG Cal [mV] channel instead of falling back to __unnamed with text-token NaNs. Quoted header trimming was also corrected while updating the same header recognition path.]

## Color Theme
When the operating system is using a dark theme, parts of the SerialUI interface lose contrast because the application forces light widget backgrounds while Qt continues to use theme-aware text and control colors. The chart subsystem also uses a fixed light color system that does not adapt to the active application palette.

[Status: done]
[Implemented:
- Main UI palette inheritance
- Removed fixed widget background styling in `SerialUI.py` for the monitor text view, log view, and tabs.
- Standard Qt widgets now inherit the active Qt and operating system palette instead of forcing light colors.

- `config.py` revision
- Removed hard-coded widget background color constants from `config.py`.
- Retained only chart fallback colors for cases where no Qt palette is available.

- Chart theme system
- Added a palette-derived chart theme helper that builds semantic colors for chart background, axis text, axis lines, grid colors, legend background, and legend text.
- Applied the palette-derived theme to both pyqtgraph and fastplotlib chart initialization and refresh paths.
- Left trace colors separate from widget colors so the existing series palette remains unchanged for now.

- Runtime theme refresh
- Added runtime theme refresh so SerialUI reapplies chart colors when the Qt application palette changes while the app is running.

- Helper functions added to `helpers/General_helper.py`
- `qcolor_to_rgba`
- `with_alpha`
- `blend_colors`
- `build_chart_theme`

## Plotting of isolated values
When occasional values are received interspersed with frequent values from another measurement, the parser and ring buffer correctly keep all channels on the same sample timeline and leave missing entries as `NaN`. This preserves alignment between slow and fast measurements, but sparse channels then appear as isolated finite values surrounded by `NaN`. In pyqtgraph, those `NaN` values break line segments. In fastplotlib, the current compaction of finite values risks connecting points across time gaps. We need a plotting approach that displays sparse event-like values together with dense continuous signals while keeping plotting fast and efficient.

[Status: implemented for pyqtgraph and fastplotlib automatic mode]
[Plan:
- Keep the current parser and circular buffer structure unchanged so all channels remain aligned on the same sample-number axis and sparse channels continue to be represented by `NaN` gaps.
- Add a plotting-level render mode concept for traces, with at least `line`, `scatter`, and `hybrid` behavior.
- Use `auto` as the default engagement mode and do not add new main-window controls in the first implementation.
- In `auto`, classify each visible trace from the current data pattern and choose between line-only, scatter-only, or hybrid behavior.
- Keep the first rollout UI-free. If manual override is needed later, add it as a context-menu action on the plot or legend rather than consuming permanent screen space.
- In pyqtgraph, keep the existing line trace with `connect='finite'` for continuous data and add a scatter overlay for isolated points detected from the visible `NaN` pattern. Done.
- Detect isolated values efficiently per channel using finite-neighbor checks, for example a point that is finite while both the previous and next samples are non-finite.
- Keep pyqtgraph legend and visibility behavior tied to the main line item while the scatter overlay remains an internal helper trace. Done.
- In fastplotlib, stop treating all finite values as a single compacted line when that would bridge time gaps. Preserve segment breaks by inserting separator rows for discontinuities and render isolated samples with a native scatter overlay. Done.
- Add a simple heuristic or per-channel mode selection so dense channels remain line plots while sparse channels can automatically switch to scatter or hybrid display.
- In fastplotlib, rebuild the visible trace buffer from the current window so line continuity follows the original sample timeline instead of the old compacted append-only representation. Done.
- Keep autoscaling and legend behavior consistent across both backends, including visibility toggles and efficient min/max computation for sparse channels.
- Implement the pyqtgraph version first because it already preserves `NaN` segment breaks cleanly, then bring fastplotlib to feature parity with the same visual behavior.]
