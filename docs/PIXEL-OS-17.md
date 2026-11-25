# PixelOS 17 on Rothko

This branch targets the Chinese Redmi K70 Ultra (`2407FRK8EC`) and the `custom_rothko-cp2a-user` development product. The reference vendor firmware is `OS3.0.308.0.WNNCNXM`. [The main branch](https://github.com/doublepi123/rothko-port/tree/main) carries the Android 16 port.

## Build the development archive

The [manifest](../tools/manifests/platform.xml) pins PixelOS `seventeen`, AOSP `android-17.0.0_r1`, and the supplementary `hardware/xiaomi` project. Keep the port checkout outside the Android tree so Soong sees only the installed device modules. To reuse an existing checkout that already has the pinned Git objects, prepare the clean Android tree with `python3 tools/prepare-source.py --reference "$PIXEL_OS_REFERENCE" --destination "$ANDROID_ROOT" --jobs 8`. Then run these commands from the port repository:

```bash
bash tools/install-source.sh "$ANDROID_ROOT"
bash tools/apply-patches.sh "$ANDROID_ROOT"
```

Stage the required original firmware and IMS APK from your local copies. Use [the input preparation procedure](CLEAN-BUILD.md) for the files and independent development certificates. Those inputs have the same device provenance as the Android 16 port. Use the Android 17 manifest and product selection in this document for the platform itself.

```bash
cd "$ANDROID_ROOT"
source build/envsetup.sh
lunch custom_rothko-cp2a-user
export ROTHKO_BUILD_PURPOSE=development
export SOONG_JAVA_HIGHMEM_POOL=true SOONG_SERIALIZE_SINGLETONS=true
export NINJA_HIGHMEM_NUM_JOBS=1 GOMEMLIMIT=24GiB
m -j8 target-files-package check_target_files_vintf
```

The verified build used a separate output directory and reused Android 16 Git objects through alternates. A prebuilt init_boot is part of the packaging dependency graph. The Android 17 patch series adds the device CIL inputs and uses Android 17's `crosvm_domain`. The low-memory changes stream large Soong outputs and serialize Blueprint work with the opt-in build settings above. The checkout's complete Android 16 patch series and manifest are archived under `archive/lineage23.2/`.

The Rothko product includes `RothkoStatusBarFrameworkOverlay` as a static overlay in `system_ext`. It sets the default always-on display (AOD) brightness to `0.007874`, down from `0.015748031`. SystemUI can still lower the brightness based on the current display brightness. To bring this change to an existing repaired image, build the overlay from the same Android tree with `m RothkoStatusBarFrameworkOverlay` and replace `/overlay/RothkoStatusBarFrameworkOverlay.apk` in a copy of the raw `system_ext` filesystem. Keep the existing platform signing certificate and file attributes. Check the ext4 filesystem and apply the AVB signing procedure below. The display service reads this resource during boot, so reboot before checking the result.

## Prepare the device repairs

Start from the development archive and retain its original SHA-256. Treat the following repairs as a host-side image assembly step. Use the exact firmware input version, verify partition sizes against the target, and keep the already verified boot and recovery chain. This repository contains the source and tools for those steps. The development archive itself is the input for image assembly.

- **Fingerprint.** Build `android.hardware.biometrics.fingerprint-service.rothko-prebuilt-vendor` from the A17 tree. Integrate the compiled program at `/vendor/bin/hw/mfp-daemon`. Preserve the original owner, permissions and `hal_fingerprint_default_exec` label. The static service and handler share the Xiaomi V2 device ABI. The stock prebuilt by itself did not advance enrollment.
- **Camera.** Run `tools/pixelos17/fix-erofs-links.py` against the raw vendor filesystem and its matching read-only host mount. The verified Android kernel rejected a group of inline symlinks spanning the originating inode block. The repair relocates their payloads and preserves targets and attributes. Verify the output filesystem with `fsck.erofs` and read the candidate on the device kernel before deployment.
- **Vibration.** Build `android.hardware.vibrator-service.rothko-alias` and use its binary and init file under vendor. Apply the original vendor file contexts. Use `tools/pixelos17/patch-odm-vibrator.py RAW_ODM OUTPUT` after stripping the ODM AVB footer. The ODM override must publish `IVibrator/default` and `IVibrator/vibratorfeature` together. Run the host alias decision test and verify the default instance at runtime.
- **IMS.** Assemble the locally supplied APK and support files using the [IMS repair procedure](../tools/pixelos17/ims/README.md). Keep the existing platform signing identity. In system_ext, retain the APK at `/system_ext/priv-app/RothkoImsService/RothkoImsService.apk`, place the supplied arm64 JNI files in its `lib/arm64` directory, and remove the two stale ODEX/VDEX entries for the replaced APK. Keep owner `0:0`, file mode `0644`, directory mode `0755`, and the `system_file` labels from the working build. Check the filesystem and re-extract the APK and every library for comparison.

  The legacy video-telephony Binder publisher is the stock `/system_ext/bin/vtservice`; it invokes `VTService_instantiate()` from `libmtk_vt_service.so`. Restore its init rc and exact private ELF dependency closure after building the ext4 system_ext image. Starting from an owned raw copy with its AVB footer removed, run `e2fsck -fn`, `resize2fs RAW_SYSTEM_EXT 672M`, and `e2fsck -fn` before staging. The patcher checks all 18 required free inodes, exact stock/JNI SHA-256 pins, the ARM64 dependency closure, existing directories, metadata and payload readback. Build `tools/pixelos17/ims/audiotrack-abi.cpp` with the Android NDK's `aarch64-linux-android35-clang++`, linking to `libaudioclient.so` and `libc++.so` extracted from the target system:

  ```bash
  aarch64-linux-android35-clang++ -std=c++17 -O2 -shared -fvisibility=hidden \
    -fno-exceptions -fno-rtti -nostdlib++ -Wl,-z,defs \
    -Wl,-soname,librothko_vt_audio_compat.so \
    tools/pixelos17/ims/audiotrack-abi.cpp TARGET_LIBAUDIOCLIENT TARGET_LIBCXX \
    -o librothko_vt_audio_compat.so
  python3 tools/pixelos17/patch-system-ext-vtservice.py \
    RAW_SYSTEM_EXT \
    STOCK_SYSTEM_EXT_DUMP \
    IMS_JNI_DIR \
    librothko_vt_audio_compat.so \
    SYSTEM_EXT_WITH_VTSERVICE
  ```

  The stock `libsink.so` imports the older `AudioTrack` constructor. Android 17 adds `codecProvenance`, an optional string whose source default is empty. The bridge supplies that default. The patcher adds its `DT_NEEDED` entry only to the staged `libsink.so` and leaves the stock input and system audio client in place. For the checked Rothko build, the stock caller allocates `0x5c8` bytes and the target `AudioTrack` occupies `0x558` bytes. Recheck the layout and symbols when the base changes.

  It installs `/bin/vtservice`, `/etc/init/init.vtservice.rc`, and the 15 private service libraries plus the bridge under `/lib64`. The only private library sourced from the pinned JNI directory is `libhidltransport.so`; the remaining files are pinned from the stock system_ext dump. The policy adds the stock executable and service labels, init domain transition, radio `find`, vtservice `add`, and the stock media callback Binder permissions. Compile and inspect that policy before image assembly; do not weaken the normal SELinux checks.

  ```bash
  source build/envsetup.sh
  lunch custom_rothko-cp2a-user
  export OUT_DIR=out-pixelos17-r14
  export ROTHKO_BUILD_PURPOSE=development
  m -j8 systemextimage-nodeps
  ```

  Verify `vtservice_service` in `system_ext_sepolicy.cil`, `media.VTS` in `system_ext_service_contexts`, and `vtservice_exec` in `system_ext_file_contexts`. Soong generates these files under `out-pixelos17-r14/soong/.intermediates/system/sepolicy/`. For the verified repair, the image target generated policy intermediates and then stopped at a missing fingerprint overlay in the staging tree. The signed repair used the booted `system_ext` as its base and incorporated the VT policy delta. Both the baseline and the repair compiled with init's policy arguments. A strict comparison found the same 53 pre-existing `neverallow` conflicts in both sets of partition inputs.
- **Hey Google.** Use the Wideband enrollment APKs and `common.util.jar` and `.xml` from Rothko global firmware `OS3.0.303.0.WNNMIXM`. Keep their original filenames in the input directory (`HotwordEnrollmentXGoogleRISCV_WIDEBAND.apk`, `HotwordEnrollmentYGoogleRISCV_WIDEBAND.apk`, `common.util.jar`, `common.util.xml`). Starting from the raw ext4 `system_ext` after the IMS repair, run `python3 tools/pixelos17/patch-system-ext-hotword.py RAW_SYSTEM_EXT WIDEBAND_INPUT_DIR OUTPUT`. The tool pins the original files by SHA-256, retains the APK signatures and adds the shared library, the enrollment permission allowlist and the TFLite feature. This step is for the Rothko firmware cohort whose SoundTrigger HAL reports the Google DSP engine (version `750457514`). Re-sign `system_ext` with its existing development key, update its top-level `vbmeta` hashtree descriptor, and verify the full chain. After boot, re-enroll through Google Voice Match and try the spoken wake phrase both unlocked with the screen on and locked with the screen off.
- **Fingerprint layout.** `RothkoSettingsUdfpsOverlay` selects the side skip button and reduces the progress ring padding to 64 pixels in the default Rothko layout. The hardware coordinates and authentication behavior stay the same. The handset test used the equivalent same-signer runtime overlay. The static resources compiled with `aapt2`.

For the verified installation, the changed filesystem images were signed separately with the existing development AVB key. The affected hashtree descriptors in `vbmeta_vendor` and top-level `vbmeta` were replaced, preserving all other descriptors, flags, rollback indexes, and the recovery entry. The full chain and VINTF both passed before writing. Image assembly and signing require the operator's local inputs and signing material. The source checks cover this branch without those inputs.

## What was verified on hardware

The development `target-files` ZIP passed CRC and VINTF with the actual vendor and ODM images. The repaired signed partitions booted on one Chinese K70 Ultra with the expected AVB digest. A data-preserving repair update followed the initial installation. On that phone, the user confirmed front and rear previews, a connected call with speech in both directions, fingerprint enrollment and unlock, and motor vibration. A captured Settings screen shows the complete enrollment ring and unobstructed skip action.

The follow-up updates changed `system_ext_a` and its hashtree descriptor in `vbmeta_a`. The first restored the Wideband enrollment components. Voice Match registered a `zh-CN` model, and SoundTrigger module 0 recorded recognition with the phone both unlocked and locked with the screen off. The second updated the static AOD overlay and preserved the hotword and IMS files. Both updates booted with the expected AVB digest, and the previous signed images were kept as a rollback pair.

After the brightness update, `adb shell cmd overlay lookup android android:dimen/config_screenBrightnessDozeFloat` returned `0.007874`, and `adb shell dumpsys display` reported that value with the screen in `DOZE`. The user confirmed that the clock was more comfortable to read in the dark, that screen-off fingerprint unlock worked, and that saying “Hey Google” while the phone was locked and the screen was off opened Gemini. The fingerprint counter and SoundTrigger logs recorded both successful actions.

The IMS follow-up changed `system_ext_a` and its hashtree descriptor in `vbmeta_a`. The signed pair passed AVB and VINTF checks, and the phone booted with SELinux enforcing. Both the legacy `media.VTS` service and the existing video-telephony AIDL service registered. The `vtservice` process stayed up and the IMS client logged no `media.VTS` retries during a 70-second observation. VoLTE, VoWiFi and video call tests remain pending.

The hardware evidence covers the locally assembled image updates and the fingerprint enrollment layout overlay. A full clean rebuild and installation from this branch remain unverified. Bluetooth accessories, NFC tags, a GNSS satellite fix, and charging rates were outside this acceptance run.
