#!/usr/bin/env python3
"""Verify staged prebuilt images for make gating and handoff checks.

The gate is deliberately narrow: missing image or size/SHA-256 mismatch fails.
It does not test the hardware release readiness flag and does not invent CRC or
compatibility claims.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stage_prebuilts import (  # noqa: E402
    FIXED_MANIFEST_SHA256, IMAGE_ORDER, StageError, load_json, sha256_file,
    validate_identity,
)

DERIVED_ORDER = ("vendor_boot", "vendor")

ROOT = Path(__file__).resolve().parents[1]


def verify_derived_tree(root: Path) -> dict:
    """Verify only the derived evidence; all paths are relative to root.

    This function deliberately reads no project/external logs. The evidence
    snapshot is expected under the vendor tree and its fixed hash is checked.
    """
    errors = []
    images = {}
    source_path = root / "source-manifest.json"
    dsource_path = root / "derived-source-manifest.json"
    dman_path = root / "derived-manifest.json"
    if not source_path.is_file():
        return {"ok": False, "errors": ["source-manifest.json missing"], "images": {}}
    if not dsource_path.is_file():
        errors.append("derived-source-manifest.json missing")
    if not dman_path.is_file():
        errors.append("derived-manifest.json missing")
    if not dsource_path.is_file() or not dman_path.is_file():
        return {"ok": False, "errors": errors, "images": images}
    source = load_json(source_path)
    dsource = load_json(dsource_path)
    dman = load_json(dman_path)
    if dman.get("source_manifest_sha256") != sha256_file(source_path):
        errors.append("derived manifest source-manifest hash mismatch")
    if dman.get("derived_source_manifest_sha256") != sha256_file(dsource_path):
        errors.append("derived manifest derived-source-manifest hash mismatch")
    if dman.get("payload_manifest_sha256") != FIXED_MANIFEST_SHA256:
        errors.append("derived manifest payload-manifest hash mismatch")
    if dman.get("signed") is not False:
        errors.append("derived manifest signed must be false")
    if dman.get("only_allowed_fstabs_change") is not True:
        errors.append("derived manifest allowed-change scope is not fstab-only")
    if dman.get("release_ready") is not False:
        errors.append("derived manifest release_ready must be false")
    if dman.get("hardware_release_ready") is not False:
        errors.append("derived manifest hardware_release_ready must be false")
    if set((dman.get("derived") or {})) != set(DERIVED_ORDER):
        errors.append("derived manifest must contain exactly vendor_boot and vendor")
    for name in DERIVED_ORDER:
        exp = (dsource.get("derived") or {}).get(name)
        rec = (dman.get("derived") or {}).get(name)
        if not exp or not rec:
            errors.append("%s derived manifest entry missing" % name)
            continue
        path = root / "derived" / ("%s.img" % name)
        if path.is_symlink() or not path.is_file():
            errors.append("%s derived image missing or symlink: %s" % (name, path))
            continue
        size = path.stat().st_size
        digest = sha256_file(path)
        if size != int(exp["size"]):
            errors.append("%s derived size %d != expected %d" %
                          (name, size, int(exp["size"])))
        if digest != exp["sha256"]:
            errors.append("%s derived sha256 %s != expected %s" %
                          (name, digest, exp["sha256"]))
        if rec.get("sha256") != digest or int(rec.get("size", -1)) != size:
            errors.append("%s derived manifest actual hash/size mismatch" % name)
        if rec.get("original", {}).get("sha256") != source.get("images", {}).get(exp["original_stock"], {}).get("sha256"):
            errors.append("%s derived original hash does not match stock manifest" % name)
        if not rec.get("recipe_code_sha256") or not rec.get("readback", {}).get("sha256"):
            errors.append("%s derived recipe/readback evidence missing" % name)
        if rec.get("signed") is not False or rec.get("release_ready") is not False:
            errors.append("%s derived signed/release_ready must be false" % name)
        if rec.get("only_allowed_fstabs_change") is not True:
            errors.append("%s derived allowed-change scope is not fstab-only" % name)
        rb = rec.get("readback") or {}
        if rb.get("base") != "vendor_root":
            errors.append("%s readback base must be vendor_root" % name)
        rbp = root / rb.get("path", "")
        if not rbp.resolve().is_relative_to(root.resolve()):
            errors.append("%s readback path escapes vendor root" % name)
        elif rbp.is_symlink() or not rbp.is_file():
            errors.append("%s readback evidence missing from vendor tree" % name)
        elif sha256_file(rbp) != rb.get("sha256"):
            errors.append("%s readback evidence hash mismatch" % name)
        elif rb.get("ok") is not True:
            errors.append("%s readback not ok" % name)
        images[name] = {"path": str(path.relative_to(root)),
                        "size": size, "sha256": digest}
    return {"ok": not errors, "errors": errors, "images": images}


def verify(root: Path, quiet: bool = False) -> dict:
    manifest = load_json(root / "source-manifest.json")
    validate_identity(manifest)
    prebuilt = root / "prebuilt"
    errors = []
    images = {}
    if prebuilt.is_symlink() or not prebuilt.is_dir():
        errors.append("prebuilt directory missing or symlink: %s" % prebuilt)
    staged_path = prebuilt / "staged-manifest.json"
    if not staged_path.is_file() or staged_path.is_symlink():
        errors.append("staged-manifest.json missing or symlink")
        staged = {}
    else:
        staged = load_json(staged_path)
        source_sha = sha256_file(root / "source-manifest.json")
        if staged.get("source_manifest_sha256") != source_sha:
            errors.append("staged manifest source-manifest hash mismatch")
        if staged.get("payload_manifest_sha256") != FIXED_MANIFEST_SHA256:
            errors.append("staged manifest payload-manifest hash mismatch")
        if staged.get("model") != "2407FRK8EC":
            errors.append("staged manifest model mismatch")
    for name in IMAGE_ORDER:
        expected = manifest["images"][name]
        path = prebuilt / ("%s.img" % name)
        if path.is_symlink() or not path.is_file():
            errors.append("%s image missing or symlink: %s" % (name, path))
            continue
        size = path.stat().st_size
        digest = sha256_file(path)
        if size != int(expected["size"]):
            errors.append("%s size %d != expected %d" %
                          (name, size, int(expected["size"])))
        if digest != expected["sha256"]:
            errors.append("%s sha256 %s != expected %s" %
                          (name, digest, expected["sha256"]))
        images[name] = {"path": str(path.relative_to(root)), "size": size,
                        "sha256": digest}
    derived_result = verify_derived_tree(root)
    errors.extend(derived_result["errors"])
    derived_images = derived_result["images"]
    result = {"schema": 1, "ok": not errors, "errors": errors,
              "stock_images": images, "derived_images": derived_images,
              "hardware_release_ready": bool(
                  staged.get("hardware_release_ready", False)) if staged else False}
    if not quiet:
        for name, rec in images.items():
            print("OK stock:%-12s %12d %s" % (name, rec["size"], rec["sha256"]))
        for name, rec in derived_images.items():
            print("OK derived:%-10s %12d %s" % (name, rec["size"], rec["sha256"]))
        for err in errors:
            print("FAIL %s" % err, file=sys.stderr)
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--make", action="store_true",
                    help="emit one compact error line for BoardConfigVendor.mk")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        result = verify(root, quiet=args.make)
    except (StageError, OSError, ValueError, json.JSONDecodeError) as exc:
        print("ROTHKO_VENDOR_PREBUILT_ERROR: %s" % exc)
        return 1
    if result["ok"]:
        return 0
    if args.make:
        print("ROTHKO_VENDOR_PREBUILT_ERROR: %s" % "; ".join(result["errors"]))
    return 1


if __name__ == "__main__":
    sys.exit(main())
