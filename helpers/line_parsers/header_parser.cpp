// --------------------------------------------------------------------------------------------------------
// header_parse.cpp
//
// High-performance parser for lines with headers and numbers
// - numbers are parsed into a numpy array
// - headers define the name of data
// - in the output array, columns indicate a channel, rows are sequential data points
// - in the input stream, space-separated numbers belong to the same channel
// - in the input stream, a comma separates channels
// - in the input stream, a new line restarts the row counter for all channels
// - empty tokens are represented as NaN
//
// The parser releases the GIL during processing but uses a single thread
//
// Urs Utzinger, May, June 2025
// --------------------------------------------------------------------------------------------------------

// #define DEBUG_LOG
#undef DEBUG_LOG

/*

**Parser Rules for Headers and Channels**

1. **Segment Splitting (Headers vs. Data)**

   * A **colon** (`:`) marks the boundary between a *header* and its *data segment*.
   * If a line has no colon before its first characters, that initial chunk is treated as **headerless**.

2. **Sub‑Channel Splitting**

   * Within each data segment (after a header or in a headerless chunk), **commas** (`,`) split into *sub‑channels*.
   * **Empty sub‑channels** (adjacent delimiters) produce an empty token, which becomes `NaN`.

3. **Row Splitting**

   * Inside each sub‑channel, **whitespace** (spaces/tabs) further splits into *rows* of values.
   * All sub‑channels of a segment align by row; missing values yield `NaN` in that row.

4. **Column Construction**

   * Each unique header name defines a group of columns:

     * If header **H** ever has >1 sub‑channel in any segment, create columns `H_1, H_2, …` up to the maximum count.
     * If header **H** always has exactly one sub‑channel, name its column simply `H`.
   * Headerless values occupy the **first columns** (in the same order they appear), numbered by position if desired.

5. **Output Table Layout**

   * **Rows** of the output = sum of all per‑segment row counts across all input lines (concatenated).
   * **Columns** = total columns from all headers (including sub‑channel expansions) plus any headerless columns.
   * Missing or non‑parseable entries become `NaN` (or raise in strict mode).

6. **Strict Mode**

   * In **default** mode, invalid numeric tokens yield `NaN`.
   * In **strict** mode, any parse failure throws an error.

*/

#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>
#include <vector>
#include <string>
#include <string_view>
#include <charconv>
#include <cctype>
#include <limits>
#include <algorithm>
#include <unordered_map>
#include <map>
#include <cstring>   
#include <sstream> 
#include "unordered_dense.h"

namespace py = pybind11;

static constexpr double NAN_VAL = std::numeric_limits<double>::quiet_NaN();
static constexpr char UNNAMED_BASE[] = "__unnamed";

//------------------------------------------------------------------------
// Trim Range:
//   Given [lo..hi), trim leading spaces and trailing spaces in string
//    by moving 'lo' forward past spaces, and 'hi' backward past spaces.
//   After calling this function, either lo >= hi (empty) or the substring [lo..hi) is “cleaned.”
//------------------------------------------------------------------------
static inline __attribute__((always_inline)) void
trim_range(std::string_view sv, size_t &lo, size_t &hi)
{
    // Trim leading whitespace
    while (lo < hi && std::isspace(static_cast<unsigned char>(sv[lo]))) {
        ++lo;
    }
    // Trim trailing whitespace
    while (hi > lo && std::isspace(static_cast<unsigned char>(sv[hi - 1]))) {
        --hi;
    }
}

