#
# SPDX-FileCopyrightText: The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
#
# Fingerprint integration for a source-built vendor image. Not included while
# vendor is the stock prebuilt; until then the prebuilt-vendor variant in
# udfps/Android.bp replaces /vendor/bin/hw/mfp-daemon in place.

PRODUCT_SOONG_NAMESPACES += hardware/xiaomi

$(call soong_config_set,XIAOMI_BIOMETRICS_FINGERPRINT,IMPL_VER,V2)

PRODUCT_PACKAGES += \
    android.hardware.biometrics.fingerprint-service.xiaomi \
    libudfpshandler

PRODUCT_VENDOR_PROPERTIES += \
    persist.vendor.fingerprint.type=udfps_optical \
    persist.vendor.fingerprint.sensor_id=5 \
    persist.vendor.fingerprint.sensor_location=610|2444|105
