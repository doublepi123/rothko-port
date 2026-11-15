# Rothko image tools

`erofs_replace_file.py` replaces one FLAT_PLAIN file in an AVB-footered EROFS
partition image without changing the filesystem layout. It then re-signs the
hashtree/FEC (same salt and properties) and regenerates the chained vbmeta.

    PATH=<dir with fec>:$PATH python3 tools/image/erofs_replace_file.py \
        --image vendor.img --vbmeta vbmeta_vendor.img \
        --path /bin/hw/mfp-daemon --payload mfp-daemon \
        --key <your-avb-key.pem> --avbtool <aosp>/external/avb/avbtool.py --out out/

Requires `dump.erofs`, `fsck.erofs` and `fec` on PATH. The payload must fit
the file's existing block extent. Building mfp-daemon with
`--remap-path-prefix` keeps embedded paths short.

It reproduced the reference rothko vendor image byte for byte.
