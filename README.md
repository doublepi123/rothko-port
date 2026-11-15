# Redmi K70 Ultra (rothko) device configuration — phase 1

Target: Chinese Redmi K70 Ultra, model `2407FRK8EC`, codename `rothko`,
MediaTek MT6989, stock `OS3.0.308.0.WNNCNXM`.

This tree is installed by copying it to `source/device/xiaomi/rothko`. It is
**not** a finished or flashable ROM. Phase 1 parameterizes the real stock
inputs, builds only the Lineage-owned partitions, and refuses to configure a
build while mandatory vendor integration evidence is missing.

## Split between stock and Lineage

| Source | Partitions |
| --- | --- |
| Stock prebuilt | `boot` (kernel), `init_boot` (stock generic ramdisk), `vendor_boot` (platform + recovery fragments, DTBO container), `dtbo`, `vendor`, `odm`, `system_dlkm`, `vendor_dlkm`, `odm_dlkm`; `mi_ext` is not staged, target not mounted, phone partition preserved |
| Built by Lineage | `system`, `system_ext`, `product` |

The stock boot header is v4 with no ramdisk; the stock generic ramdisk lives in
`init_boot`. Phase 1 keeps that image byte-for-byte through the exact
`BOARD_PREBUILT_INIT_BOOT_IMAGE` flag (verified in
`build/make/core/board_config.mk` and `Makefile`). Lineage no longer builds a
generic ramdisk here. The stock init/overlay behavior is a known compatibility
risk and must be checked on a real build/boot baseline; this tree does not
replace it to hide the risk.

The stock `vendor_boot` is also prebuilt, so `BOARD_BOOT_HEADER_VERSION` is
**not** set: setting it would make `BUILDING_VENDOR_BOOT_IMAGE` default to true
and ignore `BOARD_PREBUILT_VENDOR_BOOTIMAGE`. The generated product fragment
also sets `PRODUCT_BUILD_VENDOR_BOOT_IMAGE := false` as an explicit guard.

## Application ABI versus native libraries

The product advertises **64-bit applications only** and selects `zygote64`,
matching the device-specific vendor/ODM property overrides rather than the
generic mgvi/ramdisk template. It inherits `core_64_bit_only.mk`; app support
flags and product-side zygote/dex2oat properties are generated from the JSON.
Product-side properties are necessary because generated vendor properties
cannot alter the retained prebuilt vendor image.

`TARGET_2ND_ARCH=arm` remains a separate native-dependency choice. No ELF32 HAL,
native library or VNDK variant was deleted. One ELF32 Codec2 file exists, but
the observed init rc selects its distinct `-64b` executable; neither file
presence nor kernel `CONFIG_COMPAT` proves 32-bit app/runtime support.
Actual dumpvars and final-image properties/zygote checks are still required;
see `docs/EVIDENCE.md` and `config/app-abi-evidence.json`.

## Identity evidence

`fastboot getvar product` reports `rothko`; `odm_dlkm/etc/build.prop` reports
`ro.product.odm_dlkm.device=rothko`, `model=2407FRK8EC`,
`marketname=Redmi K70 Ultra`, `brand=Redmi`, `manufacturer=Xiaomi`. The stock
`init_boot` build.prop uses the vendor build label `missi`; that is not the
device codename and is not used by this product. Do not substitute Xiaomi 14T
Pro, `duchamp`, `vermeer`, `manet` or MT6897 values.

## Real parameter sources

All values are recorded with evidence in
`config/device-parameters.json`. The generated make fragments
`config/device-parameters.mk` and `config/product-parameters.mk` must be
regenerated, not hand-edited:

```bash
python3 config/generate_device_config.py
```

Key values:

