"""Force-remove Windows paths with restrictive ACLs (e.g. sandboxed pytest temps)."""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import win32api
import win32con
import win32security


def enable_privilege(privilege_name: str) -> None:
    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(),
        win32con.TOKEN_ADJUST_PRIVILEGES | win32con.TOKEN_QUERY,
    )
    privilege_id = win32security.LookupPrivilegeValue(None, privilege_name)
    win32security.AdjustTokenPrivileges(
        token,
        False,
        [(privilege_id, win32con.SE_PRIVILEGE_ENABLED)],
    )
    win32api.CloseHandle(token)


def take_ownership(path: Path) -> None:
    enable_privilege(win32security.SE_TAKE_OWNERSHIP_NAME)
    enable_privilege(win32security.SE_RESTORE_NAME)
    enable_privilege(win32security.SE_BACKUP_NAME)

    sid = win32security.ConvertStringSidToSid("S-1-5-32-544")  # Administrators
    if path.is_dir():
        win32security.SetNamedSecurityInfo(
            str(path),
            win32security.SE_FILE_OBJECT,
            win32security.OWNER_SECURITY_INFORMATION,
            sid,
            None,
            None,
            None,
        )
        dacl = win32security.ACL()
        dacl.AddAccessAllowedAce(
            win32security.ACL_REVISION,
            win32con.FILE_ALL_ACCESS,
            sid,
        )
        win32security.SetNamedSecurityInfo(
            str(path),
            win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
            None,
            None,
            dacl,
            None,
        )
    else:
        win32security.SetFileSecurity(
            str(path),
            win32security.OWNER_SECURITY_INFORMATION,
            win32security.SECURITY_DESCRIPTOR(),
        )


def reset_acl(path: Path) -> None:
    user_principal = f"{os.environ['USERDOMAIN']}\\{os.environ['USERNAME']}"
    grants = ("Administrators:(F)", "SYSTEM:(F)", f"{user_principal}:(F)")
    subprocess.run(
        ["icacls", str(path), "/reset", "/t", "/c"],
        check=False,
        capture_output=True,
        text=True,
    )
    for grant in grants:
        subprocess.run(
            ["icacls", str(path), "/grant:r", grant, "/t", "/c"],
            check=False,
            capture_output=True,
            text=True,
        )


def clear_readonly(path: Path) -> None:
    if path.is_dir():
        for root, dirs, files in os.walk(path, topdown=False, onerror=lambda _: None):
            root_path = Path(root)
            for name in files + dirs:
                child = root_path / name
                try:
                    child.chmod(stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
                except OSError:
                    pass
    try:
        path.chmod(stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
    except OSError:
        pass


def remove_path(path: Path) -> bool:
    if not path.exists():
        return True

    try:
        take_ownership(path)
    except Exception as exc:  # noqa: BLE001
        print(f"  take ownership warning for {path}: {exc}")

    reset_acl(path)
    clear_readonly(path)

    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return not path.exists()
    except OSError as exc:
        print(f"  shutil remove failed for {path}: {exc}")

    subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(path)], check=False)
    return not path.exists()


def collect_targets(repo_root: Path) -> list[Path]:
    patterns = (
        "build",
        ".pytest_tmp",
        "_tmp_*",
        ".pytest_*",
        ".pytest-*",
        ".codex-tmp-*",
        ".tmp-pytest-*",
        "build.protected-stale*",
    )
    targets: list[Path] = []
    seen: set[Path] = set()

    for pattern in patterns:
        for match in repo_root.glob(pattern):
            if match in seen:
                continue
            seen.add(match)
            targets.append(match)

    return sorted(targets, key=lambda p: len(str(p)), reverse=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
    )
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args()

    targets = args.paths or collect_targets(args.repo_root)
    if not targets:
        print("No locked targets found.")
        return 0

    failed: list[Path] = []
    for target in targets:
        print(f"Removing {target} ...")
        if remove_path(target):
            print("  removed")
        else:
            print("  FAILED")
            failed.append(target)

    if failed:
        print("\nFailed to remove:")
        for path in failed:
            print(f"  {path}")
        return 1

    print("\nAll targets removed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
