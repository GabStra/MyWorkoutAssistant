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
def test_motion_source_identity_skips_locked_scratch_logs_without_hiding_runtime_changes(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "scripts" / "motion_source_identity.psm1"
    test_repo = tmp_path / "source"
    runtime_dir = test_repo / "exercise_motion_pkg"
    runtime_dir.mkdir(parents=True)
    scratch_dir = test_repo / ".scratch"
    scratch_dir.mkdir()

    def git(*arguments: str) -> None:
        subprocess.run(["git", *arguments], cwd=test_repo, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "motion-test@example.invalid")
    git("config", "user.name", "Motion source identity test")
    shutil.copy2(repo_root / ".gitignore", test_repo / ".gitignore")
    runtime_file = runtime_dir / "runtime.py"
    runtime_file.write_text("VERSION = 1\n", encoding="utf-8")
    tracked_scratch_file = scratch_dir / "tracked_runtime.py"
    tracked_scratch_file.write_text("VALUE = 1\n", encoding="utf-8")
    git("add", ".gitignore", "exercise_motion_pkg/runtime.py")
    git("add", "-f", ".scratch/tracked_runtime.py")
    git("commit", "-m", "base")

    global_ignore_path = tmp_path / "global-ignore"
    global_ignore_path.write_text("/exercise_motion_pkg/generated_secret.py\n", encoding="utf-8")
    script_path = tmp_path / "check_scoped_identity.ps1"
    script_path.write_text(
        r"""$ErrorActionPreference = 'Stop'
Import-Module $env:MOTION_IDENTITY_MODULE -Force
$countBefore = $env:GIT_CONFIG_COUNT
$excludeBefore = [Environment]::GetEnvironmentVariable($env:MOTION_TEST_EXCLUDE_VALUE_NAME, 'Process')
$baseline = Get-MotionSourceIdentity -RepoRoot $env:MOTION_TEST_REPO
$scratchTrackedPath = Join-Path $env:MOTION_TEST_REPO '.scratch/tracked_runtime.py'
Set-Content -LiteralPath $scratchTrackedPath -Value 'VALUE = 2' -Encoding utf8
$scratchIdentity = Get-MotionSourceIdentity -RepoRoot $env:MOTION_TEST_REPO
if ($scratchIdentity.gitTrackedDiffSha256 -eq $baseline.gitTrackedDiffSha256) { throw 'Tracked .scratch source edit was omitted from source identity.' }
Set-Content -LiteralPath (Join-Path $env:MOTION_TEST_REPO 'exercise_motion_pkg/runtime.py') -Value 'VERSION = 2' -Encoding utf8
Set-Content -LiteralPath (Join-Path $env:MOTION_TEST_REPO 'exercise_motion_pkg/new_runtime.py') -Value 'VALUE = 1' -Encoding utf8
$privatePath = Join-Path $env:MOTION_TEST_REPO 'exercise_motion_pkg/generated_secret.py'
Set-Content -LiteralPath $privatePath -Value 'PRIVATE = 1' -Encoding utf8
$scratch = Join-Path $env:MOTION_TEST_REPO '.scratch'
New-Item -ItemType Directory -Path $scratch -Force | Out-Null
$eventPath = Join-Path $scratch 'agent.events.jsonl'
$lock = [System.IO.File]::Open($eventPath, [System.IO.FileMode]::Create, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
try {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes('{"event":"active"}')
    $lock.Write($bytes, 0, $bytes.Length); $lock.Flush()
    $identity = Get-MotionSourceIdentity -RepoRoot $env:MOTION_TEST_REPO
} finally { $lock.Dispose() }
if ($identity.gitTrackedDiffSha256 -eq $baseline.gitTrackedDiffSha256) { throw 'Tracked runtime edit was omitted from source identity.' }
if ($identity.gitTrackedDiffSha256 -eq $scratchIdentity.gitTrackedDiffSha256) { throw 'Additional tracked runtime edit was omitted from source identity.' }
if ($identity.gitUntrackedFileCount -ne 1) { throw "Expected the untracked runtime source to remain included; found $($identity.gitUntrackedFileCount)." }
if ($identity.gitUntrackedContentSha256 -eq $baseline.gitUntrackedContentSha256) { throw 'Untracked runtime source bytes were omitted from source identity.' }
& git -C $env:MOTION_TEST_REPO check-ignore --quiet -- 'exercise_motion_pkg/generated_secret.py'
if ($LASTEXITCODE -ne 0) { throw 'The pre-existing global ignore rule was not preserved.' }
if ($env:GIT_CONFIG_COUNT -ne $countBefore -or [Environment]::GetEnvironmentVariable($env:MOTION_TEST_EXCLUDE_VALUE_NAME, 'Process') -ne $excludeBefore) { throw 'Source identity changed the caller Git ignore configuration.' }
Write-Output ($identity | ConvertTo-Json -Compress)
""",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(
        MOTION_IDENTITY_MODULE=str(module_path),
        MOTION_TEST_REPO=str(test_repo),
    )
    git_config_count = int(environment.get("GIT_CONFIG_COUNT", "0") or "0")
    environment["MOTION_TEST_EXCLUDE_VALUE_NAME"] = f"GIT_CONFIG_VALUE_{git_config_count}"
    environment[f"GIT_CONFIG_KEY_{git_config_count}"] = "core.excludesFile"
    environment[f"GIT_CONFIG_VALUE_{git_config_count}"] = str(global_ignore_path)
    environment["GIT_CONFIG_COUNT"] = str(git_config_count + 1)
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(script_path)],
        cwd=repo_root,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


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
