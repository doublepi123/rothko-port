#!/usr/bin/env python3
"""Stock-framework integration checks for the rothko device tree.

Artifact-driven only. It never writes a DEVICE_MANIFEST_FILE, never treats an
empty out/vendor as vendor input, and never claims that one secilc pass proves
all neverallow/context correctness.

Subcommands:
  vintf    checkvintf --check-compat over system/system_ext/product, a derived
           vendor re-extract, and stock odm. Runs explicit vendor-SKU and
           hardware-SKU candidate/control scenarios and saves each log/rc.
  selinux  Runtime-style CIL input collection from system/core/init/selinux.cpp,
           compiled with secilc *without* -N, then sepolicy-analyze permissive,
           checkfc and sefcontext_compile. Required inputs missing = fail;
           optional runtime inputs absent = recorded, not claimed.
  init     host_init_verifier over framework partitions, derived vendor, stock
           odm, using the actual passwd/property-context arguments.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path


DEVICE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[4]
HOST_OUT_DEFAULT = os.environ.get("ANDROID_HOST_OUT", "out/host/linux-x86")
POLICY_VERSION = 30  # system/sepolicy/build/soong/policy.go PolicyVers.
KERNEL_RELEASE_DEFAULT = "6.1.138-android14-11-g6ab8c9a86a33-ab14396278"
IKCONFIG_DEFAULT = PROJECT_ROOT.parent / "offline-k70u" / "analysis" / "kernel" / "ikconfig"
STOCK_VENDOR_DEFAULT = PROJECT_ROOT / "firmware" / "dump" / "vendor"
STOCK_ODM_DEFAULT = PROJECT_ROOT / "firmware" / "dump" / "odm"


def config_value(key: str, default: str) -> str:
    try:
        config = json.loads((DEVICE_ROOT / "config" / "device-parameters.json").read_text())
    except (OSError, json.JSONDecodeError):
        return default
    return str(config.get("device", {}).get(key, default))


def sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def report_dir(value: str | None) -> Path:
    if value:
        path = Path(value).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path
    base = Path("/tmp/opencode")
    if not base.is_dir():
        base = Path(tempfile.gettempdir())
    return Path(tempfile.mkdtemp(prefix="rothko-integration-", dir=base))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def require_file(path: Path, label: str, errors: list[str]) -> None:
    if not path.is_file():
        errors.append(f"{label} missing: {path}")


def require_dir(path: Path, label: str, errors: list[str]) -> None:
    if not path.is_dir() or not any(path.iterdir()):
        errors.append(f"{label} missing or empty: {path}")


def require_tool(path: Path, label: str, errors: list[str]) -> None:
    if not path.is_file() or not os.access(path, os.X_OK):
        errors.append(f"{label} host tool missing/not executable: {path}")


def run_logged(command: list[str], log_path: Path, rc_path: Path, label: str) -> tuple[int, str, str]:
    write_text(log_path, f"$ {shlex.join(command)}\n")
    proc = subprocess.run(command, capture_output=True, text=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(proc.stdout)
        if proc.stderr:
            handle.write("\n--- stderr ---\n")
            handle.write(proc.stderr)
    write_text(rc_path, f"{proc.returncode}\n")
    print(f"{label}: rc={proc.returncode} log={log_path}")
    return proc.returncode, proc.stdout, proc.stderr


def read_mapping_version(stock_vendor: Path, override: str | None) -> tuple[str, list[str]]:
    if override:
        return override, []
    path = stock_vendor / "etc" / "selinux" / "plat_sepolicy_vers.txt"
    if not path.is_file():
        return "", [f"stock vendor plat_sepolicy_vers.txt missing: {path}"]
    version = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    if not version or not version[0].strip():
        return "", [f"empty plat_sepolicy_vers.txt: {path}"]
    return version[0].strip(), []


def select_cil_inputs(
    out: Path,
    stock_vendor: Path,
    stock_odm: Path,
    mapping_version: str | None = None,
    genfs_cil: Path | None = None,
    userdebug_plat_policy: Path | None = None,
) -> tuple[dict, list[str]]:
    """Recreate the runtime input selection from CompileSplitPolicy.

    Required: plat (or explicitly selected userdebug plat), plat mapping,
    stock vendor/plat_pub_versioned.cil, stock vendor/vendor_sepolicy.cil.
    Optional, selected only if present: plat compat, system_ext
    policy/mapping/compat, product policy/mapping, odm policy, genfs.
    """
    version, errors = read_mapping_version(stock_vendor, mapping_version)
    plat = userdebug_plat_policy or (out / "system" / "etc" / "selinux" / "plat_sepolicy.cil")
    plat_mapping = out / "system" / "etc" / "selinux" / "mapping" / f"{version}.cil"
    plat_pub = stock_vendor / "etc" / "selinux" / "plat_pub_versioned.cil"
    vendor = stock_vendor / "etc" / "selinux" / "vendor_sepolicy.cil"

    required = {
        "plat": plat,
        "plat_mapping": plat_mapping,
        "plat_pub_versioned": plat_pub,
        "vendor_policy": vendor,
    }
    for label, path in required.items():
        require_file(path, label, errors)

    before_plat_pub: list[tuple[str, Path]] = []
    candidates = [
        ("plat_compat", out / "system" / "etc" / "selinux" / "mapping" / f"{version}.compat.cil"),
        ("system_ext_policy", out / "system_ext" / "etc" / "selinux" / "system_ext_sepolicy.cil"),
        ("system_ext_mapping", out / "system_ext" / "etc" / "selinux" / "mapping" / f"{version}.cil"),
        ("system_ext_compat", out / "system_ext" / "etc" / "selinux" / "mapping" / f"{version}.compat.cil"),
        ("product_policy", out / "product" / "etc" / "selinux" / "product_sepolicy.cil"),
        ("product_mapping", out / "product" / "etc" / "selinux" / "mapping" / f"{version}.cil"),
    ]
    for label, path in candidates:
        if path.is_file():
            before_plat_pub.append((label, path))

    after_vendor: list[tuple[str, Path]] = []
    odm = stock_odm / "etc" / "selinux" / "odm_sepolicy.cil"
    if odm.is_file():
        after_vendor.append(("odm_policy", odm))

    if genfs_cil:
        if genfs_cil.is_file():
            after_vendor.append(("genfs", genfs_cil))
        else:
            errors.append(f"genfs CIL missing: {genfs_cil}")
    else:
        genfs_matches = sorted((out / "system" / "etc" / "selinux").glob("plat_sepolicy_genfs_*.cil"))
        if len(genfs_matches) == 1:
            after_vendor.append(("genfs", genfs_matches[0]))
        elif len(genfs_matches) > 1:
            errors.append(
                "ambiguous genfs CIL; pass --genfs-cil: "
                + ", ".join(str(p) for p in genfs_matches)
            )

    selected = {
        "mapping_version": version,
        "required": required,
        "before_plat_pub": before_plat_pub,
        "after_vendor": after_vendor,
        "absent": [
            label for label, path in candidates if not path.is_file()
        ] + (["odm_policy"] if not odm.is_file() else []),
    }
    return selected, errors


def build_secilc_command(
    secilc: Path,
    policy: Path,
    file_contexts: Path,
    selected: dict,
) -> list[str]:
    command = [
        str(secilc),
        str(selected["required"]["plat"]),
        "-m",
        "-M",
        "true",
        "-G",
        "-c",
        str(POLICY_VERSION),
        str(selected["required"]["plat_mapping"]),
        "-o",
        str(policy),
        "-f",
        str(file_contexts),
    ]
    command += [str(path) for _, path in selected["before_plat_pub"]]
    command += [
        str(selected["required"]["plat_pub_versioned"]),
        str(selected["required"]["vendor_policy"]),
    ]
    command += [str(path) for _, path in selected["after_vendor"]]
    return command


def build_vintf_commands(
    out: Path,
    vendor: Path,
    odm: Path,
    checkvintf: Path,
    first_api: int,
    vendor_sku: str,
    hardware_sku: str,
    kernel_release: str,
    ikconfig: Path,
) -> list[tuple[str, list[str]]]:
    common = [
        str(checkvintf),
        "--check-compat",
        "--dirmap",
        f"/system:{out / 'system'}",
        "--dirmap",
        f"/system_ext:{out / 'system_ext'}",
        "--dirmap",
        f"/product:{out / 'product'}",
        "--dirmap",
        f"/vendor:{vendor}",
        "--dirmap",
        f"/odm:{odm}",
        "--property",
        f"ro.product.first_api_level={first_api}",
        "--kernel",
        f"{kernel_release}:{ikconfig}",
    ]
    candidate = list(common)
    if vendor_sku:
        candidate += ["--property", f"ro.boot.product.vendor.sku={vendor_sku}"]
    if hardware_sku:
        candidate += ["--property", f"ro.boot.product.hardware.sku={hardware_sku}"]
    control = list(common)  # empty vendor/hardware SKU control
    return [("candidate", candidate), ("control", control)]


def build_host_init_command(
    out: Path,
    vendor: Path,
    odm: Path,
    host_init_verifier: Path,
) -> list[str]:
    command = [str(host_init_verifier)]
    passwd = [
        out / "system" / "etc" / "passwd",
        out / "system_ext" / "etc" / "passwd",
        vendor / "etc" / "passwd",
        odm / "etc" / "passwd",
        out / "product" / "etc" / "passwd",
    ]
    contexts = [
        out / "system" / "etc" / "selinux" / "plat_property_contexts",
        out / "system_ext" / "etc" / "selinux" / "system_ext_property_contexts",
        out / "product" / "etc" / "selinux" / "product_property_contexts",
        vendor / "etc" / "selinux" / "vendor_property_contexts",
        odm / "etc" / "selinux" / "odm_property_contexts",
    ]
    for path in passwd:
        command += ["-p", str(path)]
    for path in contexts:
        command += [f"--property-contexts={path}"]
    command += [
        "--out_system", str(out / "system"),
        "--out_system_ext", str(out / "system_ext"),
        "--out_vendor", str(vendor),
        "--out_odm", str(odm),
        "--out_product", str(out / "product"),
    ]
    return command


def write_selected_inputs(report: Path, selected: dict) -> None:
    lines = [f"mapping_version={selected['mapping_version']}"]
    for label, path in selected["required"].items():
        lines.append(f"required {label} {path} sha256={sha256_file(path)}")
    for label, path in selected["before_plat_pub"]:
        lines.append(f"optional {label} {path} sha256={sha256_file(path)}")
    for label, path in selected["after_vendor"]:
        lines.append(f"optional {label} {path} sha256={sha256_file(path)}")
    for label in selected["absent"]:
        lines.append(f"absent {label}")
    write_text(report / "inputs.txt", "\n".join(lines) + "\n")


def cmd_vintf(args: argparse.Namespace) -> int:
    out = Path(args.out).resolve()
    odm = Path(args.odm).resolve()
    checkvintf = Path(args.checkvintf).resolve()
    report = report_dir(args.report_dir)
    errors: list[str] = []
    for part in ("system", "system_ext", "product"):
        require_dir(out / part, f"built {part} artifact", errors)
    require_dir(odm / "etc" / "vintf", "stock odm VINTF metadata", errors)
    require_file(Path(args.ikconfig), "stock IKCONFIG", errors)
    require_tool(checkvintf, "checkvintf", errors)

    if args.derived_vendor:
        vendor = Path(args.derived_vendor).resolve()
        if vendor == (out / "vendor").resolve():
            errors.append("derived vendor must be a re-extract, not empty out/vendor")
        require_dir(vendor / "etc" / "vintf", "derived vendor VINTF metadata", errors)
    elif args.diagnostic_stock_vendor:
        vendor = Path(args.stock_vendor).resolve()
        require_dir(vendor / "etc" / "vintf", "stock vendor diagnostic metadata", errors)
    else:
        write_text(report / "NOT_RUN.txt", "derived vendor re-extract not supplied\n")
        print(
            f"NOT RUN: derived vendor re-extract not supplied; report={report}; "
            "stock vendor is diagnostic only",
            file=sys.stderr,
        )
        return 2

    if errors:
        write_text(report / "NOT_RUN.txt", "\n".join(errors) + "\n")
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        print(f"NOT RUN: checkvintf prerequisites incomplete; report={report}", file=sys.stderr)
        return 2

    commands = build_vintf_commands(
        out,
        vendor,
        odm,
        checkvintf,
        args.first_api,
        args.vendor_sku,
        args.hardware_sku,
        args.kernel_release,
        Path(args.ikconfig),
    )
    if args.diagnostic_stock_vendor:
        print("DIAGNOSTIC ONLY: stock vendor dump selected; not the derived vendor", file=sys.stderr)
    results = []
    for label, command in commands:
        scenario = report / label
        scenario.mkdir(parents=True, exist_ok=True)
        write_text(scenario / "command.txt", shlex.join(command) + "\n")
        rc, stdout, stderr = run_logged(
            command, scenario / "run.log", scenario / "rc.txt", f"checkvintf-{label}"
        )
        results.append((label, rc))
        if stdout or stderr:
            write_text(scenario / "stdout.txt", stdout)
            write_text(scenario / "stderr.txt", stderr)
    summary = "\n".join(f"{label} rc={rc}" for label, rc in results) + "\n"
    summary += "candidate/control are not real-device SKU confirmation.\n"
    write_text(report / "summary.txt", summary)
    if any(rc != 0 for _, rc in results):
        return 1
    return 0


def cmd_selinux(args: argparse.Namespace) -> int:
    out = Path(args.out).resolve()
    stock_vendor = Path(args.stock_vendor).resolve()
    stock_odm = Path(args.stock_odm).resolve()
    secilc = Path(args.secilc).resolve()
    sepolicy_analyze = Path(args.sepolicy_analyze).resolve()
    checkfc = Path(args.checkfc).resolve()
    sefcontext_compile = Path(args.sefcontext_compile).resolve()
    report = report_dir(args.report_dir)
    errors: list[str] = []
    for part in ("system", "system_ext", "product"):
        require_dir(out / part, f"built {part} artifact", errors)
    for label, tool in (
        ("secilc", secilc),
        ("sepolicy-analyze", sepolicy_analyze),
    ):
        require_tool(tool, label, errors)
    if errors:
        write_text(report / "NOT_RUN.txt", "\n".join(errors) + "\n")
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        print(f"NOT RUN: SELinux prerequisites incomplete; report={report}", file=sys.stderr)
        return 2

    selected, select_errors = select_cil_inputs(
        out,
        stock_vendor,
        stock_odm,
        args.mapping_version,
        Path(args.genfs_cil).resolve() if args.genfs_cil else None,
        Path(args.userdebug_plat_policy).resolve() if args.userdebug_plat_policy else None,
    )
    if select_errors:
        write_text(report / "NOT_RUN.txt", "\n".join(select_errors) + "\n")
        for error in select_errors:
            print(f"FAIL: {error}", file=sys.stderr)
        print(f"NOT RUN: SELinux inputs incomplete; report={report}", file=sys.stderr)
        return 2
    write_selected_inputs(report, selected)

    policy = report / "actualpolicy.bin"
    file_contexts = report / "file_contexts"
    command = build_secilc_command(secilc, policy, file_contexts, selected)
    if "-N" in command or "--disable-neverallow" in command:
        print("FAIL: neverallow checking must stay enabled", file=sys.stderr)
        return 1
    write_text(report / "command.txt", shlex.join(command) + "\n")
    rc, _, _ = run_logged(command, report / "secilc.log", report / "secilc.rc.txt", "secilc")
    if rc != 0 or not policy.is_file():
        print(f"FAIL: secilc merge/neverallow failed; report={report}", file=sys.stderr)
        return 1

    rc, stdout, _ = run_logged(
        [str(sepolicy_analyze), str(policy), "permissive"],
        report / "permissive.log",
        report / "permissive.rc.txt",
        "sepolicy-analyze-permissive",
    )
    write_text(report / "permissive.stdout.txt", stdout)
    if rc != 0:
        print(f"FAIL: sepolicy-analyze permissive failed; report={report}", file=sys.stderr)
        return 1
    if stdout.strip():
        print(f"FAIL: permissive domains present; report={report}", file=sys.stderr)
        return 1

    if not file_contexts.is_file():
        print(f"FAIL: secilc did not produce file_contexts; contexts not run; report={report}", file=sys.stderr)
        return 1
    context_errors = []
    require_tool(checkfc, "checkfc", context_errors)
    require_tool(sefcontext_compile, "sefcontext_compile", context_errors)
    if context_errors:
        write_text(report / "contexts_NOT_RUN.txt", "\n".join(context_errors) + "\n")
        for error in context_errors:
            print(f"FAIL: {error}", file=sys.stderr)
        print(f"NOT RUN: contexts check incomplete; actual policy retained at {policy}", file=sys.stderr)
        return 1
    rc, _, _ = run_logged(
        [str(checkfc), str(policy), str(file_contexts)],
        report / "checkfc.log",
        report / "checkfc.rc.txt",
        "checkfc",
    )
    if rc != 0:
        return 1
    rc, _, _ = run_logged(
        [str(sefcontext_compile), "-o", str(report / "file_contexts.bin"), str(file_contexts)],
        report / "sefcontext_compile.log",
        report / "sefcontext_compile.rc.txt",
        "sefcontext_compile",
    )
    if rc != 0:
        return 1
    write_text(report / "PASS.txt", "secilc+neverallow+permissive+contexts checks passed\n")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    out = Path(args.out).resolve()
    vendor = Path(args.derived_vendor).resolve()
    odm = Path(args.odm).resolve()
    tool = Path(args.host_init_verifier).resolve()
    report = report_dir(args.report_dir)
    errors: list[str] = []
    for part in ("system", "system_ext", "product"):
        require_dir(out / part, f"built {part} artifact", errors)
    require_dir(vendor / "etc" / "init", "derived vendor init directory", errors)
    require_dir(odm / "etc" / "init", "stock odm init directory", errors)
    require_tool(tool, "host_init_verifier", errors)
    for label, path in (
        ("system passwd", out / "system" / "etc" / "passwd"),
        ("system_ext passwd", out / "system_ext" / "etc" / "passwd"),
        ("vendor passwd", vendor / "etc" / "passwd"),
        ("odm passwd", odm / "etc" / "passwd"),
        ("product passwd", out / "product" / "etc" / "passwd"),
        ("plat property contexts", out / "system" / "etc" / "selinux" / "plat_property_contexts"),
        ("system_ext property contexts", out / "system_ext" / "etc" / "selinux" / "system_ext_property_contexts"),
        ("product property contexts", out / "product" / "etc" / "selinux" / "product_property_contexts"),
        ("vendor property contexts", vendor / "etc" / "selinux" / "vendor_property_contexts"),
        ("odm property contexts", odm / "etc" / "selinux" / "odm_property_contexts"),
    ):
        require_file(path, label, errors)
    if errors:
        write_text(report / "NOT_RUN.txt", "\n".join(errors) + "\n")
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        print(f"NOT RUN: host_init_verifier prerequisites incomplete; report={report}", file=sys.stderr)
        return 2
    command = build_host_init_command(out, vendor, odm, tool)
    write_text(report / "command.txt", shlex.join(command) + "\n")
    rc, _, _ = run_logged(command, report / "run.log", report / "rc.txt", "host_init_verifier")
    return rc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    vintf = sub.add_parser("vintf")
    vintf.add_argument("--out", required=True)
    vintf.add_argument("--derived-vendor")
    vintf.add_argument("--diagnostic-stock-vendor", action="store_true")
    vintf.add_argument("--stock-vendor", default=str(STOCK_VENDOR_DEFAULT))
    vintf.add_argument("--odm", default=str(STOCK_ODM_DEFAULT))
    vintf.add_argument("--checkvintf", default=str(Path(HOST_OUT_DEFAULT) / "bin" / "checkvintf"))
    vintf.add_argument("--first-api", type=int, default=34)
    vintf.add_argument("--vendor-sku", default="rothko")
    vintf.add_argument("--hardware-sku", default="rothko")
    vintf.add_argument("--kernel-release", default=config_value("kernel_release", KERNEL_RELEASE_DEFAULT))
    vintf.add_argument("--ikconfig", default=str(IKCONFIG_DEFAULT))
    vintf.add_argument("--report-dir")
    vintf.set_defaults(func=cmd_vintf)

    selinux = sub.add_parser("selinux")
    selinux.add_argument("--out", required=True)
    selinux.add_argument("--stock-vendor", default=str(STOCK_VENDOR_DEFAULT))
    selinux.add_argument("--stock-odm", default=str(STOCK_ODM_DEFAULT))
    selinux.add_argument("--mapping-version")
    selinux.add_argument("--genfs-cil")
    selinux.add_argument("--userdebug-plat-policy")
    selinux.add_argument("--secilc", default=str(Path(HOST_OUT_DEFAULT) / "bin" / "secilc"))
    selinux.add_argument(
        "--sepolicy-analyze", default=str(Path(HOST_OUT_DEFAULT) / "bin" / "sepolicy-analyze")
    )
    selinux.add_argument("--checkfc", default=str(Path(HOST_OUT_DEFAULT) / "bin" / "checkfc"))
    selinux.add_argument(
        "--sefcontext-compile", default=str(Path(HOST_OUT_DEFAULT) / "bin" / "sefcontext_compile")
    )
    selinux.add_argument("--report-dir")
    selinux.set_defaults(func=cmd_selinux)

    init = sub.add_parser("init")
    init.add_argument("--out", required=True)
    init.add_argument("--derived-vendor", required=True)
    init.add_argument("--odm", default=str(STOCK_ODM_DEFAULT))
    init.add_argument(
        "--host-init-verifier",
        default=str(Path(HOST_OUT_DEFAULT) / "bin" / "host_init_verifier"),
    )
    init.add_argument("--report-dir")
    init.set_defaults(func=cmd_init)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
