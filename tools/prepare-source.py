#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Create an independent pinned repo checkout using only a local source cache.

Git objects are shared through alternates; worktrees and build outputs are not.
Missing projects are reported before the destination is created. Network Git
transports are disabled, and repo sync runs in local-only mode. Git LFS inputs
are verified from local object storage or matching reference files before any
checkout is created, then copied independently without running a download.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


def run(command: list[str], *, cwd: Path | None = None, env: dict | None = None) -> str:
    return subprocess.check_output(command, cwd=cwd, env=env, text=True).strip()


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def local_lfs_files(reference: Path, projects: list[ET.Element],
                    cache_gitdirs: dict[str, Path], env: dict, jobs: int) -> list[dict]:
    """Resolve pinned LFS objects without fetch/pull/smudge or dirty-file copying."""
    run(["git", "lfs", "version"], env=env)

    def inspect(project: ET.Element) -> list[dict]:
        project_path = project.get("path", project.get("name", ""))
        gitdir = cache_gitdirs[project_path]
        prefix = ["git", f"--git-dir={gitdir}", "lfs"]
        entries = json.loads(run([*prefix, "ls-files", "--json", project.get("revision", "")], env=env))["files"]
        if not entries:
            return []
        # Vendored test fixtures can contain literal LFS pointers without being
        # LFS-managed in this repository. Honor the pinned tree's attributes;
        # matching the pointer syntax alone must not rewrite ordinary source.
        attributes = run(["git", f"--git-dir={gitdir}", "-c", "core.attributesFile=/dev/null",
                          "check-attr", f"--source={project.get('revision', '')}", "-z", "filter",
                          "--", *[entry["name"] for entry in entries]], env=env).split("\0")
        if len(attributes) % 3 != 1 or attributes[-1] != "":
            raise ValueError(f"Invalid pinned Git attribute output: {project_path}")
        filters = {attributes[i]: attributes[i + 2] for i in range(0, len(attributes) - 1, 3)}
        entries = [entry for entry in entries if filters.get(entry["name"]) == "lfs"]
        if not entries:
            return []
        settings = run([*prefix, "env"], env=env).splitlines()
        media = Path(next(line.split("=", 1)[1] for line in settings if line.startswith("LocalMediaDir=")))
        if not media.is_absolute():
            raise ValueError(f"Git LFS cache path must be absolute: {project_path}")
        resolved = []
        for entry in entries:
            name, oid, size = entry["name"], entry["oid"], entry["size"]
            if (not name or Path(name).is_absolute() or ".." in Path(name).parts
                    or entry.get("oid_type") != "sha256" or not re.fullmatch(r"[0-9a-f]{64}", oid)
                    or not isinstance(size, int) or size < 0):
                raise ValueError(f"Invalid pinned LFS input: {project_path}/{name}")
            candidates = [media / oid[:2] / oid[2:4] / oid, reference / project_path / name]
            for candidate in candidates:
                if (candidate.is_file() and not candidate.is_symlink()
                        and candidate.stat().st_size == size and file_sha256(candidate) == oid):
                    resolved.append({"project": project_path, "path": name, "sha256": oid,
                                     "size": size, "local_source": str(candidate)})
                    break
            else:
                raise ValueError(f"Missing verified local LFS object: {project_path}/{name} "
                                 f"sha256={oid} size={size}; no network fallback")
        return resolved

    with ThreadPoolExecutor(max_workers=jobs) as executor:
        return [entry for entries in executor.map(inspect, projects) for entry in entries]


def hydrate_local_lfs(destination: Path, inputs: list[dict]) -> list[dict]:
    """Replace only matching LFS pointers with independent, reverified files."""
    hydrated = []
    for entry in inputs:
        target = destination / entry["project"] / entry["path"]
        if (not target.is_file() or target.is_symlink()
                or not target.resolve().is_relative_to(destination.resolve())):
            raise ValueError(f"LFS destination must be a regular checkout file: {target}")
        if target.stat().st_size == entry["size"] and file_sha256(target) == entry["sha256"]:
            hydrated.append({**entry, "destination": str(target), "already_present": True})
            continue
        if target.stat().st_size > 1024:
            raise ValueError(f"Refusing to overwrite non-pointer LFS destination: {target}")
        pointer = target.read_text()
        if (not pointer.startswith("version https://git-lfs.github.com/spec/v1\n")
                or f"oid sha256:{entry['sha256']}\n" not in pointer
                or f"size {entry['size']}\n" not in pointer):
            raise ValueError(f"LFS checkout pointer differs from pinned input: {target}")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(prefix=".rothko-lfs-", dir=target.parent, delete=False) as stream:
                temporary = Path(stream.name)
            shutil.copyfile(entry["local_source"], temporary)
            if temporary.stat().st_size != entry["size"] or file_sha256(temporary) != entry["sha256"]:
                raise ValueError(f"Local LFS input changed while copying: {target}")
            shutil.copymode(target, temporary)
            temporary.replace(target)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        hydrated.append({**entry, "destination": str(target), "already_present": False})
    return hydrated


