#!/usr/bin/env python3
"""Input gate for the Redmi K70 Ultra (rothko) device configuration.

Two independent modes:

  build     Validate that the generated make fragments are current, the
            super/group budget is consistent, every required prebuilt image is
            staged with the expected hash, and the vendor inventory is present
            and verified. This is the gate BoardConfig.mk runs.
  evidence  Validate the original firmware inputs and the recorded evidence
            logs against config/device-parameters.json. Read-only; it does not
            touch a device.

The script never invokes a device tool, never writes to firmware inputs and
never changes slot/AVB state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
import kati_context

BOOT_MAGIC = b"ANDROID!"
VENDOR_BOOT_MAGIC = b"VNDRBOOT"
DTBO_MAGIC = 0xD7B7AB1E
FDT_MAGIC = 0xD00DFEED
CLEAN_GOALS = {"clean", "clobber", "dataclean", "installclean"}
CONFIG_GOALS = {"dump-many-vars", "dumpvars", "dumpvar"}
FRAMEWORK_GOALS = {
    "systemimage",
    "systemimage-nodeps",
    "systemextimage",
    "systemextimage-nodeps",
    "productimage",
    "productimage-nodeps",
}
# Explicitly authorized module compilation, never recovery/vendor_boot images
# or a release/full-ROM admission. Mixed or unknown goals retain release gates.
RECOVERY_MODULE_GOALS = {"recovery", "recovery-launcher", "librecovery_ui_ext"}
CHUNK = 1024 * 1024


class InputError(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def u32le(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def parse_boot_header(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        head = handle.read(64)
    if len(head) < 48 or head[:8] != BOOT_MAGIC:
        raise InputError(f"{path}: not an Android boot image")
    return {
        "magic": head[:8].decode("ascii"),
        "kernel_size": u32le(head, 8),
        "ramdisk_size": u32le(head, 12),
        "header_version": u32le(head, 40),
        "file_size": path.stat().st_size,
    }


def align(value: int, page: int) -> int:
    return (value + page - 1) // page * page


def parse_dtbo_container(data: bytes, where: str) -> dict[str, Any]:
    if len(data) < 32:
        raise InputError(f"{where}: shorter than a DTBO header")
    magic, total, header_size, entry_size, entry_count, entries_offset, page, version = (
        struct.unpack(">IIIIIIII", data[:32])
    )
    if magic != DTBO_MAGIC:
        raise InputError(f"{where}: DTBO magic {magic:#x} != {DTBO_MAGIC:#x}")
    if header_size < 32 or entries_offset < header_size:
        raise InputError(f"{where}: invalid DTBO header/entries offsets")
    if entry_size < 16 or entry_count > 64:
        raise InputError(f"{where}: implausible DTBO entry table")
    if entries_offset + entry_size * entry_count > len(data):
        raise InputError(f"{where}: DTBO entry table exceeds input")
    entries = []
    for index in range(entry_count):
        offset = entries_offset + index * entry_size
        size, dtb_offset, ident, revision = struct.unpack(">IIII", data[offset : offset + 16])
        if dtb_offset + size > len(data):
            raise InputError(f"{where}: DTBO entry {index} exceeds input")
        fdt = data[dtb_offset : dtb_offset + 8]
        if len(fdt) < 8 or struct.unpack(">I", fdt[:4])[0] != FDT_MAGIC:
            raise InputError(f"{where}: DTBO entry {index} does not contain an FDT")
        entries.append(
            {
                "size": size,
                "offset": dtb_offset,
                "id": ident,
                "revision": revision,
                "fdt_size": struct.unpack(">I", fdt[4:8])[0],
            }
        )
    return {
        "magic": hex(magic),
        "total_size": total,
        "header_size": header_size,
        "entry_size": entry_size,
        "entry_count": entry_count,
        "entries_offset": entries_offset,
        "page_size": page,
        "version": version,
        "entries": entries,
    }


def parse_vendor_boot(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if len(data) < 2128 or data[:8] != VENDOR_BOOT_MAGIC:
        raise InputError(f"{path}: not an Android vendor_boot image")
    header_version = u32le(data, 8)
    page = u32le(data, 12)
    vendor_ramdisk_size = u32le(data, 24)
    header_size = u32le(data, 2096)
    dtb_size = u32le(data, 2100)
    table_size = u32le(data, 2112)
    entry_count = u32le(data, 2116)
    entry_size = u32le(data, 2120)
    if page < 4096 or header_version != 4:
        raise InputError(f"{path}: unsupported vendor_boot header v{header_version} page {page}")
    dtb_offset = page + align(vendor_ramdisk_size, page)
    table_offset = dtb_offset + align(dtb_size, page)
    if table_offset + table_size > len(data):
        raise InputError(f"{path}: vendor ramdisk table exceeds image")
    fragments = []
    for index in range(entry_count):
        base = table_offset + index * entry_size
        size, offset, kind = struct.unpack_from("<III", data, base)
        name = data[base + 12 : base + 44].split(b"\0", 1)[0].decode("utf-8", "replace")
        fragments.append(
            {
                "index": index,
                "type": kind,
                "type_name": {1: "platform", 2: "recovery"}.get(kind, "unknown"),
                "name": name,
                "size": size,
                "offset": offset,
            }
        )
    dtb = data[dtb_offset : dtb_offset + dtb_size]
    return {
        "magic": data[:8].decode("ascii"),
        "header_version": header_version,
        "page_size": page,
        "header_size": header_size,
        "vendor_ramdisk_size": vendor_ramdisk_size,
        "dtb_size": dtb_size,
        "dtb_offset": dtb_offset,
        "table_offset": table_offset,
        "table_size": table_size,
        "fragment_table": fragments,
        "dtb_container": parse_dtbo_container(dtb, f"{path}:dtb"),
        "file_size": len(data),
    }


def parse_live_state(path: Path) -> dict[str, str]:
    document = load_json(path)
    values: dict[str, str] = {}
    for item in document.get("results", []):
        variable = item.get("variable", "")
        prefix = variable + ":"
        for line in item.get("stderr", "").splitlines():
            if line.startswith(prefix):
                values[variable] = line[len(prefix) :].strip()
                break
    return values


def resolve_project_path(project_root: Path, raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else (project_root / path)


def resolve_device_path(device_root: Path, raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else (device_root / path)


def check_generated(device_root: Path, errors: list[str]) -> None:
    generator = device_root / "config" / "generate_device_config.py"
    if not generator.is_file():
        errors.append("config/generate_device_config.py missing")
        return
    result = subprocess.run(
        [sys.executable, str(generator), "--check", "--device-root", str(device_root)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip().replace("\n", " ")
        errors.append(f"generated make fragments are stale or missing: {detail}")


def check_identity(cfg: dict[str, Any], errors: list[str]) -> None:
    device = cfg.get("device", {})
    architecture = cfg.get("architecture", {})
    if device.get("codename") != "rothko":
        errors.append(f"identity: codename is {device.get('codename')!r}, expected 'rothko'")
    if device.get("platform") != "mt6989":
        errors.append(f"identity: platform is {device.get('platform')!r}, expected 'mt6989'")
    if device.get("model") != "2407FRK8EC":
        errors.append(f"identity: model is {device.get('model')!r}, expected '2407FRK8EC'")
    if architecture.get("arch") != "arm64":
        errors.append(f"identity: arch is {architecture.get('arch')!r}, expected 'arm64'")
    if architecture.get("supports_32_bit_apps") is not False or architecture.get("supports_64_bit_apps") is not True:
        errors.append("app ABI: device-specific vendor/ODM requires 64-bit apps only")
    if architecture.get("zygote") != "zygote64":
        errors.append("app ABI: zygote must match effective ODM zygote64")
    if architecture.get("retain_native_32_bit_variants") and architecture.get("second_arch") != "arm":
        errors.append("native ABI: ARM32 variants were removed before dependency verification")
    vendor_api = device.get("vendor_api_level", device.get("vendor_sdk"))
    if vendor_api != 34:
        errors.append(
            f"identity: vendor API level is {vendor_api!r}, expected 34 "
            "(Android 14/SDK 34 vendor stack, FCM target-level 8); "
            "do not set 36 because the boot image is Android 16"
        )
    if device.get("framework_target_level") != 8:
        errors.append(
            f"identity: framework target-level is {device.get('framework_target_level')!r}, expected 8"
        )
    if device.get("sepolicy_version") != "34.0":
        errors.append(
            f"identity: sepolicy version is {device.get('sepolicy_version')!r}, expected '34.0'"
        )
    if device.get("vndk_version") != "34":
        errors.append(f"identity: VNDK version is {device.get('vndk_version')!r}, expected '34'")
    if cfg.get("build_plan", {}).get("shipping_api_level") != 34:
        errors.append("identity: shipping API level must remain 34, not 36")
    if "ready" not in cfg.get("release_readiness", {}):
        errors.append("identity: release_readiness.ready is missing")
    partitions = cfg.get("partitions", {})
    for name in cfg.get("super", {}).get("ota_group", {}).get("partitions", []):
        if name not in partitions:
            errors.append(f"identity: group partition {name} has no parameter entry")
    for name in ("boot", "vendor_boot", "dtbo", "vendor", "odm", "system_dlkm", "vendor_dlkm", "odm_dlkm"):
        if partitions.get(name, {}).get("use") != "prebuilt_stock":
            errors.append(f"build plan: {name} must be a stock prebuilt image")
    for name in ("init_boot", "boot", "vendor_boot", "dtbo"):
        if partitions.get(name, {}).get("use") != "prebuilt_stock":
            errors.append(f"build plan: {name} must be a stock prebuilt image")
    for name in ("system", "system_ext", "product"):
        if partitions.get(name, {}).get("use") != "built_by_lineage":
            errors.append(f"build plan: {name} must be built by Lineage")


def check_budget(cfg: dict[str, Any], errors: list[str]) -> None:
    parts = cfg["partitions"]
    group = cfg["super"]["ota_group"]
    names = group["partitions"]
    total = sum(int(parts[name]["stock_payload_size"]) for name in names)
    if total != cfg["super"]["sum_ota_partition_sizes"]:
        errors.append(
            "super: sum of OTA partition sizes "
            f"{total} != recorded {cfg['super']['sum_ota_partition_sizes']}"
        )
    if total > group["size"]:
        errors.append(f"super: partition sum {total} exceeds group {group['name']} size {group['size']}")
    if group["size"] > cfg["super"]["live_size"]:
        errors.append(
            f"super: group size {group['size']} exceeds live super size {cfg['super']['live_size']}"
        )
    if group["size"] - total != cfg["super"]["ota_group_slack"]:
        errors.append("super: recorded group slack does not match the partition sum")
    if cfg["super"]["live_size"] - group["size"] != cfg["super"]["super_group_gap"]:
        errors.append("super: recorded super/group gap does not match the sizes")
    target_names = cfg["super"].get("build_target_partitions", [])
    if target_names:
        target_sum = sum(int(parts[name]["stock_payload_size"]) for name in target_names)
        if target_sum != cfg["super"].get("target_partition_sum"):
            errors.append("super: build-target partition sum does not match the recorded target sum")
        if target_sum > group["size"]:
            errors.append("super: build-target partition sum exceeds the OTA group size")
        if group["size"] - target_sum != cfg["super"].get("target_group_slack"):
            errors.append("super: build-target group slack does not match")


def check_vendor_contract(vendor_root: Path, cfg: dict[str, Any], errors: list[str]) -> None:
    board = vendor_root / "BoardConfigVendor.mk"
    product = vendor_root / "rothko-vendor.mk"
    staged = vendor_root / "prebuilt" / "staged-manifest.json"
    if not vendor_root.is_dir():
        errors.append(
            "vendor/xiaomi/rothko missing; the vendor lane must provide BoardConfigVendor.mk, "
            "rothko-vendor.mk and prebuilt stock images"
        )
        return
    for path in (board, product, staged):
        if not path.is_file():
            errors.append(f"vendor contract file missing: {path.relative_to(vendor_root)}")
    if board.is_file():
        text = board.read_text(encoding="utf-8", errors="replace")
        expected_flags = {
            "boot": "BOARD_PREBUILT_BOOTIMAGE",
            "init_boot": "BOARD_PREBUILT_INIT_BOOT_IMAGE",
            "vendor_boot": "BOARD_PREBUILT_VENDOR_BOOTIMAGE",
            "dtbo": "BOARD_PREBUILT_DTBOIMAGE",
            "vendor": "BOARD_PREBUILT_VENDORIMAGE",
            "odm": "BOARD_PREBUILT_ODMIMAGE",
            "system_dlkm": "BOARD_PREBUILT_SYSTEM_DLKMIMAGE",
            "vendor_dlkm": "BOARD_PREBUILT_VENDOR_DLKMIMAGE",
            "odm_dlkm": "BOARD_PREBUILT_ODM_DLKMIMAGE",
        }
        for name, flag in expected_flags.items():
            if flag not in text:
                errors.append(f"vendor BoardConfigVendor.mk does not set {flag} for {name}")
        if "ROTHKO_HARDWARE_RELEASE_READY := false" not in text:
            errors.append("vendor BoardConfigVendor.mk must keep ROTHKO_HARDWARE_RELEASE_READY := false")
    if staged.is_file():
        try:
            manifest = load_json(staged)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"vendor staged-manifest.json unreadable: {exc}")
        else:
            if manifest.get("hardware_release_ready") is not False:
                errors.append("vendor staged-manifest.json hardware_release_ready must be false")
            images = set(manifest.get("images", {}))
            required = set(cfg.get("prebuilt_integrity", {}).get("required", []))
            missing = sorted(required - images)
            if missing:
                errors.append("vendor staged-manifest.json missing images: " + ", ".join(missing))


def check_prebuilts(cfg: dict[str, Any], vendor_root: Path, errors: list[str]) -> None:
    integrity = cfg.get("prebuilt_integrity", {})
    expected = {
        name for name, part in cfg["partitions"].items() if part.get("use") == "prebuilt_stock"
    }
    required = set(integrity.get("required", []))
    if required != expected:
        errors.append(
            "prebuilt_integrity.required does not match the configured stock partitions: "
            f"missing={sorted(expected - required)} extra={sorted(required - expected)}"
        )
    if integrity.get("source_receipt_all_verified") is not True:
        errors.append("prebuilt_integrity.source_receipt_all_verified must be true")
    manifest_path = vendor_root / "prebuilt" / "staged-manifest.json"
    try:
        manifest = load_json(manifest_path)
        manifest_images = manifest.get("images", {})
    except (OSError, json.JSONDecodeError):
        manifest_images = {}
    missing = []
    for name, part in cfg["partitions"].items():
        if part.get("use") != "prebuilt_stock":
            continue
        path = vendor_root / "prebuilt" / f"{name}.img"
        if not path.is_file():
            missing.append(name)
            continue
        size = path.stat().st_size
        if size != part["stock_payload_size"]:
            errors.append(
                f"prebuilt/{name}.img size {size} != expected {part['stock_payload_size']}"
            )
            continue
        recorded = manifest_images.get(name, {})
        if recorded.get("size") != part["stock_payload_size"]:
            errors.append(f"vendor staged-manifest.json: {name}.size does not match the device config")
        if recorded.get("sha256") != part["stock_payload_sha256"]:
            errors.append(f"vendor staged-manifest.json: {name}.sha256 does not match the device config")
    if missing:
        errors.append(
            "prebuilt images missing: "
            + ", ".join(missing)
            + "; vendor lane must stage them under vendor/xiaomi/rothko/prebuilt"
        )


def check_mi_ext(cfg: dict[str, Any], vendor_root: Path, errors: list[str]) -> None:
    mi_ext = cfg.get("build_plan", {}).get("mi_ext", {})
    allowed = {"inspection_pending", "checked_no_native_driver_evidence"}
    if mi_ext.get("status") not in allowed:
        errors.append("mi_ext: status must be inspection_pending or checked_no_native_driver_evidence")
    if mi_ext.get("target_mount") is not False:
        errors.append("mi_ext: target_mount must remain false in phase 1")
    if mi_ext.get("partition_preserved") is not True:
        errors.append("mi_ext: phone partition must be preserved")
    if mi_ext.get("build_hook") != "none":
        errors.append("mi_ext: no build hook may be assumed")
    if mi_ext.get("status") == "checked_no_native_driver_evidence" and mi_ext.get("native_driver_evidence") is not False:
        errors.append("mi_ext: checked status must record no native driver evidence")


def check_vendor_evidence(cfg: dict[str, Any], device_root: Path, errors: list[str]) -> None:
    path = device_root / "config" / "vendor-integration-evidence.json"
    if not path.is_file():
        errors.append("config/vendor-integration-evidence.json missing")
        return
    try:
        evidence = load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"vendor-integration-evidence.json unreadable: {exc}")
        return
    if evidence.get("schema") != 1:
        errors.append("vendor-integration-evidence.json: schema must be 1")
    summary = cfg.get("vendor_integration", {})
    for key, value in (
        ("vendor_api_level", summary.get("vendor_api_level")),
        ("first_api_level", summary.get("first_api_level")),
        ("framework_target_level", summary.get("framework_target_level")),
        ("sepolicy_version", summary.get("sepolicy_version")),
        ("vndk_version", summary.get("vndk_version")),
        ("pending_framework_unique_libraries", summary.get("pending_framework_unique_libraries")),
    ):
        if key in ("pending_framework_unique_libraries",):
            actual = evidence.get("hal_elf", {}).get(key)
        else:
            actual = evidence.get(key)
        if actual != value:
            errors.append(
                f"vendor-integration-evidence.json: {key}={actual!r} does not match device config {value!r}"
            )
    for key, wanted in (
        ("vendor_api_level", 34),
        ("first_api_level", 34),
        ("framework_target_level", 8),
        ("sepolicy_version", "34.0"),
        ("vndk_version", "34"),
    ):
        if evidence.get(key) != wanted:
            errors.append(
                f"vendor-integration-evidence.json: {key}={evidence.get(key)!r}, expected {wanted!r}"
            )
    if evidence.get("vintf", {}).get("checkvintf_result") is None:
        errors.append("vendor-integration-evidence.json: no checkvintf result; do not claim VINTF pass")
    if evidence.get("selinux", {}).get("neverallow_result") is None:
        errors.append("vendor-integration-evidence.json: no SELinux neverallow result; do not claim pass")
    hal_elf = evidence.get("hal_elf", {})
    pending = hal_elf.get("pending_framework_unique_libraries")
    if pending != 0:
        errors.append(
            f"vendor-integration-evidence.json: {pending} framework-provided candidate libraries "
            "remain pending baseline; do not assume system_ext provides them"
        )
    missing_nonbase = hal_elf.get("missing_nonbase")
    if missing_nonbase != 0:
        errors.append(
            f"vendor-integration-evidence.json: {missing_nonbase} non-base-tagged dependencies are "
            "unresolved (mostly Android graphics/common/memtrack interfaces); do not assume system_ext"
        )
    namespace = str(evidence.get("linker", {}).get("namespace_status", ""))
    if namespace.startswith("unknown"):
        errors.append(
            "vendor-integration-evidence.json: linker namespace reachability is unknown; "
            "do not claim the HAL dependency check passed"
        )
    vndk = evidence.get("vndk_compatibility", {})
    if vndk.get("vndk_version") != "34":
        errors.append("vendor-integration-evidence.json: VNDK version must be 34")
    if vndk.get("status") != "verified":
        errors.append(
            "vendor-integration-evidence.json: VNDK 34 compatibility is pending build-baseline "
            "system/system_ext/product artifacts and linker/checkvintf checks"
        )
    if evidence.get("status", "").startswith("incomplete") or evidence.get("claim") != "passed":
        errors.append(
            "vendor-integration-evidence.json: vendor integration is not passed: "
            f"{evidence.get('status', 'missing status')}"
        )


def check_module_evidence(cfg: dict[str, Any], device_root: Path, errors: list[str]) -> None:
    path = device_root / "config" / "module-compatibility.json"
    if not path.is_file():
        errors.append("config/module-compatibility.json missing")
        return
    try:
        evidence = load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"module-compatibility.json unreadable: {exc}")
        return
    module = cfg.get("module_compatibility", {})
    if evidence.get("schema") != 1:
        errors.append("module-compatibility.json: schema must be 1")
    if evidence.get("boot_kernel_release") != module.get("boot_kernel_release"):
        errors.append("module-compatibility.json: boot kernel release does not match the device config")
    if evidence.get("kernel_config", {}).get("CONFIG_MODVERSIONS") != "y":
        errors.append("module-compatibility.json: CONFIG_MODVERSIONS is not recorded as y")
    if evidence.get("kernel_config", {}).get("CONFIG_MODULE_SIG_FORCE") != "not set":
        errors.append("module-compatibility.json: CONFIG_MODULE_SIG_FORCE must be recorded as not set")
    sets = evidence.get("module_sets", {})
    for key, wanted in (
        ("system_dlkm", module.get("system_dlkm_module_count")),
        ("vendor_dlkm", module.get("vendor_dlkm_module_count")),
        ("vendor_boot_ramdisk00", module.get("vendor_boot_module_count")),
    ):
        if sets.get(key, {}).get("module_count") != wanted:
            errors.append(f"module-compatibility.json: {key} module count does not match device config")
    crc = evidence.get("crc_cross_check", {})
    for key in ("vendor_dlkm_crc_mismatches", "vendor_boot_crc_mismatches"):
        if crc.get(key) != 0:
            errors.append(f"module-compatibility.json: {key} is not zero")
    summary_crc = module.get("crc_cross_check", {})
    for key in ("vendor_dlkm_overlap_symbols", "vendor_boot_overlap_symbols", "vendor_dlkm_overlap_occurrences", "vendor_boot_overlap_occurrences"):
        if crc.get(key) != summary_crc.get(key):
            errors.append(f"module-compatibility.json: {key} does not match device config")
    same_magic = evidence.get("same_magic", {})
    if same_magic.get("release_prefix_ignored_when_has_crcs") is not True:
        errors.append("module-compatibility.json: same_magic has_crcs handling is not recorded")
    if same_magic.get("crc_section_present_modules") != (
        module.get("system_dlkm_module_count", 0)
        + module.get("vendor_dlkm_module_count", 0)
        + module.get("vendor_boot_module_count", 0)
    ):
        errors.append("module-compatibility.json: not every module has __versions")
    if same_magic.get("vermagic_suffix_variants") != 1:
        errors.append("module-compatibility.json: vermagic suffix is not uniform")
    if same_magic.get("module_layout_crc_mismatches") != 0:
        errors.append("module-compatibility.json: module_layout CRC mismatch")
    if evidence.get("status") == "incompatible":
        errors.append("module-compatibility.json: status is incompatible")
    if evidence.get("status") != (
        "same_magic_suffix_match_crc_overlap_consistent_module_layout_match_kernel_crcs_unverified_runtime_unproven"
    ):
        errors.append("module-compatibility.json: unexpected status")


def _require(mapping: dict[str, Any], key: str, label: str, errors: list[str]) -> Any:
    value = mapping.get(key)
    if value in (None, "", [], {}):
        errors.append(f"vendor-inventory.json: {label}.{key} is missing")
    return value


def check_inventory(
    cfg: dict[str, Any], device_root: Path, inventory_path: Path, errors: list[str]
) -> None:
    if not inventory_path.is_file():
        errors.append(
            "config/vendor-inventory.json missing; required evidence: vendor/odm/dlkm "
            "images, VINTF manifest+matrix+check result, enforcing SELinux policy+neverallow "
            "result, verified HAL inventory, verified kernel-module match, shipping API level"
        )
        return
    try:
        inventory = load_json(inventory_path)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"vendor-inventory.json unreadable: {exc}")
        return

    if inventory.get("schema") != 1:
        errors.append("vendor-inventory.json: schema must be 1")
    if inventory.get("device") != "rothko":
        errors.append("vendor-inventory.json: device must be rothko")
    if inventory.get("source_firmware") != cfg["device"]["firmware_incremental"]:
        errors.append(
            "vendor-inventory.json: source_firmware must match "
            f"{cfg['device']['firmware_incremental']}"
        )

    images = inventory.get("images", {})
    required_images = [
        name
        for name, part in cfg["partitions"].items()
        if part.get("use") in ("prebuilt_stock", "prebuilt_stock_blocked")
        and name not in ("boot", "init_boot", "vendor_boot", "dtbo")
    ]
    for name in required_images:
        entry = images.get(name)
        if not isinstance(entry, dict):
            errors.append(f"vendor-inventory.json: images.{name} is missing")
            continue
        raw_path = _require(entry, "path", f"images.{name}", errors)
        size = _require(entry, "size", f"images.{name}", errors)
        digest = _require(entry, "sha256", f"images.{name}", errors)
        expected = cfg["partitions"][name]
        if size not in (None, "") and size != expected["stock_payload_size"]:
            errors.append(f"vendor-inventory.json: images.{name}.size does not match stock payload")
        if digest not in (None, "") and digest != expected["stock_payload_sha256"]:
            errors.append(f"vendor-inventory.json: images.{name}.sha256 does not match stock payload")
        if raw_path:
            path = resolve_device_path(device_root, str(raw_path))
            if not path.is_file():
                errors.append(f"vendor-inventory.json: images.{name}.path does not exist: {path}")
            else:
                if path.stat().st_size != entry.get("size"):
                    errors.append(f"vendor-inventory.json: images.{name}.size mismatch")
                if sha256_file(path) != entry.get("sha256"):
                    errors.append(f"vendor-inventory.json: images.{name}.sha256 mismatch")

    vintf = inventory.get("vintf", {})
    for key in ("vendor_manifest", "vendor_matrix", "framework_matrix"):
        entry = vintf.get(key)
        if not isinstance(entry, dict):
            errors.append(f"vendor-inventory.json: vintf.{key} is missing")
            continue
        raw_path = _require(entry, "path", f"vintf.{key}", errors)
        digest = _require(entry, "sha256", f"vintf.{key}", errors)
        if raw_path:
            path = resolve_device_path(device_root, str(raw_path))
            if not path.is_file():
                errors.append(f"vendor-inventory.json: vintf.{key}.path does not exist: {path}")
            elif digest and sha256_file(path) != digest:
                errors.append(f"vendor-inventory.json: vintf.{key}.sha256 mismatch")
    vintf_check = vintf.get("check", {})
    if vintf_check.get("result") != "compatible":
        errors.append("vendor-inventory.json: vintf.check.result must be 'compatible'")
    if not vintf_check.get("tool"):
        errors.append("vendor-inventory.json: vintf.check.tool is missing")
    if not vintf_check.get("log"):
        errors.append("vendor-inventory.json: vintf.check.log is missing")
    else:
        log_path = resolve_device_path(device_root, str(vintf_check["log"]))
        if not log_path.is_file():
            errors.append(f"vendor-inventory.json: vintf.check.log does not exist: {log_path}")

    selinux = inventory.get("selinux", {})
    if selinux.get("mode") != "enforcing":
        errors.append("vendor-inventory.json: selinux.mode must be 'enforcing'")
    _require(selinux, "vendor_policy_sha256", "selinux", errors)
    neverallow = selinux.get("neverallow", {})
    if neverallow.get("result") != "pass":
        errors.append("vendor-inventory.json: selinux.neverallow.result must be 'pass'")
    if not neverallow.get("log"):
        errors.append("vendor-inventory.json: selinux.neverallow.log is missing")
    else:
        log_path = resolve_device_path(device_root, str(neverallow["log"]))
        if not log_path.is_file():
            errors.append(f"vendor-inventory.json: selinux.neverallow.log does not exist: {log_path}")

    hal_inventory = inventory.get("hal_inventory", {})
    if hal_inventory.get("verified") is not True:
        errors.append("vendor-inventory.json: hal_inventory.verified must be true")
    if not hal_inventory.get("source"):
        errors.append("vendor-inventory.json: hal_inventory.source is missing")
    kernel_modules = inventory.get("kernel_modules", {})
    if kernel_modules.get("verified") is not True:
        errors.append("vendor-inventory.json: kernel_modules.verified must be true")
    if not kernel_modules.get("source"):
        errors.append("vendor-inventory.json: kernel_modules.source is missing")
    if inventory.get("shipping_api_level") != cfg["device"]["vendor_sdk"]:
        errors.append(
            "vendor-inventory.json: shipping_api_level must match vendor SDK "
            f"{cfg['device']['vendor_sdk']}"
        )
    mi_ext = inventory.get("mi_ext_integration", {})
    if mi_ext.get("implemented") is not True:
        errors.append("vendor-inventory.json: mi_ext_integration.implemented must be true")
    if not mi_ext.get("build_hook"):
        errors.append("vendor-inventory.json: mi_ext_integration.build_hook is missing")
    if not mi_ext.get("mechanism"):
        errors.append("vendor-inventory.json: mi_ext_integration.mechanism is missing")


def check_forbidden(cfg: dict[str, Any], device_root: Path, errors: list[str]) -> None:
    patterns = cfg.get("gates", {}).get("forbidden_code_patterns", [])
    commands = cfg.get("gates", {}).get("forbidden_script_commands", [])
    make_files = sorted(device_root.rglob("*.mk"))
    scripts = sorted((device_root / "scripts").glob("*"))
    for path in make_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in patterns:
            if pattern in text:
                errors.append(f"forbidden configuration in {path.relative_to(device_root)}: {pattern}")
    for path in scripts:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in patterns:
            if pattern in text:
                errors.append(f"forbidden configuration in scripts/{path.name}: {pattern}")
        for command in commands:
            if re.search(rf"(?<![\w-]){re.escape(command)}(?![\w-])", text, re.IGNORECASE):
                errors.append(f"device operation token in scripts/{path.name}: {command}")


def check_release_gate(cfg: dict[str, Any], errors: list[str]) -> None:
    readiness = cfg.get("release_readiness", {})
    if readiness.get("ready") is not True:
        errors.append(
            "release readiness is false: full/OTA build is not release-ready "
            "(snapshot/overlay/ABI/VINTF/neverallow/VNDK34; mi_ext checked with no "
            "native driver evidence but target not mounted)"
        )
    if cfg.get("prebuilt_integrity", {}).get("hardware_release_ready") is not True:
        errors.append("release readiness: vendor hardware_release_ready must be true")
    mi_ext = cfg.get("build_plan", {}).get("mi_ext", {})
    if mi_ext.get("status") not in {"inspection_pending", "checked_no_native_driver_evidence"} or mi_ext.get("target_mount") is not False:
        errors.append("release readiness: mi_ext must remain not target-mounted with checked/pending status")


def check_vendor_integration_evidence(device_root: Path, project_root: Path, errors: list[str]) -> None:
    evidence_path = device_root / "config" / "vendor-integration-evidence.json"
    inventory_path = project_root / "firmware" / "reports" / "inventory.json"
    gaps_path = project_root / "firmware" / "reports" / "nonbase-gaps.tsv"
    if not evidence_path.is_file():
        errors.append("config/vendor-integration-evidence.json missing")
        return
    if not inventory_path.is_file() or not gaps_path.is_file():
        errors.append("vendor evidence inputs missing: inventory.json or nonbase-gaps.tsv")
        return
    evidence = load_json(evidence_path)
    inventory = load_json(inventory_path)
    sources = evidence.get("sources", {})
    for key, record in sources.items():
        raw = record.get("path")
        digest = record.get("sha256")
        if not raw or not digest:
            errors.append(f"vendor-integration-evidence.json: sources.{key} path/sha256 missing")
            continue
        path = resolve_project_path(project_root, raw)
        if not path.is_file():
            errors.append(f"vendor-integration-evidence.json: sources.{key} missing: {path}")
        elif sha256_file(path) != digest:
            errors.append(f"vendor-integration-evidence.json: sources.{key} sha256 mismatch")

    vintf = inventory.get("vintf", {})
    expected_vintf = {
        "manifest_matrix_files": len(vintf.get("files", [])),
        "hal_names": len(vintf.get("hal_names", [])),
        "kernel_versions": vintf.get("kernel_versions", []),
    }
    for key, value in expected_vintf.items():
        if evidence.get("vintf", {}).get(key) != value:
            errors.append(f"vendor-integration-evidence.json: vintf.{key} does not match inventory")
    if str(evidence.get("framework_target_level")) not in [str(x) for x in vintf.get("target_levels", [])]:
        errors.append("vendor-integration-evidence.json: framework target-level does not match inventory")

    selinux = inventory.get("selinux", {})
    if evidence.get("selinux", {}).get("policy_files") != len(selinux.get("files", [])):
        errors.append("vendor-integration-evidence.json: SELinux policy file count does not match inventory")
    versions = [item.get("text", "").strip() for item in selinux.get("version_files", [])]
    if evidence.get("sepolicy_version") not in versions:
        errors.append("vendor-integration-evidence.json: sepolicy version does not match inventory")
    if evidence.get("selinux", {}).get("precompiled_present") != selinux.get("precompiled_present"):
        errors.append("vendor-integration-evidence.json: precompiled policy flag does not match inventory")

    linker = inventory.get("linker_evidence", {})
    if evidence.get("linker", {}).get("config_files") != len(linker.get("files", [])):
        errors.append("vendor-integration-evidence.json: linker config file count does not match inventory")
    if evidence.get("linker", {}).get("namespace_status") != linker.get("namespace_status"):
        errors.append("vendor-integration-evidence.json: linker namespace status does not match inventory")
    if evidence.get("linker", {}).get("public_libraries") != len(linker.get("public_libraries", [])):
        errors.append("vendor-integration-evidence.json: public library count does not match inventory")
    if evidence.get("linker", {}).get("vndk_artifacts") != len(linker.get("vndk_artifacts", [])):
        errors.append("vendor-integration-evidence.json: VNDK artifact count does not match inventory")
    vndk_values = [item.get("value") for item in inventory.get("build_props", {}).get("ro.product.vndk.version", [])]
    if evidence.get("vndk_version") not in vndk_values:
        errors.append("vendor-integration-evidence.json: VNDK version does not match inventory")

    hal_elf = inventory.get("hal_elf", [])
    pending_rows = sum(len(item.get("unresolved_framework_candidates", [])) for item in hal_elf)
    missing_nonbase = sum(len(item.get("missing_nonbase", [])) for item in hal_elf)
    cross_partition = sum(len(item.get("cross_partition_dependencies", [])) for item in hal_elf)
    statuses: dict[str, int] = {}
    unique_pending: set[str] = set()
    unique_unknown: set[str] = set()
    with gaps_path.open("r", encoding="utf-8", errors="replace") as handle:
        next(handle, None)
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 4:
                continue
            library, status = fields[2], fields[3]
            statuses[status] = statuses.get(status, 0) + 1
            if status == "unresolved_framework_candidate_pending_baseline":
                unique_pending.add(library)
            elif status not in ("file_present_namespace_unknown",):
                unique_unknown.add(library)
    hals_with_file_candidates = sum(
        1
        for item in hal_elf
        if any(dep.get("file_present_same_abi") for dep in item.get("dependencies", []))
    )
    hals_with_framework_candidates = sum(
        1 for item in hal_elf if item.get("unresolved_framework_candidates")
    )
    expected_hal = {
        "hal_count": len(hal_elf),
        "cross_partition_dependencies": cross_partition,
        "pending_framework_rows": pending_rows,
        "pending_framework_unique_libraries": len(unique_pending),
        "missing_nonbase": missing_nonbase,
        "unknown_nonbase_unique": len(unique_unknown),
        "hals_with_file_candidates": hals_with_file_candidates,
        "hals_with_framework_candidates": hals_with_framework_candidates,
    }
    release_claim = evidence.get("claim") == "passed"
    snapshot_only = {"pending_framework_rows", "pending_framework_unique_libraries"}
    for key, value in expected_hal.items():
        if not release_claim and key in snapshot_only:
            continue
        if evidence.get("hal_elf", {}).get(key) != value:
            errors.append(f"vendor-integration-evidence.json: hal_elf.{key} does not match inventory")


def check_module_abi(device_root: Path, project_root: Path, errors: list[str]) -> None:
    script = device_root / "scripts" / "check_module_abi.py"
    if not script.is_file():
        errors.append("scripts/check_module_abi.py missing")
        return
    result = subprocess.run(
        [sys.executable, str(script), "--check", "--device-root", str(device_root), "--project-root", str(project_root)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip().replace("\n", " ")
        errors.append(f"module compatibility evidence is stale: {detail}")


def check_evidence(cfg: dict[str, Any], device_root: Path, project_root: Path, errors: list[str]) -> None:
    parts = cfg["partitions"]

    app_evidence = device_root / "config" / "app-abi-evidence.json"
    if not app_evidence.is_file():
        errors.append("app ABI decision evidence missing")
    else:
        for raw, expected in load_json(app_evidence).get("sources", {}).items():
            source = resolve_project_path(project_root, raw)
            if not source.is_file() or sha256_file(source) != expected:
                errors.append(f"app ABI source missing or changed: {raw}")

    for name, part in parts.items():
        raw = part.get("source")
        if not raw:
            continue
        path = resolve_project_path(project_root, str(raw))
        if not path.is_file():
            errors.append(f"evidence input missing: {path}")
            continue
        if path.stat().st_size != part["stock_payload_size"]:
            errors.append(f"{name}: input size {path.stat().st_size} != {part['stock_payload_size']}")
        digest = sha256_file(path)
        if digest != part["stock_payload_sha256"]:
            errors.append(f"{name}: input sha256 {digest} != {part['stock_payload_sha256']}")

        header = part.get("header")
        if name in ("boot", "init_boot") and header:
            parsed = parse_boot_header(path)
            for key in ("magic", "header_version", "kernel_size", "ramdisk_size"):
                if parsed[key] != header[key]:
                    errors.append(f"{name}: {key} {parsed[key]!r} != recorded {header[key]!r}")
        if name == "vendor_boot" and header:
            parsed = parse_vendor_boot(path)
            for key in ("magic", "header_version", "page_size", "vendor_ramdisk_size", "dtb_size"):
                if parsed[key] != header[key]:
                    errors.append(f"{name}: {key} {parsed[key]!r} != recorded {header[key]!r}")
            if parsed["fragment_table"] != header["fragment_table"]:
                errors.append(f"{name}: vendor ramdisk fragment table does not match")
            recorded_dtb = part["dtb_container"]
            actual_dtb = parsed["dtb_container"]
            for key in ("magic", "entry_count", "total_size"):
                if actual_dtb[key] != recorded_dtb[key]:
                    errors.append(f"{name}: dtb container {key} {actual_dtb[key]!r} != {recorded_dtb[key]!r}")
            if actual_dtb["entries"][0]["size"] != recorded_dtb["fdt_size"]:
                errors.append(f"{name}: base DTB size does not match")
        if name == "dtbo":
            parsed = parse_dtbo_container(path.read_bytes(), str(path))
            recorded = part["container"]
            for key in ("magic", "entry_count", "total_size"):
                if parsed[key] != recorded[key]:
                    errors.append(f"{name}: container {key} {parsed[key]!r} != {recorded[key]!r}")
            if parsed["entries"][0]["size"] != recorded["fdt_size"]:
                errors.append(f"{name}: overlay FDT size does not match")

    manifest_path = project_root / "logs" / "parent-manifest-expectations.json"
    if manifest_path.is_file():
        manifest = load_json(manifest_path)
        for name, part in parts.items():
            record = manifest.get("partitions", {}).get(name)
            if not record:
                continue
            if record.get("size") != part["stock_payload_size"]:
                errors.append(f"{name}: manifest size does not match config")
            if record.get("hash") != part["stock_payload_sha256"]:
                errors.append(f"{name}: manifest hash does not match config")
    else:
        errors.append(f"evidence log missing: {manifest_path}")

    metadata_path = project_root / "logs" / "parent-dynamic-partition-metadata.json"
    if metadata_path.is_file():
        metadata = load_json(metadata_path)
        group = metadata.get("groups", [{}])[0]
        if group.get("name") != cfg["super"]["ota_group"]["name"]:
            errors.append("super: OTA group name does not match metadata")
        if group.get("size") != cfg["super"]["ota_group"]["size"]:
            errors.append("super: OTA group size does not match metadata")
        if group.get("partitions") != cfg["super"]["ota_group"]["partitions"]:
            errors.append("super: OTA group partition list does not match metadata")
        if metadata.get("live_super_size_bytes") != cfg["super"]["live_size"]:
            errors.append("super: live size does not match metadata")
        vab = cfg["virtual_ab"]
        if metadata.get("snapshot_enabled") != int(vab["snapshot_enabled"]):
            errors.append("virtual A/B: snapshot_enabled does not match metadata")
        if metadata.get("vabc_enabled") != int(vab["vabc_enabled"]):
            errors.append("virtual A/B: vabc_enabled does not match metadata")
        if metadata.get("vabc_compression_param") != vab["compression"]:
            errors.append("virtual A/B: compression does not match metadata")
        if metadata.get("cow_version") != vab["cow_version"]:
            errors.append("virtual A/B: cow_version does not match metadata")
        if metadata.get("compression_factor") != vab["compression_factor"]:
            errors.append("virtual A/B: compression_factor does not match metadata")
    else:
        errors.append(f"evidence log missing: {metadata_path}")

    live_path = project_root / "logs" / "live-fastboot-readonly-20261031.json"
    if live_path.is_file():
        live = parse_live_state(live_path)
        expected = {
            "product": "rothko",
            "current-slot": "a",
            "slot-successful:a": "yes",
            "slot-successful:b": "no",
            "slot-unbootable:a": "no",
            "slot-unbootable:b": "yes",
            "partition-size:super": cfg["super"]["live_size_hex"].removeprefix("0x"),
            "partition-size:boot_a": "4000000",
            "partition-size:vendor_boot_a": "4000000",
            "partition-size:init_boot_a": "800000",
            "partition-size:dtbo_a": "800000",
        }
        for key, wanted in expected.items():
            if live.get(key) != wanted:
                errors.append(f"live state: {key}={live.get(key)!r} != {wanted!r}")
    else:
        errors.append(f"evidence log missing: {live_path}")

    inventory_path = project_root / "firmware" / "reports" / "ramdisk_inventory.json"
    if inventory_path.is_file():
        inventory = load_json(inventory_path)
        vendor_boot = parts["vendor_boot"]
        recorded_images = inventory.get("input_images", {})
        for key in ("init_boot", "vendor_boot"):
            if recorded_images.get(key, {}).get("sha256") != parts[key]["stock_payload_sha256"]:
                errors.append(f"ramdisk inventory: {key} hash does not match config")
        files = inventory.get("ramdisks", {}).get("vendor_boot", {}).get("files", [])
        by_name = {Path(item["archive"]).name: item for item in files}
        if by_name.get("vendor_ramdisk00", {}).get("archive_sha256") != vendor_boot["vendor_ramdisk00_sha256"]:
            errors.append("ramdisk inventory: vendor_ramdisk00 hash does not match config")
        if by_name.get("vendor_ramdisk01", {}).get("archive_sha256") != vendor_boot["vendor_ramdisk01_sha256"]:
            errors.append("ramdisk inventory: vendor_ramdisk01 hash does not match config")
        if by_name.get("vendor_ramdisk00", {}).get("ko_count") != vendor_boot["ramdisk_ko_count"]:
            errors.append("ramdisk inventory: module count does not match config")
    else:
        errors.append(f"evidence log missing: {inventory_path}")

    odm_prop = project_root / "firmware" / "dump" / "odm_dlkm" / "etc" / "build.prop"
    if odm_prop.is_file():
        props = {}
        for line in odm_prop.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                props[key.strip()] = value.strip()
        expected_props = {
            "ro.product.odm_dlkm.device": "rothko",
            "ro.product.odm_dlkm.model": "2407FRK8EC",
            "ro.product.odm_dlkm.marketname": "Redmi K70 Ultra",
            "ro.product.odm_dlkm.brand": "Redmi",
            "ro.product.odm_dlkm.manufacturer": "Xiaomi",
        }
        for key, wanted in expected_props.items():
            if props.get(key) != wanted:
                errors.append(f"odm_dlkm build.prop: {key}={props.get(key)!r} != {wanted!r}")
    else:
        errors.append(f"evidence input missing: {odm_prop}")

    fstab = (
        project_root
        / "firmware"
        / "dump"
        / "ramdisks"
        / "vendor_boot"
        / "vendor_ramdisk00"
        / "first_stage_ramdisk"
        / "fstab.mt6989"
    )
    if fstab.is_file():
        text = fstab.read_text(encoding="utf-8", errors="replace")
        for mount in ("system_ext", "product", "mi_ext"):
            if not re.search(rf"^{mount}\s", text, re.MULTILINE):
                errors.append(f"fstab: expected a {mount} mount entry")
        if "fstab.mt6897" in text:
            errors.append("fstab: unexpectedly references mt6897")
    else:
        errors.append(f"evidence input missing: {fstab}")

    mi_ext = cfg.get("partitions", {}).get("mi_ext", {})
    for key, expected in (
        ("report", "3b39ace8a75411cd3ad7927ed1b574fbc0ea64e786c5fe1aa3771af0263db1cc"),
        ("report_json", "2c6985b474dd6eb7fc005c3b621389faecbe11a2c06327c941c1c13ea91b5bf8"),
    ):
        raw = mi_ext.get(key)
        if not raw:
            errors.append(f"mi_ext: {key} path missing")
            continue
        path = resolve_project_path(project_root, raw)
        if not path.is_file():
            errors.append(f"mi_ext evidence missing: {path}")
        elif sha256_file(path) != expected:
            errors.append(f"mi_ext evidence sha256 mismatch: {path}")

    check_vendor_integration_evidence(device_root, project_root, errors)
    check_module_abi(device_root, project_root, errors)


def main() -> int:
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-root", default=str(default_root))
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--vendor-inventory", default=None)
    parser.add_argument("--vendor-root", default=None)
    parser.add_argument("--mode", choices=("build", "evidence", "all"), default="build")
    parser.add_argument("--make", action="store_true", help="emit one gate line for make")
    parser.add_argument("--make-goals", default="")
    parser.add_argument("--make-context", choices=("configuration", "build"), default="build")
    parser.add_argument("--makefile-list", default="")
    parser.add_argument("--original-goals", default="")
    parser.add_argument("--kati-context-report-dir", type=Path)
    args = parser.parse_args()

    device_root = Path(args.device_root).resolve()
    if args.project_root:
        project_root = Path(args.project_root).resolve()
    elif args.mode in ("evidence", "all"):
        project_root = device_root.parents[2]
    else:
        project_root = device_root
    if args.vendor_root:
        vendor_root = Path(args.vendor_root).resolve()
    else:
        root = device_root
        for _ in range(3):
            root = root.parent
        vendor_root = root / "vendor" / "xiaomi" / "rothko"
    config_path = device_root / "config" / "device-parameters.json"
    if not config_path.is_file():
        message = f"ROTHKO_PREFLIGHT_ERROR: missing canonical config {config_path}"
        print(message if args.make else f"ERROR: {message}", file=sys.stdout if args.make else sys.stderr)
        return 1
    cfg = load_json(config_path)

    if args.make and not args.mode == "evidence":
        goals = {goal for goal in args.make_goals.split() if goal}
        if goals and goals <= CLEAN_GOALS:
            return 0

    errors: list[str] = []
    goals = {goal for goal in args.make_goals.split() if goal}
    provenance = kati_context.inspect(device_root) if args.make else {"approved_cleanspec": False}
    trusted_empty_cleanspec = args.make and not goals and provenance.get("approved_cleanspec") is True
    configuration_only = bool(
        args.make
        and (
            args.make_context == "configuration" or trusted_empty_cleanspec
            or (goals and goals <= CONFIG_GOALS)
        )
    )
    framework_only = bool(args.make and goals and goals <= FRAMEWORK_GOALS)
    recovery_modules_only = bool(args.make and goals and goals <= RECOVERY_MODULE_GOALS)
    if args.mode in ("build", "all"):
        check_generated(device_root, errors)
        check_identity(cfg, errors)
        check_budget(cfg, errors)
        if configuration_only or framework_only or recovery_modules_only:
            # Buildable-input layer: real product config, vendor contract and
            # staged image manifest only. Do not require framework compatibility
            # results that cannot exist before these finite modules are built.
            # Recovery module compilation is not Recovery image/device release.
            check_vendor_contract(vendor_root, cfg, errors)
            check_prebuilts(cfg, vendor_root, errors)
        else:
            # Release layer: full vendor integration, release readiness and module evidence.
            check_release_gate(cfg, errors)
            check_vendor_contract(vendor_root, cfg, errors)
            check_prebuilts(cfg, vendor_root, errors)
            check_mi_ext(cfg, vendor_root, errors)
            check_vendor_evidence(cfg, device_root, errors)
            check_module_evidence(cfg, device_root, errors)
            inventory_path = (
                Path(args.vendor_inventory).resolve()
                if args.vendor_inventory
                else device_root / "config" / "vendor-inventory.json"
            )
            check_inventory(cfg, device_root, inventory_path, errors)
        check_forbidden(cfg, device_root, errors)
    if args.mode in ("evidence", "all"):
        check_evidence(cfg, device_root, project_root, errors)

    if args.kati_context_report_dir:
        try:
            report_dir = args.kati_context_report_dir.resolve()
            report_dir.relative_to(Path(os.environ.get("OUT_DIR", "out")).resolve())
            report_dir.mkdir(parents=True, exist_ok=True)
            report = {"makefile_list": args.makefile_list[:8192], "make_goals": args.make_goals,
                "original_goals": args.original_goals, "requested_context": args.make_context,
                "configuration_only": configuration_only, "framework_only": framework_only,
                "recovery_modules_only": recovery_modules_only,
                "ancestor": provenance, "gate_errors": errors, "passed": not errors}
            target = report_dir / f"context-{os.getpid()}-{time.time_ns()}.json"
            target.write_text(json.dumps(report, indent=2) + "\n")
        except (OSError, ValueError) as exc:
            errors.append(f"Kati context evidence could not be saved safely: {exc}")

    if not errors:
        return 0

    if args.make:
        print("ROTHKO_PREFLIGHT_ERROR: " + " | ".join(errors))
    else:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"FAILED: {len(errors)} input gate(s)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
