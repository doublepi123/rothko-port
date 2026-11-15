# Redmi K70 Ultra (rothko) vendor prebuilt phase 1

Scope: `vendor/xiaomi/rothko/` only. This lane does not edit
`device/`, `source/`, `build-baseline/`, firmware inputs, or any phone.

## Architecture

This is **not** a blob-complete reconstruction and **not** a release OTA.

Stock source images are immutable and remain byte-for-byte in `prebuilt/`:

- `boot.img`, `init_boot.img`, `dtbo.img`
- `odm.img`, `system_dlkm.img`, `vendor_dlkm.img`, `odm_dlkm.img`
- plus the original stock `vendor_boot.img` and `vendor.img` as evidence

Two reviewed **derived** images live in `derived/`:

- `vendor_boot.img` — original vendor_boot with only fstab lines removed
- `vendor.img` — original vendor with only fstab lines removed

`BOARD_PREBUILT_VENDOR_BOOTIMAGE` and `BOARD_PREBUILT_VENDORIMAGE` point to
those two derived files; the other seven flags point to stock `prebuilt/`.
`system`, `system_ext` and `product` are built by Lineage in this phase.
`mi_ext` is not staged or claimed; no prebuilt hook is invented.

Canonical target path: `vendor/xiaomi/rothko/prebuilt/<partition>.img`.

## Device identity whitelist

Only the CN `Redmi K70 Ultra`, model **2407FRK8EC**, firmware branch
**WNNCNXM**, `rothko`, is accepted. The Xiaomi 14T Pro and other models are
not accepted. There is no wildcard device/model substitution.

## Source manifest and staging

`source-manifest.json` uses project-relative source paths:

- boot/init_boot/vendor_boot/dtbo: `../offline-k70u/images/`
- vendor/odm/dlkm images: `firmware/images/`

Staging is deliberately local and dry-run by default:

```bash
cd vendor/xiaomi/rothko
python3 scripts/stage_prebuilts.py           # verify only
python3 scripts/stage_prebuilts.py --apply   # publish stock prebuilt/
python3 scripts/stage_derived.py --apply     # publish the two fstab-only derived images
python3 scripts/stage_derived.py --apply --metadata-only  # refresh evidence/manifest only
```

Before copying, the script independently:

1. verifies `firmware/manifest/payload_manifest.bin` has the fixed .308
   SHA-256 (`25cb38be…c833`);
2. parses `new_partition_info` from that manifest;
3. cross-checks every target against
   `logs/parent-manifest-expectations.json`;
4. verifies every source size/hash against both;
5. checks boot/vendor_boot/DTBO/EROFS headers.

It uses an ordinary `shutil.copyfile` copy (a reflink optimization may be added
later), never a hardlink. Copies are staged in a private directory and re-hashed; only after all nine pass are they atomically
renamed into `prebuilt/`. A failed run publishes no new image. No blob fixups
are applied.

`prebuilt/staged-manifest.json` records the nine stock hashes.
The parent readback JSON snapshots are copied byte-for-byte into `evidence/`
under this vendor tree. `derived-manifest.json` records their path relative
to the **vendor root** (`base: "vendor_root"`) and their fixed SHA-256; runtime
verification reads only this tree and does not require the original
`lineage-k70u/logs/` checkout.

`derived-manifest.json` records, separately:

- original stock size/hash and derived size/hash;
- recipe-code hash and the internal evidence-snapshot hash;
- `only_allowed_fstabs_change: true`;
- `signed: false`, `avb_verified: false`, `release_ready: false`,
  `hardware_release_ready: false`.

The derived images are **not** OEM-signed or AVB-validated; no fstab AVB flag
was changed and no readiness claim is made.

## Make integration

`BoardConfigVendor.mk` defines the actual `BOARD_PREBUILT_*` flags:

```text
BOARD_PREBUILT_BOOTIMAGE
BOARD_PREBUILT_INIT_BOOT_IMAGE
BOARD_PREBUILT_VENDOR_BOOTIMAGE
BOARD_PREBUILT_DTBOIMAGE
BOARD_PREBUILT_VENDORIMAGE
BOARD_PREBUILT_ODMIMAGE
BOARD_PREBUILT_SYSTEM_DLKMIMAGE
BOARD_PREBUILT_VENDOR_DLKMIMAGE
BOARD_PREBUILT_ODM_DLKMIMAGE
```