def prepare(reference: Path, manifest: Path, destination: Path, jobs: int) -> dict:
    env = os.environ.copy()
    env.update(GIT_ALLOW_PROTOCOL="file", GIT_TERMINAL_PROMPT="0",
               GIT_NO_LAZY_FETCH="1", REPO_SKIP_SELF_UPDATE="1", GIT_LFS_SKIP_SMUDGE="1")
    if destination.exists():
        raise ValueError("destination must not exist")
    projects = ET.parse(manifest).getroot().findall("project")
    if not projects:
        raise ValueError("manifest contains no projects")
    cache_gitdirs: dict[str, Path] = {}

    def locate(project: ET.Element) -> tuple[str, Path]:
        path = project.get("path", project.get("name", ""))
        revision = project.get("revision", "")
        if not path or Path(path).is_absolute() or ".." in Path(path).parts:
            raise ValueError("invalid project path")
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError(f"project is not pinned to a commit: {path}")
        gitdir = reference / ".repo/projects" / f"{path}.git"
        if not gitdir.is_dir():
            gitdir = Path(run(["git", "-C", str(reference / path), "rev-parse", "--absolute-git-dir"], env=env))
        subprocess.run(["git", f"--git-dir={gitdir}", "cat-file", "-e", f"{revision}^{{commit}}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, env=env)
        return path, gitdir

    with ThreadPoolExecutor(max_workers=jobs) as executor:
        for path, gitdir in executor.map(locate, projects):
            cache_gitdirs[path] = gitdir
    lfs_inputs = local_lfs_files(reference, projects, cache_gitdirs, env, jobs)
    repo_source = reference / ".repo/repo"
    repo_revision = run(["git", "-C", str(repo_source), "rev-parse", "HEAD"], env=env)
    if run(["git", "-C", str(repo_source), "status", "--porcelain"], env=env):
        raise ValueError("repo tool cache must be clean")
    destination.mkdir(parents=True)
    metadata = destination / ".repo"
    metadata.mkdir()
    shutil.copytree(repo_source, metadata / "repo", symlinks=True)
    frozen = metadata / "frozen-manifest"
    frozen.mkdir()
    shutil.copyfile(manifest, frozen / "default.xml")
    run(["git", "init", "-q", "-b", "main", str(frozen)], env=env)
    run(["git", "-C", str(frozen), "add", "default.xml"], env=env)
    run(["git", "-C", str(frozen), "-c", "user.name=Source bootstrap",
         "-c", "user.email=build@localhost", "commit", "-q", "-m", "Freeze local manifest"], env=env)
    launcher = str(metadata / "repo/repo")
    run([launcher, "init", "-u", frozen.as_uri(), "-b", "main", "-m", "default.xml",
         "--reference", str(reference), "--repo-url", repo_source.as_uri(),
         "--no-clone-bundle", "--no-use-superproject", "-g", "all"], cwd=destination, env=env)

    # repo's local checkout phase requires metadata normally initialized by its
    # fetch phase. Initialize it using the cached repo implementation, then set
    # explicit local object alternates instead of contacting an upstream remote.
    sys.path.insert(0, str(metadata / "repo"))
    from manifest_xml import RepoClient

    client = RepoClient(str(metadata))
    for project in client.projects:
        project._InitGitDir(quiet=True)
        cached = cache_gitdirs[project.relpath]
        (Path(project.objdir) / "objects/info/alternates").write_text(str((cached / "objects").resolve()) + "\n")
        shallow = cached / "shallow"
        if shallow.is_file():
            shutil.copyfile(shallow, Path(project.gitdir) / "shallow")
    run([launcher, "sync", "--local-only", "--no-manifest-update", "--no-auto-gc",
         "--fail-fast", "-j", str(jobs)], cwd=destination, env=env)
    lfs_files = hydrate_local_lfs(destination, lfs_inputs)
    result = {
        "projects": len(projects), "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "repo_revision": repo_revision, "network_fetch": False, "old_output_reused": False,
        "reference": str(reference), "destination": str(destination),
        "lfs_files": lfs_files, "lfs_network_fetch": False,
    }
    (metadata / "source-preparation.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).parent / "manifests/platform.xml")
    parser.add_argument("--jobs", type=int, choices=range(1, 17), default=16)
    args = parser.parse_args()
    try:
        result = prepare(args.reference.resolve(), args.manifest.resolve(), args.destination.resolve(), args.jobs)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"SOURCE_PREPARATION_ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
