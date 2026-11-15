#!/usr/bin/env python3
"""Remove one reviewed allow line from vendor_sepolicy.cil as text only.

Only the exact frozen source hash, single-line statement, and candidate hash
are accepted. No CIL compiler, image build, installation, or target execution
is performed. rc 0 means only the byte-level text conversion succeeded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SCRIPT_VERSION = "1"
SOURCE_SHA256 = "d60dee27ff79fe0d0c05d26156af35c83bff36c93db09556b1ea724e0e14f1f5"
CANDIDATE_SHA256 = "4e2ecfad15f8984e806ec82cd98bfc422982af48d89d147ce7cf28bc67018a07"
TARGET_LINE = 12179
TARGET_STATEMENT = "(allow system_server_34_0 self (capability (sys_module)))"
VENDOR_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = VENDOR_ROOT.parents[2]
CANDIDATE_REL = Path("candidate/vendor/etc/selinux/vendor_sepolicy.cil")
DIRECTIVES = {
    "neverallow": rb"^\(neverallow\s",
    "assertion": rb"^\((?:neverallow|assert)\s",
    "mapping": rb"^\((?:mapping|typemap|typebounds)\s",
    "type": rb"^\((?:type|typeattribute|typealias|typepermissive|typebounds)\s",
}


class PolicyTighteningError(Exception): pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def lf_lines(data: bytes) -> list[bytes]:
    """Split only on LF so line numbers match the source line numbering."""
    parts = data.split(b"\n")
    lines = [part + b"\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    if b"".join(lines) != data:
        raise PolicyTighteningError("internal line split did not preserve bytes")
    return lines


def directive_stats(lines: list[bytes]) -> dict:
    stats = {}
    for name, pattern in DIRECTIVES.items():
        matched = [line for line in lines if re.match(pattern, line)]
        stats[name] = {"count": len(matched), "sha256": sha256_bytes(b"".join(matched))}
    return stats


def find_target(lines: list[bytes], statement: str, expected_line: int) -> int:
    needle = statement.encode("utf-8")
    hits = []
    for number, line in enumerate(lines, 1):
        body = line[:-1] if line.endswith(b"\n") else line
        if body == needle:
            hits.append((number, line))
        elif needle in line:
            raise PolicyTighteningError(
                "target statement is embedded, commented, or string-disguised on "
                "line %d; refusing a partial match" % number)
    if len(hits) != 1:
        raise PolicyTighteningError(
            "expected exactly one exact full-line target statement, found %d" % len(hits))
    number, line = hits[0]
    if number != expected_line:
        raise PolicyTighteningError(
            "target statement found on line %d, expected line %d" % (number, expected_line))
    if line != needle + b"\n":
        raise PolicyTighteningError("target line is not exactly one LF-terminated statement")
    return number


def assert_safe_report(report: Path, input_path: Path) -> None:
    if report == input_path:
        raise PolicyTighteningError("report directory equals the input file")
    if report == input_path.parent or report.is_relative_to(input_path.parent):
        raise PolicyTighteningError("report directory must not be the input directory")
    if input_path.is_relative_to(report):
        raise PolicyTighteningError("report directory must not contain the input file")
    if report.is_relative_to(input_path):
        raise PolicyTighteningError("report directory must not be below the input file")
    for protected in (PROJECT_ROOT / "source", VENDOR_ROOT / "prebuilt", VENDOR_ROOT / "derived"):
        protected = protected.resolve(strict=False)
        if report == protected or report.is_relative_to(protected) or protected.is_relative_to(report):
            raise PolicyTighteningError("report directory is inside a protected tree: %s" % protected)


def tighten(input_path: Path, report_dir: Path) -> dict:
    input_path = Path(input_path).resolve(strict=True)
    if not input_path.is_file():
        raise PolicyTighteningError("input is not a regular file: %s" % input_path)
    data = input_path.read_bytes()
    source_hash = sha256_bytes(data)
    if source_hash != SOURCE_SHA256:
        raise PolicyTighteningError(
            "source sha256 mismatch: expected %s, got %s" % (SOURCE_SHA256, source_hash))

    lines = lf_lines(data)
    target_line = find_target(lines, TARGET_STATEMENT, TARGET_LINE)
    index = target_line - 1
    removed = lines[index]
    candidate = b"".join(lines[:index] + lines[index + 1:])
    offset = sum(len(line) for line in lines[:index])
    if candidate != data[:offset] + data[offset + len(removed):]:
        raise PolicyTighteningError("internal error: removal changed bytes beyond the target line")
    candidate_hash = sha256_bytes(candidate)
    if candidate_hash != CANDIDATE_SHA256:
        raise PolicyTighteningError(
            "candidate sha256 mismatch: expected %s, got %s" % (CANDIDATE_SHA256, candidate_hash))

    source_stats = directive_stats(lines)
    candidate_stats = directive_stats(lf_lines(candidate))
    for name in ("neverallow", "assertion", "mapping", "type"):
        if source_stats[name] != candidate_stats[name]:
            raise PolicyTighteningError("%s directives changed; refusing broad deletion" % name)

    report = Path(report_dir)
    if report.exists() or report.is_symlink():
        raise PolicyTighteningError("report directory already exists or is a symlink: %s" % report)
    report_resolved = report.resolve(strict=False)
    assert_safe_report(report_resolved, input_path)
    report.mkdir(parents=True, exist_ok=False)
    if report.resolve(strict=True) != report_resolved:
        raise PolicyTighteningError("report directory resolution changed after creation")
    assert_safe_report(report.resolve(strict=True), input_path)

    candidate_path = report / CANDIDATE_REL
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    if candidate_path.exists() or candidate_path.is_symlink():
        raise PolicyTighteningError("candidate path already exists: %s" % candidate_path)
    candidate_path.write_bytes(candidate)
    if sha256_file(candidate_path) != candidate_hash:
        raise PolicyTighteningError("written candidate hash mismatch")
    if sha256_file(input_path) != source_hash:
        raise PolicyTighteningError("input file changed during the run")

    receipt = {
        "schema": 1,
        "tool": "tighten_vendor_policy.py",
        "script_version": SCRIPT_VERSION,
        "tool_sha256": sha256_file(Path(__file__).resolve()),
        "source": {"path": str(input_path), "size": len(data), "sha256": source_hash},
        "target": {"line": target_line, "statement": TARGET_STATEMENT, "hits": 1,
                   "removed_bytes": len(removed), "removed_sha256": sha256_bytes(removed)},
        "candidate": {"path": str(candidate_path.relative_to(report)),
                      "size": len(candidate), "sha256": candidate_hash},
        "all_other_bytes_identical": True,
        "directives": {"source": source_stats, "candidate": candidate_stats},
        "neverallow_unchanged": True,
        "assertions_unchanged": True,
        "mappings_unchanged": True,
        "types_unchanged": True,
        "input_unchanged": True,
        "whole_policy_accepted": False,
        "derived_image_built": False,
        "runtime_functionality_verified": False,
        "no_target_exec": True,
        "installed": False,
        "scope": ("Text-only removal of one exact allow line. No CIL execution, "
                  "no image build, no installation; runtime function is unverified."),
    }
    receipt_path = report / "result.json"
    if receipt_path.exists():
        raise PolicyTighteningError("receipt path already exists: %s" % receipt_path)
    with open(receipt_path, "w", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print("removed one exact allow statement at line %d; candidate %s" %
          (target_line, candidate_hash))
    print("text-only conversion; whole policy, image, and runtime are NOT accepted or verified")
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="read-only vendor_sepolicy.cil")
    parser.add_argument("--report-dir", required=True, help="new directory for candidate and receipt")
    args = parser.parse_args(argv)
    try:
        tighten(Path(args.input), Path(args.report_dir))
        return 0
    except (PolicyTighteningError, OSError, ValueError) as exc:
        print("ROTHKO_POLICY_TIGHTENING_ERROR: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
