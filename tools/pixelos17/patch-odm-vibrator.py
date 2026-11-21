#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Add the standard vibrator instance to Rothko's stock ODM override.

Pass a raw ODM filesystem with its AVB footer already removed. The output
keeps the image geometry and modifies only the existing inline XML extent.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Final
from xml.etree import ElementTree as ET

MANIFEST: Final = "/etc/vintf/manifest/vendor.xiaomi.hardware.vibratorfeature.service.xml"


def manifest_bytes(image: Path, directory: Path) -> bytes:
    xml = directory / "vibrator.xml"
    subprocess.run(
        ["fsck.erofs", "--no-preserve", f"--path={MANIFEST}", f"--extract={xml}", image],
        check=True,
    )
    return xml.read_bytes()


def updated_manifest(original: bytes) -> bytes:
    root = ET.fromstring(original)
    matches = [hal for hal in root.findall("hal") if hal.findtext("name") == "android.hardware.vibrator"]
    if len(matches) != 1:
        raise ValueError("expected exactly one vibrator HAL declaration")
    hal = matches[0]
    if hal.get("format") != "aidl" or hal.get("override") != "true":
        raise ValueError("expected the stock AIDL vibrator override")
    if [entry.text for entry in hal.findall("fqname")] != ["IVibrator/vibratorfeature"]:
        raise ValueError("expected the stock vibratorfeature instance")
    ET.SubElement(hal, "fqname").text = "IVibrator/default"
    for node in root.iter():
        if node.text is not None and not node.text.strip():
            node.text = None
        if node.tail is not None and not node.tail.strip():
            node.tail = None
    payload = ET.tostring(root, encoding="utf-8")
    if len(payload) > len(original):
        raise ValueError("updated manifest does not fit the original extent")
    return payload.ljust(len(original), b" ")


def patch(image: Path, output: Path) -> None:
    if output.exists():
        raise FileExistsError(output)
    with image.open("rb") as stream:
        stream.seek(1024)
        superblock = stream.read(128)
    if len(superblock) != 128 or struct.unpack_from("<I", superblock)[0] != 0xE0F5E1E2:
        raise ValueError("expected an EROFS image")
    blocks = struct.unpack_from("<I", superblock, 36)[0]
    if superblock[12] != 12 or blocks * 4096 != image.stat().st_size:
        raise ValueError("expected a raw 4 KiB-block ODM image without its AVB footer")
    layout = subprocess.check_output(["dump.erofs", f"--path={MANIFEST}", "-e", image], text=True)
    if not re.search(r"\bLayout:\s*2\b", layout) or not re.search(r"\b1 extents found\b", layout):
        raise ValueError("expected a single inline EROFS extent")
    extent = re.search(r"^\s*0:\s*0\.\.\s*(\d+)\s*\|\s*\d+\s*:\s*(\d+)\.\.\s*(\d+)", layout, re.M)
    if extent is None:
        raise ValueError("cannot parse the manifest extent")
    length, start, end = map(int, extent.groups())
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        directory = Path(temporary)
        original = manifest_bytes(image, directory)
        if not length == len(original) == end - start or end > image.stat().st_size:
            raise ValueError("manifest extent does not match the extracted XML")
        replacement = updated_manifest(original)
        candidate = directory / "odm.img"
        shutil.copyfile(image, candidate)
        with candidate.open("r+b") as stream:
            stream.seek(start)
            if stream.read(length) != original:
                raise ValueError("raw manifest bytes do not match the extracted XML")
            stream.seek(start)
            stream.write(replacement)
        (directory / "vibrator.xml").unlink()
        if manifest_bytes(candidate, directory) != replacement:
            raise ValueError("updated manifest extraction does not verify")
        subprocess.run(["fsck.erofs", candidate], check=True)
        os.link(candidate, output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_odm", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    patch(args.raw_odm, args.output)


if __name__ == "__main__":
    main()
