#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Add the verified Rothko Wideband enrollment payload to a raw system_ext image."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Final

APK_DIRS: Final = (
    "/priv-app/HotwordEnrollmentOKGoogleRISCV",
    "/priv-app/HotwordEnrollmentXGoogleRISCV",
)
INPUTS: Final = (
    (
        "HotwordEnrollmentYGoogleRISCV_WIDEBAND.apk",
        APK_DIRS[0] + "/HotwordEnrollmentOKGoogleRISCV.apk",
        "a308d9531771b631e5e922492978ce4d559825b26ffdc400be173653608756a8",
    ),
    (
        "HotwordEnrollmentXGoogleRISCV_WIDEBAND.apk",
        APK_DIRS[1] + "/HotwordEnrollmentXGoogleRISCV.apk",
        "50b187dcc13b56bc3d7c17173a780381db2c2c656ca0e13f88d0e9620554957e",
    ),
    (
        "common.util.jar",
        "/framework/com.android.hotwordenrollment.common.util.jar",
        "7037c3761c26924cf047a88ce0ed85d1ba37239ac71ac5cd3cce9a2e9c6df4d6",
    ),
    (
        "common.util.xml",
        "/etc/permissions/com.android.hotwordenrollment.common.util.xml",
        "8d962466733e9c7b44d65f0a4ea86c48ffa29490bc67dfceac7a44e3a8eeaa10",
    ),
)
LABEL: Final = b"u:object_r:system_file:s0\0"


class HotwordImageError(RuntimeError):
    pass


def add_hotword(image: Path, firmware: Path, output: Path) -> None:
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    with image.open("rb") as stream:
        _ = stream.seek(-64, os.SEEK_END)
        if stream.read(4) == b"AVBf":
            raise HotwordImageError("strip the AVB footer from a copy of system_ext first")

    files: dict[str, bytes] = {}
    for name, destination, expected in INPUTS:
        payload = (firmware / name).read_bytes()
        if hashlib.sha256(payload).hexdigest() != expected:
            raise HotwordImageError(f"firmware SHA-256 mismatch: {name}")
        files[destination] = payload

    permissions = ['<?xml version="1.0" encoding="utf-8"?>', '<permissions>']
    for package in ("okgoogle", "xgoogle"):
        permissions.extend((
            f'    <privapp-permissions package="com.android.hotwordenrollment.{package}">',
            '        <permission name="android.permission.KEYPHRASE_ENROLLMENT_APPLICATION" />',
            '        <permission name="android.permission.INTERACT_ACROSS_USERS" />',
            '    </privapp-permissions>',
        ))
    files["/etc/permissions/privapp-permissions-google-hotword.xml"] = (
        "\n".join([*permissions, "</permissions>", ""]).encode()
    )
    files["/etc/permissions/com.mediatek.hardware.vow.gva.tflite.xml"] = (
        b'<?xml version="1.0" encoding="utf-8" ?>\n\n<permissions>\n'
        b'    <feature name="com.mediatek.hardware.vow.gva.tflite"/>\n</permissions>\n'
    )

    debugfs_env = {**os.environ, "LC_ALL": "C"}
    _ = subprocess.run(["e2fsck", "-fn", image], check=True)
    for destination in (*APK_DIRS, *files):
        result = subprocess.run(
            ["debugfs", "-R", f"stat {destination}", image],
            check=True,
            capture_output=True,
            env=debugfs_env,
        )
        if b"File not found by ext2_lookup" not in result.stderr:
            raise HotwordImageError(f"expected an absent path in system_ext: {destination}")

    with tempfile.TemporaryDirectory(prefix="rothko-hotword-", dir=output.parent) as scratch:
        work = Path(scratch)
        candidate = work / "system_ext.img"
        _ = subprocess.run(["cp", "--reflink=auto", "--sparse=always", "--", image, candidate], check=True)
        _ = (work / "selinux.label").write_bytes(LABEL)
        commands = [f"mkdir {directory}" for directory in APK_DIRS]
        for number, (destination, payload) in enumerate(files.items()):
            name = f"payload-{number}"
            _ = (work / name).write_bytes(payload)
            commands.append(f"write {name} {destination}")

        for destination in (*APK_DIRS, *files):
            mode = "040755" if destination in APK_DIRS else "0100644"
            commands.extend((
                f"set_inode_field {destination} mode {mode}",
                f"set_inode_field {destination} uid 0",
                f"set_inode_field {destination} gid 0",
                f"ea_set -f selinux.label {destination} security.selinux",
            ))
        _ = (work / "populate.debugfs").write_text("\n".join(commands) + "\n")
        _ = subprocess.run(["debugfs", "-w", "-f", "populate.debugfs", candidate], cwd=work, check=True)
        _ = subprocess.run(["e2fsck", "-fn", candidate], check=True)

        for destination in (*APK_DIRS, *files):
            stat = subprocess.check_output(
                ["debugfs", "-R", f"stat {destination}", candidate], env=debugfs_env
            )
            mode = b"0755" if destination in APK_DIRS else b"0644"
            if not stat or (b"Mode:  " + mode not in stat.splitlines()[0]
                            or b"User:     0   Group:     0" not in stat
                            or b'"u:object_r:system_file:s0\\000"' not in stat):
                raise HotwordImageError(f"unexpected installed metadata: {destination}")
            if destination in files:
                content = subprocess.check_output(["debugfs", "-R", f"cat {destination}", candidate])
                if content != files[destination]:
                    raise HotwordImageError(f"installed payload mismatch: {destination}")
        output.hardlink_to(candidate)


def main() -> int:
    args = sys.argv[1:]
    usage = f"Usage: {Path(sys.argv[0]).name} RAW_SYSTEM_EXT WIDEBAND_INPUT_DIR OUTPUT"
    if args in (["-h"], ["--help"]):
        print(usage)
        return 0
    if len(args) != 3:
        print(usage, file=sys.stderr)
        return 2
    image, firmware, output = map(Path, args)
    try:
        add_hotword(image.resolve(), firmware.resolve(), output.absolute())
    except (OSError, HotwordImageError, subprocess.CalledProcessError) as exc:
        print(f"HOTWORD_IMAGE_ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Verified hotword filesystem: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
