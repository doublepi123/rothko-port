#!/usr/bin/env python3
"""Emit the fixed two-deny APEX checkpoint reduction profile, text only.

Every artifact is pinned. rc 0 means only that the five pinned inputs matched
and the fixed profile bytes were written with an honest receipt. It is NOT a
policy compile, function pass, install, first-stage boot, or runtime approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from tighten_vendor_policy import PolicyTighteningError, assert_safe_report

SCRIPT_VERSION = "1"
PROFILE_NAME = "apexd_legacy_checkpoint_reductions.cil"
PROFILE_PATH = Path(__file__).resolve().parents[1] / "policy" / PROFILE_NAME
RULE_DIR = b"(deny apexd vold_metadata_file (dir (search)))\n"
RULE_FILE = b"(deny apexd vold_metadata_file (file (getattr open read write)))\n"
PROFILE_BYTES = RULE_DIR + RULE_FILE
PROFILE_SHA256 = "7ee420308108be89067acf9a4d8ed375e3ce792153359400cd16c7f85bc6d3ad"
EXPECTED_RULES = (RULE_DIR, RULE_FILE)
HEADER_MACRO = b"#define COM_ANDROID_APEX_FLAGS_MOUNT_BEFORE_DATA false"
HEADER_MACRO_TRUE = b"#define COM_ANDROID_APEX_FLAGS_MOUNT_BEFORE_DATA true"
MAX_HEADER_BYTES = 1 << 20
PINS = {
    "system_image": "ce4f4abca132d18804d6b26d4da51e76e85479304f7de6ea45809165138867e4",
    "apexd": "dba2171535def3064a95c14e7fd47e79a4964f5189be38e82340c73ebdc73caa",
    "init": "2d0173079ef46eda0075e4c25c14959d6d5b395b4ac4473652f53e81f6781c10",
    "init_boot": "b7acb150c417af59506ccaa7770684b1455578f3d40589e35d7057c93cac2507",
    "flag_header": "fff2588ebdeb4ae2837c96d6f4232a0b57f28acdfb8940d8e6b0f85dddabf2e1",
}
ARGUMENTS = (("system_image", "--system-image"), ("apexd", "--apexd"),
             ("init", "--init"), ("init_boot", "--init-boot"),
             ("flag_header", "--flag-header"))
PROJECT_ROOT = Path(__file__).resolve().parents[4]
PARENT_BINDING_REL = Path(
    "logs/lineage-rothko-build-20261101-132134/final-artifact-acceptance-20261101-194534/"
    "apex-legacy-mode-parent-binding-20261101-221202/result.json")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_profile() -> bytes:
    data = PROFILE_PATH.read_bytes()
    if data != PROFILE_BYTES:
        raise PolicyTighteningError("on-disk fixed profile changed; fresh review required")
    if hashlib.sha256(data).hexdigest() != PROFILE_SHA256:
        raise PolicyTighteningError(
            "profile sha256 mismatch: the fixed profile changed; fresh review required")
    lines = data.splitlines(keepends=True)
    if len(lines) != 2 or tuple(lines) != EXPECTED_RULES or b"".join(lines) != data:
        raise PolicyTighteningError("profile must be exactly the two fixed LF-terminated deny rules; fresh review required")
    for line in lines:
        if not line.startswith(b"(deny apexd vold_metadata_file "):
            raise PolicyTighteningError("profile contains a non-fixed deny rule")
    return data


def load_inputs(args) -> dict:
    inputs = {}
    for key, option in ARGUMENTS:
        path = Path(getattr(args, key)).resolve(strict=True)
        if not path.is_file():
            raise PolicyTighteningError("%s is not a regular file: %s" % (option, path))
        actual = sha256_file(path)
        if actual != PINS[key]:
            raise PolicyTighteningError(
                "%s sha256 mismatch: expected %s, got %s; fresh review required"
                % (option, PINS[key], actual))
        inputs[key] = {"path": path, "size": path.stat().st_size, "sha256": actual}
    return inputs


def validate_header(path: Path) -> dict:
    with open(path, "rb") as handle:
        data = handle.read(MAX_HEADER_BYTES + 1)
    if len(data) > MAX_HEADER_BYTES:
        raise PolicyTighteningError("flag header is unexpectedly large: %s" % path)
    lines = data.splitlines()
    if [line for line in lines if line == HEADER_MACRO] != [HEADER_MACRO] or \
            data.count(HEADER_MACRO + b"\n") != 1:
        raise PolicyTighteningError(
            "flag header must contain exactly one 'MOUNT_BEFORE_DATA false' line; fresh review required")
    if HEADER_MACRO_TRUE in lines:
        raise PolicyTighteningError("flag header must not enable MOUNT_BEFORE_DATA; fresh review required")
    return {"macro": HEADER_MACRO.decode("utf-8"), "macro_false": True,
            "exact_macro_line_count": 1}


def assert_report_ok(report: Path, inputs: dict) -> None:
    for key, record in inputs.items():
        source = record["path"]
        assert_safe_report(report, source)
        parent = source.parent
        if report == parent or report.is_relative_to(parent):
            raise PolicyTighteningError("report directory is inside an input directory: %s" % parent)
    for ancestor in report.parents:
        stamp = ancestor / "result.json"
        if stamp.is_file():
            try:
                if json.loads(stamp.read_text(encoding="utf-8")).get("tool") == \
                        "prepare_legacy_apex_policy.py":
                    raise PolicyTighteningError(
                        "report directory is nested inside an existing output: %s" % ancestor)
            except (OSError, ValueError):
                pass


def prepare(args) -> dict:
    inputs = load_inputs(args)
    profile = validate_profile()
    header = validate_header(inputs["flag_header"]["path"])
    report = Path(args.report_dir)
    if report.exists() or report.is_symlink():
        raise PolicyTighteningError("report directory already exists or is a symlink: %s" % report)
    resolved = report.resolve(strict=False)
    assert_report_ok(resolved, inputs)
    report.mkdir(parents=True, exist_ok=False)
    actual = report.resolve(strict=True)
    if actual != resolved:
        raise PolicyTighteningError("report directory resolution changed after creation")
    assert_report_ok(actual, inputs)

    candidate = report / PROFILE_NAME
    with open(candidate, "xb") as handle:
        handle.write(profile)
    if sha256_file(candidate) != PROFILE_SHA256:
        raise PolicyTighteningError("written profile hash mismatch")
    for key, record in inputs.items():
        if sha256_file(record["path"]) != record["sha256"]:
            raise PolicyTighteningError("%s changed during the run; inputs are read-only" % key)

    receipt = {
        "schema": 1,
        "tool": "prepare_legacy_apex_policy.py",
        "script_version": SCRIPT_VERSION,
        "tool_sha256": sha256_file(Path(__file__).resolve()),
        "rc0_meaning": ("pinned inputs matched and the fixed profile bytes were emitted; "
                        "no policy compile, function pass, or runtime approval"),
        "inputs": {key: {"path": str(record["path"]), "size": record["size"],
                         "sha256": record["sha256"], "pin": PINS[key], "pin_matched": True}
                   for key, record in inputs.items()},
        "profile": {"path": PROFILE_NAME, "size": len(profile), "sha256": PROFILE_SHA256,
                    "rule_count": 2,
                    "rules": [line.decode("utf-8").rstrip("\n") for line in EXPECTED_RULES],
                    "only_fixed_two_deny_rules": True},
        "header": {"path": str(inputs["flag_header"]["path"]), "macro": header["macro"],
                   "macro_false": True, "exact_macro_line_count": 1},
        "parent_binding": {
            "result_json": str(PROJECT_ROOT / PARENT_BINDING_REL),
            "exists": (PROJECT_ROOT / PARENT_BINDING_REL).is_file(),
            "apexd_main_constexpr_true_setter_lines_142_148_eliminated_parent_verified": True,
            "normal_vold_binder_rollback_retained": True,
            "checked_by_this_tool": False},
        "second_stage_only": True,
        "policy_compiled": False,
        "secilc_invoked": False,
        "function_pass_verified": False,
        "image_built": False,
        "make_hook_added": False,
        "installed": False,
        "device_changed": False,
        "first_stage_boot_verified": False,
        "runtime_rollback_verified": False,
        "inputs_unchanged": True,
        "candidate_rehashed": True,
        "scope": ("Emit one fixed two-rule external CIL candidate and a receipt. "
                  "No secilc, policy compile, function pass, install, first-stage boot, "
                  "or runtime approval is performed or claimed."),
    }
    receipt_path = report / "result.json"
    with open(receipt_path, "x", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write("\n")
    stored = json.loads(receipt_path.read_text(encoding="utf-8"))
    if stored["profile"]["sha256"] != PROFILE_SHA256 or stored["inputs"] != receipt["inputs"]:
        raise PolicyTighteningError("receipt re-read does not match the emitted profile")

    print("emitted fixed two-deny profile %s (sha256 %s)" % (candidate, PROFILE_SHA256))
    print("text-only emission; policy compile, function, first-stage, and runtime are NOT verified")
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system-image", required=True, help="read-only system.img")
    parser.add_argument("--apexd", required=True, help="pinned actual apexd binary")
    parser.add_argument("--init", required=True, help="pinned second-stage init binary")
    parser.add_argument("--init-boot", required=True, help="pinned stock init_boot.img")
    parser.add_argument("--flag-header", required=True, help="pinned generated flags header")
    parser.add_argument("--report-dir", required=True, help="new directory for candidate and receipt")
    args = parser.parse_args(argv)
    try:
        prepare(args)
        return 0
    except (PolicyTighteningError, OSError, ValueError) as exc:
        print("ROTHKO_LEGACY_APEX_POLICY_ERROR: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
