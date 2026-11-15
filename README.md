# Redmi K70 Ultra / rothko device tree

Target: Chinese Redmi K70 Ultra, model `2407FRK8EC`, MediaTek MT6989.
Current baseline: LineageOS `lineage-23.2` / Android 16, vendor inputs from
`OS3.0.308.0.WNNCNXM`. This is an experimental source tree, not an official
device release or a complete reproducible ROM.

## Current components

| Path | Purpose |
| --- | --- |
| `BoardConfig.mk`, `config/` | Device identity, partition/ABI parameters and build preflight |
| `ims/` | IMS import and permissions; proprietary APK excluded |
| `carrier-capability/` | Device carrier voice overlay |
| `statusbar/` | Framework/SystemUI display geometry RROs, including `pixel_pitch=57.0` |
| `vibrator_alias/` | Alias for the stock vibratorfeature instance |
| `udfps/` | Lineage Xiaomi HAL handler and prebuilt-vendor compatibility target |
| `fingerprint.mk` | Future source-built vendor integration fragment, currently not included |
| `recovery/` | Existing recovery runtime configuration |
| `scripts/` | Preflight and input validation |

The superseded FOD state-bridge and deferred-frame static overlays have been
removed. Do not re-enable them when using the current Lineage Xiaomi HAL.
The active framework patch retains lockscreen geometry; it does not include
the old FOD implementation.

## Fingerprint build forms

`libudfpshandler` is the shared handler for the ordinary
`hardware/xiaomi` AIDL service. A second target,
`android.hardware.biometrics.fingerprint-service.rothko-prebuilt-vendor`,
links the handler statically for replacing the original daemon inside a
prebuilt vendor image. Both targets have compiled; the latter formal target
has not itself been flashed. The phone ran the earlier spike02 build of the
same migration approach.

`fingerprint.mk` lists packages and properties for a source-built vendor.
Before enabling it, resolve the original service/VINTF declarations,
SELinux, template-group path compatibility and runtime dependencies.
Adding `PRODUCT_PACKAGES` cannot insert files into a prebuilt vendor image.

## Inputs and build limits

See [IMS extraction notes](ims/prebuilt/README.md). Board/vendor inputs remain
prebuilt, with `TARGET_NO_KERNEL` enabled. Full image/OTA targets deliberately
fail preflight while required integration evidence is absent; keep that gate.
Partial module builds do not satisfy it.

`config/device-parameters.json` is the parameter source; generated makefiles
must be regenerated through `config/generate_device_config.py`, not edited.
Some checks still depend on the original firmware/evidence workspace.

Current tests cover only one Chinese device. International 14T Pro support,
all hardware variants, complete recovery/OTA and official acceptance are
unverified. The top-level preparation repository contains the build boundary,
validation summary and official-readiness checklist.
