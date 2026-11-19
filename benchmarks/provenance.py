"""Source and runtime provenance helpers for frozen benchmark cohorts."""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _git_snapshot(root: Path) -> dict[str, object]:
    commit = _git(root, "rev-parse", "HEAD")
    branch = _git(root, "branch", "--show-current")
    remote_url = _git(root, "remote", "get-url", "origin")
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    diff = _git(root, "diff", "HEAD", "--binary")
    untracked_raw = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    untracked_hashes: dict[str, str] = {}
    if untracked_raw:
        for relative in (item for item in untracked_raw.split("\0") if item):
            candidate = root / relative
            if candidate.is_file():
                untracked_hashes[relative] = sha256_file(candidate)
    available = commit is not None
    status_text = status or ""
    diff_bytes = (diff or "").encode("utf-8")
    return {
        "available": available,
        "commit_sha": commit.strip() if commit else None,
        "branch": branch.strip() if branch else None,
        "remote_url": remote_url.strip() if remote_url else None,
        "dirty_worktree": bool(status_text.strip()) if available else None,
        "status_porcelain": status_text.splitlines() if available else None,
        "status_sha256": hashlib.sha256(status_text.encode("utf-8")).hexdigest()
        if available else None,
        "tracked_diff_sha256": hashlib.sha256(diff_bytes).hexdigest()
        if available else None,
        "untracked_file_sha256": untracked_hashes if available else None,
    }


def capture_source_manifest(
    root: str | Path,
    source_files: Iterable[str],
) -> dict[str, object]:
    """Capture exact source-file hashes, Git state, and installed package versions.

    The manifest is intentionally independent of the current benchmark output
    directory. Callers should write it beside the frozen cohort lock and store
    the resulting file SHA-256 in that lock.
    """
    root_path = Path(root).resolve()
    source_hashes: dict[str, str] = {}
    for relative in sorted(set(source_files)):
        path = root_path / relative
        if not path.is_file():
            raise FileNotFoundError(f"required source file is missing: {relative}")
        source_hashes[relative] = sha256_file(path)

    package_versions = sorted(
        f"{distribution.metadata.get('Name', 'unknown')}=={distribution.version}"
        for distribution in importlib.metadata.distributions()
    )
    package_snapshot = "\n".join(package_versions) + "\n"

    lock_names = (
        "uv.lock",
        "poetry.lock",
        "Pipfile.lock",
        "requirements.lock",
        "requirements.txt",
        "conda-lock.yml",
    )
    lock_hashes = {
        name: sha256_file(root_path / name)
        for name in lock_names
        if (root_path / name).is_file()
    }
    declaration_names = ("pyproject.toml", "setup.cfg", "setup.py")
    declaration_hashes = {
        name: sha256_file(root_path / name)
        for name in declaration_names
        if (root_path / name).is_file()
    }

    return {
        "schema_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository_root": ".",
        "source_files_sha256": source_hashes,
        "git": _git_snapshot(root_path),
        "environment": {
            "python_version": sys.version,
            "python_executable_name": Path(sys.executable).name,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "os_name": os.name,
            "package_versions": package_versions,
            "package_versions_sha256": hashlib.sha256(
                package_snapshot.encode("utf-8")
            ).hexdigest(),
            "dependency_lock_files_sha256": lock_hashes,
            "dependency_declaration_files_sha256": declaration_hashes,
        },
    }


def verify_source_manifest(
    root: str | Path,
    manifest: dict[str, object],
) -> list[str]:
    """Return all missing or changed source paths; an empty list means verified."""
    root_path = Path(root).resolve()
    source_hashes = manifest.get("source_files_sha256")
    if not isinstance(source_hashes, dict):
        raise ValueError("source manifest has no source_files_sha256 mapping")
    mismatches: list[str] = []
    for relative, expected in sorted(source_hashes.items()):
        path = (root_path / str(relative)).resolve()
        if not path.is_relative_to(root_path):
            mismatches.append(f"unsafe-path:{relative}")
        elif not path.is_file():
            mismatches.append(f"missing:{relative}")
        elif sha256_file(path) != expected:
            mismatches.append(f"changed:{relative}")

    environment = manifest.get("environment")
    if not isinstance(environment, dict):
        raise ValueError("source manifest has no environment mapping")

    current_packages = sorted(
        f"{distribution.metadata.get('Name', 'unknown')}=={distribution.version}"
        for distribution in importlib.metadata.distributions()
    )
    package_snapshot = "\n".join(current_packages) + "\n"
    current_package_sha = hashlib.sha256(
        package_snapshot.encode("utf-8")
    ).hexdigest()
    if current_package_sha != environment.get("package_versions_sha256"):
        mismatches.append("environment:package_versions")
    if sys.version != environment.get("python_version"):
        mismatches.append("environment:python_version")
    if platform.platform() != environment.get("platform"):
        mismatches.append("environment:platform")
    if platform.machine() != environment.get("machine"):
        mismatches.append("environment:machine")
    if platform.processor() != environment.get("processor"):
        mismatches.append("environment:processor")
    if os.name != environment.get("os_name"):
        mismatches.append("environment:os_name")

    for category in (
        "dependency_lock_files_sha256",
        "dependency_declaration_files_sha256",
    ):
        expected_files = environment.get(category, {})
        if not isinstance(expected_files, dict):
            raise ValueError(f"source manifest has invalid {category}")
        for relative, expected in sorted(expected_files.items()):
            path = (root_path / str(relative)).resolve()
            if not path.is_relative_to(root_path):
                mismatches.append(f"unsafe-path:{relative}")
            elif not path.is_file():
                mismatches.append(f"missing:{relative}")
            elif sha256_file(path) != expected:
                mismatches.append(f"changed:{relative}")

    return mismatches
