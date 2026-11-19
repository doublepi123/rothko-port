#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Stage pinned local firmware inputs without the original investigation layout.

Inputs are read only. No downloads, signing, or device operations are performed.
The two derived images are explicit, hash-pinned prebuilt inputs; this command
does not claim to regenerate them or authenticate them as OEM-signed images.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def prepare(source: Path, stock: Path, derived: Path, payload: Path, ims: Path) -> dict:
    vendor = source / "vendor/xiaomi/rothko"
    sys.path.insert(0, str(vendor / "scripts"))
    from stage_prebuilts import (
        FIXED_MANIFEST_SHA256, IMAGE_ORDER, StageError, copy_verified,
        load_json, read_header, sha256_file, validate_identity,
    )
    from verify_prebuilts import verify

    manifest = load_json(vendor / "source-manifest.json")
    validate_identity(manifest)
    if sha256_file(payload) != FIXED_MANIFEST_SHA256:
        raise StageError("payload manifest does not match the pinned CN firmware")
    derived_manifest = load_json(vendor / "derived-source-manifest.json")
    inputs: list[tuple[Path, Path, dict]] = []
    images = {}
    for name in IMAGE_ORDER:
        expected = manifest["images"][name]
        original = stock / f"{name}.img"
        inputs.append((original, vendor / "prebuilt" / original.name, expected))
        images[name] = {
            "path": f"prebuilt/{original.name}", "size": expected["size"],
            "sha256": expected["sha256"], "expected_sha256": expected["sha256"],
        }
    for name in ("vendor_boot", "vendor"):
        expected = derived_manifest["derived"][name]
        inputs.append((derived / f"{name}.img", vendor / "derived" / f"{name}.img", expected))
    ims_expected = {"size": ims.stat().st_size,
                    "sha256": "a4b25608dfd07d0789f1b24b0d719ac46de233c91765d1d94b890d53294638c3"}
    inputs.append((ims, source / "device/xiaomi/rothko/ims/prebuilt/ImsService.apk", ims_expected))

    # Verify every input before publishing any file in the destination tree.
    for original, dest, expected in inputs:
        if original.is_symlink() or not original.is_file():
            raise StageError(f"input must be a regular file: {original}")
        if original.stat().st_size != expected["size"] or sha256_file(original) != expected["sha256"]:
            raise StageError(f"input size/hash mismatch: {original.name}")
        if dest.is_symlink() or dest.parent.is_symlink():
            raise StageError(f"destination cannot be a symlink: {dest}")
        if original.resolve() == dest.resolve():
            raise StageError("input and destination must be distinct")
        if dest.exists() and sha256_file(dest) != expected["sha256"]:
            raise StageError(f"refusing to overwrite different destination: {dest}")
    for name in IMAGE_ORDER:
        images[name]["header"] = read_header(stock / f"{name}.img", manifest["images"][name]["kind"])
    for original, dest, expected in inputs:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            copy_verified(original, dest, expected)
    receipt = {
        "schema": 1, "applied": True, "device": "rothko", "model": manifest["model"],
        "market_name": manifest["market_name"], "firmware": manifest["firmware"],
        "source_manifest_sha256": sha256_file(vendor / "source-manifest.json"),
        "payload_manifest_sha256": sha256_file(payload), "fixups": [],
        "hardware_release_ready": False, "images": images,
        "staged_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "input_mode": "local pinned stock and derived prebuilt files",
    }
    (vendor / "prebuilt/staged-manifest.json").write_text(json.dumps(receipt, indent=2) + "\n")
    verified = verify(vendor, quiet=True)
    if not verified["ok"]:
        raise StageError("staged input validation failed: " + "; ".join(verified["errors"]))
    return {"ok": True, "stock_images": len(IMAGE_ORDER), "derived_images": 2,
            "ims_sha256": ims_expected["sha256"], "hardware_release_ready": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--stock-images", type=Path, required=True)
    parser.add_argument("--derived-images", type=Path, required=True)
    parser.add_argument("--payload-manifest", type=Path, required=True)
    parser.add_argument("--ims-apk", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.source_root.resolve(), args.stock_images.resolve(),
                         args.derived_images.resolve(), args.payload_manifest.resolve(),
                         args.ims_apk.resolve())
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"INPUT_PREPARATION_ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
