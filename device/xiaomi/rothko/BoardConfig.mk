#
# SPDX-FileCopyrightText: The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
#
# Redmi K70 Ultra (rothko, 2407FRK8EC, MT6989)
#
# Phase 1 split:
#   stock prebuilt : boot (kernel), init_boot (stock generic ramdisk),
#                    vendor_boot (platform + recovery fragments, DTBO container),
#                    dtbo, vendor, odm, system_dlkm, vendor_dlkm, odm_dlkm
#   built by Lineage: system, system_ext, product
#   mi_ext         : checked, no native driver/VINTF evidence; NOT staged;
#                    target not mounted, phone partition preserved
#
# The values below come from config/device-parameters.json. Evidence for each
# value is recorded there and in docs/EVIDENCE.md. Do not hand-edit the
# generated fragments.

DEVICE_PATH := device/xiaomi/rothko

include $(DEVICE_PATH)/config/device-parameters.mk

# Preserve every original request through Soong's Kati visibility filter.
# Forwarding is NOT permission: preflight still allows only framework goals;
# mixed framework+OTA/full requests must remain visible and fail that gate.
PARSE_TIME_MAKE_GOALS += $(sort $(ORIGINAL_MAKECMDGOALS) $(MAKECMDGOALS))

# The vendor lane owns the stock prebuilt images and their BOARD_PREBUILT_*
# flags. The contract is required, not optional: fail clearly if it is absent
# instead of silently building without vendor-owned prebuilts.
ROTHKO_VENDOR_BOARD := vendor/xiaomi/rothko/BoardConfigVendor.mk
ifeq (,$(wildcard $(ROTHKO_VENDOR_BOARD)))
$(error required vendor contract missing: $(ROTHKO_VENDOR_BOARD))
endif
include $(ROTHKO_VENDOR_BOARD)

# Keep secondary-arch libraries while using the branch's supported dynamic
# mediaserver selection. This product's zygote64 configuration starts the
# 64-bit service; do not change the global prefer32 default or either arch.
TARGET_DYNAMIC_64_32_MEDIASERVER := true

# Keep the retired custom SDK36 Recovery disabled (Soong defaults to false).
# User-selected OrangeFox must use the parent's independent prebuilt vendor_boot
# and matching AVB composition, not a self-built SDK36 Recovery.

# Refuse to configure a build while required inputs are missing, hashes do not
# match, the super/group budget is invalid, or vendor integration is unproven.
# preflight prints one ROTHKO_PREFLIGHT_ERROR line naming the missing inputs.
# Cleaning does not require a complete device input set.
# Soong dumpvars (lunch/get_build_var) invokes Kati with
# MAKECMDGOALS=<goals> and sets DUMP_MANY_VARS/CALLED_FROM_SETUP=true. That is a
# configuration read, not a release build. The separate cleanspec entry point
# receives no Kati goals and needs only configuration/input verification.
# Empty main.mk and full/OTA invocations retain the complete release gate.
ROTHKO_MAKE_CONTEXT := build
ROTHKO_BUILD_PURPOSE ?= release
ifeq ($(origin MAKECMDGOALS),command line)
  ifneq (,$(DUMP_MANY_VARS))
    ifeq ($(CALLED_FROM_SETUP),true)
      ROTHKO_MAKE_CONTEXT := configuration
    endif
  endif
endif
# MAKEFILE_LIST is reset during product imports. The helper independently
# verifies the approved Kati ancestor's actual -f/suffix for cleanspec only.
ROTHKO_PREFLIGHT_OUT := $(shell python3 $(DEVICE_PATH)/scripts/preflight.py --make --device-root $(DEVICE_PATH) --make-goals '$(MAKECMDGOALS)' --original-goals '$(ORIGINAL_MAKECMDGOALS)' --build-purpose '$(ROTHKO_BUILD_PURPOSE)' --make-context $(ROTHKO_MAKE_CONTEXT) --makefile-list '$(MAKEFILE_LIST)' --kati-context-report-dir '$(OUT_DIR)/rothko-kati-context' 2>&1 || echo ROTHKO_PREFLIGHT_COMMAND_FAILED)
ifneq (,$(strip $(ROTHKO_PREFLIGHT_OUT)))
$(error $(ROTHKO_PREFLIGHT_OUT))
endif

TARGET_NO_BOOTLOADER := true
# No separate built /kernel artifact. AOSP retains BOARD_PREBUILT_BOOTIMAGE
# and extracts VINTF kernel information from that actual stock boot instead.
TARGET_NO_KERNEL := true
# Lineage tasks/kernel.mk guards its self-build independently of the AOSP
# prebuilt-boot path. Keep the stock kernel in boot.img, with no kernel source.
TARGET_NO_KERNEL_OVERRIDE := true
TARGET_OTA_ASSERT_DEVICE := rothko

# Partition mount points confirmed by the stock first-stage fstab.
TARGET_COPY_OUT_VENDOR := vendor
TARGET_COPY_OUT_PRODUCT := product
TARGET_COPY_OUT_SYSTEM_EXT := system_ext
TARGET_COPY_OUT_ODM := odm
TARGET_COPY_OUT_ODM_DLKM := odm_dlkm
TARGET_COPY_OUT_SYSTEM_DLKM := system_dlkm
TARGET_COPY_OUT_VENDOR_DLKM := vendor_dlkm

TARGET_USERIMAGES_USE_F2FS := true
BOARD_USES_METADATA_PARTITION := true
BOARD_FLASH_BLOCK_SIZE := 4096

# system/product/system_ext are built as ext4; the stock fstab accepts both
# erofs and ext4 for these logical partitions. The stock vendor/odm/dlkm images
# keep their original filesystem and are copied as prebuilts.
BOARD_SYSTEMIMAGE_FILE_SYSTEM_TYPE := ext4
BOARD_PRODUCTIMAGE_FILE_SYSTEM_TYPE := ext4
BOARD_SYSTEM_EXTIMAGE_FILE_SYSTEM_TYPE := ext4

# init_boot is the stock prebuilt image, supplied through the exact
# BOARD_PREBUILT_INIT_BOOT_IMAGE flag verified in build/make/core. The stock
# generic ramdisk keeps stock init/overlay behavior; its compatibility with the
# Lineage framework is a later real check, not something this tree replaces.
# BOARD_BOOT_HEADER_VERSION is deliberately not set: setting it would make
# BUILDING_VENDOR_BOOT_IMAGE default to true and ignore the stock
# BOARD_PREBUILT_VENDOR_BOOTIMAGE. No kernel, init_boot or vendor_boot is built.

# BOARD_AVB_ENABLE := false only means this offline build does not sign
# generated images. It does not disable, alter or claim the phone's AVB state.
# The OEM private keys are not available; test keys must not be presented as
# stock signing. Stock prebuilts keep their original OEM signatures. Generated
# images are unsigned and are not flashable.
BOARD_AVB_ENABLE := false

# VINTF is intentionally not synthesized here. The stock vendor image is
# Android 14/SDK 34 while this framework is Android 16; compatibility must be
# proven from the vendor inventory before a build. preflight blocks the build
# until that evidence is supplied. No empty manifest is created.
#
# The reviewed permission-only device-private system_ext CIL below is appended
# to the existing Lineage private dirs. It contains five narrowing denies and
# is not a compatibility pass; no ignore/permissive policy or new filesystem
# label is enabled.
SYSTEM_EXT_PRIVATE_SEPOLICY_DIRS += $(DEVICE_PATH)/sepolicy/system_ext/private
