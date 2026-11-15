# Parent readback evidence snapshots

These files are byte-for-byte copies of the parent readback evidence used to
stage the two derived images. They are snapshots for a relocatable vendor tree;
runtime `verify_prebuilts.py` reads only this directory and the vendor tree.

| snapshot | source at staging time | SHA-256 |
|---|---|---|
| `parent-derived-vendor-boot-readback.json` | `lineage-k70u/logs/parent-derived-vendor-boot-readback.json` | `c74b02a86c9bccf65d00e77030cbdc08cbc61e1b1441da87760439f88fdccfd4` |
| `parent-derived-vendor-readback.json` | `lineage-k70u/logs/parent-derived-vendor-readback.json` | `78aeebf3f524e1560cd1c7878d1eec8ed3513d231770ae04a4a818b452d1cb1d` |

`derived-manifest.json` records `readback.base: "vendor_root"` and paths
relative to the vendor root. No external logs are required by the runtime
verifier.
