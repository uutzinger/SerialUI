# line_parsers

This folder contains the `line_parsers` package used by SerialUI.

It provides C-accelerated text parsers built with `pybind11`:
- `line_parsers.simple_parser`
- `line_parsers.header_parser`

Build in-place from this folder:

```bash
python3 setup.py build_ext --inplace -v
```
