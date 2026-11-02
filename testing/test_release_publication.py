import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import publish_release_assets as publisher


class ReleaseBuildTests(unittest.TestCase):
    def test_successful_build_with_current_archives_is_reusable(self):
        run = dict(id=42, head_sha="sha", head_branch="1.5.9", conclusion="success", status="completed")
        artifacts = {"artifacts": [dict(name="SerialUI-archive-macos", expired=False)]}
        with patch.object(publisher, "gh_json", side_effect=[{"workflow_runs": [run]}, artifacts]):
            self.assertEqual(publisher.find_build("owner/repo", "build-macos.yml", "1.5.9", "sha", 1),
                             (42, False, []))

    def test_reuses_queued_and_successful_tag_builds_without_dispatch(self):
        with patch.object(publisher, "find_build", side_effect=[
            (None, True, []), (42, False, []),
        ]), patch.object(publisher, "gh") as gh, patch.object(publisher.time, "sleep"):
            self.assertEqual(publisher.ensure_builds(
                "owner/repo", "1.5.9", "1.5.9", "sha", ["linux"]), {"linux": 42})
        gh.assert_not_called()

    def test_waits_for_tag_run_to_appear_before_dispatching(self):
        with patch.object(publisher, "find_build", side_effect=[
            (None, False, []), (42, False, []),
        ]), patch.object(publisher, "gh") as gh, patch.object(publisher.time, "sleep"), \
                patch.object(publisher.time, "monotonic", return_value=10):
            publisher.ensure_builds("owner/repo", "1.5.9", "1.5.9", "sha", ["linux"])
        gh.assert_not_called()

    def test_missing_build_dispatched_once_even_if_not_immediately_visible(self):
        with patch.object(publisher, "find_build", side_effect=[
            (None, False, []), (None, False, []), (None, True, []), (42, False, []),
        ]), patch.object(publisher, "gh") as gh, patch.object(publisher.time, "sleep"):
            publisher.ensure_builds("owner/repo", "1.5.9", "1.5.9", "sha", ["linux"],
                                    grace_seconds=0)
        gh.assert_called_once_with("workflow", "run", "build-linux.yml",
                                   "--repo", "owner/repo", "--ref", "1.5.9")

    def test_failed_build_stops_instead_of_dispatching_duplicate(self):
        with patch.object(publisher, "find_build", return_value=(None, False, [42])), \
                patch.object(publisher, "gh") as gh:
            with self.assertRaisesRegex(RuntimeError, "failed or was cancelled"):
                publisher.ensure_builds("owner/repo", "1.5.9", "1.5.9", "sha", ["linux"])
        gh.assert_not_called()

    def test_stuck_build_times_out_without_dispatching(self):
        with patch.object(publisher, "find_build", return_value=(None, True, [])), \
                patch.object(publisher, "gh") as gh:
            with self.assertRaisesRegex(RuntimeError, "Timed out"):
                publisher.ensure_builds("owner/repo", "1.5.9", "1.5.9", "sha", ["linux"],
                                        timeout_seconds=0)
        gh.assert_not_called()

    def test_wrong_commit_ignored_and_expired_artifacts_are_not_reused(self):
        runs = [
            dict(id=1, head_sha="other", head_branch="1.5.9", conclusion="success", status="completed"),
            dict(id=2, head_sha="sha", head_branch="1.5.9", conclusion="success", status="completed"),
        ]
        expired = {"artifacts": [dict(name="SerialUI-archive-test", expired=True)]}
        with patch.object(publisher, "gh_json", side_effect=[{"workflow_runs": runs}, expired]) as api:
            self.assertEqual(publisher.find_build("owner/repo", "build-macos.yml", "1.5.9", "sha", 1),
                             (None, False, []))
        self.assertIn("/runs/2/artifacts", api.call_args.args[1])


