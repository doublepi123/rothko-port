# Evidence map and design notes

This file explains where every build parameter came from and which choices are
deliberate. The machine-readable source of truth is
`config/device-parameters.json`; generated make fragments are derived from it.

## Inputs read for this phase

| Input | What it establishes |
| --- | --- |
| `logs/parent-manifest-expectations.json` | payload sizes and SHA-256 for all 13 target partitions |
| `logs/parent-dynamic-partition-metadata.json` | OTA group `main`, group size, VABC/snapshot/COW values |
| `logs/live-fastboot-readonly-20261031.json` | live product, slots, super and boot-family partition sizes |
| `firmware/reports/ramdisk_inventory.json` | init_boot/vendor_boot ramdisk hashes, entries, module list, fstab |
| `firmware/reports/inventory.json` | extracted vendor/odm/system_dlkm/vendor_dlkm/odm_dlkm inventory, VINTF/SELinux artifacts |
| `firmware/dump/ramdisks/vendor_boot/vendor_ramdisk00/first_stage_ramdisk/fstab.mt6989` | mount points and fstab filename (mt6989) |
| `firmware/dump/odm_dlkm/etc/build.prop` | rothko / 2407FRK8EC / Redmi K70 Ultra identity |
| `firmware/dump/ramdisks/vendor_boot/vendor_ramdisk00/prop.default` | vendor userspace Android 14 / SDK 34, `mgvi_64_armv82`, security patch |
| `offline-k70u/unpacked/{boot,init_boot,vendor_boot}.json` | boot header versions, kernel/ramdisk sizes, vendor_boot fragment table |
| `offline-k70u/analysis/kernel/ikconfig` | 4 KiB pages, binder/binderfs, module signing |
| `offline-k70u/analysis/kernel/evidence.json` | kernel release and OTA post-build/security-patch metadata |
| `firmware/reports/input-report.md` | mixed Android 16 boot / Android 14 vendor baseline, FCM/VNDK/SELinux summary |
| `firmware/reports/boot-parameters.md` | boot header/module vermagic mismatch evidence |
| `firmware/reports/module-vermagic.tsv` | per-module vermagic/name/hash evidence |
| `firmware/reports/nonbase-gaps.tsv` | 38 framework-provided candidates and 8 graphics/common/memtrack-tagged dependencies, with statuses |
| `firmware/reports/library-index.tsv` | recursive ELF32/ELF64 library index |
| `firmware/reports/inventory.json` | full build props, VINTF, SELinux, linker, HAL and module inventory |

`firmware/receipts/extraction.json` reports `all_verified: true` for the
extracted vendor/odm/system_dlkm/vendor_dlkm/odm_dlkm images. That is integrity
against the payload manifest, not OEM signature authentication.

## Partition evidence

| Partition | Size (bytes) | SHA-256 (first 16 hex) | Use |
| --- | --- | --- | --- |
| boot | 67108864 | `462fbecbc89db679` | stock prebuilt; header v4, ramdisk 0, kernel 16547799 |
| init_boot | 8388608 | `b7acb150c417af59` | stock prebuilt generic ramdisk; header v4, kernel 0, ramdisk 3132722; init/overlay compatibility risk |
| vendor_boot | 67108864 | `b0028698bbe0eb56` | stock prebuilt; header v4, page 4096, ramdisk 54949411, dtb 444690 |
| dtbo | 8388608 | `70221d0d6d28bb0f` | stock prebuilt; DTBO container, 1 entry, total 113247 |
| vendor | 1644716032 | `e417733a560a5a60` | stock prebuilt |
| odm | 881057792 | `7e9ae9013b9c449e` | stock prebuilt |
| system_dlkm | 7471104 | `df485f93fb3b5a30` | stock prebuilt; must match the stock kernel |
| vendor_dlkm | 21970944 | `c050e3f48404c463` | stock prebuilt |
| odm_dlkm | 348160 | `fc59d5085c32bbfa` | stock prebuilt |
| system_ext | 936304640 | `743f8a9ac9e932c1` | Lineage-built; stock size is a reference only |
| system | 880361472 | `aba303d44e6acbee` | Lineage-built; stock size is a reference only |
| product | 4464340992 | `6f1d3f42592b14d3` | Lineage-built; stock size is a reference only |
| mi_ext | 126640128 | `d601de14ce56da97` | checked, no native driver/VINTF evidence; not staged, target not mounted, phone partition preserved |