//------------------------------------------------------------------------
// Split Headers and Data Segments:
//   split segment into header, data
//   header can contain (A–Z or a–z) or a digit (0–9) or underscore (_)
//   header can also be enclosed in quotes '' or "" to allow any character (not yet supported)
//   headerless chunk can ocur at beginning when header with colon is not present
// Example
// "  α=123, β:45 ,  γ:hello, `xyz`  , trailing beta_1: 1,2 3,4"
// will produce the following segments:
//{
//  { "",        "α=123"                    },
//  { "β",       "45"                       },
//  { "γ",       "hello, `xyz`  , trailing" },
//  { "beta_1",  "1,2 3,4"                  }
//}
// parsing the following segment
//  { "1,2 3,4"}
// should produce
//  [[  1, 2, 4]
//   [Nan, 3, Nan]]
//------------------------------------------------------------------------
static inline __attribute__((always_inline)) std::vector<std::pair<std::string_view,std::string_view>>
split_headers(std::string_view sv)
{
    size_t len = sv.size();

    // First pass: find all “header:” positions
    struct HeaderPos {
        size_t hdr_start;  // index of first character of header
        size_t colon_pos;  // index of ':' position
        bool quoted;       // true if this header has quotes
    };

    // Reserve header positions
    //   a rough estimate: number of colons <= half the length of the string
    //   avoids repeated re‐allocs if many headers
    std::vector<HeaderPos> hdrs;
    hdrs.reserve(std::min(len / 2, size_t(16)));

    for (size_t pos = 0; pos < len; ++pos) {
        if (sv[pos] == ':') {
            if (pos >= 1 && (sv[pos - 1] == '"' || sv[pos - 1] == '\'')) {
                char quote = sv[pos - 1];
                // find the matching quote
                size_t start = pos -1;
                bool found = false;
                while (start > 0) {
                    --start;
                    if (sv[start] == quote) {
                        found = true;
                        break;
                    }
                }
                if (found && start < pos - 1) {
                    // We have quotes from start..(pos-1).  The actual header text is
                    // inside them (start+1 .. pos-1).  We'll return that without quotes.
                    hdrs.push_back({ start + 1, pos, true });
                    continue; 
                } // If we didn’t find a matching quote, fall through to the unquoted logic.
            }

            // Otherwise use "unquoted" case: back up over [A-Za-z0-9_] to find where header name begins
            size_t start = pos;
            while (start > 0) {
                unsigned char c = static_cast<unsigned char>(sv[start - 1]);
                if (std::isalnum(c) || c == '_') {
                    --start;
                } else {
                    break;
                }
            }
            if (start < pos) {
                // We did see at least one valid header character before ':'
                hdrs.push_back({ start, pos, false });
            }
        }
    }

    // If no headers found, return one ("", trimmed‐entire‐string) pair
    if (hdrs.empty()) {
        // Find trimmed bounds of [0..len)
        size_t lo = 0, hi = len;
        trim_range(sv, lo, hi);
        if (lo >= hi) {
            return { { std::string_view(""), std::string_view("") } };
        }
        return { { std::string_view(""), sv.substr(lo, hi - lo) } };
    }

    // Prepare result; 
    //   reserve capacity = (#headers) + (maybe 1 for prefix)
    std::vector<std::pair<std::string_view, std::string_view>> segs;
    segs.reserve(hdrs.size() + 1);

    // Handle any “headerless prefix” before the first header
    if (hdrs[0].hdr_start > 0) {
        size_t lo = 0, hi = hdrs[0].hdr_start;
        trim_range(sv, lo, hi);
        if (lo < hi) {
            // Only push if not empty after trimming
            segs.emplace_back(
                std::string_view(""),
                sv.substr(lo, hi - lo)
            );
        }
    }

    // For each header-data pair, compute trimmed bounds, then substr once
    for (size_t i = 0; i < hdrs.size(); ++i) {
        auto &H = hdrs[i];

        // a) Extract “header” 
        //  - if quoted, that range is exactly the inner-quote text
        //  - if unquoted, that range is the  run[A-Za-z0-9_]+
        std::string_view header_sv = 
            sv.substr(H.hdr_start, H.colon_pos - H.hdr_start);

        // If it was quoted, we already skipped the surrounding quotes. 
        // If it was unquoted, this is exactly the name.
        // (No further trimming needed.)

        // b) next, extract “data” from right after the colon up to next header’s start or end:
        size_t dlo = H.colon_pos + 1;
        size_t dhi = (i + 1 < hdrs.size() ? hdrs[i + 1].hdr_start : len);
        std::string_view data_sv;

        // c) trim the data range [dlo..dhi) to remove leading/trailing spaces
        if (dlo >= dhi) {
            // handle empty, `data` stays as the empty string.
            data_sv = std::string_view("");
        } else if (sv[dlo] != ' ' && sv[dhi - 1] != ' ') {
            // already clean
            data_sv = sv.substr(dlo, dhi - dlo);
        } else {
            // only now do trim_range
            trim_range(sv, dlo, dhi);
            data_sv = (dlo < dhi ? sv.substr(dlo, dhi - dlo) : std::string_view(""));
        }

        // d) Finally, push the (header_sv, data_sv) pair
        segs.emplace_back(header_sv, data_sv);
    }

    return segs;
}