class ReleaseUploadTests(unittest.TestCase):
    def test_ref_must_match_release_commit(self):
        with patch.object(publisher, "gh_json", side_effect=[{"sha": "release"}, {"sha": "other"}]), \
                patch.object(publisher, "gh") as gh:
            with self.assertRaisesRegex(ValueError, "must point to release"):
                publisher.publish("owner/repo", "1.5.9", "main", ["linux"], Path("unused"))
        gh.assert_not_called()

    def test_complete_release_needs_no_builds_downloads_or_uploads(self):
        assets = [{"name": name, "size": 1} for platform in ("linux", "macos", "windows")
                  for name in publisher.package_names("1.5.9", platform)]
        with patch.object(publisher, "gh_json", side_effect=[
            {"sha": "release"}, {"sha": "release"}, {"assets": assets},
        ]), patch.object(publisher, "gh") as gh, patch.object(publisher, "find_build") as builds:
            publisher.publish("owner/repo", "1.5.9", "1.5.9", ["linux", "macos", "windows"],
                              Path("unused"))
        gh.assert_not_called()
        builds.assert_not_called()

    def test_partial_release_validates_archives_and_uploads_only_missing_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "windows"
            directory.mkdir()
            for name in publisher.package_names("1.5.9", "windows"):
                with zipfile.ZipFile(directory / name, "w") as archive:
                    archive.writestr("SerialUI.exe", b"test executable")
            existing = directory / "SerialUI-1.5.9-windows-amd64.zip"
            assets = [{"name": existing.name, "size": existing.stat().st_size}]
            with patch.object(publisher, "gh_json", side_effect=[
                {"sha": "release"}, {"sha": "release"}, {"assets": assets},
            ]), patch.object(publisher, "ensure_builds", return_value={"windows": 42}), \
                    patch.object(publisher, "gh") as gh:
                publisher.publish("owner/repo", "1.5.9", "1.5.9", ["windows"], root)
            self.assertEqual(gh.call_args.args,
                             ("release", "upload", "1.5.9", "--repo", "owner/repo",
                              directory / "SerialUI-1.5.9-windows-arm64.zip"))

    def test_invalid_archive_is_never_uploaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "macos").mkdir()
            (root / "macos" / "SerialUI-1.5.9-macos-arm64.zip").write_bytes(b"broken zip")
            with patch.object(publisher, "gh_json", side_effect=[
                {"sha": "release"}, {"sha": "release"}, {"assets": []},
            ]), patch.object(publisher, "ensure_builds", return_value={"macos": 42}), \
                    patch.object(publisher, "gh") as gh:
                with self.assertRaises(zipfile.BadZipFile):
                    publisher.publish("owner/repo", "1.5.9", "1.5.9", ["macos"], root)
            self.assertEqual(gh.call_count, 1)  # Download only.


class ReleaseScriptTests(unittest.TestCase):
    def test_existing_tag_dispatches_only_publisher_and_watches_exact_run(self):
        source = Path(__file__).resolve().parents[1] / "scripts" / "build_release_all.sh"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "scripts" / source.name).write_text(source.read_text())
            (root / "config.py").write_text('VERSION = "1.5.9"\n')
            (root / "scripts" / "release.sh").write_text('echo "release $*"\n')
            bin_dir = root / "bin"
            bin_dir.mkdir()
            (bin_dir / "git").write_text('#!/bin/bash\nexit 0\n')
            (bin_dir / "gh").write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
state = pathlib.Path(__file__).parent / 'state.json'
if args[:2] == ['auth', 'status'] or args[0] == 'api':
    pass
elif args[:2] == ['repo', 'view']:
    print('owner/repo' if 'nameWithOwner' in args else 'main')
elif args[:2] == ['workflow', 'run']:
    assert args[2] == 'publish-release-assets.yml', args
    inputs = dict(value.split('=', 1) for value in args if '=' in value)
    assert inputs['platforms'] == 'linux,windows', inputs
    state.write_text(json.dumps(inputs))
elif args[:2] == ['run', 'list']:
    inputs = json.loads(state.read_text())
    print(json.dumps([{'databaseId': 999, 'displayTitle': 'Unrelated run'},
                      {'databaseId': 42, 'displayTitle': f"Publish release {inputs['tag']} ({inputs['request_id']})"}]))
elif args[:2] == ['run', 'watch']:
    assert args[2] == '42' and '--exit-status' in args, args
    raise SystemExit(int(os.environ.get('FAKE_WATCH_EXIT', '0')))
elif args[:2] == ['release', 'view']:
    print('https://example.test/release/1.5.9')
else:
    raise SystemExit(f'Unexpected gh operation: {args}')
''')
            for executable in bin_dir.iterdir():
                executable.chmod(0o755)
            result = subprocess.run(['bash', str(root / 'scripts' / source.name), '--skip-macos'],
                                    env={**os.environ, 'PATH': f'{bin_dir}:{os.environ["PATH"]}'},
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((root / 'dist').exists())

            failed = subprocess.run(['bash', str(root / 'scripts' / source.name), '--skip-macos'],
                                    env={**os.environ, 'PATH': f'{bin_dir}:{os.environ["PATH"]}',
                                         'FAKE_WATCH_EXIT': '1'}, text=True, capture_output=True)
            self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
            self.assertNotIn('Done.', failed.stdout)


if __name__ == "__main__":
    unittest.main()