The stock `vendor_boot` contains two fragments:

- type `1` (`platform`), unnamed, size 41030553, offset 0;
- type `2` (`recovery`), name `recovery`, size 13918858, offset 41030553.

Its `dtb` payload is itself a DTBO container (`0xd7b7ab1e`) with one entry and a
base FDT of 444626 bytes. The `dtbo` partition is a separate DTBO container with
one 113183-byte overlay. Both are preserved as prebuilts; no standalone FDT is
substituted for the container.

The stock first-stage fstab (`fstab.mt6989`) mounts `system_ext`, `product`,
`mi_ext`, `vendor`, `odm`, `vendor_dlkm`, `odm_dlkm` and `system_dlkm`, and
mounts `userdata`/`metadata` as f2fs. Lineage builds `system`, `system_ext` and
`product` as ext4. The stock fstab accepts both erofs and ext4 for those
partitions.

## Super budget

- OTA group `main`: `9653190656` bytes.
- Sum of the nine stock OTA group partition sizes: `8963211264` bytes.
- Phase-1 build target omits `mi_ext`: eight logical partitions sum to
  `8836571136` bytes, with `816619520` bytes slack in the same group.
- Stock group slack: `689979392` bytes.
- Live super size from fastboot: `9663676416` bytes (`0x240000000`).
- Live-super minus OTA-group: `10485760` bytes.

The OTA layout describes the update target, not the current super metadata or
snapshot state. The build uses it as the dynamic-partition budget; it does not
claim that the live device currently has that group layout.

## Virtual A/B

The OTA metadata records `snapshot_enabled=1`, `vabc_enabled=1`,
`vabc_compression_param=gz`, `cow_version=2`, `compression_factor=4096`.
`device.mk` inherits `vabc_features.mk` and the generated product fragment sets
the COW version, gzip compression and factor explicitly. No OTA package is
generated in this phase.

## Mixed vendor baseline

The boot image reports Android 16 / SDK 36. The vendor/ODM/DLKM stack and vendor
ramdisks report Android 14 / SDK 34. Extracted evidence also records:

- VINTF target-level `8`;
- SELinux policy `34.0` (`vendor/etc/selinux/plat_sepolicy_vers.txt`);
- VNDK `34` (`ro.product.vndk.version`);
- `ro.product.first_api_level=34` and `ro.board.first_api_level=34`.

The build keeps `PRODUCT_SHIPPING_API_LEVEL := 34` and vendor API 34. Setting
vendor API 36 would treat the Android 16 boot image as proof that the vendor
stack is API 36, which it is not. `preflight.py` rejects 36.

## Kati entry-point correction after the first isolated build

The isolated run completed the Soong generation step, then exited 1 in Kati
cleanspec parsing, with max/oom/oom_kill events all zero. The old custom gate
mistook its empty MAKECMDGOALS for a full/OTA request and required post-image
VINTF/SELinux evidence before those images could exist. The failed log and
systemd receipt remain preserved; no readiness flag was changed to pass it.

The configuration context now additionally recognizes only
`firstword(MAKEFILE_LIST)==build/make/core/cleanbuild.mk`. Empty `main.mk`,
package/main or a main stack merely containing cleanbuild later are not
implicitly allowed. Identity, actual prebuilt and budget checks still run.

This branch filters normal Ninja goals through `PARSE_TIME_MAKE_GOALS`
(`build/make/core/ninja_config.mk:12-56`). No vendor ninja_config extension was
present. An initial retry registered only the three framework goals, but that
loses `otapackage` from Kati visibility for a mixed `systemimage otapackage`
request even though Ninja retains it. That visibility defect is now corrected
in the external tree: append the complete sorted
`ORIGINAL_MAKECMDGOALS` + `MAKECMDGOALS` request to the existing forwarding
extension. **Forwarding a target does not allow it.** The unchanged Python
framework-only set still rejects a mixed full/OTA request; empty main remains
the full/release path. No VINTF, policy or dependency checks are disabled.

