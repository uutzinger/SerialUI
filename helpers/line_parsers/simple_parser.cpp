// --------------------------------------------------------------------------------------------------------
// simple_parser.cpp
//
// High-performance simple parser for lines with numbers
// - numbers are parsed into a numpy array
// - in the array, columns indicate a channel, rows are sequential data points
// - in the input data stream, space-separated numbers belong to the same channel
// - in the input data stream a comma separates channels
// - in the input data stream, a new line restarts the row counter for all channels
// - empty tokens are represented as NaN
//
// This parser processes 400_000 lines per second
//  (when random generated lines contain 1..20 values per channel and 1..5 channels)
// The parser releases the GIL during processing but uses a single thread
//
// Urs Utzinger, May 2025
// --------------------------------------------------------------------------------------------------------

#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h> 
#include <vector>
#include <string>
#include <charconv>
#include <cctype>
#include <limits>
#include <algorithm>
#include <string_view>
#include <cstring>   // memchr

// Add this block:
#if defined(_MSC_VER)
    #define FORCE_INLINE __forceinline
#elif defined(__GNUC__) || defined(__clang__)
    #define FORCE_INLINE inline __attribute__((always_inline))
#else
    #define FORCE_INLINE inline
#endif

namespace py = pybind11;

static constexpr double NAN_VAL = std::numeric_limits<double>::quiet_NaN();

//------------------------------------------------------------------------
// Split Channels: 
//   split on comma, preserving empty tokens
//------------------------------------------------------------------------
static FORCE_INLINE
void split_channels(std::string_view sv,
                    std::vector<std::string_view> &out) {
    out.clear();
    const char *begin = sv.data();
    const char *end   = begin + sv.size();
    const char *p     = begin;

    while (p <= end) {
        // find the next comma (or nullptr if none)
        const char *q = (const char*)std::memchr(p, ',', end - p);
        if (q == nullptr) q = end;
        out.emplace_back(p, q - p);
        p = q + 1;
    }    
}

//------------------------------------------------------------------------
// Split Numbers: 
//   split on whitespace, parse doubles, optionally strict
//------------------------------------------------------------------------
static FORCE_INLINE
split_numbers(std::string_view sv,
              std::vector<double> &out,
              bool strict,
              bool gil_release)
{
    out.clear();
    size_t start = 0;
    size_t N = sv.size();

    for (size_t i = 0; i <= N; ++i) {
        if (i == N || std::isspace((unsigned char)sv[i])) {
            if (i > start) {
                double v = NAN_VAL;
                auto fc = std::from_chars(sv.data() + start,
                                          sv.data() + i, v);
                if (fc.ec == std::errc()) {
                    out.push_back(v);
                }
                else {
                    if (strict) {
                        if (gil_release) { py::gil_scoped_acquire acquire;} 
                        throw py::value_error(
                            std::string("Failed to parse '")
                            + std::string(sv.substr(start, i - start))
                            + "' as double");
                    }
                    out.push_back(NAN_VAL);
                }
            }
            start = i + 1;
        }
    }
}