//------------------------------------------------------------------------
// Split Channels: 
//   split on comma 
//   preserving empty tokens
//------------------------------------------------------------------------
static inline __attribute__((always_inline)) void split_channels(
    std::string_view sv,
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
//   split on whitespace
//   parse doubles
//   none numeric tokes pushes NaN
//   numeric prefix + junk, parse prefix skip rest
//   optional strict mode and gil release
//
// the strings provided to this function should not include commas or colons
//------------------------------------------------------------------------
static inline __attribute__((always_inline)) void 
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
// Parse Line by Line
//
// Takes a list of text lines and parses them into an array
//------------------------------------------------------------------------
#ifdef DEBUG_LOG
py::tuple parse_lines(
    const py::list &py_lines,                           // List of lines (str)
    const py::object &channel_names_obj = py::object(), // List of variable names (str), optional
    bool strict = false,                                // Strict parsing mode, optional
    bool gil_release = false,                           // Release GIL during parsing, optional
    bool debug = false) {                               // Debugging flag, optional
#else
py::tuple parse_lines(
    const py::list &py_lines,                           // List of lines (str)
    const py::object &channel_names_obj = py::object(), // List of variable names (str), optional
    bool strict = false,                                // Strict parsing mode, optional
    bool gil_release = false) {                         // Release GIL during parsing, optional
#endif

    #ifdef DEBUG_LOG
    std::ostringstream log; // debug log stream
    #endif

    // Grab python list of lines to std::vector<std::string> ----------------
    //   this will allow to free the GIL while processing the lines
    size_t n_lines = py_lines.size();
    std::vector<std::string> lines;
    lines.reserve(n_lines);
    for (size_t i = 0; i < n_lines; ++i)
        lines.emplace_back(py::cast<std::string>(py_lines[i]));

    #ifdef DEBUG_LOG
    if (debug) log << "[parse_lines] Got " << lines.size() << " lines from Python\n";
    #endif

    // Grab channel names ----------------------------------------------------
    bool return_dict = false;    // API return kind   
    py::dict channel_names_dict;
    py::list channel_names_list;
    ankerl::unordered_dense::map<std::string, size_t> channel_index;
    //std::unordered_map<std::string, size_t> channel_index; // maps channel name → index
    std::vector<std::string> channel_names;                // maps index → channel name
    size_t n_channel_names;
    
    // channel_names not provided
    if (channel_names_obj.is_none()) {
        // if no channel_names are provided, create an empty vector
        return_dict = false;
        n_channel_names = 0;
        channel_index.reserve(128);
        channel_names.reserve(128);

    // channel_names provided as list
    } else if (py::isinstance<py::list>(channel_names_obj)) {
        return_dict = false;
        channel_names_list  = channel_names_obj.cast<py::list>(); 
        n_channel_names = channel_names_list.size();
        size_t anticipated = std::max(n_channel_names, size_t(128));
        channel_index.reserve(anticipated);
        channel_names.resize(n_channel_names);  
        // Build name→index map from the list
        // Build index→name map from the list
        for (auto &hdr : channel_names_list) {
            // hdr is a Python string, cast it to std::string
            std::string nm = hdr.cast<std::string>();
            size_t idx = channel_index.size(); // index is current size
            channel_index.emplace(nm, idx);
            channel_names[idx] = nm; 
        }

    // channel_names provided as dictionary ---
    } else if (py::isinstance<py::dict>(channel_names_obj)) {
        return_dict = true;
        py::dict tmp = channel_names_obj.cast<py::dict>();
        // Treat {} like None: no prior channel names known -> use list mode
        if (tmp.empty()) {            n_channel_names = 0;
            channel_index.reserve(128);
        } else {
            channel_names_dict = std::move(tmp);
            n_channel_names = channel_names_dict.size();

            // Build name→index map from the dict keys and values.
            // dict is { "channel_name": index, … }
            size_t anticipated = std::max(n_channel_names, size_t(128));
            channel_index.reserve(anticipated);
            size_t max_channel_index = 0;
            for (auto item : channel_names_dict) {
                size_t idx = static_cast<size_t>(item.second.cast<long>());
                max_channel_index = std::max(max_channel_index, idx);
            }
            channel_names.resize(max_channel_index + 1);
            for (auto item : channel_names_dict) {
                // item.first  → a Python string
                // item.second → a Python int
                std::string nm = item.first.cast<std::string>();
                size_t idx     = static_cast<size_t>(item.second.cast<long>());
                channel_index.emplace(nm, idx);
                channel_names[idx] = nm;
            }
        }

    // channel_names object not supported
    } else {
        throw py::type_error("`channel_names` must be a list or dict");
    }

    #ifdef DEBUG_LOG
    if (debug) log << "[parse_lines] Got " << n_channel_names << " channel names from Python\n";
    if (debug) log << "[parse_lines] Made " << channel_index.size() << " channel indices\n";
    #endif

    // Drop the GIL for the heavy work so that other python threads can run -----------------------------------
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
    // std::vector<std::string_view> channels;
    // channels.reserve(buffer_col_capacity); 

    #ifdef DEBUG_LOG
    if (debug) log << "[parse_lines] Reserved " << buffer_col_capacity << " columns for buffer\n";
    if (debug) log << "[parse_lines] Reserved " << buffer_row_capacity << " rows for buffer\n";
    #endif

    // Speed optimization: use a parsed number buffers
    std::vector<std::vector<double>> parsed;
    parsed.reserve(buffer_col_capacity);        // assume at most ~buffer_col_capcity channels per line

    // Parse all lines ----------------------------------
    // --------------------------------------------------

    std::vector<std::string_view> subs; // subchannel storage, reused
    subs.reserve(8);                    // assume up to 8 subchannels per segment

    for (size_t li = 0; li < n_lines; ++li) {

        auto segs = split_headers(std::string_view(lines[li]));

        #ifdef DEBUG_LOG
        if (debug) {
            log << "[line " << li << "] split_headers → " << segs.size() << " segments:\n";
            for (auto &p : segs) {
                log << "   header='" << std::string(p.first) 
                    << "'  data='" << std::string(p.second) << "'\n";
            }
        }
        #endif

        // We collect, for each header in this line:
        //     - base_name   (std::string, e.g. "myheader" or "")
        //     - n_subs      (int)
        //     - channel_len (how many rows that header will occupy = max parsed-vector length, or 1)
        //     - parsed      (a vector<vector<double>>, one per sub)
        //     - col_indices (vector<size_t>, indices into channel_index for each sub)
        //
        //    We store these in a small temporary struct so that we can 
        //    (a) discover all channel counts & update channel_index, and 
        //    (b) only after that grow buffer, fill data in one shot.
        struct HeaderData {
            std::string                base_name;
            int                        n_subs;
            size_t                     channel_len;
            std::vector<std::vector<double>> parsed;
            std::vector<size_t>        col_indices;
        };

        std::vector<HeaderData> line_headers;
        line_headers.reserve(segs.size());

        size_t n_new_rows = 1;   // at least one row per line, even if no data

        // First pass over segs: split channels & numbers, discover sub channel counts,
        //    compute channel_len per header, and update channel_index/channel_names on the fly.
        for (auto &sp : segs) {
            std::string_view hdr_sv  = sp.first;  // header name (or "")
            std::string_view data_sv = sp.second; // raw text after colon

            // Convert hdr_sv to an owning std::string for key manipulation:
             std::string base;
            if (hdr_sv.empty()) {
                base = std::string(UNNAMED_BASE); // default header name for headerless
            } else {
                base.assign(hdr_sv);
            }

            HeaderData hd;
            hd.base_name = base;

            // Split on commas into subs[]
            subs.clear();
            split_channels(data_sv, subs);

            #ifdef DEBUG_LOG
            if (debug) {
                log << "     -> " << subs.size() << " subchannels:";
                for (auto &sv : subs) {
                    log << " [" << std::string(sv) << "]";
                }
                log << "\n";
            }
            #endif

            int n_subs = (int)subs.size();

            // No data in this header segment, we still need at create least one subcolumn

            if (n_subs <= 0) {
                n_subs = 1; 
                subs.resize(1); // one empty sub
                subs[0] = std::string_view("");
            }
            hd.n_subs = n_subs;  // number of subcolumns for this header

            // Parse the subs into numbers

            // Resize parsed so that parsed[i] is available
            parsed.clear();
            parsed.resize(n_subs);
            // For each subs[i], split into numbers
            size_t sub_len = 0;
            for (int i = 0; i < n_subs; ++i) {
                split_numbers(subs[i], parsed[i], strict, gil_release);
                sub_len = std::max(sub_len, parsed[i].size());
            }
            if (sub_len == 0) sub_len = 1;  // force at least one row of NaN
            hd.channel_len = sub_len;
            hd.parsed = parsed;

            #ifdef DEBUG_LOG
            if (debug) {
                for (int i = 0; i < n_subs; ++i) {
                    log << "       sub[" << i << "] parsed " << parsed[i].size() << " numbers\n";
                }
            }
            #endif

            // Now ensure that subcolumns "hdr_1 .. hdr_n_subs" exists in channel_index
            //
            //    - If “hdr” itself already existed (with no “_i”), that means the user gave a
            //      channel name “hdr” in channel_ names. In that case, we want to treat that as “hdr_1”.
            //      We do this by: (a) look up index_of["hdr"], (b) rename it to index_of["hdr_1"], 
            //      and erase index_of["hdr"].
            //
            //    - Next, for i = 1..n_subs, if “hdr_i” is not yet in index_of, we assign it a new index:
            //      new_idx = channel_names.size(); channel_names.push_back("hdr_i"); channel_index["hdr_i"] = new_idx;

            size_t single_channel_colidx; // for the n_subs == 1 case

            if (n_subs == 1) {
                // One sub‐column: (special case) ------------------------------------------------
                // we check if base or base+"_1" already exists.

                // First, see if "base_1" is already in the index (from a prior multi-sub use).
                std::string base1 = base + "_1";

                if (channel_index.count(base1)) {
                    // We already have "base_1" as the correct column.  Use that.
                    single_channel_colidx = channel_index[base1];
                    // hd.col_indices.push_back(single_channel_colidx);

                    #ifdef DEBUG_LOG
                    if (debug) log << "    reusing existing sub-column '"
                                << base1 << "' at index " << single_channel_colidx << "\n";
                    #endif
                }                

                else if (channel_index.count(base)) {
                    // We already had exactly "base" (no suffix).  Reuse that index:
                    single_channel_colidx = channel_index[base];
                    // hd.col_indices.push_back(single_channel_colidx);

                    #ifdef DEBUG_LOG
                    if (debug) log << "    reusing existing column '"
                                << base << "' at index " << single_channel_colidx << "\n";
                    #endif
                }                
                
                else {
                    // Neither "base_1" nor "base" exists → make a new "base" column:
                    single_channel_colidx = channel_names.size();
                    channel_names.push_back(base);
                    channel_index.emplace(base, single_channel_colidx);
                    // hd.col_indices.push_back(new_col);

                    #ifdef DEBUG_LOG
                    if (debug) log << "    created column '"
                                << base << "' at index " << single_channel_colidx << "\n";
                    #endif
                }
            } else {
                // More than one sub channel → we must create "base_1", "base_2", ..., "base_n_subs"

                // If channel_index already had exactly “base” (no suffix), convert it into “base_1”:
                if (channel_index.count(base)) {
                    // This means user‐provided channel_names included “header” exactly once. We want to re‐label it as “header_1”.
                    size_t old_idx = channel_index[base];
                    channel_index.erase(base);

                    std::string base1 = base + "_1";
                    channel_names[old_idx] = base1;
                    channel_index.emplace(base1, old_idx);
                    
                    #ifdef DEBUG_LOG
                    if (debug) log << "    renamed column '" << base << "' to " << base1 << "\n";
                    #endif

                    // Now create base_2..base_n_subs
                    for (int i = 2; i <= n_subs; ++i) {
                        std::string hi = base + "_" + std::to_string(i);
                        if (!channel_index.count(hi)) {
                            size_t new_col = channel_names.size();
                            channel_names.push_back(hi);
                            channel_index.emplace(hi, new_col);

                            #ifdef DEBUG_LOG
                            if (debug) log << "    created column '" << hi << "' at index " << new_col << "\n";
                            #endif

                        }
                    }
                }
                else {
                    // “base” not in index yet; create base_1..base_n_subs from scratch
                    for (int i = 1; i <= n_subs; ++i) {
                        std::string hi = base + "_" + std::to_string(i);
                        if (!channel_index.count(hi)) {
                            size_t new_col = channel_names.size();
                            channel_names.push_back(hi);
                            channel_index.emplace(hi, new_col);

                            #ifdef DEBUG_LOG
                            if (debug) log << "    created column '" << hi << "' at index " << new_col << "\n";
                            #endif

                        }
                    }
                }
            }

            // Store col_indices for each sub, keep name as is if only one channel
            hd.col_indices.clear();
            hd.col_indices.reserve(n_subs);
            if (n_subs == 1) {
                // hd.col_indices.push_back(channel_index[base]);
                hd.col_indices.push_back(single_channel_colidx);
            } else {
                for (int i = 1; i <= n_subs; ++i) {
                    std::string hi = base + "_" + std::to_string(i);
                    hd.col_indices.push_back(channel_index[hi]);
                }
            }

            #ifdef DEBUG_LOG
            if (debug) {
                log << "    header '" << hd.base_name << "' has " << hd.n_subs 
                    << " subcolumns, max rows = " << hd.channel_len << "\n";
                for (int i = 0; i < hd.n_subs; ++i) {
                    log << "      sub[" << i << "] has " << hd.parsed[i].size() 
                        << " values: ";
                    for (double v : hd.parsed[i]) {
                        log << v << " ";
                    }
                    log << "\n";
                }
                for (size_t i = 0; i < hd.col_indices.size(); ++i) {
                    log << "      col_indices[" << i << "] = " << hd.col_indices[i] << "\n";
                }
            }
            #endif

            n_new_rows = std::max(n_new_rows, sub_len);

            line_headers.push_back(std::move(hd));

        } // end for each seg

        // Now that we have discovered all sub channel counts for every header in this line,
        //    n_new_rows is the maximum “height” we need for row‐blocks of this line.
        //    Also, channel_index.size() == total columns needed so far.

        // Grow rows and cols if needed --------------------------------
        n_cols_used = channel_names.size();

        #ifdef DEBUG_LOG
        if (debug) {
            log << "  After line " << li 
                << ", need " << n_new_rows 
                << " new rows, total rows so far = " 
                << (n_rows_used + n_new_rows) << "\n";
            log << "  Current total columns = " << n_cols_used << "\n";
        }
        #endif

        // Grow rows if needed
        // We grow buffer length by factors of 2
        size_t needed_rows = n_rows_used + n_new_rows;
        if (needed_rows > buffer_row_capacity) {
            // Double until we can fit
            while (buffer_row_capacity < needed_rows) {
                buffer_row_capacity *= 2;
            }
            buffer.resize(buffer_row_capacity * buffer_col_capacity, NAN_VAL);
        }

        // Grow columns if needed -----------------------------
        // We grow buffer columns to exactly the number we need for fast numpy conversion
        if (n_cols_used > buffer_col_capacity) {
            size_t old_col_cap = buffer_col_capacity;
            size_t new_col_cap = n_cols_used;
            std::vector<double> newbuf(buffer_row_capacity * new_col_cap, NAN_VAL);
            // Copy each existing row’s old columns into the new buffer
            for (size_t r = 0; r < n_rows_used; ++r) {
                // copy columns 0..old_col_cap-1
                std::copy_n(
                    &buffer[r * old_col_cap],
                    old_col_cap,
                    &newbuf[r * new_col_cap]
                );
            }

            buffer.swap(newbuf);
            buffer_col_capacity = new_col_cap;
        }

        // Finally, fill the buffer for this line. We reserve rows
        //    [n_rows_used .. n_rows_used + n_new_rows - 1], all columns.
        size_t row_base = n_rows_used;
        size_t col_cap = buffer_col_capacity; // new capacity

        #ifdef DEBUG_LOG
        if (debug) {
            log << "  Filling buffer rows " << row_base 
                << " to " << (row_base + n_new_rows - 1) 
                << ", columns 0 to " << (col_cap - 1) << "\n";
        }
        #endif

        for (auto &hd : line_headers) {
            for (int j = 0; j < hd.n_subs; ++j) {
                size_t colidx = hd.col_indices[j];
                auto &vals = hd.parsed[j];
                for (size_t vi=0; vi< vals.size(); ++vi) {
                    buffer[(row_base + vi) * col_cap + colidx] = vals[vi];
                }
                // If vals.size() < hd.channel_len, those rows remain NaN
            }
        }

        // Advance the global row‐counter by how many rows this line actually used
        n_rows_used += n_new_rows;
    } // end for each line

    // Finalize the buffer and prepare output ------------------------------------------------------------------
    //   We have:
    //      std::vector<double> buffer;
    //      size_t n_rows_used, n_cols_used;    // only [0..n_rows_used) × [0..n_cols_used) are valid
    //      size_t buffer_col_capacity;         // overall “stride” width in your buffer

    #ifdef DEBUG_LOG
    if (debug) {
        log << "[parse_lines] Done parsing all lines. Final size = "
            << n_rows_used << " × " << n_cols_used << "\n";
    }
    #endif

    // Reacquire the GIL for returning results ----------------------------------------------------------------
    if (gil_release) { py::gil_scoped_acquire acquire;}
    // --------------------------------------------------------------------------------------------------------
    // --------------------------------------------------------------------------------------------------------

    // Compute the shape and strides for the numpy array. 
    //    We want a 2D array of shape (n_rows_used, n_cols_used), laid out row‐major in memory.  
    //    Each row is contiguous in `buffer.data()`.
    //    The full row length in C++ is`buffer_col_capacity` doubles,
    //       so the stride between row i and row i+1 is `buffer_col_capacity * sizeof(double)`.
    //    We only want columns [0..n_cols_used), 
    //       therefore numpy array’s “column stride” is simply `sizeof(double)`.

    std::vector<Py_ssize_t> shape_vec  = { (Py_ssize_t)n_rows_used, (Py_ssize_t)n_cols_used };
    std::vector<Py_ssize_t> strides = {
        (Py_ssize_t)(buffer_col_capacity * sizeof(double)),  // bytes to advance one row
        (Py_ssize_t)(sizeof(double))                        // bytes to advance one column
    };

    // Create a py::capsule that owns the `std::vector<double>` so that it isn't
    //    destroyed while the NumPy array is alive.  We heap‐allocate a new `vector<double>`
    //    via `new`, move your existing `buffer` into it, and tell the capsule to delete
    //    it when the Python object is finalized.

    auto *heap_vec = new std::vector<double>(std::move(buffer));
    py::capsule free_when_done(heap_vec, [](void *p) {
        delete static_cast<std::vector<double>*>(p);
    });

    // Finally, create the NumPy array, passing the raw data pointer, shape, strides,
    //    and the capsule as the “base”.  As long as the Python array is alive, the capsule
    //    (and thus the heap‐allocated vector) will stay alive.

    auto arr = py::array_t<double>(
        shape_vec,              // shape (n_rows, n_cols)
        strides,            // strides in bytes
        heap_vec->data(),   // pointer to the double data
        free_when_done      // capsule that will delete heap_vec when done
    );

    // Build shape
    py::tuple shape_tuple = py::make_tuple((py::ssize_t)n_rows_used, (py::ssize_t)n_cols_used);

    // Build channel_names for output

    if (return_dict) {
        // We need to return channel_names dictionary
        py::dict channel_names_dict_out;
        for (size_t col_idx = 0; col_idx < n_cols_used; ++col_idx) {
            const std::string &key = channel_names[col_idx];
            channel_names_dict_out[py::str(key)] = (py::ssize_t)col_idx;
        }
        #ifdef DEBUG_LOG
        // Return (array, shape, dict, debug_string)
        return py::make_tuple(
            arr, 
            shape_tuple, 
            channel_names_dict_out,
            py::str(log.str())
        );
        #else
        return py::make_tuple(
            arr, 
            shape_tuple, 
            channel_names_dict_out
        );
        #endif
    } else {
        // We need to return channel_names list
        py::list channel_names_list_out;
        for (size_t col_idx = 0; col_idx < n_cols_used; ++col_idx) {
            std::string key = channel_names[col_idx];
            channel_names_list_out.append(py::str(key));
        }
        #ifdef DEBUG_LOG
        // Return (array, shape, list, debug_string)
        return py::make_tuple(
            arr, 
            shape_tuple, 
            channel_names_list_out,
            py::str(log.str())
        );
        #else
        return py::make_tuple(
            arr, 
            shape_tuple, 
            channel_names_list_out
        );
        #endif
    } 
}

#ifdef DEBUG_LOG
PYBIND11_MODULE(header_parser, m) {
    m.doc() = "Parse lines with optional headers into NumPy arrays";
    m.def("parse_lines", 
          &parse_lines,
          py::arg("lines"),
          py::arg("channel_names") = py::none(),
          py::arg("strict") = false,
          py::arg("gil_release") = false,
          py::arg("debug") = false,
          "Parse text lines with headers and data separated by colon"
          "Parse data separated by space and colon into a 2D NumPy array."
          "Input: list of lines (str), list of channel names (str), strict (bool)."
          "Return: array, shape (n_rows, n_cols), updated channel names."
          "If strict=True, raises an error on parse failure."
          "If gil_release=True, releases python GIL during parsing loop."
          "If debug=True, and DEBUGLOG was on during compile, will produce debug info.");
}
#else
PYBIND11_MODULE(header_parser, m) {
    m.doc() = "Parse lines with optional headers into NumPy arrays";
    m.def("parse_lines", 
          &parse_lines,
          py::arg("lines"),
          py::arg("channel_names") = py::none(),
          py::arg("strict") = false,
          py::arg("gil_release") = false,
          "Parse text lines with headers and data separated by colon"
          "Parse data separated by space and colon into a 2D NumPy array."
          "Input: list of lines (str), list of channel names (str), strict (bool)."
          "Return: array, shape (n_rows, n_cols), updated channel names."
          "If strict=True, raises an error on parse failure."
          "If gil_release=True, releases python GIL during parsing loop.");
}
#endif