Regression tests include the actual upstream ninja_config.mk, consume its
actual KATI_GOALS output with the real preflight, and cover normal framework,
framework+OTA, framework+droid, framework+all and empty requests. The `all`
modifier is correctly retained by Kati while upstream excludes it from Ninja.
The first test run incorrectly expected `all` in Ninja too; its failure log
is preserved before correcting that assertion. These probes are not a ROM
build result. Do not modify an already-running installed tree: stage the
external correction, then archive its prior input/configure record and apply
it at the next verified terminal boundary with a fresh configure/new unit.

## App ABI correction: 64-bit apps, separately retained native ARM32

The initial `supports_32_bit_apps=true` used generic ramdisk/mgvi properties.
That inference is superseded, not runtime evidence. Original firmware inputs and
earlier reports remain unchanged. See `config/app-abi-evidence.json` for hashes.

`vendor/build.prop` first contains a generic dual-ABI block, then its rothko
block overrides ABI at lines 203-205 to `arm64-v8a`, empty ABI32, `arm64-v8a`.
`odm/etc/build.prop` repeats that device-specific 64-only ABI at 56-58 and
311-313, and sets `ro.zygote=zygote64` at 146. Vendor's `zygote64_32` at 65/256
does not win over the later ODM map load.

The checked source `system/core/init/property_service.cpp:1117-1216` accumulates
properties in a map, permitting later values to replace earlier `ro.*` values
before publication. Vendor loads before ODM, then product. ABI derivation at
1012-1065 prefers product, ODM, vendor, system. This tree configures no custom
vendor init library; the source default `vendor_load_properties()` is weak and
empty. Actual built init/overrides and normal Android runtime remain unverified.

The product now inherits `core_64_bit_only.mk`, with generated
`TARGET_SUPPORTS_32_BIT_APPS=false`, `TARGET_SUPPORTS_64_BIT_APPS=true`.
Because `PRODUCT_VENDOR_PROPERTIES` cannot rewrite the retained vendor image,
the generated product properties explicitly select `ro.zygote=zygote64` and
`dalvik.vm.dex2oat64.enabled=true` in the later-loaded product partition.
`board_config.mk:370-401` omits advertised ABI32 when 32-bit app support is false,
independently of the native secondary build architecture.

Native ARM32 is a separate, unresolved dependency question. The vendor image
contains ELF32 `android.hardware.media.c2@1.2-mediatek` (EM_ARM), while the found
Codec2 service rc selects the separate ELF64 `...-64b` executable (EM_AARCH64).
File presence does not prove the ELF32 service runs or that 32-bit apps work.
Keep `TARGET_2ND_ARCH=arm`, native libraries and VNDK 34 variants for now; delete
none on the basis of the app-mode correction. Their actual APEX providers,
symbols and namespaces still require the normal dependency checks.

### Mandatory real-build verification (not yet run)

After actual lunch, capture actual `get_build_var`/dumpvars values for
`TARGET_SUPPORTS_32_BIT_APPS`, `TARGET_SUPPORTS_64_BIT_APPS`,
`TARGET_CPU_ABI_LIST`, `TARGET_CPU_ABI_LIST_32_BIT`,
`TARGET_CPU_ABI_LIST_64_BIT`, `TARGET_2ND_ARCH` and `TARGET_2ND_CPU_ABI`.
Expected app values: false, true, `arm64-v8a`, empty, `arm64-v8a`;
native secondary remains `arm` / `armeabi-v7a` pending dependency verification.
Do not infer these effective values only from generated make text.

Re-extract final system/system_ext/product images and combine their actual
properties with the verified derived vendor and stock ODM in the init load
order, including imports and any built vendor-init override. Require effective
`ro.product.cpu.abilist=arm64-v8a`, empty ABI32, ABI64 `arm64-v8a`,
`ro.zygote=zygote64` and the 64-bit dex2oat selection. Inspect the selected
`/system/etc/init/hw/init.zygote64.rc`: primary zygote uses `app_process64`,
without selecting an `app_process32` secondary zygote. A generic init.rc
reference to the optional secondary service is not proof it is selected.
Record image hashes, selected property sources/overrides and script content.
These are pending artifact checks, not results of the static tests below.