| Parameter | Value | Source |
| --- | --- | --- |
| platform | `mt6989` | stock fstab name, module names, kernel evidence |
| architecture | `arm64`, `armv8-2a` userspace baseline | vendor userspace product `mgvi_64_armv82` |
| boot / init_boot / vendor_boot / dtbo size | `67108864` / `8388608` / `67108864` / `8388608` | payload manifest + live partition sizes |
| super live size | `9663676416` (`0x240000000`) | live fastboot read-only query |
| OTA group `main` | `9653190656` | OTA payload metadata |
| OTA partition sum | `8963211264` | payload partition sizes |
| VAB | snapshots + VABC + `gz` + COW v2, factor `4096` | OTA payload metadata |
| shipping API / vendor API | `34` / `34` | `ro.product.first_api_level=34`, SDK 34 vendor base |
| framework target-level | `8` | extracted VINTF target-levels |
| SELinux policy | `34.0` | `plat_sepolicy_vers.txt` |
| VNDK | `34` | `ro.product.vndk.version` |
| vendor security patch | `2026-02-01` | stock vendor prop |
| OTA metadata security patch | `2026-08-01` | OTA metadata/kernel evidence |

The OTA group layout is a **target layout**, not a readback of current live
super metadata or snapshot state. The 10 MiB difference between the live super
size and the OTA group is recorded, not interpreted.

## Mixed baseline: Android 16 boot + Android 14 vendor

The boot image reports Android 16/SDK 36, but `vendor`, `odm`, `system_dlkm`,
`vendor_dlkm`, `odm_dlkm`, the vendor ramdisk and SELinux report Android 14 /
SDK 34, VINTF target-level 8, policy 34.0 and VNDK 34. The build therefore keeps
`PRODUCT_SHIPPING_API_LEVEL := 34` and vendor API 34. Setting vendor API 36
would flatten two real baselines into a guess; `preflight.py` rejects it.

Module compatibility is recorded separately:

- `system_dlkm`: 60 modules, vermagic matches the boot kernel release
  `g6ab8c9a86a33...`, signed.
- `vendor_dlkm`: 268 modules and vendor_boot ramdisk: 236 modules, vermagic
  `ga418eeb69cb6...`, unsigned.
- All 564 stock modules have `__versions` and the same vermagic suffix
  `SMP preempt mod_unload modversions aarch64`; all have `module_layout` CRC
  `0xea759d7f`.
- `kernel/module/version.c` `same_magic(has_crcs=true)` skips the release
  prefix and compares only that suffix, so the git-hash difference alone is
  **not** a rejection reason. It is not a build gate.
- The `__versions` CRC cross-check shows 522 vendor_dlkm symbols (8,797
  occurrences) and 424 vendor_boot symbols (5,729 occurrences) matching the
  system_dlkm GKI module CRCs, with 0 mismatches.
- Status: same_magic suffix and CRC overlap consistent, `module_layout`
  matching, **kernel symbol CRC table not located (may be present) and runtime
  load unproven**. Do not claim full compatibility or incompatibility from the
  string alone.
- Final VNDK 34 compatibility is **pending build-baseline products**: after
  Lineage `system`/`system_ext`/`product` artifacts exist, check vendor HAL
  DT_NEEDED/linker namespaces, `checkvintf` and SELinux `neverallow` against
  that baseline.

`config/module-compatibility.json` is reproducible with
`scripts/check_module_abi.py --check`.

## Build gates

`BoardConfig.mk` runs `scripts/preflight.py --make` at configuration time.
There are three layers:

1. **Configuration / dumpvars**: product identity, generated fragments,
   super/group budget, vendor contract and the staged image manifest only.
   It does not require framework compatibility results that cannot exist yet.
2. **Framework build** (`systemimage`, `systemextimage`, `productimage`): the
   same buildable-input layer, so the Lineage baseline can compile. This is not
   release-ready.
3. **Full / OTA / release**: the complete list below. It remains closed.

Soong `dumpvars` is the actual configuration path used by `lunch` and
`get_build_var`: it invokes Kati with the `dump-many-vars` target,
`MAKECMDGOALS=<goals>`, and sets `DUMP_MANY_VARS` and
`CALLED_FROM_SETUP=true`. `BoardConfig.mk` recognizes that specific
configuration context; a normal no-goal `make` stays on the full/release path.
There is no custom skip/release environment variable.

The release build stops with a named list when any of these is missing or
inconsistent:

- generated fragments are stale;
- identity or architecture does not match `rothko`/`mt6989`;
- super/group budget is invalid;
- a required prebuilt image is missing, has the wrong size, or has the wrong
  SHA-256; the required stock set is the 9 staged images:
  boot/init_boot/vendor_boot/dtbo/vendor/odm/system_dlkm/vendor_dlkm/odm_dlkm;