//------------------------------------------------------------------------
// Parse lines into a 2D NumPy array
//   `strict` controls error behavior
//   channel_names, if provided, will be updated or created
//------------------------------------------------------------------------
py::tuple parse_lines(
        const py::list &py_lines,                         // List of lines (str)
        const py::object &channel_names_obj = py::object(), // List of variable names (str), optional
        bool strict = false,                              // Strict parsing mode, optional
        bool gil_release = false ) {                      // Release GIL during parsing, optional

    // -- Grab python list of lines to std::vector<std::string> ----------------
    // This will allow to free the GIL while processing the lines
    size_t n_lines = py_lines.size();
    std::vector<std::string> lines;
    lines.reserve(n_lines);
    for (size_t i = 0; i < n_lines; ++i)
        lines.emplace_back(py::cast<std::string>(py_lines[i]));

    // Grab channels names ----------------------------------------------------
    bool return_dict = false;    // API return kind    
    py::dict channel_names_dict;
    py::list channel_names_list;

    size_t n_channel_names;
    // channel_names not provided  ---
    if (channel_names_obj.is_none()) {
        // if no channel_names are provided, create an empty vector
        return_dict = false;
        n_channel_names = 0;
        channel_names_list = py::list();
    // channel_names provided as list ---
    } else if (py::isinstance<py::list>(channel_names_obj)) {
        return_dict = false;
        channel_names_list = channel_names_obj.cast<py::list>();
        n_channel_names = channel_names_list.size();
    // channel_names provided as dictionary ---
    } else if (py::isinstance<py::dict>(channel_names_obj)) {
        return_dict = true;
        py::dict tmp = channel_names_obj.cast<py::dict>();
        if (tmp.empty()) {
            // Treat {} like None: no prior names → use list mode
            n_channel_names = 0;
            channel_names_list = py::list();
        } else {
            channel_names_dict = std::move(tmp);
            n_channel_names = channel_names_dict.size();
        }
    // channel_names object not supported
    } else {
        throw py::type_error("`channel_names` must be a list or dict");
    }

    // -- Drop the GIL for the heavy work so that other python threads can run --------------------------------
    if (gil_release) { py::gil_scoped_release release; }
    // --------------------------------------------------------------------------------------------------------
    // Do not call or use py:: objects and functions after this point
    // --------------------------------------------------------------------------------------------------------

    size_t buffer_row_capacity = 16; 
    size_t buffer_col_capacity;
    if (n_channel_names > 0) {
        buffer_col_capacity = n_channel_names;
    } else {
        buffer_col_capacity = 4;
    }

    size_t n_rows_used = 0; 
    size_t n_cols_used = 0;

    std::vector<double> buffer(
        buffer_row_capacity * buffer_col_capacity,
        NAN_VAL);
    std::vector<std::string_view> channels;
    channels.reserve(buffer_col_capacity); 

    // Speed optimization: use a parsed number buffers
    std::vector<std::vector<double>> parsed;
    // parsed.reserve(buffer_col_capacity);        // assume at most ~buffer_col_capcity channels per line

    // -- Parse all lines -------------------------------
    // --------------------------------------------------
    for (size_t li = 0; li < n_lines; ++li) {
        // -- grab line ---------------------------------
        const std::string &line = lines[li];

        // -- split into channel-strings ----------------
        split_channels(std::string_view(line), channels);
        size_t n_channels = channels.size();
        n_cols_used = std::max(n_cols_used, n_channels);

        // -- parse each channel ------------------------
        // speed optimization: reserve space for parsed numbers
        //
        // parsed.clear();
        // parsed.resize(n_channels);
        // for (size_t i = 0; i < n_channels; ++i) {
        //     parsed.emplace_back();       // new empty vector<double>
        //     parsed.back().reserve(16);   // or whatever your average is
        // }
        // speed optimization: prepare parsed holders and pre-reserve
        parsed.assign(n_channels, std::vector<double>());  // size = n_channels
        for (size_t i = 0; i < n_channels; ++i) {
            parsed[i].reserve(16);
        }
        size_t channel_len = 0;
        for (size_t ci = 0; ci < n_channels; ++ci) {
            split_numbers(channels[ci], parsed[ci], strict, gil_release);
            channel_len = std::max(channel_len, parsed[ci].size());
        }
        if (channel_len == 0) { channel_len = 1; } // force one “empty” row so we get all-NaNs

        // -- grow rows if needed ----------------------
        if (n_rows_used + channel_len > buffer_row_capacity) {
            size_t needed = n_rows_used + channel_len;
            while (buffer_row_capacity < needed) buffer_row_capacity *= 2;
            buffer.resize(buffer_row_capacity * buffer_col_capacity,
                        NAN_VAL);
        }

        // -- grow columns if needed -------------------
        if (n_cols_used > buffer_col_capacity) {
            size_t old_cols = buffer_col_capacity;
            buffer_col_capacity = n_cols_used;
            std::vector<double> newbuf(
                buffer_row_capacity * buffer_col_capacity,
                NAN_VAL
            );
            for (size_t r = 0; r < n_rows_used; ++r) {
                std::copy_n(&buffer[r*old_cols], old_cols,
                            &newbuf[r*buffer_col_capacity]);
            }
            buffer.swap(newbuf);
        }

        // -- fill data buffer -------------------------
        for (size_t ci = 0; ci < n_channels; ++ci) {
            auto &vals = parsed[ci];
            for (size_t vi = 0; vi < vals.size(); ++vi) {
                buffer[(n_rows_used + vi)*buffer_col_capacity + ci] = vals[vi];
            }
        }
        n_rows_used += channel_len;
    }

    // -- Reacquire the GIL for returning results -------------------------------------------------------------
    if (gil_release) { py::gil_scoped_acquire acquire;}
    // --------------------------------------------------------------------------------------------------------
    // --------------------------------------------------------------------------------------------------------

    // -- Create shape output variable -----------------
    py::tuple shape_tuple = py::make_tuple(
        (py::ssize_t)n_rows_used,
        (py::ssize_t)n_cols_used
    );

    // -- Convert buffer to a NumPy array --------------
    std::vector<Py_ssize_t> shape_vec  = { (Py_ssize_t)n_rows_used, (Py_ssize_t)n_cols_used };
    std::vector<Py_ssize_t> strides = {
        (Py_ssize_t)(buffer_col_capacity * sizeof(double)),  // bytes to advance one row
        (Py_ssize_t)(sizeof(double))                        // bytes to advance one column
    };

    auto *heap_vec = new std::vector<double>(std::move(buffer));
    py::capsule free_when_done(heap_vec, [](void *p) {
        delete static_cast<std::vector<double>*>(p);
    });

    auto arr = py::array_t<double>(
        shape_vec,              // shape (n_rows, n_cols)
        strides,            // strides in bytes
        heap_vec->data(),   // pointer to the double data
        free_when_done      // capsule that will delete heap_vec when done
    );

    // -- Prepare channel_names for output
    // if we have more columns than the initially provided channel_names, we need to create additional names
    // if input channel_names was a list, output will be list also
    // if input channel_names was a dict, output will be dict also
    // if we have the same or less number of columns than the intially provided list we return the initial names
    if (n_channel_names < n_cols_used) {
        // Update the channel names
        if (return_dict) {
            // We need to return channel_names dictionary
            for (size_t col_idx = n_channel_names; col_idx < n_cols_used; ++col_idx) {
                size_t candidate = col_idx+1;
                std::string key = std::to_string(candidate);
                while (channel_names_dict.contains(py::str(key))) {
                    candidate++;
                    key = std::to_string(candidate);
                }
                channel_names_dict[py::str(key)] = (py::ssize_t)col_idx;
            }
            return py::make_tuple(
                arr, 
                shape_tuple, 
                channel_names_dict
            );
        } else {
            // We need to return channel_names list
            for (size_t col_idx = n_channel_names; col_idx < n_cols_used; ++col_idx) {
                channel_names_list.append(py::str(std::to_string(col_idx + 1)));
            }
            return py::make_tuple(
                arr, 
                shape_tuple, 
                channel_names_list
            );
        }
    } else {
        // No changes in variable names, return object as is
        if (return_dict) {
            return py::make_tuple(arr, shape_tuple, channel_names_dict);
        } else {
            return py::make_tuple(arr, shape_tuple, channel_names_list);
        }
    }

}

PYBIND11_MODULE(simple_parser, m) {
    m.doc() = "Simple line parser";
    m.def("parse_lines",
          &parse_lines,
          py::arg("lines"),
          py::arg("channel_names") = py::none(),
          py::arg("strict") = false,
          py::arg("gil_release") = false,
          "Parse text lines with numbers separated by space and colon into a 2D NumPy array."
          "Input: list of lines (str), list of channel names (str), strict (bool)."
          "Return: array, shape (n_rows, n_cols), updated channel names."
          "If strict=True, raises an error on parse failure."
          "If gil_release=True, releases python GIL during parsing loop.");
}
