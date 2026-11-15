# Rothko vendor input preparation

This repository stores source manifests, evidence snapshots and input
validation/staging scripts. It contains **no partition images or vendor
shared libraries**. It is not a blob-complete vendor tree and does not yet
implement a portable extract-utils workflow.

## Input layout

`source-manifest.json` records CN `OS3.0.308.0.WNNCNXM` image hashes.
The existing scripts expect the original project layout:

- boot/init_boot/vendor_boot/dtbo under `../offline-k70u/images/`;
- vendor/odm/dlkm images under `firmware/images/`;
- a pinned payload manifest and parent expectations/evidence under the
  original project's firmware/logs directories.

Read the scripts before staging. These dependencies are not supplied here.
Copying this repository into an arbitrary Lineage checkout does not by itself
make staging or a full build succeed.

## Existing staging entry points

From the repository root, with the documented inputs already available:

```bash
python3 scripts/stage_prebuilts.py
python3 scripts/stage_prebuilts.py --apply
python3 scripts/stage_derived.py --apply
```

The first command validates without publishing images. `--apply` stages local
files; it does not flash a phone. Scripts pin the CN model/firmware and reject
other inputs rather than silently substitute an international variant.

`BoardConfigVendor.mk` still points to prebuilt and derived images.
`derived-manifest.json` describes the earlier fstab-only derivation, not the
latest signed vendor image with the Lineage fingerprint HAL. Do not use it
as a receipt for current phone contents.

## Remaining work

Build a proper proprietary file list, extraction/fixup recipes, source-built
vendor/odm and matching init/VINTF/SELinux integration. The current phone's
fingerprint, VoWMic and hotword experiments also include post-build image
processing documented in the top-level preparation repository.

GPL/module source requests and OEM/Google redistribution permissions are
separate matters. Image hashes and extraction scripts do not confer a right
to redistribute the extracted binaries. Keys and personal device data are
excluded.