- the required `vendor/xiaomi/rothko/BoardConfigVendor.mk` or
  `rothko-vendor.mk` is absent (the makefile errors instead of silently
  dropping vendor configuration);
- `config/vendor-integration-evidence.json` still reports no `checkvintf`
  result, no `neverallow` result, 38 pending framework-provided candidates, 8
  unresolved graphics/common/memtrack-tagged dependencies, or unknown linker
  namespace;
- `config/vendor-inventory.json` is absent or does not prove the vendor
  integration (required shape:
  `config/vendor-inventory.requirements.json`);
- `config/module-compatibility.json` is missing, stale, or has nonzero CRC
  mismatches;
- release readiness is still `false` (snapshot/overlay/ABI/VINTF/neverallow/
  VNDK34; mi_ext checked with no native driver evidence but target not mounted).

`mi_ext` content has been checked (`firmware/extra/mi_ext/reports/
mi_ext-content.md`, SHA-256 `3b39ace8...`): 5 APK, 1 JAR, 0 native `.so`/ELF,
0 VINTF, 10 Taiyi assets (124,464,825 bytes). The existing references are
HyperOS framework/overlay content, not identified hardware drivers. It remains
not staged and not mounted in the phase-1 target; the phone partition is
preserved and no build/prebuilt hook is assumed. This does **not** prove all
Android functionality is independent of mi_ext. A userdebug build with
prebuilt boot/init_boot/vendor_boot does not automatically adapt the overlay;
`ROTHKO_HARDWARE_RELEASE_READY` stays false. Do not delete or repurpose the
phone partition.

A framework-only `make systemimage` (also `systemextimage`/`productimage`) is
allowed so the Lineage baseline can be built before vendor integration is
complete. This is not a release pass: the full/release goals still stop on the
vendor evidence gaps, VNDK 34 baseline checks, mi_ext/runtime unknowns, and
`ROTHKO_HARDWARE_RELEASE_READY=false`. VINTF/SELinux are not bypassed.

VINTF and SELinux are intentionally not synthesized. The stock vendor stack is
Android 14/SDK 34 while this framework is Android 16. No empty device manifest,
no disabled VINTF check, no global permissive policy and no test-key AVB signing
is added. The gate requires a verified vendor inventory with:

- vendor manifest, vendor matrix and framework matrix with SHA-256;
- a `checkvintf`-style result of `compatible`;
- an enforcing SELinux policy hash and a passing `neverallow` result;
- verified HAL inventory and kernel-module match;
- shipping API 34.

The raw firmware inventory at `firmware/reports/inventory.json` contains useful
extracted VINTF/SELinux artifacts, but it does not contain a compatibility or
neverallow check result. It therefore does not satisfy
`config/vendor-inventory.json` by itself.

`config/vendor-integration-evidence.json` records the remaining gaps honestly:
96 VINTF manifest/matrix files, 139 HAL names, target-level 8, policy 34.0,
VNDK 34, 77 HAL ELFs, 23 cross-partition dependencies, 783 pending framework
candidate rows covering 38 unique framework-provided candidate libraries, and 8
non-base-tagged dependencies (mostly Android graphics/common/memtrack standard
interface libraries). 76 HALs have file candidates, but that is not proof of
successful namespace linking. Linker namespace reachability remains unknown
pending the build baseline/linker configuration. None of these is assumed to be
provided by `system_ext`, and the dependency check is not claimed as passed.

## Not authorized

This phase does not flash, erase, reboot, switch slots, disable AVB or touch
modem/TEE/preloader/calibration partitions. Slot `a` is the successful slot;
slot `b` is marked unbootable. The stock kernel is Android 14-based and its
known CVEs remain; this device tree does not rebuild or patch it. Generated
images are unsigned and are not flashable.

## How to use

