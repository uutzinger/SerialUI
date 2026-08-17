# Changelog

All notable changes to SerialUI are documented here.

## 1.5.8 - 2026-08-16

### Fixed

- Prevent duplicate BLE notification subscriptions by guarding asynchronous start and stop transitions and ignoring stale completions from earlier connections.
- Restore BLE notifications through the same guarded path after reconnect instead of calling `start_notify()` directly.
- Start and stop Serial/BLE receivers only when aggregate Terminal or Plotter demand changes, without retriggering reception for every command or repeated ready event.
- Keep Terminal and Plotter as independent consumers of one received stream using unique Qt signal connections.
- Preserve one synchronous `readyRead` connection when Serial receiver start requests are repeated.

### Added

- Add focused regression tests for overlapping BLE lifecycle requests, reconnects, repeated ready events, Terminal/Plotter fan-out, aggregate receiver demand, and repeated Serial starts.

### Validation

- Pass 13 focused lifecycle and command-framing tests, Python compilation checks, and `git diff --check`.
- Live MAX30001G BLE hardware validation remains pending.

## 1.5.7 - 2026-08-01

### Fixed

- Route command text and file sends only to checked, connected Serial and BLE sources.
- Preserve each selected transport's configured end-of-line bytes exactly, including CR, LF, CRLF, LFCR, and no terminator.
- Keep MAX30001G line-oriented commands such as `.` and `z` usable over BLE by appending the expected final terminator.
- Keep recording state synchronized with the checked Serial and BLE display sources.

### Added

- Add focused command-payload tests for line endings, multiline commands, trailing newlines, and empty input.
- Document release changes in this changelog so release notes can be generated from the matching version section.
