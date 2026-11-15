#!/usr/bin/env python3
"""Recompute the stock kernel/module compatibility evidence for rothko.

This is an evidence checker, not a device tool. It reads the extracted stock
modules and the stock kernel config, then verifies config/module-compatibility.json.

The important nuance: the vendor module vermagic release (ga418eeb69cb6) does
not equal the boot kernel release (g6ab8c9a86a33). That string difference alone
is not proof of binary incompatibility. This checker parses the MODVERSIONS
__versions symbol CRCs from every module and compares vendor modules with the
system_dlkm GKI modules whose vermagic matches the boot kernel release.

It does not claim a runtime module load. No kernel symbol CRC table
(vmlinux/Module.symvers/System.map) was acquired.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
from pathlib import Path

SECTION_VERSIONS = "__versions"
SECTION_MODINFO = ".modinfo"
CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def elf_sections(path: Path) -> dict[str, bytes]:
    data = path.read_bytes()
    if data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1:
        raise ValueError(f"{path}: expected little-endian ELF64 module")
    shoff = struct.unpack_from("<Q", data, 0x28)[0]
    shentsize = struct.unpack_from("<H", data, 0x3A)[0]
    shnum = struct.unpack_from("<H", data, 0x3C)[0]
    shstrndx = struct.unpack_from("<H", data, 0x3E)[0]

    def u64(offset: int) -> int:
        return struct.unpack_from("<Q", data, offset)[0]

    def u32(offset: int) -> int:
        return struct.unpack_from("<I", data, offset)[0]

    shstr_offset = u64(shoff + shstrndx * shentsize + 0x18)
    shstr_size = u64(shoff + shstrndx * shentsize + 0x20)
    shstr = data[shstr_offset : shstr_offset + shstr_size]
    sections: dict[str, bytes] = {}
    for index in range(shnum):
        header = shoff + index * shentsize
        name = shstr[u32(header) :].split(b"\0", 1)[0].decode("utf-8", "replace")
        offset = u64(header + 0x18)
        size = u64(header + 0x20)
        sections[name] = data[offset : offset + size]
    return sections


def modinfo_values(path: Path) -> dict[str, str]:
    info = elf_sections(path).get(SECTION_MODINFO, b"")
    values: dict[str, str] = {}
    for item in info.split(b"\0"):
        if b"=" in item:
            key, value = item.split(b"=", 1)
            values[key.decode("utf-8", "replace")] = value.decode("utf-8", "replace")
    return values


def parse_versions(path: Path) -> list[tuple[str, int]]:
    data = elf_sections(path).get(SECTION_VERSIONS, b"")
    # struct modversion_info: unsigned long crc; char name[56] on 64-bit.
    entries = []
    for offset in range(0, len(data) - 63, 64):
        block = data[offset : offset + 64]
        crc = struct.unpack_from("<Q", block, 0)[0]
        name = block[8:].split(b"\0", 1)[0].decode("utf-8", "replace")
        if name:
            entries.append((name, crc))
    return entries


def signed_module(path: Path) -> bool:
    result = subprocess.run(
        ["modinfo", "-F", "sig_id", str(path)],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def parse_ikconfig(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("# ") and " is not set" in line:
            key = line[2:].split(" is not set", 1)[0]
            values[key] = "not set"
        elif "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value.strip().strip('"')
    return values


def summarize_set(paths: list[Path], signed: bool | None = None) -> dict:
    vermagics: dict[str, int] = {}
    crc_symbols: set[str] = set()
    conflicting: set[str] = set()
    crc_map: dict[str, set[int]] = {}
    signed_count = 0
    for path in paths:
        info = modinfo_values(path)
        vermagic = info.get("vermagic", "")
        vermagics[vermagic] = vermagics.get(vermagic, 0) + 1
        if signed is True or (signed is None and signed_module(path)):
            signed_count += 1
        for name, crc in parse_versions(path):
            crc_symbols.add(name)
            crc_map.setdefault(name, set()).add(crc)
    for name, values in crc_map.items():
        if len(values) > 1:
            conflicting.add(name)
    dominant = max(vermagics, key=vermagics.get) if vermagics else ""
    return {
        "module_count": len(paths),
        "vermagic": dominant,
        "vermagic_variants": len(vermagics),
        "signed_modules": signed_count,
        "unsigned_modules": len(paths) - signed_count,
        "crc_symbols": len(crc_symbols),
        "conflicting_symbol_crcs": len(conflicting),
        "_crc_map": crc_map,
    }


def same_magic_summary(paths: list[Path]) -> dict:
    suffixes: dict[str, int] = {}
    layout_crcs: dict[str, int] = {}
    crc_present = 0
    for path in paths:
        vermagic = modinfo_values(path).get("vermagic", "")
        suffix = vermagic.split(" ", 1)[1] if " " in vermagic else vermagic
        suffixes[suffix] = suffixes.get(suffix, 0) + 1
        versions = parse_versions(path)
        if versions:
            crc_present += 1
        for name, crc in versions:
            if name == "module_layout":
                key = hex(crc)
                layout_crcs[key] = layout_crcs.get(key, 0) + 1
    dominant_suffix = max(suffixes, key=suffixes.get) if suffixes else ""
    dominant_layout = max(layout_crcs, key=layout_crcs.get) if layout_crcs else ""
    return {
        "release_prefix_ignored_when_has_crcs": True,
        "crc_section_present_modules": crc_present,
        "modules_examined": len(paths),
        "vermagic_suffix": dominant_suffix,
        "vermagic_suffix_variants": len(suffixes),
        "module_layout_crc": dominant_layout,
        "module_layout_crc_modules": layout_crcs.get(dominant_layout, 0),
        "module_layout_crc_mismatches": len(paths) - layout_crcs.get(dominant_layout, 0),
    }


def main() -> int:
    default_device = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-root", default=str(default_device))
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--check", action="store_true", default=True)
    parser.add_argument("--json", action="store_true", help="print computed JSON")
    args = parser.parse_args()

    device_root = Path(args.device_root).resolve()
    project_root = (
        Path(args.project_root).resolve()
        if args.project_root
        else device_root.parents[2]
    )
    firmware = project_root / "firmware"
    system_dir = firmware / "dump" / "system_dlkm" / "lib" / "modules"
    vendor_dir = firmware / "dump" / "vendor_dlkm" / "lib" / "modules"
    ramdisk_dir = (
        firmware
        / "dump"
        / "ramdisks"
        / "vendor_boot"
        / "vendor_ramdisk00"
        / "lib"
        / "modules"
    )
    ikconfig_path = project_root.parent / "offline-k70u" / "analysis" / "kernel" / "ikconfig"
    evidence_path = project_root.parent / "offline-k70u" / "analysis" / "kernel" / "evidence.json"
    expected_path = device_root / "config" / "module-compatibility.json"

    for path in (system_dir, vendor_dir, ramdisk_dir, ikconfig_path, expected_path):
        if not path.exists():
            print(f"missing input: {path}", file=sys.stderr)
            return 1

    system_paths = sorted(system_dir.glob("*.ko"))
    vendor_paths = sorted(vendor_dir.glob("*.ko"))
    ramdisk_paths = sorted(ramdisk_dir.glob("*.ko"))
    system = summarize_set(system_paths)
    vendor = summarize_set(vendor_paths)
    ramdisk = summarize_set(ramdisk_paths)

    system_map = system["_crc_map"]
    overlaps = {}
    for label, module_set in (("vendor_dlkm", vendor), ("vendor_boot", ramdisk)):
        overlap = 0
        mismatches = 0
        for name, values in module_set["_crc_map"].items():
            if name in system_map:
                overlap += 1
                if values != system_map[name]:
                    mismatches += 1
        overlaps[label] = {
            "overlap_symbols": overlap,
            "crc_mismatches": mismatches,
        }

    kernel_config = parse_ikconfig(ikconfig_path)
    boot_release = json.loads((device_root / "config" / "device-parameters.json").read_text())[
        "device"
    ]["kernel_release"]

    computed = {
        "boot_kernel_release": boot_release,
        "kernel_config": {
            "CONFIG_MODVERSIONS": kernel_config.get("CONFIG_MODVERSIONS"),
            "CONFIG_MODULE_SIG": kernel_config.get("CONFIG_MODULE_SIG"),
            "CONFIG_MODULE_SIG_FORCE": kernel_config.get("CONFIG_MODULE_SIG_FORCE"),
            "CONFIG_MODULE_SIG_PROTECT": kernel_config.get("CONFIG_MODULE_SIG_PROTECT"),
            "CONFIG_MODULE_SIG_ALL": kernel_config.get("CONFIG_MODULE_SIG_ALL"),
            "CONFIG_MODULE_SIG_HASH": kernel_config.get("CONFIG_MODULE_SIG_HASH"),
            "CONFIG_GKI_HIDDEN_*": "present"
            if any(key.startswith("CONFIG_GKI_HIDDEN_") and value == "y" for key, value in kernel_config.items())
            else "absent",
            "CONFIG_CFI_CLANG": kernel_config.get("CONFIG_CFI_CLANG"),
            "CONFIG_LTO_NONE": kernel_config.get("CONFIG_LTO_NONE"),
            "CONFIG_ARM64_4K_PAGES": kernel_config.get("CONFIG_ARM64_4K_PAGES"),
        },
        "module_sets": {
            "system_dlkm": {key: value for key, value in system.items() if not key.startswith("_")},
            "vendor_dlkm": {key: value for key, value in vendor.items() if not key.startswith("_")},
            "vendor_boot_ramdisk00": {
                key: value for key, value in ramdisk.items() if not key.startswith("_")
            },
        },
        "crc_cross_check": {
            "system_dlkm_symbols": system["crc_symbols"],
            "system_dlkm_conflicting_symbol_crcs": system["conflicting_symbol_crcs"],
            "vendor_dlkm_overlap_symbols": overlaps["vendor_dlkm"]["overlap_symbols"],
            "vendor_dlkm_crc_mismatches": overlaps["vendor_dlkm"]["crc_mismatches"],
            "vendor_boot_overlap_symbols": overlaps["vendor_boot"]["overlap_symbols"],
            "vendor_boot_crc_mismatches": overlaps["vendor_boot"]["crc_mismatches"],
        },
        "same_magic": same_magic_summary(system_paths + vendor_paths + ramdisk_paths),
        "kernel_symbol_crc_table_available": None,
        "kernel_symbol_crc_table_status": "not located in the stripped Image.elf; __kcrctab may be present, so absence is not claimed",
        "runtime_load_verified": False,
        "status": "same_magic_suffix_match_crc_overlap_consistent_module_layout_match_kernel_crcs_unverified_runtime_unproven",
    }

    if args.json:
        print(json.dumps(computed, indent=2))

    expected = json.loads(expected_path.read_text())
    problems = []
    for key in ("boot_kernel_release",):
        if expected.get(key) != computed[key]:
            problems.append(f"{key}: {expected.get(key)!r} != {computed[key]!r}")
    for key, value in computed["kernel_config"].items():
        if expected.get("kernel_config", {}).get(key) != value:
            problems.append(
                f"kernel_config.{key}: {expected.get('kernel_config', {}).get(key)!r} != {value!r}"
            )
    for set_name, values in computed["module_sets"].items():
        expected_set = expected.get("module_sets", {}).get(set_name, {})
        for key in ("module_count", "vermagic", "vermagic_variants", "signed_modules", "unsigned_modules", "crc_symbols", "conflicting_symbol_crcs"):
            if expected_set.get(key) != values.get(key):
                problems.append(
                    f"module_sets.{set_name}.{key}: {expected_set.get(key)!r} != {values.get(key)!r}"
                )
    for key, value in computed["crc_cross_check"].items():
        if expected.get("crc_cross_check", {}).get(key) != value:
            problems.append(
                f"crc_cross_check.{key}: {expected.get('crc_cross_check', {}).get(key)!r} != {value!r}"
            )
    for key, value in computed["same_magic"].items():
        if expected.get("same_magic", {}).get(key) != value:
            problems.append(
                f"same_magic.{key}: {expected.get('same_magic', {}).get(key)!r} != {value!r}"
            )
    if expected.get("kernel_symbol_crc_table_status") != computed["kernel_symbol_crc_table_status"]:
        problems.append("kernel_symbol_crc_table_status does not match")
    if expected.get("status") != computed["status"]:
        problems.append(f"status: {expected.get('status')!r} != {computed['status']!r}")

    # Verify recorded source hashes.
    expected_sources = expected.get("sources", {})
    for key, path in (
        ("ikconfig", ikconfig_path),
        ("kernel_evidence", evidence_path),
        ("module_vermagic", firmware / "reports" / "module-vermagic.tsv"),
        ("boot_parameters", firmware / "reports" / "boot-parameters.md"),
        ("kernel_module_version_reference", project_root / "logs" / "kernel-module-version-reference.c"),
    ):
        record = expected_sources.get(key, {})
        if record.get("sha256") and record["sha256"] != sha256_file(path):
            problems.append(f"sources.{key}: sha256 mismatch")

    if problems:
        for problem in problems:
            print(f"MISMATCH: {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
