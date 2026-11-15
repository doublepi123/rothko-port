#
# Redmi K70 Ultra (rothko) — product-side vendor hook, phase 1.
#
# BoardConfigVendor.mk owns the BOARD_PREBUILT_* image paths. This product
# makefile intentionally does not add generic HAL packages, VINTF fragments,
# SELinux policy, or PRODUCT_COPY_FILES for proprietary images. Those are
# separate device/vendor integration decisions and must be based on the real
# vendor inventory.
#
ROTHKO_VENDOR_PATH := vendor/xiaomi/rothko
ROTHKO_VENDOR_SOURCE_MANIFEST := $(ROTHKO_VENDOR_PATH)/source-manifest.json

# No PRODUCT_PACKAGES are invented here.
