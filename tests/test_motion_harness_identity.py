import subprocess
import sys

import pytest

from scripts import build_motion_fixed_fixtures, motion_speed_harness


def _git(repo, *arguments):
    return subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_run_identity_covers_tracked_and_untracked_worktree_content(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Motion test")
    tracked_path = repo / "pipeline.py"
    tracked_path.write_text("base\n", encoding="utf-8")
    _git(repo, "add", "pipeline.py")
    _git(repo, "commit", "-m", "base")

    monkeypatch.setattr(motion_speed_harness, "REPO_ROOT", repo)
    monkeypatch.setattr(motion_speed_harness, "resolve_motion_python", lambda: sys.executable)
    clean_identity = motion_speed_harness.capture_run_identity()
    assert clean_identity["gitWorktreeClean"] is True
    assert clean_identity["gitUntrackedFileCount"] == 0

    tracked_path.write_text("staged\n", encoding="utf-8")
    _git(repo, "add", "pipeline.py")
    tracked_path.write_text("worktree\n", encoding="utf-8")
    untracked_path = repo / "new_module.py"
    untracked_path.write_text("first version\n", encoding="utf-8")
    changed_identity = motion_speed_harness.capture_run_identity()

    assert changed_identity["gitCommit"] == clean_identity["gitCommit"]
    assert changed_identity["gitDiffSha256"] != clean_identity["gitDiffSha256"]
    assert changed_identity["gitUntrackedFileCount"] == 1
    assert changed_identity["gitUntrackedContentSha256"] != clean_identity["gitUntrackedContentSha256"]
    assert changed_identity["gitWorktreeClean"] is False

    untracked_path.write_text("second version\n", encoding="utf-8")
    changed_untracked_identity = motion_speed_harness.capture_run_identity()
    assert changed_untracked_identity["gitDiffSha256"] == changed_identity["gitDiffSha256"]
    assert changed_untracked_identity["gitUntrackedContentSha256"] != changed_identity["gitUntrackedContentSha256"]


def test_fixture_builder_falls_back_to_embedded_contract_without_retained_artifact_identity(
    tmp_path,
):
    retained = tmp_path / "base" / "dumbbell-upright-row" / "selected"
    retained.mkdir(parents=True)
    (retained / "revalidation.json").write_text(
        '{"status":"valid","selectionValidationPolicyVersion":119}',
        encoding="utf-8",
    )
    contract = {"schemaVersion": 1, "movementType": "repetition"}
    destination = tmp_path / "fixture" / "contract.json"

    _, contract_sha = build_motion_fixed_fixtures.resolve_contract(
        tmp_path / "base",
        "dumbbell-upright-row",
        tmp_path / "contract-cache",
        {"visionPayload": {"exerciseMotionContract": contract}},
        destination,
    )

    assert destination.is_file()
    assert build_motion_fixed_fixtures.sha256_file(destination) == contract_sha
    assert destination.read_text(encoding="utf-8").strip() == (
        '{\n "schemaVersion": 1,\n "movementType": "repetition"\n}'
    )


def test_fixture_builder_preserves_existing_output_directory(tmp_path, monkeypatch):
    output_dir = tmp_path / "retained-fixtures"
    output_dir.mkdir()
    evidence = output_dir / "fixture_manifest.json"
    evidence.write_text('{"retained": true}\n', encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["build_motion_fixed_fixtures.py", "--output-dir", str(output_dir)],
    )

    with pytest.raises(SystemExit, match="--output-dir already exists and was preserved"):
        build_motion_fixed_fixtures.main()

    assert evidence.read_text(encoding="utf-8") == '{"retained": true}\n'
