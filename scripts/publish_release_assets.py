#!/usr/bin/env python3
"""Reuse release builds and publish their archives from a GitHub runner."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import quote
import zipfile


WORKFLOWS = {
    "linux": ("build-linux.yml", (
        "linux-ubuntu22-x86_64", "linux-ubuntu24-aarch64", "linux-ubuntu24-x86_64",
        "linux-ubuntu26-aarch64", "linux-ubuntu26-x86_64",
    )),
    "macos": ("build-macos.yml", ("macos-arm64",)),
    "windows": ("build-windows.yml", ("windows-amd64", "windows-arm64")),
    "raspbian": ("build-raspbian.yml", ()),
}


def gh_json(*args):
    return json.loads(subprocess.check_output(["gh", *args], text=True))


def gh(*args):
    subprocess.run(["gh", *map(str, args)], check=True)


def package_names(tag, platform):
    return {f"SerialUI-{tag}-{suffix}.zip" for suffix in WORKFLOWS[platform][1]}


def find_build(repo, workflow, ref, sha, count):
    """Return a reusable run, whether a build is active, and completed failures."""
    runs = gh_json("api", f"repos/{repo}/actions/workflows/{workflow}/runs"
                   f"?branch={quote(ref, safe='')}&per_page=100")["workflow_runs"]
    matching = [run for run in runs if run["head_sha"] == sha and run["head_branch"] == ref]
    for run in matching:
        if run["conclusion"] != "success":
            continue
        artifacts = gh_json("api", f"repos/{repo}/actions/runs/{run['id']}/artifacts?per_page=100")
        usable = [item for item in artifacts["artifacts"]
                  if item["name"].startswith("SerialUI-archive-") and not item["expired"]]
        if len(usable) == count:
            return run["id"], False, []
    active = any(run["status"] != "completed" for run in matching)
    failures = [run["id"] for run in matching
                if run["status"] == "completed" and run["conclusion"] != "success"]
    return None, active, failures


def ensure_builds(repo, tag, ref, sha, platforms, grace_seconds=60, timeout_seconds=1800):
    """Wait for tag-triggered builds; dispatch only missing or expired builds."""
    started = time.monotonic()
    dispatched = set()
    ready = {}
    while len(ready) < len(platforms):
        for platform in platforms:
            if platform in ready:
                continue
            workflow, suffixes = WORKFLOWS[platform]
            run_id, active, failures = find_build(repo, workflow, ref, sha, len(suffixes) or 1)
            if run_id:
                ready[platform] = run_id
                print(f"{platform}: reusing successful run {run_id} at {sha}", flush=True)
            elif active:
                print(f"{platform}: waiting for existing build at {sha}", flush=True)
            elif platform not in dispatched:
                if failures:
                    raise RuntimeError(f"{platform}: build failed or was cancelled: {failures}. "
                                       "Rerun the failed workflow before retrying publication.")
                # A freshly pushed tag may not appear in the Actions API immediately.
                if time.monotonic() - started >= grace_seconds:
                    print(f"{platform}: starting missing build on {ref}", flush=True)
                    gh("workflow", "run", workflow, "--repo", repo, "--ref", ref)
                    dispatched.add(platform)
        if len(ready) == len(platforms):
            return ready
        if time.monotonic() - started >= timeout_seconds:
            raise RuntimeError("Timed out waiting for release builds")
        time.sleep(15)
    return ready


def publish(repo, tag, ref, platforms, directory):
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+[a-zA-Z0-9._-]*", tag):
        raise ValueError("Expected a version tag such as 1.5.9")
    if not platforms or any(platform not in WORKFLOWS for platform in platforms):
        raise ValueError("Select one or more of linux, macos, windows, raspbian")
    sha = gh_json("api", f"repos/{repo}/commits/{quote(tag, safe='')}")["sha"]
    ref_sha = gh_json("api", f"repos/{repo}/commits/{quote(ref, safe='')}")["sha"]
    if ref_sha != sha:
        raise ValueError(f"Build ref {ref} must point to release {tag} commit {sha}")
    release = gh_json("release", "view", tag, "--repo", repo, "--json", "assets")
    existing = {asset["name"]: asset for asset in release["assets"]}
    pending = []
    for platform in platforms:
        expected = package_names(tag, platform)
        if expected and expected <= existing.keys():
            print(f"{platform}: all packages already published; skipping", flush=True)
        else:
            pending.append(platform)
    runs = ensure_builds(repo, tag, ref, sha, pending)
    upload = []
    for platform, run_id in runs.items():
        destination = directory / platform
        gh("run", "download", run_id, "--repo", repo, "--pattern", "SerialUI-archive-*",
           "--dir", destination)
        packages = sorted(destination.rglob(f"SerialUI-{tag}-*.zip"))
        names = [package.name for package in packages]
        expected = package_names(tag, platform)
        if (expected and set(names) != expected) or len(names) != (len(expected) or 1):
            raise RuntimeError(f"{platform}: unexpected package set: {names}")
        for package in packages:
            with zipfile.ZipFile(package) as archive:
                bad_member = archive.testzip()
                if bad_member:
                    raise RuntimeError(f"Corrupt archive: {package}: {bad_member}")
            print(f"Validated {package.name} ({package.stat().st_size} bytes)", flush=True)
            if package.name in existing:
                if existing[package.name]["size"] != package.stat().st_size:
                    raise RuntimeError(f"Existing release asset has a different size: {package.name}")
                print(f"Already published: {package.name}", flush=True)
            else:
                upload.append(package)
    if len({package.name for package in upload}) != len(upload):
        raise RuntimeError("Duplicate package filenames")
    if upload:
        gh("release", "upload", tag, "--repo", repo, *upload)
    print(f"Uploaded {len(upload)} new packages to release {tag}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--build-ref", default="")
    parser.add_argument("--platforms", default="linux,macos,windows")
    parser.add_argument("--directory", type=Path, default=Path("packages"))
    args = parser.parse_args()
    platforms = list(dict.fromkeys(args.platforms.split(",")))
    publish(args.repo, args.tag, args.build_ref or args.tag, platforms, args.directory)


if __name__ == "__main__":
    main()