```bash
# 1. The vendor lane owns vendor/xiaomi/rothko and stages its prebuilt images
#    there. This device tree only includes its BoardConfigVendor.mk and
#    inherits rothko-vendor.mk; it does not stage or write vendor files.
#    Vendor staging keeps ROTHKO_HARDWARE_RELEASE_READY := false.
#    mi_ext is not staged, target not mounted, phone partition preserved;
#    content check found no native driver evidence.

# 2. Provide config/vendor-inventory.json with the evidence described above.
#    Do not fabricate it. The device preflight also checks the vendor contract
#    and the staged image hashes under vendor/xiaomi/rothko/prebuilt.

# 3. Check the inputs without building.
scripts/check_module_abi.py --check
scripts/preflight.py --mode build
scripts/preflight.py --mode evidence

# 4. Real stock-framework checks after the framework artifacts exist.
#    Derived vendor is required for the real check; stock vendor is diagnostic.
scripts/check_stock_framework.py vintf --out "$OUT" --derived-vendor <derived-vendor>
scripts/check_stock_framework.py selinux --out "$OUT"
scripts/check_stock_framework.py init --out "$OUT" --derived-vendor <derived-vendor>

# 5. In a synced LineageOS 23.2 tree:
source build/envsetup.sh
lunch lineage_rothko-userdebug
m
```

`vendor/lineage/config/common_full_phone.mk` is a hard inheritance. If the
Lineage vendor tree is not synced, the build fails with a missing-file error
rather than silently producing a non-Lineage product.

## Stock framework checks

`scripts/check_stock_framework.py` consumes real artifacts; it never writes a
`DEVICE_MANIFEST_FILE` and never treats empty `out/vendor` as a vendor source.

- `vintf`: `checkvintf --check-compat` with dirmaps for built
  `/system`, `/system_ext`, `/product`, the **derived vendor re-extract**
  (`/vendor`), and stock `/odm`. It passes first API 34, the exact kernel
  release plus `IKCONFIG` via `--kernel=<release>:<config>`. It runs both
  the `--vendor-sku`/`--hardware-sku` rothko candidate and an empty-SKU
  control, even if the candidate fails, and saves each scenario's command,
  log and rc. The fastboot empty SKU is not a real Android SKU and neither
  scenario is treated as device confirmation. A missing derived vendor is
  "not run"; `--diagnostic-stock-vendor` explicitly runs the stock vendor
  dump as a diagnostic only. The 96 XML files are not concatenated or merged.
- `selinux`: follows the runtime `CompileSplitPolicy` input selection:
  plat CIL, plat mapping, plat compat (optional), system_ext
  policy/mapping/compat (optional), product policy/mapping (optional),
  **stock vendor `plat_pub_versioned.cil` (required)**, stock vendor
  `vendor_sepolicy.cil` (required), stock odm CIL (optional), and an optional
  genfs CIL. Required inputs missing fail; optional absent inputs are recorded
  as absent, not claimed. It uses Android secilc flags
  (`-v -m -M true -G -c 30`) and leaves neverallow enabled (no `-N`).
  After a successful compile it runs `sepolicy-analyze permissive` and
  requires no permissive domain, then `checkfc` and `sefcontext_compile` on
  the emitted `file_contexts`. A missing context tool is explicitly "not run",
  not a pass. Reports, actualpolicy.bin, logs and rc are retained under
  `--report-dir` (unique `/tmp/opencode/rothko-integration-*` by default).
- `init`: `host_init_verifier` with `-p` passwd files, per-partition
  `--property-contexts`, and `--out_system/--out_system_ext/--out_vendor/
  --out_odm/--out_product`. The vendor argument must be the derived vendor
  re-extract. Missing passwd/property-context inputs or the host tool are
  explicit failures.

Host tools default to `$ANDROID_HOST_OUT/bin` (or
`out/host/linux-x86/bin`); missing tools or artifacts produce a nonzero
"NOT RUN" result. These checks are buildable targets, not prerequisites for
compiling the host tools, so there is no circular "check result before tool
build" requirement. `secilc` success alone is not a claim that all
neverallow/context checks passed; those checks have their own logs and rc.

## Tests

```bash
tests/run-tests.sh
```

The tests are static: image hashes/headers, manifest agreement, super/group
budget, model isolation, vendor-inventory failure and absence of device
operations. They do not build the tree and do not touch the phone.

See `docs/EVIDENCE.md` for the detailed evidence map and design notes.
