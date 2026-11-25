# SPDX-FileCopyrightText: The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
"""Protect the narrow stock MediaTek legacy VT service integration."""
from pathlib import Path
import importlib.util
import unittest

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "device/xiaomi/rothko/sepolicy/system_ext/private"
CONTEXTS = POLICY / "service_contexts"
FILE_CONTEXTS = POLICY / "file_contexts"
POLICY_RULES = POLICY / "vtservice.te"
PATCHER_PATH = ROOT / "tools/pixelos17/patch-system-ext-vtservice.py"
SPEC = importlib.util.spec_from_file_location("vtservice_image", PATCHER_PATH)
PATCHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCHER)


class ImsServiceContextTest(unittest.TestCase):
    def test_legacy_service_uses_stock_specific_label(self):
        entries = [line.split() for line in CONTEXTS.read_text().splitlines() if line.strip()]
        self.assertEqual(entries.count(["media.VTS", "u:object_r:vtservice_service:s0"]), 1)

    def test_daemon_executable_uses_stock_exec_label(self):
        self.assertEqual(
            FILE_CONTEXTS.read_text().splitlines(),
            ["/(system_ext|system/system_ext)/bin/vtservice u:object_r:vtservice_exec:s0"],
        )

    def test_policy_has_only_the_required_service_permissions(self):
        rules = POLICY_RULES.read_text()
        for expected in (
            "type vtservice, domain, coredomain;",
            "type vtservice_exec, exec_type, file_type, system_file_type;",
            "init_daemon_domain(vtservice)",
            "type vtservice_service, service_manager_type;",
            "binder_use(vtservice)",
            "binder_service(vtservice)",
            "allow radio vtservice_service:service_manager find;",
            "allow vtservice vtservice_service:service_manager add;",
            "allow vtservice mediaserver:binder { call transfer };",
            "allow mediaserver vtservice:binder transfer;",
            "allow vtservice mediaserver:fd use;",
        ):
            self.assertIn(expected, rules)
        self.assertNotIn("default_android_service", rules)
        self.assertNotIn("permissive", rules)

    def test_image_patcher_pins_exact_legacy_dependency_closure(self):
        self.assertEqual(len(PATCHER.INPUTS), 17)
        self.assertEqual(len(PATCHER.PRIVATE_LIBS), 15)
        self.assertEqual(
            {name for name, *_ in PATCHER.INPUTS if name.endswith(".so")},
            PATCHER.PRIVATE_LIBS,
        )
        self.assertEqual(
            [name for name, *_ in PATCHER.INPUTS if name == "libhidltransport.so"],
            ["libhidltransport.so"],
        )
        for name, _, digest, _, _ in PATCHER.INPUTS:
            self.assertRegex(digest, r"^[0-9a-f]{64}$", name)


if __name__ == "__main__":
    unittest.main()
