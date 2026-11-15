# Inventory

## Published here

| Item | Origin | Notes |
| --- | --- | --- |
| Device tree | original | `ImsService.apk` removed |
| Vendor staging scripts | original | stock images removed |
| frameworks/base | 1 commit on LineageOS `bc9fdde5` | FOD lifecycle, screen-off wake, UDFPS frame ordering |
| frameworks/native | 1 commit on LineageOS `9568531f` | vibrator instance fallback, BLASTBufferQueue init race |
| packages/apps/Settings | 1 commit on LineageOS `72494c35` | UDFPS enrollment UI |
| packages/apps/CarrierConfig | 1 commit on AOSP `b9722cd5` | voice capability snapshot, checked dump |
| bootable/recovery | 1 commit on LineageOS `acd99f7c` | normal-exit bridge, loader guard |
| system/sepolicy | 4 commits on LineageOS `885cc500` | system_ext CIL additions, native zygote gate, checked revisions |
| external/perfetto | 1 commit on AOSP `df0f96de` | non-blocking kernel wakelock tracing |
| hardware/xiaomi | 2 commits on LineageOS `f71c6821` | load unsuffixed legacy HAL; prebuilt-vendor build of the AIDL HAL |
| mfp-daemon-rs | 2 commits on hoshikv `2f42d751` | superseded by hardware/xiaomi + rothko UdfpsHandler |
| rothko-image-tools | original | verified to reproduce the shipped vendor image byte for byte |

Local-only build-host tweaks to `build/soong` and `build/blueprint` are not
exported.

## Not redistributable (obtain yourself)

| Item | Source |
| --- | --- |
| Stock boot, init_boot, vendor_boot, dtbo, vendor, odm, system_dlkm, vendor_dlkm, odm_dlkm | CN firmware `OS3.0.308.0.WNNCNXM` (hashes in `android_vendor_xiaomi_rothko/source-manifest.json`) |
| `ImsService.apk` | same firmware, `system_ext/priv-app/ImsService/` |
| SCP firmware with the Google hotword engine (`scp_a`) | global firmware `OS3.0.303.0.WNNMIXM`, `scp.img` |
| `HotwordEnrollmentOKGoogleRISCV_WIDEBAND`, `HotwordEnrollmentXGoogleRISCV_WIDEBAND` (v36), `com.android.hotwordenrollment.common.util.jar` | global firmware `OS3.0.303.0.WNNMIXM`, `product` / `system_ext` |
| Google apps | any GApps package you are licensed to use |
| AVB / platform signing keys | generate your own |

## Known gaps

The reference build applied these on images after `m`. They are documented
in PORTING-NOTES.md but are not yet build rules:

1. `/vendor/bin/hw/mfp-daemon` replaced by
   `android.hardware.biometrics.fingerprint-service.rothko-prebuilt-vendor`
   (`rothko-image-tools/erofs_replace_file.py`). With a source-built vendor,
   include `fingerprint.mk` instead.
2. `/vendor/etc/audio_param/VoWMicSetting_AudioParam.xml`:
   `dual_ch_transfer` 1 -> 0 (global firmware value).
3. system_ext: the two v36 hotword enrollment apps, the
   `hotwordenrollment.common.util` library and a permission file declaring
   the feature `com.mediatek.hardware.vow.gva.tflite`.
4. `scp_a` flashed with the global 303 SCP image.
