# Copyright (C) 2026 The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
# /// script
# requires-python = ">=3.12"
# dependencies = ["defusedxml==0.7.1"]
# ///
# Run: uv run --no-project tools/check-source.py [--matrix]
"""Check tracked source packaging without requiring firmware or Android builds."""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Final, override
from urllib.parse import unquote, urlsplit

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring

ROOT: Final = Path(__file__).resolve().parent.parent
INDEX_FIELDS: Final = 4
FORBIDDEN_SUFFIXES: Final = frozenset(
    {".apk", ".img", ".jar", ".so", ".pem", ".pk8", ".bundle", ".bin"},
)
SENSITIVE_PATTERNS: Final = (
    r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----",
    r"gh[pousr]_[A-Za-z0-9]{20,}",
    r"/home/(?!runner/)[A-Za-z0-9_.-]+/",
    r"192\.168\.\d{1,3}\.\d{1,3}",
)
SENSITIVE: Final = re.compile("|".join(SENSITIVE_PATTERNS))


@dataclass(frozen=True, slots=True)
class SourceCheckError(Exception):
    """Report packaging failures without printing sensitive matching content."""

    issues: tuple[str, ...]

    @override
    def __str__(self) -> str:
        """Format the collected file-level errors."""
        return "\n".join(self.issues)


@dataclass(frozen=True, slots=True)
class PatchSeries:
    """One pinned upstream project and its local patch directory."""

    project: str
    name: str
    base: str
    url: str


def read_series() -> tuple[PatchSeries, ...]:
    """Parse the index once before using it as workflow matrix input."""
    rows: list[PatchSeries] = []
    for number, line in enumerate(
        (ROOT / "patches/BASES.tsv").read_text().splitlines(), start=1,
    ):
        fields = line.split("\t")
        if len(fields) != INDEX_FIELDS:
            raise SourceCheckError(
                (f"BASES.tsv:{number}: expected four tab-separated fields",),
            )
        project, name, base, url = fields
        source = urlsplit(url)
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_.-]+)*", project)
            or any(part in {".", ".."} for part in project.split("/"))
            or not re.fullmatch(r"[A-Za-z0-9_-]+", name)
            or not re.fullmatch(r"[0-9a-f]{40}", base)
            or source.scheme != "https"
            or source.netloc not in {"github.com", "android.googlesource.com"}
            or source.query
            or source.fragment
        ):
            raise SourceCheckError(
                (f"BASES.tsv:{number}: invalid path, base or upstream URL",),
            )
        if not tuple((ROOT / "patches" / name).glob("*.patch")):
            raise SourceCheckError((f"{name}: no active patches",))
        rows.append(PatchSeries(project, name, base, url))
    if not rows or len({r.project for r in rows}) != len(rows):
        raise SourceCheckError(("BASES.tsv: empty index or duplicate project",))
    if len({r.name for r in rows}) != len(rows):
        raise SourceCheckError(("BASES.tsv: duplicate patch directory",))
    return tuple(rows)


def syntax_issues(path: Path, text: str) -> tuple[str, ...]:
    """Parse source formats without expanding XML entities."""
    issues: list[str] = []
    if path.suffix == ".xml":
        try:
            _ = fromstring(text, forbid_dtd=True)
        except (ET.ParseError, DefusedXmlException) as exc:
            issues.append(f"{path.relative_to(ROOT)}: invalid XML: {exc}")
    if path.suffix == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            issues.append(f"{path.relative_to(ROOT)}: invalid JSON: {exc}")
    if path.suffix == ".py":
        try:
            _ = ast.parse(text, filename=str(path.relative_to(ROOT)))
        except SyntaxError as exc:
            issues.append(f"{path.relative_to(ROOT)}: invalid Python: {exc}")
    return tuple(issues)


def source_issues(name: str) -> tuple[str, ...]:
    """Inspect one tracked payload and its local references."""
    path = ROOT / name
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        return (f"{name}: excluded binary or key payload",)
    if path.is_symlink():
        return (f"{name}: tracked symlink requires an explicit source audit",)
    text = path.read_text()
    issues = list(syntax_issues(path, text))
    if SENSITIVE.search(text):
        issues.append(f"{name}: private path, address, token or key marker")
    if path.suffix == ".sh":
        result = subprocess.run(
            ["/bin/bash", "-n"],
            input=text, capture_output=True, text=True, check=False,
        )
        if result.returncode:
            issues.append(f"{name}: invalid shell syntax: {result.stderr.strip()}")
    if path.suffix == ".md":
        for link in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", text):
            target = urlsplit(link.group(1))
            if target.scheme or not target.path:
                continue
            if not (path.parent / unquote(target.path)).exists():
                issues.append(f"{name}: missing link target {target.path}")
    return tuple(issues)


def check_sources() -> None:
    """Check tracked files and index coverage without modifying the tree."""
    series = read_series()
    tracked = subprocess.check_output(
        ["/usr/bin/git", "ls-files", "-z"], cwd=ROOT,
    ).decode().rstrip("\0").split("\0")
    issues: list[str] = []
    for name in tracked:
        issues.extend(source_issues(name))
    indexed = {r.name for r in series}
    issues.extend(
        f"{patch.relative_to(ROOT)}: patch directory missing from index"
        for patch in (ROOT / "patches").glob("*/*.patch")
        if patch.parent.name not in indexed
    )
    if issues:
        raise SourceCheckError(tuple(issues))
    _ = sys.stdout.write(
        f"PASS: {len(tracked)} tracked files; {len(series)} indexed patch series\n",
    )


def main() -> int:
    """Run source checks or emit the validated GitHub matrix."""
    try:
        if sys.argv[1:] == ["--matrix"]:
            _ = sys.stdout.write(
                json.dumps({"project": [row.name for row in read_series()]}) + "\n",
            )
            return 0
        if sys.argv[1:]:
            _ = sys.stderr.write("Usage: check-source.py [--matrix]\n")
            return 2
        check_sources()
    except SourceCheckError as exc:
        _ = sys.stderr.write(f"{exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
