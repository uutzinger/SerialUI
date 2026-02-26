## Data Parsing
This document defines the expected behavior for SerialUI text parsing.

The C accelerate implementation `helpers/line_parsers/simple_parser.cpp` and `helpers/line_parsers/header_parser.cpp` as well as the python version `helpers/Qgraph_helper.py` must match these specifications.

Binary parsing is not covered here yet.

### Examples No Header

```text
Line: "1 2 3, 4"
```
Produces 2 channels and 3 rows:

- ch1 = [1, 2, 3]
- ch2 = [4, NaN, NaN]

```text
Line 1: "1, 2"
Line 2: "1, 2, 3"
```
Produces 3 channels, where:
- ch1 = [1, 1]
- ch2 = [2, 2]
- ch3 = [NaN, 3]
  
### Examples With Header

```text
Line: "HeaderA: 1 2 HeaderB: 10"
```

Rows = 2

- HeaderA = [1, 2]
- HeaderB = [10, NaN]

```text
Line: "HeaderA: 1, 2 HeaderB: 10"
```

Creates:

- HeaderA_1 = [1]
- HeaderA_2 = [2]
- HeaderB = [10]

```text
Line: "1 2, HeaderA: 3 4"
```

Creates:

- __unnamed_1 = [1, 2]
- HeaderA = [3, 4]

Variable names can include `[A-Za-z0-9_/]` and include spaces such as `Blood Pressure:`
 
## Core Concepts
- A **line** is the atomic input unit.
- A **channel** is one plotted data trace (one output column).
- **Comma** (`,`) splits channels (sub-channels in header mode).
- **Whitespace** splits values within a channel (output rows).
- Missing values are filled with `NaN`.

## Numeric Token Rules
- Tokens are read per whitespace-separated item.
- Valid numeric token -> parsed float.
- Invalid token -> `NaN` (non-strict mode).
- Numeric prefix + trailing junk is accepted as numeric prefix.
  Example: `1abc` parses as `1`.
- Empty segment (for example between `,,`) produces a `NaN` placeholder row.

## Simple Mode (No Headers)
Simple mode treats each line as comma-separated channels.

### Line-to-row behavior
- For one line, each channel may contain a different number of values.
- Rows added by that line = maximum value count among channels in that line.
- Channels with fewer values get `NaN` in remaining rows.

### Across lines
- Each new line appends rows after the previous line.
- If later lines introduce more channels, new columns are added.
- Existing channel names are preserved when provided; missing names are appended numerically (`"1"`, `"2"`, ...).

## Header Mode
Header mode parses `<header>: <data>` segments within each line.

### Header detection
- Colon (`:`) separates header from data.
- Unquoted headers support multi-word names (for example `Blood Pressure:`).
- For unquoted headers, each header word must start with `[A-Za-z_]`.
- For unquoted headers, the remaining characters in each word may be `[A-Za-z0-9_/]`.
  Examples: `frame/s`, `m/s`, `rpm_1`.
- Delimiters are still reserved and not part of unquoted names: `:`, `,`, and whitespace.
- Quoted headers are also supported before `:` using matching quotes.

### Headerless data
- Headerless prefix before first header is preserved.
- Headerless channels use base name `__unnamed`.

### Sub-channels
- Inside each header segment, commas split sub-channels.
- A header may therefore produce 1..N columns.
- If a header appears multiple times in the same line, sub-channels are appended in appearance order.
  Example: `A:1 2 A:3 4` -> `A_1=[1,2]`, `A_2=[3,4]` (no overwrite).

### Column naming rules
- If a header has total `k` sub-channels in a line:
  - `k == 1` -> prefer `H`
  - `k > 1` -> canonical names `H_1..H_k`
- If a header was previously single-column and later becomes multi-column, it is canonicalized to suffixed form (`H -> H_1`, add `H_2..`).
- Headerless channels are named `__unnamed_1`, `__unnamed_2`, ...

### Line-to-row behavior
- For one input line, rows added = maximum value count across all sub-channels from all header segments in that line.
- All segments in the line align to the same row block.
- Missing entries are `NaN`.

## Strict vs Non-Strict
- Default mode is non-strict: unparseable tokens become `NaN`.
- Strict mode raises parse errors on unparseable tokens.
- SerialUI runtime currently uses non-strict mode for live parsing.

## Current Scope and Future Additions
This spec now covers:

- simple/header parity behavior
- naming/canonicalization rules
- repeated-header behavior
- malformed token behavior

Future updates should add:

- binary parser specification
- additional corner cases as they are discovered
- explicit compatibility expectations for legacy logs/devices