## Module compatibility evidence

Stock module sets:

| Set | Count | Vermagic | Signed |
| --- | ---: | --- | ---: |
| `system_dlkm` | 60 | `6.1.138-android14-11-g6ab8c9a86a33-ab14396278 ... modversions aarch64` | 60 |
| `vendor_dlkm` | 268 | `6.1.138-android14-11-ga418eeb69cb6 ... modversions aarch64` | 0 |
| `vendor_boot` ramdisk | 236 | `6.1.138-android14-11-ga418eeb69cb6 ... modversions aarch64` | 0 |

The boot kernel release is `g6ab8c9a86a33...`; system_dlkm matches it, while the
vendor sets use `ga418eeb69cb6...`. The kernel config has `CONFIG_MODVERSIONS=y`,
`CONFIG_MODULE_SIG=y`, `CONFIG_MODULE_SIG_FORCE` not set,
`CONFIG_MODULE_SIG_PROTECT=y`, `CONFIG_MODULE_SIG_SHA1=y`, GKI hidden configs,
CFI and 4 KiB pages.

The release-string difference is **not** treated as proof of binary
incompatibility. The independently fetched kernel reference
`logs/kernel-module-version-reference.c` shows `same_magic()` skipping the
kernel-version prefix when `has_crcs` is true and comparing the remainder.
All 564 stock modules contain `__versions`, share the same suffix
`SMP preempt mod_unload modversions aarch64`, and have `module_layout` CRC
`0xea759d7f`. The release-prefix difference is therefore not a rejection
reason, and vermagic string equality is deliberately **not** a build gate.

`scripts/check_module_abi.py` also parses every module's `__versions` CRC table
and compares vendor symbols with the system_dlkm GKI module map:

- 522 unique vendor_dlkm symbols (8,797 occurrences) overlap; 0 CRC mismatches.
- 424 unique vendor_boot symbols (5,729 occurrences) overlap; 0 CRC mismatches.
- system_dlkm has 1,187 symbols and 0 conflicting CRCs.

Status: `same_magic_suffix_match_crc_overlap_consistent_module_layout_match_kernel_crcs_unverified_runtime_unproven`.
The kernel symbol CRC table (`__kcrctab`) was not located in the stripped
`Image.elf`; this is not a claim that the image has no CRC data. No module load
or boot test was performed. Do not claim full compatibility or incompatibility
without runtime or located kernel CRC evidence.

## HAL ELF, VINTF and SELinux evidence

`firmware/reports/inventory.json` records 96 VINTF manifest/matrix files, 139
HAL names, target-level 8, no kernel versions in the matrices, 51 SELinux policy
files and a precompiled policy (version 34.0). There is **no** `checkvintf`
compatibility result and **no** `neverallow` result.

The HAL ELF analysis covers 77 executables, 2,555 library-index entries and 23
cross-partition dependencies. The previous lib64/hw false gaps were corrected;
nested lib64/hw candidates are now indexed. 783 rows remain
`unresolved_framework_candidate_pending_baseline`, representing **38 unique
framework-provided candidate libraries**. Eight non-base-tagged dependencies
have no file in the acquired images; they are mostly Android
graphics/common/memtrack standard interface libraries, so their absence is not
evidence that they are non-base libraries supplied by `system_ext`. 76 HALs have
file candidates, but that is not proof of successful namespace linking. Linker
namespace reachability is `unknown` pending a build baseline/linker
configuration. These libraries are listed, not guessed. `system_ext` is not
assumed to provide them, and the dependency check is not claimed as passed.
Final VNDK 34 compatibility requires building Lineage `system`, `system_ext` and
`product` baseline artifacts, then checking vendor HAL DT_NEEDED/linker
namespaces, `checkvintf` and SELinux `neverallow` against that baseline.

## Live read-only device evidence

These are read-only observations, not a boot or hardware certification.

