## Scripts

### Setup

A `setup.sh/setup.ps1` script creates a vritual python environment to run the application. It includes all required dependencies.

### Release

Use of release scripts from the repository root. The release version is read from `VERSION` in `config.py`.

Option style:
- Linux shell convention uses `--long-option` (for example `--build-executable`).
- PowerShell convention uses `-Parameter` (for example `-BuildExecutable`).
- `scripts/release.sh` accepts both styles for parity (`--build-executable` and `-build-executable`).

Linux examples (`scripts/release.sh`):

- Show options: `./scripts/release.sh --help`
- Update ankerl for C-accelerated parser extension: `./scripts/release.sh --update-ankerl`
- Build C++ accelerated parser extension before packaging: `./scripts/release.sh --build-c-accelerated`
- Build standalone executable (also creates `dist/SerialUI-*.zip`): `./scripts/release.sh --build-executable`
- Build, commit, tag, and push: `./scripts/release.sh --build-executable --build-c-accelerated --commit --tag --push`
- Create GitHub release for an existing version tag without rebuilding: `./scripts/release.sh --release`
- Create GitHub release only for an existing pushed tag (never build/tag/push): `./scripts/release.sh --create-release`
- Upload existing archives in `dist/` (`*.tar.gz`, `*.zip`) to an existing release: `./scripts/release.sh --upload-assets`

Windows examples (`scripts/release.ps1`):

- Show options: `.\scripts\release.ps1 -Help`
- Build standalone executable (also creates `dist\SerialUI-*.zip`): `.\scripts\release.ps1 -BuildExecutable`
- Build standalone executable + C-accelerated parser: `.\scripts\release.ps1 -BuildExecutable -BuildCAccelerated`
- Create GitHub release only for an existing pushed tag (never build/tag/push): `.\scripts\release.ps1 -CreateRelease`
- Upload existing archives in `dist\` to an existing release: `.\scripts\release.ps1 -UploadAssets`

### Github workflows

There are scripts that create my Github workflows to create executables on different platforms.

`build_realease_all.sh` creates all of the builds

On Windows amr64 platform, llvmlite is not available and numba acceleration is not activated.
