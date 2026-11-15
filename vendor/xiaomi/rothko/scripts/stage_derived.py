#!/usr/bin/env python3
"""Stage the two reviewed derived images without touching the nine stock prebuilts.

Derived images:
  vendor_boot.img  — stock vendor_boot with only fstab lines removed
  vendor.img       — stock vendor with only fstab lines removed

The script verifies the stock original, the derived expected hash, the parent
readback log, and the recipe source hash before copying. No AVB/signature
validity is claimed; the derived images remain unsigned test inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from stage_prebuilts import (  # noqa: E402
    FIXED_MANIFEST_SHA256, StageError, copy_verified, load_json, sha256_file,
    validate_identity,
)

DERIVED = ("vendor_boot", "vendor")
DERIVED_PREFIX = "derived"


def project_root(vendor_root: Path) -> Path:
    return vendor_root.parents[2]


def recipe_hash(project: Path, files: list[str]) -> str:
    lines = []
    for rel in sorted(files):
        p = project / rel
        if not p.is_file() or p.is_symlink():
            raise StageError("recipe file missing or symlink: %s" % rel)
        lines.append("%s\0%s" % (rel, sha256_file(p)))
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def validate_readback(name: str, log: dict, expected_hash: str) -> bool:
    if not log.get("ok"):
        raise StageError("%s: parent readback is not ok" % name)
    actual = log.get("sha256") if name == "vendor_boot" else log.get("derived_sha256")
    if actual != expected_hash:
        raise StageError("%s: readback hash does not match derived expected hash" % name)
    if name == "vendor_boot":
        for field in ("header_fields_preserved_except_ramdisk_size",
                      "dtb_container_and_bootconfig_identical",
                      "fragment_types_names_board_ids_order_identical",
                      "no_old_avb_footer_carried"):
            if not log.get(field):
                raise StageError("vendor_boot: readback field false: %s" % field)
        for frag in log.get("fragments", []):
            if not frag.get("all_other_members_metadata_and_content_identical"):
                raise StageError("vendor_boot: non-fstab member changed")
            for change in frag.get("changed", []):
                if not change.get("path", "").endswith(("fstab.mt6989", "fstab.emmc",
                                                        "recovery.fstab")):
                    raise StageError("vendor_boot: non-fstab change %s"
                                     % change.get("path"))
        return True
    if name == "vendor":
        if log.get("unexpected_differences"):
            raise StageError("vendor: readback unexpected differences")
        allowed = log.get("allowed_modifications", [])
        if not allowed:
            raise StageError("vendor: readback has no allowed modifications")
        for change in allowed:
            if change.get("path") not in ("etc/fstab.emmc", "etc/fstab.mt6989"):
                raise StageError("vendor: non-fstab change %s" % change.get("path"))
        if not log.get("hardlink_groups_match"):
            raise StageError("vendor: hardlink groups differ")
        return True
    raise StageError("unknown derived image %s" % name)


def parse_header(path: Path, kind: str) -> dict:
    if kind == "vendor_boot":
        data = path.read_bytes()[:2128]
        if data[:8] != b"VNDRBOOT":
            raise StageError("derived vendor_boot magic mismatch")
        return {"magic": "VNDRBOOT",
                "header_version": struct.unpack_from("<I", data, 8)[0],
                "page_size": struct.unpack_from("<I", data, 12)[0],
                "kernel_addr": hex(struct.unpack_from("<I", data, 16)[0]),
                "ramdisk_addr": hex(struct.unpack_from("<I", data, 20)[0]),
                "dtb_size": struct.unpack_from("<I", data, 2100)[0],
                "dtb_addr": hex(struct.unpack_from("<Q", data, 2104)[0])}
    if kind == "vendor":
        with open(path, "rb") as fh:
            fh.seek(1024)
            if fh.read(4) != bytes.fromhex("e2e1f5e0"):
                raise StageError("derived vendor is not EROFS")
        return {"magic": "EROFS", "superblock_offset": 1024}
    raise StageError("unknown derived kind %s" % kind)


def copy_evidence(vendor_root: Path, project: Path, d: dict) -> dict:
    src = project / d["readback"]
    if src.is_symlink() or not src.is_file():
        raise StageError("readback log missing: %s" % src)
    expected = {"size": src.stat().st_size, "sha256": d["readback_sha256"]}
    if sha256_file(src) != expected["sha256"]:
        raise StageError("readback source hash mismatch: %s" % src)
    evidence = vendor_root / "evidence"
    if evidence.is_symlink():
        raise StageError("evidence directory is a symlink")
    evidence.mkdir(exist_ok=True)
    if not evidence.resolve().is_relative_to(vendor_root.resolve()):
        raise StageError("evidence directory escapes vendor root")
    target = evidence / src.name
    if target.is_symlink():
        raise StageError("evidence target is a symlink: %s" % target)
    if target.exists() and sha256_file(target) == expected["sha256"]:
        pass
    else:
        copy_verified(src, target, expected)
    return {"base": "vendor_root",
            "path": str(target.relative_to(vendor_root)),
            "sha256": expected["sha256"], "ok": True, "snapshot": True}


def stage(vendor_root: Path, project: Path, source_manifest: dict,
          derived_manifest: dict, apply: bool, metadata_only: bool = False) -> dict:
    validate_identity(source_manifest)
    if derived_manifest.get("device") != "rothko" or \
            derived_manifest.get("model") != "2407FRK8EC":
        raise StageError("derived source manifest identity mismatch")
    if derived_manifest.get("signed") is not False or \
            derived_manifest.get("release_ready") is not False or \
            derived_manifest.get("hardware_release_ready") is not False:
        raise StageError("derived source manifest must be signed=false, "
                         "release_ready=false, hardware_release_ready=false")
    if set(derived_manifest.get("derived", {})) != set(DERIVED):
        raise StageError("derived source manifest must contain exactly %s" % (DERIVED,))

    derived_dir = vendor_root / DERIVED_PREFIX
    if derived_dir.is_symlink():
        raise StageError("derived directory is a symlink")
    derived_dir.mkdir(exist_ok=True)
    if not derived_dir.resolve().is_relative_to(vendor_root.resolve()):
        raise StageError("derived directory escapes vendor root")

    records = {}
    stock_records = {}
    for name in DERIVED:
        d = derived_manifest["derived"][name]
        original_name = d["original_stock"]
        if original_name not in source_manifest["images"]:
            raise StageError("%s: original stock %s not in source manifest"
                             % (name, original_name))
        original = source_manifest["images"][original_name]
        original_path = vendor_root / "prebuilt" / ("%s.img" % original_name)
        if original_path.is_symlink() or not original_path.is_file():
            raise StageError("%s: stock original missing: %s" % (name, original_path))
        original_hash = sha256_file(original_path)
        if original_path.stat().st_size != int(original["size"]) or \
                original_hash != original["sha256"]:
            raise StageError("%s: stock original was modified" % name)
        stock_records[original_name] = {
            "path": str(original_path.relative_to(vendor_root)),
            "size": original_path.stat().st_size,
            "sha256": original_hash,
        }

        source = project / d["source"]
        if source.is_symlink() or not source.is_file():
            raise StageError("%s: derived source missing: %s" % (name, source))
        if source.stat().st_size != int(d["size"]) or sha256_file(source) != d["sha256"]:
            raise StageError("%s: derived source size/hash mismatch" % name)
        readback_path = project / d["readback"]
        if readback_path.is_symlink() or not readback_path.is_file():
            raise StageError("%s: readback log missing: %s" % (name, readback_path))
        if sha256_file(readback_path) != d["readback_sha256"]:
            raise StageError("%s: readback log hash mismatch" % name)
        readback = load_json(readback_path)
        validate_readback(name, readback, d["sha256"])
        rhash = recipe_hash(project, d.get("recipe_files", []))
        records[name] = {
            "source": str(d["source"]),
            "source_size": source.stat().st_size,
            "source_sha256": d["sha256"],
            "original_stock": original_name,
            "original": stock_records[original_name],
            "recipe_code_sha256": rhash,
            "recipe_files": sorted(d.get("recipe_files", [])),
            "readback": {
                "path": str(d["readback"]),
                "sha256": d["readback_sha256"],
                "ok": True,
            },
            "only_allowed_fstabs_change": True,
            "signed": False,
            "release_ready": False,
            "header": parse_header(source, name),
        }
        print("%-12s original %s %12d -> derived %12d %s" %
              (name, original_hash[:12], int(original["size"]),
               int(d["size"]), d["sha256"]))
    if not apply:
        print("dry run only; rerun with --apply to publish derived/")
        return {"schema": 1, "applied": False, "stock": stock_records,
                "derived": records}

    if metadata_only:
        # Reuse the already published large images; refresh only evidence and
        # metadata. The image bytes are still checked against the expected hash.
        for name in DERIVED:
            d = derived_manifest["derived"][name]
            target = derived_dir / ("%s.img" % name)
            if target.is_symlink() or not target.is_file():
                raise StageError("%s: existing derived image missing" % name)
            if target.stat().st_size != int(d["size"]) or sha256_file(target) != d["sha256"]:
                raise StageError("%s: existing derived image hash mismatch" % name)
        for name in DERIVED:
            records[name]["readback"] = copy_evidence(
                vendor_root, project, derived_manifest["derived"][name])
    else:
        staging = derived_dir / (".staging-%d" % os.getpid())
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir()
        try:
            for name in DERIVED:
                d = derived_manifest["derived"][name]
                copy_verified(project / d["source"], staging / ("%s.img" % name),
                              {"size": int(d["size"]), "sha256": d["sha256"]})
            for name in DERIVED:
                if (derived_dir / ("%s.img" % name)).is_symlink():
                    raise StageError("%s: target is a symlink" % name)
                os.replace(staging / ("%s.img" % name),
                           derived_dir / ("%s.img" % name))
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        shutil.rmtree(staging, ignore_errors=True)
        for name in DERIVED:
            records[name]["readback"] = copy_evidence(
                vendor_root, project, derived_manifest["derived"][name])

    result = {
        "schema": 1,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "device": "rothko",
        "model": "2407FRK8EC",
        "source_manifest_sha256": sha256_file(vendor_root / "source-manifest.json"),
        "derived_source_manifest_sha256": sha256_file(vendor_root / "derived-source-manifest.json"),
        "payload_manifest_sha256": FIXED_MANIFEST_SHA256,
        "stock": stock_records,
        "derived": {},
        "only_allowed_fstabs_change": True,
        "blob_fixups": [],
        "signed": False,
        "avb_verified": False,
        "release_ready": False,
        "hardware_release_ready": False,
        "notes": [
            "Only fstab lines were removed by the reviewed recipes; no AVB/signature claim.",
            "The nine stock prebuilt images were not modified.",
            "Derived images are local test inputs, not a release OTA.",
        ],
    }
    for name in DERIVED:
        rec = dict(records[name])
        target = derived_dir / ("%s.img" % name)
        digest = sha256_file(target)
        if digest != derived_manifest["derived"][name]["sha256"]:
            raise StageError("%s: published hash mismatch" % name)
        rec["path"] = str(target.relative_to(vendor_root))
        rec["size"] = target.stat().st_size
        rec["sha256"] = digest
        result["derived"][name] = rec
    with open(vendor_root / "derived-manifest.json", "w") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("refreshed evidence/derived-manifest.json; large images not recopied"
          if metadata_only else
          "published 2 derived images and derived-manifest.json")
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--project-root", default=None)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--metadata-only", action="store_true",
                    help="refresh evidence/manifest only; do not recopy large images")
    args = ap.parse_args(argv)
    vendor_root = Path(args.root).resolve()
    project = (Path(args.project_root).resolve() if args.project_root
               else project_root(vendor_root))
    try:
        source = load_json(vendor_root / "source-manifest.json")
        derived = load_json(vendor_root / "derived-source-manifest.json")
        stage(vendor_root, project, source, derived, args.apply, args.metadata_only)
        return 0
    except (StageError, OSError, ValueError, ImportError) as exc:
        print("ROTHKO_VENDOR_DERIVED_ERROR: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
