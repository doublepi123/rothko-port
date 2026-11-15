# LineageOS 23.2 for Redmi K70 Ultra (rothko)

Unofficial, experimental LineageOS `lineage-23.2` (Android 16) bring-up for the
Chinese Redmi K70 Ultra (`2407FRK8EC`, codename `rothko`, MediaTek MT6989).

This tree contains source only. No Xiaomi, MediaTek or Google binaries are
included; you extract them yourself from official firmware (see
[INVENTORY.md](INVENTORY.md)).

## Layout

| Directory | Becomes | Contents |
| --- | --- | --- |
| `android_device_xiaomi_rothko/` | `device/xiaomi/rothko` | Board/product config, sepolicy, overlays, vibrator alias service, recovery runtime |
| `android_vendor_xiaomi_rothko/` | `vendor/xiaomi/rothko` | Scripts and manifests that stage the stock prebuilt images (images not included) |
| `patches/android_*/` | forks of the matching Lineage/AOSP repos | `git format-patch` series on top of the base commit in `patches/BASES.tsv` |
| `mfp-daemon-rs/` | `/vendor/bin/hw/mfp-daemon` | Rust fingerprint AIDL HAL, fork of hoshikv/mfp-daemon-rs (branch `rothko`) |
| `rothko-image-tools/` | host tools | In-place EROFS file replacement with AVB/FEC re-signing |
| `local_manifests/rothko.xml` | `.repo/local_manifests/` | Template that pulls the forks once they are published |
| `PORTING-NOTES.md` | | Root causes and fixes for voice wake, vibration and fingerprint |

## Status

Tested on one device by its owner (USER build, SELinux enforcing, AVB with a
development key):

- Boots to system on slot a; calls and camera work.
- Vibration works.
- Under-display fingerprint unlock works, including quick presses on a
  screen-off (AOD/doze) device.
- "Hey Google" wakes the device from screen-off through the SCP DSP.

Everything else should be treated as untested. This is not a release.

## Building

1. Sync LineageOS `lineage-23.2`.
2. Apply each series in `patches/` to its repo (`./apply-patches.sh <source-root>`),
   or use the published forks via `local_manifests/rothko.xml`.
3. Copy `android_device_xiaomi_rothko` and `android_vendor_xiaomi_rothko` to
   `device/xiaomi/rothko` and `vendor/xiaomi/rothko`.
4. Stage the stock images and the IMS APK as described in
   `android_vendor_xiaomi_rothko/README.md` and
   `android_device_xiaomi_rothko/ims/prebuilt/README.md`.
5. `lunch lineage_rothko-bp4a-user && m`, signing with your own keys.

Steps that the reference build performed on images after `m` (not yet
expressed as build rules) are listed under "Known gaps" in
[INVENTORY.md](INVENTORY.md).

## Licenses

Device tree, patches and tools: Apache-2.0 unless a file says otherwise.
`mfp-daemon-rs`: Apache-2.0, see its `LICENSE` and `NOTICE`.

## Disclaimer

Flashing modified partitions can brick the device. You need an unlocked
bootloader, a working recovery and your own backups.
