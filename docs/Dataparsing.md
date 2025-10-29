## Data Parsing
When receiving data, it will need to be in a consistent format.
The basic unit is a line of text, terminated with an EOL character.
Simple parsing with no variable names as well as parsing with names is supported.
In future binary data transmission will be supported.

In general for text parsing:

- Values separated with **spaces** are consider belonging to the **same channel**.
- Values separated by **comma** are considered belonging to **different channels**.
- **Newline** advances data counter for all channels.
- **Headers** are proceeded with a **colon**.

A channel is a data trace on a chart.

Code was designed to handle empty headers, multiple spaces or commas. If you attempt using spaces and numbers in the header you should consider replacing the space with an underscore.

### Simple Parsing No Header
With a new line, the values will be added to the previous line's channels.
If number of channels increases, the previous channels will be incorporated.

```
Line 1: "value1, value2"
``` 
Results in two channels

```
Line 1: "value1 value2"
```
Results in one channel with two values

```
Line 1: "value1 value2, value3"
```
Results in two channels whereas second channel has one value and second value is NaN.

```
Line 1: "value1, value2"
Line 2: "value1, value2, value3"
```
Results in 3 channels with 2 values but 3rd channel is prepended with NaN.

During plotting, NaN values are not included, allowing to plot data from channels with many data points simultaneously with channels with fewer data points on the same graph.

### Parsing with Header
```
Line 1: "HeaderA: value1 value2 HeaderB: value1"
```
Results in channel named "HeaderA" with two values and channel named HeaderB with two values whereas second vale is NaN.

```
Line 1: "HeaderA: value1, value 2 HeaderB: value1"
```
Results in channel named "HeaderA_1" with value1 and channel named HeaderA_2 with value2 and channel named "HeaderB" with value1.
