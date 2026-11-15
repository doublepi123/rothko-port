# Porting notes

## Screen-off "Hey Google" (SCP DSP hotword)

- The CN SCP firmware reports the MediaTek default engine, so Google's app
  stays on software hotword (`trusted_hotword_software`) and cannot wake the
  device from screen-off.
- The global `OS3.0.303.0.WNNMIXM` SCP image contains the Google engine.
  It matches the CN build closely enough to swap: same signing certificate,
  byte-identical scp/vow/sensorhub kernel modules, identical SCP device-tree
  nodes. The bootloader loads SCP only on a normal Linux boot (not from
  fastboot or recovery), and `scp` is not covered by vbmeta.
- With that SCP the engine is TFLite. It needs the v36 hotword enrollment
  apps and the matching `common.util` library from the same global build.
  With the `com.mediatek.hardware.vow.gva.tflite` feature declared, they
  choose `config_tflite.xml` / `*.tflite` models. zh-CN maps to
  `*_small_universal`. The older v35 apps send the legacy `.mmap` model,
  which crashes the SCP about 330 ms after `VOW_MODEL_START`.
- `VoWMicSetting_AudioParam.xml` `dual_ch_transfer` was aligned with the
  global value (0). On its own it did not stop the crash.
- Package manager caches system_ext packages by directory mtime. When
  replacing them, bump the directory and file mtimes or the old version stays
  active.

## Vibration

The stock HAL registers only `IVibrator/vibratorfeature`, not
`IVibrator/default`. Two things make vibration work: the
`vibrator_alias` service in the device tree, and a fallback to that
instance in `frameworks/native`'s `VibratorHalController`.

## Under-display fingerprint

- The fingerprint HAL is LineageOS `hardware/xiaomi`'s AIDL service
  (`IMPL_VER V2`) with a rothko `UdfpsHandler` (device `udfps/`). It loads
  the stock Goodix legacy HAL, `/odm/lib64/hw/fingerprint.goodix_fod.so`.
- `hw_get_module_by_class()` never finds that file because it has no
  variant suffix. The `hardware/xiaomi` patch falls back to dlopen()ing it.
- Handler, per press: `extCmd(1, 1)` for finger down, local HBM via
  `/dev/mi_display/disp_feature` (ioctl `0x400c440e`, value 2), then
  `extCmd(10, 1|6)` when the display event (type 2) reports the FOD layer
  ready. Release reverses this.
- Screen off: the handler enables TouchFeature mode 10 and polls
  `/sys/class/touch/touch_dev/fod_press_status`. Keyguard authentication
  stays running while the screen is off, so a screen-off press is captured
  directly by the HAL and the framework wakes on `onAuthenticated`. This
  matches LineageOS mt6895-common. No framework changes are needed.
- Tested with stock (FOD-patch-free) services and SystemUI: lit and
  screen-off unlock, including quick taps, about 150 ms per match.
- Keep the template group path `/data/vendor_de/<user>/fpdata` (no
  trailing slash) when migrating from the stock HAL, or existing templates
  are not found.
- SystemUI sizes the UDFPS icon from `pixel_pitch`. rothko is 57.0 um
  (1220x2712 at 445.614 dpi), set in the SystemUI geometry overlay.
- The earlier `mfp-daemon-rs` fork and the frameworks/base FOD patch are
  superseded by this stack.
