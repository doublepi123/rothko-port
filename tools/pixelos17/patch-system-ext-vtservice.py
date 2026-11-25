#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Add the verified legacy MediaTek VT service to a raw system_ext image."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

INPUTS = (
    ("vtservice", "bin/vtservice", "7ddbdb412d91a0180ae80609039d5c5ff48c73f94dcb35454b3ca91ffe0747bb", 0o100755, "u:object_r:vtservice_exec:s0"),
    ("init.vtservice.rc", "etc/init/init.vtservice.rc", "9df51aa74b0ed175bcd008e29a9daf88060abeb36eb3bd5a593a66b7edbeb33f", 0o100644, "u:object_r:system_file:s0"),
    ("libmtk_vt_service.so", "lib64/libmtk_vt_service.so", "4a7de6296c04837d71b769cf67445723d21b0021988e2602df1783550cebac13", 0o100644, "u:object_r:system_lib_file:s0"),
    ("libhidltransport.so", "lib64/libhidltransport.so", "0e39b1360691f3d0239129fc8800385ebf0f8973244dca7840c1fea6653a261c", 0o100644, "u:object_r:system_lib_file:s0"),
    ("libcomutils.so", "lib64/libcomutils.so", "c3e3b4a2ce912b4c8040624eeff38137fee6abead1202dadf6ffe7ed225c6a2e", 0o100644, "u:object_r:system_lib_file:s0"),
    ("libimsma.so", "lib64/libimsma.so", "9e372dd878f8cc4d8bc6c80617af8f3efcfdf80347c4f3c261d1872929614749", 0o100644, "u:object_r:system_lib_file:s0"),
    ("libimsma_adapt.so", "lib64/libimsma_adapt.so", "9ebe8d913398e8e5c958c221d9c9d0ac1f970625e72308b5631f264b4326473f", 0o100644, "u:object_r:system_lib_file:s0"),
    ("libimsma_rtp.so", "lib64/libimsma_rtp.so", "aaf41f692aa8d3e2aaffad6c674dc40eeea1d25e5c5f7525f52bbeabca8c2f45", 0o100644, "u:object_r:system_lib_file:s0"),
    ("libimsma_socketwrapper.so", "lib64/libimsma_socketwrapper.so", "9679e24bf6cb5fd82cf0deca50a4588a7601b503b4cede82c42b2e50b1afb2c8", 0o100644, "u:object_r:system_lib_file:s0"),
    ("libsignal.so", "lib64/libsignal.so", "bae209290043f263f990bf814158dc338f611cb8d649856db48454536b0cbfac", 0o100644, "u:object_r:system_lib_file:s0"),
    ("libsink.so", "lib64/libsink.so", "bb3d2bf5af3195bae8e4ffa64a60326fa284b187af4ee3c0769b18f47b2550f4", 0o100644, "u:object_r:system_lib_file:s0"),
    ("libsource.so", "lib64/libsource.so", "f61f2171832daadfdb4f7175c631e139065250f1d6d5ff30381a8426346370ef", 0o100644, "u:object_r:system_lib_file:s0"),
    ("libvcodec_cap.so", "lib64/libvcodec_cap.so", "683017a10de4519f2698110b63ef48066d05ebcaed7bf67f82e518460e9b9ac5", 0o100644, "u:object_r:system_lib_file:s0"),
    ("libvcodec_capenc.so", "lib64/libvcodec_capenc.so", "e7c53409aaefc3c9d1db9041527eafce9d835e033b4cdb4f4c2562c1e664b0fd", 0o100644, "u:object_r:system_lib_file:s0"),
    ("libvt_avsync.so", "lib64/libvt_avsync.so", "0879b73c9925e37f68180e2101309e4cbe4254cb200ee7411084f3ef9ce6ec0a", 0o100644, "u:object_r:system_lib_file:s0"),
    ("vendor.mediatek.hardware.videotelephony@1.0.so", "lib64/vendor.mediatek.hardware.videotelephony@1.0.so", "d2aa9c6c934b6f1d078a310bb7933e4ec0ec4c7f51f22dd510fdb4f099f1964d", 0o100644, "u:object_r:system_lib_file:s0"),
    ("vendor.mediatek.hardware.videotelephony-V1-ndk.so", "lib64/vendor.mediatek.hardware.videotelephony-V1-ndk.so", "2a7a90566700791fa87e34544806be7aed67f0c122a351a7711e06b725a1f4be", 0o100644, "u:object_r:system_lib_file:s0"),
)
STOCK_PATHS = {
    "vtservice": "bin/vtservice",
    "init.vtservice.rc": "etc/init/init.vtservice.rc",
    **{name: f"lib64/{name}" for name, *_ in INPUTS if name.endswith(".so") and name != "libhidltransport.so"},
}
PRIVATE_LIBS = frozenset(name for name, *_ in INPUTS if name.endswith(".so"))
AUDIO_COMPAT = "librothko_vt_audio_compat.so"
AUDIO_CTOR = (
    "_ZN7android10AudioTrackC1E19audio_stream_type_tj14audio_format_t20audio_channel_mask_tm"
    "20audio_output_flags_tRKNS_2wpINS0_19IAudioTrackCallbackEEEi15audio_session_t"
    "NS0_13transfer_typeEPK20audio_offload_info_tRKNS_7content22AttributionSourceState"
    "EPK18audio_attributes_tbfi"
)
AUDIO_CTOR_17 = AUDIO_CTOR + "RKNSt3__112basic_stringIcNSM_11char_traitsIcEENSM_9allocatorIcEEEE"