The device BoardConfig must include it explicitly:

```make
include vendor/xiaomi/rothko/BoardConfigVendor.mk
```

If the product wants the product-side hook, the device product makefile should
inherit it explicitly:

```make
$(call inherit-product, vendor/xiaomi/rothko/rothko-vendor.mk)
```

This lane does not edit the device tree. `rothko-vendor.mk` is the product-side
hook and intentionally adds no speculative HAL packages, VINTF fragments,
SELinux policy, or `PRODUCT_COPY_FILES` for proprietary images.

The make gate is narrow: missing image, size mismatch, SHA-256 mismatch, or a
missing/invalid staged manifest fails. It does not assert CRC or hardware
release readiness. `ROTHKO_HARDWARE_RELEASE_READY` remains `false`.

VINTF/SELinux integration belongs to the device lane and must use the real
vendor inventory; no empty manifest and no permissive policy is provided.

## Authorized policy preparation (text candidate only)

The user separately authorized audited policy derivation with **permission
reductions only**, all neverallow assertions retained, OEM originals preserved
and no phone operation. This expands the allowed preparation scope, not the
identity of the currently staged images: both current derived image manifests
still describe only their reviewed fstab changes. Do not publish a future
policy-modified image under that unchanged fstab-only claim.

`scripts/tighten_vendor_policy.py` implements one bounded reviewed reduction:
remove exactly the complete line
`(allow system_server_34_0 self (capability (sys_module)))` at line 12179.
The original CIL must have SHA-256
`d60dee27ff79fe0d0c05d26156af35c83bff36c93db09556b1ea724e0e14f1f5`;
the candidate must have SHA-256
`4e2ecfad15f8984e806ec82cd98bfc422982af48d89d147ce7cf28bc67018a07`.
Wrong hashes, target count/shape/line changes or nonfresh/unsafe report paths
fail closed. There is no force/hash-bypass mode or generic conflict filter.

```bash
python3 -B scripts/tighten_vendor_policy.py \
  --input "$IMAGE_BOUND_VENDOR_CIL" \
  --report-dir "$FRESH_EXTERNAL_REPORT_DIR"
```

Supply the real CIL read from the hash-bound selected vendor image, not an
unverified analysis substitute. The output is only a new candidate CIL and
honest JSON receipt under a fresh external directory. The input and all other
bytes/assertions/types/mappings remain unchanged; protected source/prebuilt/
derived trees and input-directory descendants are refused as report targets.
The script executes no CIL compiler, target binary, image builder or installer.

Parent replay on the actual fixed input returned 0 and reproduced the exact
previously tested candidate bytes. That candidate's real strict secilc result
remains **255**, with 141 assertion failures instead of baseline 142. Tool rc 0
is a text transformation result, not acceptance of a policy, image, hardware
feature or ROM. No current vendor image, BoardConfig hook or source manifest
was changed by adding this tool. The same byte-identical candidate did not
need another duplicate secilc run.

Twelve focused safety/negative tests and the complete 26-test vendor tooling
suite pass. Real replay, source/tool hashes and all test/command exit codes:
`logs/lineage-rothko-build-20261101-132134/final-artifact-acceptance-20261101-194534/policy-tightening-tool-verification-20261101-210535/`.
Additional policy changes require their own security/function rationale and
full actual-image acceptance; this tool does not authorize broad rule deletion.

### Fixed compiler-deny profile (not integrated or installed)

This branch supports CIL `deny`, processed before neverallow checks. The fixed
`policy/reviewed_reductions.cil` contains only the three reviewed reductions:
system_server_34_0 sys_module and virtual_face/virtual_fingerprint property-file
read/open. SHA-256:
`b594b175b2d149ab91702c578b49fd1acbb5f16acc64e3740d6cc0392de5891f`.
This is a separate path, not a change to the pinned text tool above. There is
no generic failure-to-deny generator, make hook, image or source installation.

Built-host positive/negative fixtures and binary round-trip show only selected
permissions removed, with neverallow still enforced. Against all 11 unchanged
actual image CILs, the combined layer still returns secilc **255 / 138** failures
(baseline 255 / 142). Tool/experiment success is not policy or ROM acceptance.
The current staged images and fstab-only manifests are unchanged.
Evidence: `cil-deny-capability-20261101-211603/`,
`policy-deny-combined-20261101-212413/` and
`cil-deny-source-validation-20261101-212738/` below the final acceptance root
named above. The latest complete vendor suite contains 27 tests, all passing;
the earlier 26-test run is a retained historical result.

