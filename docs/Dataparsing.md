## Data Parsing
The data source will need to format data. Simple parsing with no variable names and parsing with names is supported.

Values separated with spaces are consider belonging to same channel. 

Values separated by comma are considered belonging to new channel.

### Simple Parsing No Header
With a new line, the values will be added to the previous line's channels.
If more channels arrive, the previous channels will be incorporated.

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
Results in 3 channels with 2 values but 3rd channel is internally prepended with NaN.

During plotting, NaN values are not included, allowing to plot data from channels with many data points simultaneously with channels with fewer data points on the same graph.

### Parsing with Header
```
Line 1: "HeaderA: value1 value 2 HeaderB: value1"
```
Results in Channel named "HeaderA" with two values and Channel named HeaderB with two values whereas second one is internally set to NaN.

```
Line 1: "HeaderA: value1, value 2 HeaderB: value1"
```
Results in Channel named "HeaderA_1" with value1 and Channel named HeaderA_2 with value2 and Channel named "HeaderB" with value1.