- `logs/live-recovery-readonly-20261031.json`: environment is OrangeFox
  recovery, not Android userspace. `ro.boot.product.hardware.sku=rothko`,
  `ro.boot.product.vendor.sku=` empty, `ro.boot.slot_suffix=_a`.
  `boot_a`/`init_boot_a`/`dtbo_a` SHA-256 equal the stock .308 inputs
  (`462fbecb...`, `b7acb150...`, `70221d0d...`). `vendor_boot_a` is
  `a0bd6597...`, not the stock `b0028698...`; the difference is the external
  OrangeFox installation, which this task did not perform.
- `logs/parent-recovery-module-comparison.json`: recovery required 230 unique
  modules and observed all 230 loaded; two sampled module files matched local
  SHA-256. Normal mode required 214 unique, observed 209; adsp,
  mtk_swpm_perf_arm_pmu, slbc_ipi, slbc_mt6989 and slbc_trace were not
  observed. This is not proof that all module CRCs or Android HALs pass.
- `logs/parent-live-super-layout.json`: geometry is metadata max 65536, three
  metadata slots, logical block 4096; six header/table checksums valid. COW
  allocations exist while queried `system_a`/`vendor_a` dm tables are linear;
  `/metadata/ota/state` is empty, so merge state remains unknown. Do not flash
  or switch slots.
- `logs/parent-live-partition-size-comparison.json`: all nine active A logical
  sizes equal the exact .308 payload image sizes. Equal size is not content
  hash equality.

No generation/geometry fields are added to the build JSON unless a real
compilation flag needs them.

## Identity discrepancy: `missi`

The stock `init_boot` build.prop contains
`ro.product.bootimage.device=missi` and
`ro.bootimage.build.fingerprint=Xiaomi/missi/missi:16/...`. This is a vendor
bootimage build label. The device identity is established by:

- `fastboot getvar product` -> `rothko`;
- `odm_dlkm/etc/build.prop` -> rothko / 2407FRK8EC / Redmi K70 Ultra;
- `vendor/etc/build.prop` -> `ro.product.vendor.device=rothko`;
- OTA post-build fingerprint -> `Redmi/rothko/rothko:16/...`.

The product uses `rothko`, never `missi`.

## Design choices

### init_boot is stock prebuilt (phase 1)

`BOARD_PREBUILT_INIT_BOOT_IMAGE` is the exact, verified flag in
`build/make/core/board_config.mk` and `Makefile`; phase 1 uses it. The stock
generic ramdisk in `init_boot` is kept byte-for-byte. This deliberately avoids
building a Lineage generic ramdisk while the vendor stack is still stock, but it
carries a real init/overlay compatibility risk with the Lineage framework. That
risk must be checked on a real build/boot baseline, not hidden by replacing the
ramdisk. No invented init_boot flag and no `BOARD_INIT_BOOT_HEADER_VERSION`
build path are used.

### boot/vendor_boot/dtbo are prebuilt

`BOARD_PREBUILT_BOOTIMAGE`, `BOARD_PREBUILT_VENDOR_BOOTIMAGE` and
`BOARD_PREBUILT_DTBOIMAGE` are verified in `build/make/core/Makefile`. Since
`BOARD_BOOT_HEADER_VERSION` is not set, the vendor_boot build branch is not
selected; the prebuilt branch copies the stock image unchanged. This preserves
the stock kernel, the platform/recovery fragment table and the DTBO container.

### Vendor/ODM/DLKM are prebuilt

`BOARD_PREBUILT_VENDORIMAGE`, `BOARD_PREBUILT_ODMIMAGE`,
`BOARD_PREBUILT_SYSTEM_DLKMIMAGE`, `BOARD_PREBUILT_VENDOR_DLKMIMAGE` and
`BOARD_PREBUILT_ODM_DLKMIMAGE` are verified in the source. The stock kernel and
its signed modules must stay a matched set; rebuilding them from the Lineage
tree would break module vermagic/signing.

### mi_ext content checked; no native driver evidence

`firmware/extra/mi_ext/reports/mi_ext-content.md` (SHA-256
`3b39ace8a75411cd3ad7927ed1b574fbc0ea64e786c5fe1aa3771af0263db1cc`) and
`mi_ext-content.json` (SHA-256
`2c6985b474dd6eb7fc005c3b621389faecbe11a2c06327c941c1c13ea91b5bf8`) record
the actual `mi_ext` image: 126,640,128 bytes, SHA-256
`d601de14ce56da97f71766246699f32ec80d43c9c078b3d073bd95c6770182a7`.