### Pinned legacy APEX preparation (external candidate only)

`scripts/prepare_legacy_apex_policy.py` emits the separate fixed
`policy/apexd_legacy_checkpoint_reductions.cil` only when five exact reviewed
artifacts match: system.img, actual apexd, second-stage init, stock init_boot and
the generated mount_before_data=false header. The source profile itself is
also read and hash-checked. Changed artifacts/flag/profile require fresh review;
there is no force/hash-bypass mode. This pins one security review, not a ROM
version support policy. Future builds are not silently accepted by the old guard.

```bash
python3 -B scripts/prepare_legacy_apex_policy.py \
  --system-image "$ACTUAL_SYSTEM_IMAGE" --apexd "$IMAGE_BOUND_APEXD" \
  --init "$IMAGE_BOUND_SECOND_STAGE_INIT" --init-boot "$STOCK_INIT_BOOT" \
  --flag-header "$GENERATED_FLAGS_HEADER" --report-dir "$FRESH_EXTERNAL_REPORT"
```

Use the guarded emitted candidate, not a raw make hook to the source fragment.
There is no automatic installation hook here. The current actual ARM64 apexd
eliminates the true-setter for the newer early-mount mode; normal vold Binder
rollback remains. Stock first-stage init and runtime rollback are not verified.

The real five-artifact replay succeeds only as text emission. Original 11 CIL
inputs plus the original three reductions and guarded two-rule output still
fail strict secilc: **255 / 135** failures, down from 138 with exactly the three
reviewed old metadata assertion failures removed and no new failure headers.
All assertions remain enabled and originals unchanged. Eleven focused guard
tests and the subsequent complete 38-test vendor suite pass. Receipts live at
the final acceptance root in `apex-policy-guard-parent-validation-20261101-222435/`,
`policy-deny-apex-legacy-combined-20261101-222557/` and
`reconciled-source88-apex-guard-suites-20261101-222557/`. Neither a successful
guard nor these tests mean the policy, hardware or ROM is accepted.

## Tests

```bash
cd vendor/xiaomi/rothko
python3 -m unittest tests.test_staging -v
```

Focused tests cover unknown model/market, tampered hash, partial missing
source, and actual staged hashes.

## Distribution

The proprietary `.img` files are local inputs and are gitignored:

```text
/prebuilt/*.img
/prebuilt/staged-manifest.json
/prebuilt/.staging-*/
/proprietary/
```

This is not a redistributable OTA. All images remain subject to the original
OEM terms. `derived/*.img` is also gitignored; `derived-manifest.json` is the
local evidence record.

## Build-lane input contract

The build lane can rely on these actual files and fields:

- Required include: `include vendor/xiaomi/rothko/BoardConfigVendor.mk`
  (no optional `-include` fallback).
- Stock inputs: nine images under `prebuilt/`, verified by
  `prebuilt/staged-manifest.json` and `source-manifest.json`.
- Derived inputs: `derived/vendor_boot.img` and `derived/vendor.img`, verified by
  `derived-manifest.json` and `derived-source-manifest.json`.
- `derived-manifest.json` fields:
  - `source_manifest_sha256`, `derived_source_manifest_sha256`,
    `payload_manifest_sha256`;
  - separate `stock` and `derived` entries, each with size/SHA-256;
  - per-derived `original`, `recipe_code_sha256`, `readback.base` (must be
    `vendor_root`), `readback.path` (relative to vendor root),
    `readback.sha256`, `readback.ok`, `readback.snapshot`;
  - `only_allowed_fstabs_change`, `blob_fixups`, `signed`, `avb_verified`,
    `release_ready`, `hardware_release_ready`.
- `verify_prebuilts.py` reads 9 stock images and 2 derived images plus the
  internal `evidence/` snapshots. It has no runtime dependency on the original
  extraction workspace or `lineage-k70u/logs/`.
- `verify_prebuilts.py --make` checks nine stock plus two derived images and
  fails on missing/tampered inputs. It does not assert OEM signatures or AVB.
