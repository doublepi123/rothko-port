#!/usr/bin/env python3
"""Stage the stock rothko images into this vendor tree.

Architecture (phase 1):
  * stock prebuilt: boot, init_boot, vendor_boot, dtbo, vendor, odm,
    system_dlkm, vendor_dlkm, odm_dlkm;
  * Lineage-built: system, system_ext, product (not staged here).

The staging source is either ../offline-k70u/images or firmware/images.
Every image is cross-checked against:
  1. the fixed payload_manifest.bin hash,
  2. the independent parent-manifest-expectations.json,
  3. the checked-in source-manifest.json.

No hardlink is used. A copy goes to a private staging directory, is re-hashed,
and only then atomically renamed into prebuilt/. A failed run never publishes a
new image. Proprietary images are deliberately gitignored and are not shipped
by this repository.
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

VENDOR_ROOT = Path(__file__).resolve().parents[1]
IMAGE_ORDER = ("boot", "init_boot", "vendor_boot", "dtbo",
               "vendor", "odm", "system_dlkm", "vendor_dlkm", "odm_dlkm")
FIXED_MANIFEST_SHA256 = "25cb38be498d09100bb95cfc12fe2ffe43f4878a49265837d2e940289d23c833"
REQUIRED_MODEL = "2407FRK8EC"
REQUIRED_MARKET = "Redmi K70 Ultra"
REQUIRED_REGION = "CN"
REQUIRED_BRANCH = "WNNCNXM"
CHUNK = 1 << 20


class StageError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_identity(manifest: dict) -> None:
    if manifest.get("schema") != 1:
        raise StageError("unsupported source manifest schema")
    if manifest.get("device") != "rothko":
        raise StageError("device is not rothko: %r" % manifest.get("device"))
    if manifest.get("model") != REQUIRED_MODEL:
        raise StageError("model is not the CN K70 Ultra 2407FRK8EC: %r"
                         % manifest.get("model"))
    if set(manifest.get("allowed_models", [])) != {REQUIRED_MODEL}:
        raise StageError("allowed_models must be exactly the CN K70 Ultra 2407FRK8EC")
    if manifest.get("market_name") != REQUIRED_MARKET:
        raise StageError("market name is not Redmi K70 Ultra: %r"
                         % manifest.get("market_name"))
    if manifest.get("region") != REQUIRED_REGION:
        raise StageError("region is not CN")
    if manifest.get("firmware_branch") != REQUIRED_BRANCH:
        raise StageError("firmware branch is not WNNCNXM")
    if manifest.get("fixups") not in ([], None):
        raise StageError("unexplained fixups are not permitted: %r"
                         % manifest.get("fixups"))
    images = manifest.get("images")
    if not isinstance(images, dict) or set(images) != set(IMAGE_ORDER):
        raise StageError("source manifest image set is not exactly %s" % (IMAGE_ORDER,))
    for name, rec in images.items():
        if not rec.get("source") or Path(rec["source"]).is_absolute():
            raise StageError("%s: source must be a project-relative path" % name)
        if int(rec.get("size", 0)) <= 0:
            raise StageError("%s: invalid expected size" % name)
        if not isinstance(rec.get("sha256"), str) or len(rec["sha256"]) != 64:
            raise StageError("%s: invalid expected sha256" % name)


def validate_payload_root(project_root: Path, manifest: dict) -> dict:
    """Independently verify the fixed payload manifest and parent expectations."""
    pm = manifest.get("payload_manifest") or {}
    mpath = project_root / pm.get("source", "")
    ppath = project_root / pm.get("parent_expectations", "")
    if not mpath.is_file():
        raise StageError("payload manifest missing: %s" % mpath)
    actual = sha256_file(mpath)
    if actual != FIXED_MANIFEST_SHA256 or pm.get("sha256") != FIXED_MANIFEST_SHA256:
        raise StageError("payload manifest hash is not the fixed .308 manifest")
    if not ppath.is_file():
        raise StageError("parent expectations missing: %s" % ppath)
    parent = load_json(ppath)
    if parent.get("manifest_sha256") != FIXED_MANIFEST_SHA256:
        raise StageError("parent expectations manifest hash mismatch")
    # Parse the manifest with the firmware library (read-only), not a receipt.
    sys.path.insert(0, str(project_root / "firmware" / "scripts"))
    from k70u_fwlib import parse_manifest  # noqa: PLC0415
    raw = mpath.read_bytes()
    mf = parse_manifest(raw)
    parts = {p["name"]: p for p in mf["partitions"]}
    expected = {}
    for name in IMAGE_ORDER:
        p = parts.get(name)
        if p is None or not p.get("new_partition_info"):
            raise StageError("partition %s is absent from payload manifest" % name)
        size = int(p["new_partition_info"]["size"])
        digest = p["new_partition_info"]["hash"]
        expected[name] = {"size": size, "sha256": digest}
        par = (parent.get("partitions") or {}).get(name)
        if not par or int(par.get("size", -1)) != size or par.get("hash") != digest:
            raise StageError("parent expectations disagree with manifest for %s" % name)
        rec = manifest["images"][name]
        if int(rec["size"]) != size or rec["sha256"] != digest:
            raise StageError("source manifest disagrees with manifest for %s" % name)
    return expected


def source_path(project_root: Path, rec: dict) -> Path:
    return (project_root / rec["source"]).resolve()


def read_header(path: Path, kind: str) -> dict:
    if kind == "boot":
        data = path.read_bytes()[:64]
        if data[:8] != b"ANDROID!":
            raise StageError("%s: not an Android boot image" % path)
        return {"magic": "ANDROID!",
                "header_version": struct.unpack_from("<I", data, 40)[0],
                "header_size": struct.unpack_from("<I", data, 20)[0],
                "kernel_size": struct.unpack_from("<I", data, 8)[0],
                "ramdisk_size": struct.unpack_from("<I", data, 12)[0]}
    if kind == "vendor_boot":
        data = path.read_bytes()[:2128]
        if data[:8] != b"VNDRBOOT":
            raise StageError("%s: not a vendor_boot image" % path)
        return {"magic": "VNDRBOOT",
                "header_version": struct.unpack_from("<I", data, 8)[0],
                "page_size": struct.unpack_from("<I", data, 12)[0],
                "kernel_addr": hex(struct.unpack_from("<I", data, 16)[0]),
                "ramdisk_addr": hex(struct.unpack_from("<I", data, 20)[0]),
                "cmdline": data[28:2076].split(b"\0", 1)[0].decode("ascii", "replace"),
                "dtb_size": struct.unpack_from("<I", data, 2100)[0],
                "dtb_addr": hex(struct.unpack_from("<Q", data, 2104)[0])}
    if kind == "dtbo":
        data = path.read_bytes()[:32]
        magic, total, hsize, esize, count, eoffset, page, version = \
            struct.unpack_from(">IIIIIIII", data)
        if magic != 0xD7B7AB1E:
            raise StageError("%s: not a DTBO container" % path)
        return {"magic": hex(magic), "total_size": total,
                "header_size": hsize, "entry_count": count,
                "entries_offset": eoffset, "page_size": page,
                "version": version}
    if kind == "erofs":
        with open(path, "rb") as fh:
            fh.seek(1024)
            magic = fh.read(4)
        if magic != bytes.fromhex("e2e1f5e0"):
            raise StageError("%s: not an EROFS image" % path)
        return {"magic": "EROFS", "superblock_offset": 1024}
    raise StageError("unknown image kind %r" % kind)


def verify_source(project_root: Path, name: str, rec: dict, expected: dict) -> dict:
    path = source_path(project_root, rec)
    if path.is_symlink() or not path.is_file():
        raise StageError("%s: source missing or symlink: %s" % (name, path))
    size = path.stat().st_size
    digest = sha256_file(path)
    if size != int(expected["size"]) or digest != expected["sha256"]:
        raise StageError("%s: source size/hash mismatches manifest" % name)
    return {"name": name, "source": str(rec["source"]), "path": str(path),
            "size": size, "sha256": digest,
            "header": read_header(path, rec["kind"])}


def copy_verified(source: Path, dest: Path, expected: dict) -> str:
    """Copy without hardlink, re-hash, and return the digest."""
    tmp = dest.with_name(dest.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    shutil.copyfile(source, tmp)
    digest = sha256_file(tmp)
    if digest != expected["sha256"] or tmp.stat().st_size != int(expected["size"]):
        tmp.unlink(missing_ok=True)
        raise StageError("copy hash/size mismatch for %s" % source)
    os.replace(tmp, dest)
    return digest


def stage(project_root: Path, vendor_root: Path, manifest: dict,
          expected: dict, apply: bool) -> dict:
    validate_identity(manifest)
    target_dir = vendor_root / "prebuilt"
    if target_dir.is_symlink():
        raise StageError("prebuilt directory is a symlink")
    if not target_dir.exists():
        target_dir.mkdir(parents=True)
    if not target_dir.resolve().is_relative_to(vendor_root.resolve()):
        raise StageError("prebuilt directory escapes vendor root")
    sources = {name: verify_source(project_root, name, manifest["images"][name], expected[name])
               for name in IMAGE_ORDER}
    print("verified source images:")
    for name in IMAGE_ORDER:
        print("  %-12s %12d  %s  %s" %
              (name, sources[name]["size"], sources[name]["sha256"],
               sources[name]["header"]))
    if not apply:
        print("dry run only; rerun with --apply to publish")
        return {"schema": 1, "applied": False, "images": sources}

    for name in IMAGE_ORDER:
        if (target_dir / ("%s.img" % name)).is_symlink():
            raise StageError("target image is a symlink: %s" % name)
    staging = target_dir / (".staging-%d" % os.getpid())
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    try:
        for name in IMAGE_ORDER:
            copy_verified(Path(sources[name]["path"]),
                          staging / ("%s.img" % name), expected[name])
        # All copies are verified before any final path is touched.
        for name in IMAGE_ORDER:
            os.replace(staging / ("%s.img" % name), target_dir / ("%s.img" % name))
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    shutil.rmtree(staging, ignore_errors=True)
    staged = {
        "schema": 1,
        "applied": True,
        "device": "rothko",
        "model": REQUIRED_MODEL,
        "market_name": REQUIRED_MARKET,
        "firmware": manifest.get("firmware"),
        "source_manifest_sha256": sha256_file(vendor_root / "source-manifest.json"),
        "payload_manifest_sha256": FIXED_MANIFEST_SHA256,
        "fixups": [],
        "hardware_release_ready": False,
        "staged_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "images": {},
    }
    for name in IMAGE_ORDER:
        p = target_dir / ("%s.img" % name)
        digest = sha256_file(p)
        if digest != expected[name]["sha256"]:
            raise StageError("published %s failed final hash" % name)
        staged["images"][name] = {
            "path": str(p.relative_to(vendor_root)),
            "size": p.stat().st_size,
            "sha256": digest,
            "expected_sha256": expected[name]["sha256"],
            "header": sources[name]["header"],
        }
    with open(target_dir / "staged-manifest.json", "w") as fh:
        json.dump(staged, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("published %d images and prebuilt/staged-manifest.json" % len(IMAGE_ORDER))
    return staged


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(VENDOR_ROOT))
    ap.add_argument("--project-root", default=None)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    vendor_root = Path(args.root).resolve()
    project_root = (Path(args.project_root).resolve() if args.project_root
                    else vendor_root.parents[2])
    try:
        manifest = load_json(vendor_root / "source-manifest.json")
        validate_identity(manifest)
        expected = validate_payload_root(project_root, manifest)
        stage(project_root, vendor_root, manifest, expected, args.apply)
        return 0
    except (StageError, OSError, ValueError, ImportError) as exc:
        print("ROTHKO_VENDOR_STAGE_ERROR: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