Content: 5 APK, 1 JAR, 0 native `.so`/ELF32/ELF64, 0 VINTF XML, 10 Taiyi assets
(124,464,825 bytes); 5 of 21 fstab-referenced directories contain files, 16 are
empty. The existing references are HyperOS framework/overlay content, not
identified hardware drivers; one `/system_ext/framework/hyperos.rustruntime.jar`
reference remains unresolved because system_ext was not acquired. This report
does not prove all Android functionality is independent of `mi_ext`.

Phase 1 does not stage or mount `mi_ext`; the phone partition is preserved and
no `BOARD_PREBUILT_MI_EXTIMAGE` or generic logical-partition hook is assumed. A
userdebug build with prebuilt boot/init_boot/vendor_boot does not automatically
adapt the mi_ext overlay; `ROTHKO_HARDWARE_RELEASE_READY` remains false. Do not
delete or repurpose the phone partition.

### Offline AVB signing is off; device AVB is untouched

`BOARD_AVB_ENABLE := false` and `PRODUCT_BUILD_VBMETA_IMAGE := false` only mean
this offline build does not sign generated images. They do not disable, alter
or claim the phone's AVB state. The OEM private AVB keys are not available.
Stock prebuilts keep their original OEM signatures when copied; images built
here are unsigned. No test key is used, and no output is claimed to be
flashable.

### VINTF and SELinux are gated, not synthesized

No `DEVICE_MANIFEST_FILE`, `DEVICE_MATRIX_FILE`, `BOARD_SEPOLICY_DIRS` or
permissive boot argument is added. The raw extracted vendor inventory contains
VINTF files and SELinux policy artifacts, but not a `checkvintf` compatibility
result or a `neverallow` result. `config/vendor-inventory.json` must add those
results, with hashes, before the build is allowed. The current gaps are recorded
in `config/vendor-integration-evidence.json`: 38 framework-provided candidate
libraries and 8 graphics/common/memtrack-tagged dependencies unresolved, unknown
linker namespace, no checkvintf result and no neverallow result. None of these is treated as passed.

## Known limitations

- The stock kernel is `6.1.138-android14-11-g6ab8c9a86a33-ab14396278`, built
  from an Android 14 base. The vendor security patch is `2026-02-01`; the OTA
  metadata reports `2026-08-01`. A newer framework patch does not update the
  kernel or vendor. Known kernel/vendor CVEs remain and are not patched here.
- The vendor stack is Android 14/SDK 34 while the framework is Android 16.
  VINTF compatibility is not yet proven; no `checkvintf` result was run.
- HAL inventory and SELinux neverallow compatibility are not yet proven.
  `mi_ext` content was checked and shows no native driver/VINTF evidence, but
  its runtime necessity/overlay adaptation is not proven. 38 framework-provided
  candidate libraries plus 8
  non-base-tagged graphics/common/memtrack dependencies are unresolved, the
  linker namespace is unknown, and `system_ext` is not assumed to resolve them.
  Final VNDK 34 compatibility needs build-baseline products.
- Vendor module vermagic has a different release prefix, but `same_magic` with
  `__versions` ignores that prefix; suffix and `module_layout` CRC are
  consistent. Kernel symbol CRCs were not located and no runtime module load or
  boot test was done.
- The stock vendor modules are unsigned; `CONFIG_MODULE_SIG_FORCE` is not set.
  This is stock state, not a pass.
- The stock `vendor_boot` recovery fragment is preserved, but recovery
  compatibility with the stock `init_boot` generic ramdisk is not validated in phase 1.
- No physical-device test, flashing, slot switch or boot test is authorized by
  this phase. Slot `b` is unbootable; slot `a` is the only successful slot.
- The source tree is still being synchronized; `vendor/lineage` is not present
  yet. The product has a hard inheritance on
  `vendor/lineage/config/common_full_phone.mk` so a missing Lineage vendor tree
  fails loudly instead of producing a non-Lineage image.
