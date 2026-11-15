#
# Redmi K70 Ultra (rothko, 2407FRK8EC, CN/WNNCNXM) — vendor prebuilt phase 1
#
# This file is the vendor-side BoardConfig hook. The device BoardConfig must
# include it explicitly with:
#     include vendor/xiaomi/rothko/BoardConfigVendor.mk
# (This lane does not edit the device tree.)
#
# Nine stock images are kept byte-for-byte. Only vendor_boot and vendor use
# reviewed derived images with fstab-only removals. Framework/system/product/
# system_ext are built by Lineage and are intentionally not listed here.
# No mi_ext prebuilt hook is assumed.
#
ROTHKO_VENDOR_PATH := vendor/xiaomi/rothko
ROTHKO_PREBUILT_DIR := $(ROTHKO_VENDOR_PATH)/prebuilt
ROTHKO_DERIVED_DIR := $(ROTHKO_VENDOR_PATH)/derived
ROTHKO_VENDOR_SOURCE_MANIFEST := $(ROTHKO_VENDOR_PATH)/source-manifest.json

# Stock prebuilt partitions. Names are the actual lineage-23.2 flags.
BOARD_PREBUILT_BOOTIMAGE := $(ROTHKO_PREBUILT_DIR)/boot.img
BOARD_PREBUILT_INIT_BOOT_IMAGE := $(ROTHKO_PREBUILT_DIR)/init_boot.img
# Derived only-fstab updates: vendor_boot and vendor. The seven other
# stock images remain byte-identical prebuilts.
BOARD_PREBUILT_VENDOR_BOOTIMAGE := $(ROTHKO_DERIVED_DIR)/vendor_boot.img
BOARD_PREBUILT_DTBOIMAGE := $(ROTHKO_PREBUILT_DIR)/dtbo.img
BOARD_PREBUILT_VENDORIMAGE := $(ROTHKO_DERIVED_DIR)/vendor.img
BOARD_PREBUILT_ODMIMAGE := $(ROTHKO_PREBUILT_DIR)/odm.img
BOARD_PREBUILT_SYSTEM_DLKMIMAGE := $(ROTHKO_PREBUILT_DIR)/system_dlkm.img
BOARD_PREBUILT_VENDOR_DLKMIMAGE := $(ROTHKO_PREBUILT_DIR)/vendor_dlkm.img
BOARD_PREBUILT_ODM_DLKMIMAGE := $(ROTHKO_PREBUILT_DIR)/odm_dlkm.img

# Readiness is an independent gate. This flag deliberately stays false; a
# successful prebuilt hash check does not prove VINTF/SELinux or bootability.
ROTHKO_HARDWARE_RELEASE_READY := false

# Narrow build gate: only missing images or size/SHA-256 mismatch fail. It
# does not assert CRC, compatibility, or OEM authentication. Cleaning is not
# blocked by absent binaries.
ifneq ($(filter clean clobber dataclean installclean,$(MAKECMDGOALS)),)
else
ROTHKO_PREBUILT_GATE := $(shell python3 $(ROTHKO_VENDOR_PATH)/scripts/verify_prebuilts.py --make --root $(ROTHKO_VENDOR_PATH) 2>&1 || echo ROTHKO_VENDOR_PREBUILT_COMMAND_FAILED)
ifneq (,$(strip $(ROTHKO_PREBUILT_GATE)))
$(error $(ROTHKO_PREBUILT_GATE))
endif
endif
