## Scripts

### Setup

A `setup.sh/setup.ps1` script creates a vritual python environment to run the application. It includes all required dependencies.

### Release

Use of release scripts from the repository root. The release version is read from `VERSION` in `config.py`.

`scripts/build_release_all.sh` commits, tags, and pushes a new version, creates its GitHub release, and waits for packages to be published entirely within GitHub. Push the release automation changes to the default branch before using this flow.

```bash
bash scripts/build_release_all.sh
```

Linux, macOS, and Windows builds start automatically when the version tag is pushed. The publishing workflow reuses queued, running, or successful builds at that exact commit. It waits briefly for tag-triggered runs to appear before dispatching a missing build, and rebuilds expired artifacts when packages have not yet been published. Failed builds stop publication; rerun the failed build in GitHub Actions, then run the release script again.

The GitHub runner validates the package ZIPs and attaches missing packages directly to the release. No package downloads or uploads pass through your computer, and existing release assets are preserved. Repeating the command with an existing tag resumes publication; platforms whose packages are already attached are skipped. Local uncommitted changes are not included when reusing an existing tag.

Use `--skip-linux`, `--skip-macos`, or `--skip-windows` to omit packages. Raspbian remains off by default; `--with-raspbian` enables it and requires the configured self-hosted runner. `--build-ref` must resolve to the same commit as the release tag. `--commit-only` still stops after the local commit.

For local copies of published packages:

```bash
gh release download 1.5.9 --pattern 'SerialUI-*.zip' --dir dist
```

The individual `scripts/run_github_*_build.sh` tools are still available for explicit builds and local downloads. To download an existing successful build without starting another one, pass `--run-id <id>`.

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

The `build-linux.yml`, `build-macos.yml`, and `build-windows.yml` workflows build executables on tag pushes or manual dispatch. `publish-release-assets.yml` uses `scripts/publish_release_assets.py` to reuse or start the selected builds and publish their archives. Its token has Actions write permission to dispatch missing builds and Contents write permission to attach release assets.

On Windows amr64 platform, llvmlite is not available and numba acceleration is not activated.