class VtserviceImageError(RuntimeError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(args: list[str], *, env: dict[str, str] | None = None) -> bytes:
    result = subprocess.run(args, check=True, capture_output=True, env=env)
    return result.stdout


def is_missing(image: Path, destination: str, env: dict[str, str]) -> bool:
    result = subprocess.run(
        ["debugfs", "-R", f"stat /{destination}", str(image)],
        check=False,
        capture_output=True,
        env=env,
    )
    output = result.stdout + result.stderr
    return b"File not found by ext2_lookup" in output


def free_inodes(image: Path, env: dict[str, str]) -> int:
    header = run(["dumpe2fs", "-h", str(image)], env=env).decode("ascii", "replace")
    match = re.search(r"^Free inodes:\s*(\d+)\s*$", header, re.MULTILINE)
    if match is None:
        raise VtserviceImageError("could not read ext4 free inode count")
    return int(match.group(1))


def inspect_elf(path: Path, env: dict[str, str]) -> set[str]:
    header = run(["readelf", "-h", str(path)], env=env).decode("ascii", "replace")
    if not re.search(r"Class:\s+ELF64\b", header) or not re.search(r"Machine:\s+AArch64\b", header):
        raise VtserviceImageError(f"expected a 64-bit ARM ELF: {path.name}")
    dynamic = run(["readelf", "-d", str(path)], env=env).decode("ascii", "replace")
    needed = {
        line.split("[", 1)[1].split("]", 1)[0]
        for line in dynamic.splitlines()
        if "Shared library:" in line
    }
    soname = next((line.split("[", 1)[1].split("]", 1)[0]
                   for line in dynamic.splitlines() if "Library soname:" in line), None)
    if path.name == "libhidltransport.so" and soname != path.name:
        raise VtserviceImageError("pinned libhidltransport has an unexpected SONAME")
    return needed


def validate_private_closure(sources: dict[str, Path], env: dict[str, str]) -> None:
    observed = {name: inspect_elf(path, env) for name, path in sources.items() if name.endswith(".so")}
    binary_needed = inspect_elf(sources["vtservice"], env)
    if "libmtk_vt_service.so" not in binary_needed:
        raise VtserviceImageError("vtservice no longer links libmtk_vt_service.so")
    pending, reached = ["libmtk_vt_service.so"], set()
    while pending:
        name = pending.pop()
        if name in reached:
            continue
        reached.add(name)
        if name not in observed:
            raise VtserviceImageError(f"missing pinned private ELF dependency: {name}")
        pending.extend(observed[name] & PRIVATE_LIBS - reached)
    if reached != PRIVATE_LIBS:
        raise VtserviceImageError(f"unused private libraries in staged closure: {sorted(PRIVATE_LIBS - reached)}")


def add_vtservice(image: Path, stock: Path, jni: Path, audio_compat: Path, output: Path) -> None:
    image, stock, jni, audio_compat, output = (p.resolve() for p in (image, stock, jni, audio_compat, output))
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    if not output.parent.is_dir():
        raise VtserviceImageError("output parent directory must already exist")
    with image.open("rb") as stream:
        _ = stream.seek(-64, os.SEEK_END)
        if stream.read(4) == b"AVBf":
            raise VtserviceImageError("strip the AVB footer from a copy of system_ext first")

    files: dict[str, tuple[bytes, int, str]] = {}
    sources: dict[str, Path] = {}
    for name, destination, expected, mode, label in INPUTS:
        source = jni / name if name == "libhidltransport.so" else stock / STOCK_PATHS[name]
        if source.is_symlink() or not source.is_file():
            raise VtserviceImageError(f"input must be a regular file: {source}")
        payload = source.read_bytes()
        if sha256(payload) != expected:
            raise VtserviceImageError(f"input SHA-256 mismatch: {name}")
        sources[name] = source
        files[destination] = (payload, mode, label)

    env = {**os.environ, "LC_ALL": "C"}
    validate_private_closure(sources, env)
    deps = inspect_elf(audio_compat, env)
    dynamic = run(["readelf", "-d", str(audio_compat)], env=env).decode("ascii", "replace")
    if "libaudioclient.so" not in deps or f"Library soname: [{AUDIO_COMPAT}]" not in dynamic:
        raise VtserviceImageError("unexpected AudioTrack compatibility library dependencies or SONAME")
    symbols = run(["readelf", "--dyn-syms", "-W", str(audio_compat)], env=env).decode("ascii", "replace")
    if not re.search(rf"\sGLOBAL\s+DEFAULT\s+\d+\s+{AUDIO_CTOR}$", symbols, re.MULTILINE) or not re.search(
        rf"\sUND\s+{AUDIO_CTOR_17}$", symbols, re.MULTILINE
    ):
        raise VtserviceImageError("AudioTrack compatibility library lacks the old export or new import")
    files[f"lib64/{AUDIO_COMPAT}"] = (audio_compat.read_bytes(), 0o100644, "u:object_r:system_lib_file:s0")
    _ = run(["e2fsck", "-fn", str(image)], env=env)
    for directory in ("bin", "etc/init", "lib64"):
        if is_missing(image, directory, env):
            raise VtserviceImageError(f"required system_ext directory is absent: /{directory}")
    for destination in files:
        if not is_missing(image, destination, env):
            raise VtserviceImageError(f"refusing to replace existing path: /{destination}")
    available = free_inodes(image, env)
    if available < len(files):
        raise VtserviceImageError(
            f"system_ext has {available} free inodes; {len(files)} are required"
        )

    with tempfile.TemporaryDirectory(prefix="rothko-vtservice-", dir=output.parent) as scratch:
        work = Path(scratch)
        candidate = work / "system_ext.img"
        _ = subprocess.run(
            ["cp", "--reflink=auto", "--sparse=always", "--", str(image), str(candidate)],
            check=True,
        )
        sink = work / "libsink.so"
        sink_payload, sink_mode, sink_label = files["lib64/libsink.so"]
        sink.write_bytes(sink_payload)
        sink_deps = inspect_elf(sink, env)
        _ = run(["patchelf", "--add-needed", AUDIO_COMPAT, str(sink)], env=env)
        if inspect_elf(sink, env) != sink_deps | {AUDIO_COMPAT}:
            raise VtserviceImageError("unexpected changes to libsink.so dependencies")
        files["lib64/libsink.so"] = (sink.read_bytes(), sink_mode, sink_label)

        commands = []
        for number, (destination, (payload, mode, label)) in enumerate(files.items()):
            source_name = f"payload-{number}"
            label_name = f"selinux-label-{number}"
            (work / source_name).write_bytes(payload)
            (work / label_name).write_bytes((label + "\0").encode())
            commands.extend((
                f"write {source_name} /{destination}",
                f"set_inode_field /{destination} mode {mode:07o}",
                f"set_inode_field /{destination} uid 0",
                f"set_inode_field /{destination} gid 0",
                f"ea_set -f {label_name} /{destination} security.selinux",
            ))
        (work / "populate.debugfs").write_text("\n".join(commands) + "\n")
        _ = subprocess.run(["debugfs", "-w", "-f", "populate.debugfs", candidate], cwd=work, check=True, capture_output=True, env=env)
        _ = run(["e2fsck", "-fn", str(candidate)], env=env)

        for destination, (payload, mode, label) in files.items():
            stat = run(["debugfs", "-R", f"stat /{destination}", str(candidate)], env=env)
            mode_text = f"{mode & 0o7777:04o}".encode()
            if (
                not re.search(rb"Mode:\s+" + mode_text + rb"\b", stat)
                or b"User:     0   Group:     0" not in stat
                or (b'"' + label.encode() + b"\\000\"") not in stat
            ):
                raise VtserviceImageError(f"unexpected installed metadata: /{destination}")
            content = run(["debugfs", "-R", f"cat /{destination}", str(candidate)], env=env)
            if content != payload:
                raise VtserviceImageError(f"installed payload mismatch: /{destination}")
        output.hardlink_to(candidate)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_system_ext", type=Path, help="raw ext4 system_ext image without AVB footer")
    parser.add_argument("stock_system_ext_dump", type=Path, help="extracted matching stock system_ext root")
    parser.add_argument("ims_jni_dir", type=Path, help="verified ARM64 IMS JNI directory")
    parser.add_argument("audio_compat", type=Path, help="ARM64 AudioTrack bridge built against the target system libraries")
    parser.add_argument("output", type=Path, help="new output image; must not exist")
    args = parser.parse_args(argv)
    try:
        add_vtservice(args.raw_system_ext, args.stock_system_ext_dump, args.ims_jni_dir, args.audio_compat, args.output)
    except (OSError, VtserviceImageError, subprocess.CalledProcessError) as exc:
        print(f"VTSERVICE_IMAGE_ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Verified legacy MediaTek VT service image: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
