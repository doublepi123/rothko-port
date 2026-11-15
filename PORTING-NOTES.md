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

- `mfp-daemon-rs` (rothko branch) replaces the stock `mfp-daemon`. The
  framework side (frameworks/base patch) drives the FodEngine 2.0 monitor,
  lease and release commands. It also handles screen-off wake presses.
- Intermittent "screen wakes but never unlocks": a quick screen-off press
  (about 80 ms) produces only `GF_ERROR_TOO_FAST`. That acquired notice
  never resumes the request, and the framework de-duplicates the monitor
  command. If the re-arm after the wake release is lost, the touch FOD
  monitor (`Touch_Fod_Enable`) stays off until the next screen-off. The
  fix in commit "fod: re-arm ON monitor after a screen-off wake press
  release" falls back to a full revalidated re-arm. It also re-syncs the
  monitor after every successful lease stop.
