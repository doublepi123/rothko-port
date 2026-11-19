"""Check the actual product generator against missing and unavailable OTA images."""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "device/xiaomi/rothko/config"
SPEC = importlib.util.spec_from_file_location("rothko_device_config", CONFIG / "generate_device_config.py")
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)


class PartitionPlanTest(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((CONFIG / "device-parameters.json").read_text())

    def test_actual_twelve_image_plan_generates_coherent_metadata(self):
        plan = self.cfg["build_plan"]
        parts = GENERATOR.validate_ota_partition_plan(plan)
        self.assertEqual(len(parts), 12)
        self.assertEqual(set(parts), set(plan["built_by_lineage"] + plan["stock_prebuilt"]))
        rendered = GENERATOR.render_product(self.cfg)
        self.assertIn("PRODUCT_BUILD_VBMETA_IMAGE := false", rendered)
        self.assertIn("AB_OTA_UPDATER := true", rendered)
        self.assertNotIn("    vbmeta", rendered)
        self.assertFalse(plan["avb"]["device_avb_touched"])

    def test_old_unproduced_vbmeta_entries_are_rejected(self):
        self.cfg["build_plan"]["ota_partitions"] += ["vbmeta", "vbmeta_system", "vbmeta_vendor"]
        with self.assertRaisesRegex(ValueError, "unavailable=.*vbmeta"):
            GENERATOR.render_product(self.cfg)

    def test_missing_real_init_boot_image_is_rejected(self):
        self.cfg["build_plan"]["ota_partitions"].remove("init_boot")
        with self.assertRaisesRegex(ValueError, "missing=.*init_boot"):
            GENERATOR.render_product(self.cfg)

    def test_duplicate_partition_is_rejected(self):
        self.cfg["build_plan"]["ota_partitions"].append("system")
        with self.assertRaisesRegex(ValueError, "duplicate partition"):
            GENERATOR.render_product(self.cfg)

    def test_implicit_avb_signing_change_is_rejected(self):
        self.cfg["build_plan"]["avb"]["enabled"] = True
        with self.assertRaisesRegex(ValueError, "AVB signing to remain disabled"):
            GENERATOR.render_product(self.cfg)


if __name__ == "__main__":
    unittest.main()
