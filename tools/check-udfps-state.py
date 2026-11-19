#!/usr/bin/env python3
# SPDX-FileCopyrightText: The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
"""Compile and exercise the production UDFPS operation gate without a device."""
from pathlib import Path
import os
import shlex
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="rothko-udfps-state-") as temporary:
    executable = Path(temporary) / "udfps-state"
    compiler = shlex.split(os.environ.get("CXX", "c++"))
    subprocess.run([*compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=undefined", "-fno-sanitize-recover=all",
                    str(root / "tests/udfps-state.cpp"), "-o", str(executable)], check=True)
    subprocess.run([str(executable)], check=True)
