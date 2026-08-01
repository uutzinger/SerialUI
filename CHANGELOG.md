# Changelog

All notable changes to SerialUI are documented here.

## 1.5.7 - 2026-08-01

### Fixed

- Route command text and file sends only to checked, connected Serial and BLE sources.
- Preserve each selected transport's configured end-of-line bytes exactly, including CR, LF, CRLF, LFCR, and no terminator.
- Keep MAX30001G line-oriented commands such as `.` and `z` usable over BLE by appending the expected final terminator.
- Keep recording state synchronized with the checked Serial and BLE display sources.

### Added

- Add focused command-payload tests for line endings, multiline commands, trailing newlines, and empty input.
- Document release changes in this changelog so release notes can be generated from the matching version section.
