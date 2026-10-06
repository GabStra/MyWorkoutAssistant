from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell identity module requires Windows pwsh")
def test_motion_source_identity_requires_a_clean_committed_tree_unless_explicitly_overridden(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "scripts" / "motion_source_identity.psm1"
    test_repo = tmp_path / "source"
    test_repo.mkdir()

    def git(*arguments: str) -> None:
        subprocess.run(["git", *arguments], cwd=test_repo, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "motion-test@example.invalid")
    git("config", "user.name", "Motion source identity test")
    tracked_file = test_repo / "runtime.py"
    tracked_file.write_text("committed runtime\n", encoding="utf-8")
    git("add", "runtime.py")
    git("commit", "-m", "base")

    script_path = tmp_path / "check_identity.ps1"
    script_path.write_text(
        """param([string]$RepoRoot, [string]$ModulePath, [switch]$AllowDirty, [switch]$ExpectRejected)
Import-Module $ModulePath -Force
$identity = Get-MotionSourceIdentity -RepoRoot $RepoRoot
$rejected = $false
try {
    Assert-MotionSourceIdentity -Identity $identity -AllowDirtyWorktree:$AllowDirty
} catch {
    $rejected = $true
}
if ($rejected -ne [bool]$ExpectRejected) { exit 2 }
Write-Output ($identity | ConvertTo-Json -Compress)
""",
        encoding="utf-8",
    )

    def check(*extra: str, rejected: bool) -> dict:
        result = subprocess.run(
            [
                "pwsh", "-NoProfile", "-File", str(script_path),
                "-RepoRoot", str(test_repo),
                "-ModulePath", str(module_path),
                *extra,
                *( ["-ExpectRejected"] if rejected else [] ),
            ],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        import json

        return json.loads(result.stdout.strip().splitlines()[-1])

    clean_identity = check(rejected=False)
    assert clean_identity["gitWorktreeClean"] is True
    assert clean_identity["gitCommit"]

    tracked_file.write_text("unstaged runtime\n", encoding="utf-8")
    assert check(rejected=True)["gitWorktreeClean"] is False
    git("add", "runtime.py")
    assert check(rejected=True)["gitWorktreeClean"] is False

    untracked_file = test_repo / "new_runtime.py"
    untracked_file.write_text("untracked runtime\n", encoding="utf-8")
    dirty_identity = check("-AllowDirty", rejected=False)
    assert dirty_identity["gitWorktreeClean"] is False
    assert dirty_identity["gitUntrackedFileCount"] == 1
    assert dirty_identity["gitUntrackedContentSha256"] != clean_identity["gitUntrackedContentSha256"]

    untracked_file.write_text("changed untracked runtime\n", encoding="utf-8")
    changed_identity = check("-AllowDirty", rejected=False)
    assert changed_identity["gitUntrackedContentSha256"] != dirty_identity["gitUntrackedContentSha256"]


@pytest.mark.skipif(os.name != "nt" or shutil.which("pwsh") is None, reason="PowerShell identity module requires Windows pwsh")
def test_motion_source_identity_hashes_tracked_and_untracked_submodule_bytes(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "scripts" / "motion_source_identity.psm1"
    upstream = tmp_path / "submodule-source"
    upstream.mkdir()
    test_repo = tmp_path / "source"
    test_repo.mkdir()

    def git(cwd: Path, *arguments: str) -> None:
        subprocess.run(["git", *arguments], cwd=cwd, check=True, capture_output=True)

    for path in (upstream, test_repo):
        git(path, "init", "-q")
        git(path, "config", "user.email", "motion-test@example.invalid")
        git(path, "config", "user.name", "Motion source identity test")
    runtime_file = upstream / "worker.py"
    runtime_file.write_text("VERSION = 'one'\n", encoding="utf-8")
    git(upstream, "add", "worker.py")
    git(upstream, "commit", "-m", "submodule base")
    git(test_repo, "-c", "protocol.file.allow=always", "submodule", "add", str(upstream), "third_party/worker")
    git(test_repo, "commit", "-m", "add worker submodule")

    script_path = tmp_path / "read_identity.ps1"
    script_path.write_text(
        """param([string]$RepoRoot, [string]$ModulePath)
Import-Module $ModulePath -Force
$identity = Get-MotionSourceIdentity -RepoRoot $RepoRoot
Write-Output ($identity | ConvertTo-Json -Compress)
""",
        encoding="utf-8",
    )

    def identity() -> dict:
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(script_path), "-RepoRoot", str(test_repo), "-ModulePath", str(module_path)],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        import json

        return json.loads(result.stdout.strip().splitlines()[-1])

    initial_identity = identity()
    runtime_file = test_repo / "third_party" / "worker" / "worker.py"
    runtime_file.write_text("VERSION = 'two'\n", encoding="utf-8")
    tracked_change_identity = identity()
    assert tracked_change_identity["gitSubmoduleWorktreeSha256"] != initial_identity["gitSubmoduleWorktreeSha256"]

    untracked_file = test_repo / "third_party" / "worker" / "extra.py"
    untracked_file.write_text("VALUE = 1\n", encoding="utf-8")
    untracked_change_identity = identity()
    assert untracked_change_identity["gitSubmoduleWorktreeSha256"] != tracked_change_identity["gitSubmoduleWorktreeSha256"]
