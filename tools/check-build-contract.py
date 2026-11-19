#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Exercise the real preflight CLI without proprietary firmware inputs."""

from pathlib import Path
import subprocess
import sys


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    device = root / "device/xiaomi/rothko"
    vendor = root / "vendor/xiaomi/rothko"
    if (vendor / "prebuilt").exists():
        print("Run this check in a source-only checkout without staged firmware.", file=sys.stderr)
        return 2
    cases = [
        ("development inputs still required", "target-files-package", "", "development", False),
        ("development VINTF tool inputs still required", "target-files-package check_target_files_vintf", "", "development", False),
        ("VINTF tool mixed with OTA release gate", "check_target_files_vintf", "otapackage", "development", True),
        ("default full build release gate", "target-files-package", "", "release", True),
        ("development OTA release gate", "otapackage", "", "development", True),
        ("development bacon release gate", "bacon", "", "development", True),
        ("mixed original OTA release gate", "target-files-package", "otapackage", "development", True),
        ("framework original OTA release gate", "systemimage", "otapackage", "release", True),
        ("clean mixed with full build", "clean", "target-files-package", "release", True),
    ]
    for label, goals, original, purpose, release in cases:
        result = subprocess.run(
            [sys.executable, str(device / "scripts/preflight.py"), "--make",
             "--device-root", str(device), "--vendor-root", str(vendor),
             "--make-goals", goals, "--original-goals", original, "--build-purpose", purpose],
            capture_output=True, text=True, check=False,
        )
        text = result.stdout + result.stderr
        if (result.returncode != 1 or "prebuilt images missing" not in text
                or ("release readiness is false" in text) != release):
            print(f"FAIL: {label}\n{text}", file=sys.stderr)
            return 1
        print(f"PASS: {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
