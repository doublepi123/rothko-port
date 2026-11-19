#
# SPDX-FileCopyrightText: The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
#
# Redmi K70 Ultra (rothko) product configuration.
#
# This product deliberately does not add speculative MediaTek/Xiaomi HAL
# packages, permissions, VINTF fragments or SELinux policy. Those must come
# from the verified vendor inventory. The build gate in BoardConfig.mk stops
# configuration until that evidence exists.

include device/xiaomi/rothko/config/product-parameters.mk

# The stock vendor compatibility matrix requires vendor-ndk 34. Keep the
# matching snapshot instead of substituting current-platform library ABIs.
PRODUCT_EXTRA_VNDK_VERSIONS += 34

# The stock health estimate is zero/unreliable below full charge. Use Android's
# observed charging progress for time-to-full; retain all charging controls.
PRODUCT_SYSTEM_PROPERTIES += ro.config.prefer_charge_step_estimate=true


# Partial, evidence-frozen compatibility matrix fragment (174 observed HAL
# instances in 93 HAL groups). It is an exact static candidate, not complete
# device compatibility, and actual runtime registration is unverified. The
# module installs a byte-frozen XML fragment into product/etc/vintf; it does
# not replace or merge the Lineage framework compatibility matrix.
PRODUCT_PACKAGES += rothko_framework_compatibility_matrix

# Registration-only alias of the verified stock vibrator node. The declaration
# must stay with vibratorfeature in the same ODM override HAL, not in vendor.
# Prebuilt vendor/ODM images require the separately reviewed image integration.
PRODUCT_PACKAGES += \
    android.hardware.vibrator-service.rothko-alias \
    rothko_vibrator_alias_odm_manifest

# init_boot is a stock prebuilt (stock generic ramdisk); do not build a
# Lineage generic ramdisk here. The stock init/overlay behavior is a known
# compatibility risk to check later.
$(call inherit-product, $(SRC_TARGET_DIR)/product/emulated_storage.mk)

# Virtual A/B with snapshots and gz COW, as recorded in the OTA metadata.
$(call inherit-product, $(SRC_TARGET_DIR)/product/virtual_ab_ota/vabc_features.mk)

# The stock fstab lists system_ext, product and mi_ext separately; the built
# system/system_ext/product images are placed by the dynamic partition layout.
# No copy of the stock fstab or stock properties is made here: the stock
# vendor_boot is kept as a prebuilt image and continues to provide them.

# Verified same-firmware IMS service and exact device provider/capability overlays.
# Standard signature/privapp/uses-library checks remain enabled.
PRODUCT_PACKAGES += \
    RothkoImsService \
    rothko_ims_privapp_permissions \
    RothkoImsTelephonyOverlay \
    RothkoImsFrameworkOverlay

# Same-device .308 stock display geometry; resource-only runtime overlays.
# Keep framework-res and the framework bootclasspath byte-for-byte unchanged.
PRODUCT_PACKAGES += \
    RothkoStatusBarFrameworkOverlay \
    RothkoStatusBarSystemUIOverlay

# Limited same-firmware unconditional-positive voice profiles only; no global/NR override.
PRODUCT_PACKAGES += RothkoCarrierVoiceCapabilityOverlay
