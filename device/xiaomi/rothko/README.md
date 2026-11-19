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
prebuilt vendor image. The formal target was deployed on 2026-11-16. The first
operation-gated trial regressed unlocking; a protocol-timing correction was
flashed and read back but failed physical acceptance. On 2026-11-17 compiler
probes proved that the static handler used V1 while the service used V2:
the handler's extCmd offset selected V2's authenticate entry. Both now inherit
one V2 build default, and the handler rejects V1 compilation. The corrected
executable was flashed, read back and independently accepted by the user for
both screen-on and screen-off unlocking on 2026-11-17.

The handler now enables touch FOD only during authentication or enrollment.
Idle touches and late display events cannot enable local HBM. Cancellation,
success, errors, session close, lockout and completed enrollment stop the
operation; failed authentication can retry within its existing request. A real
touch held while Keyguard starts authentication can begin contact once the
operation is active. Display events control NIT capture independently of
pointer/acquired ordering; acquired callbacks do not force NIT off early. Apply
all three `hardware/xiaomi` patches and rebuild the service and handler
together because their internal interface gains the operation-start hook.
Host state tests use `python3 tools/check-udfps-state.py` from the port root.
The V2-corrected build passed the user's unlocking trial. Idle-touch illumination
and a user-initiated call still require separate acceptance for this build.

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
