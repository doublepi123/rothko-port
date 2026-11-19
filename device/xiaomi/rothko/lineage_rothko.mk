#
# SPDX-FileCopyrightText: The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
#

# Inherit from those products. Most specific first.
$(call inherit-product, $(SRC_TARGET_DIR)/product/core_64_bit_only.mk)
$(call inherit-product, $(SRC_TARGET_DIR)/product/full_base_telephony.mk)

# Inherit from the device makefile.
$(call inherit-product, device/xiaomi/rothko/device.mk)

# Inherit the vendor-side product hook (no speculative HALs/VINTF/SELinux).
# The hook is required; missing it must fail, not silently drop vendor config.
ROTHKO_VENDOR_PRODUCT := vendor/xiaomi/rothko/rothko-vendor.mk
ifeq (,$(wildcard $(ROTHKO_VENDOR_PRODUCT)))
$(error required vendor product hook missing: $(ROTHKO_VENDOR_PRODUCT))
endif
$(call inherit-product, $(ROTHKO_VENDOR_PRODUCT))

# Inherit common LineageOS configuration.
$(call inherit-product, vendor/lineage/config/common_full_phone.mk)

# Disposable development certificates are supplied by the build operator.
# Their use does not alter the independent hardware/release readiness gates.
ifeq ($(ROTHKO_BUILD_PURPOSE),development)
PRODUCT_DEFAULT_DEV_CERTIFICATE := vendor/xiaomi/rothko/keys/releasekey
endif

PRODUCT_BRAND := Redmi
PRODUCT_DEVICE := rothko
PRODUCT_MANUFACTURER := Xiaomi
PRODUCT_MODEL := Redmi K70 Ultra
PRODUCT_NAME := lineage_rothko
PRODUCT_GMS_CLIENTID_BASE := android-xiaomi

# The stock vendor/odm images identify:
#   ro.product.odm_dlkm.device=rothko
#   ro.product.odm_dlkm.model=2407FRK8EC
#   ro.product.odm_dlkm.marketname=Redmi K70 Ultra
#   ro.product.odm_dlkm.brand=Redmi
#   ro.product.odm_dlkm.manufacturer=Xiaomi
# See docs/EVIDENCE.md for the bootimage build-label discrepancy.
