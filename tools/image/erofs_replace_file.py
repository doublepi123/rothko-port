#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Replace one file inside an AVB-protected EROFS partition image, in place.

The file must use the FLAT_PLAIN layout and the new payload must fit its
existing block extent, so only the file's data blocks and its inode change.
The partition is re-signed (same salt, FEC roots and properties) and the
chained vbmeta image is regenerated with only that partition's hashtree
descriptor replaced. Host-only: it never talks to a device.
"""
import argparse
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile

BLK = 4096
EROFS_MAGIC = 0xE0F5E1E2


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(8 << 20), b''):
            h.update(b)
    return h.hexdigest()


def load_avbtool(path):
    spec = importlib.util.spec_from_file_location('avbtool', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse(avb, path):
    image = avb.ImageHandler(str(path), read_only=True)
    footer, header, descriptors, _ = avb.Avb()._parse_image(image)
    image.seek(footer.vbmeta_offset if footer else 0)
    blob = image.read(header.SIZE + header.authentication_data_block_size + header.auxiliary_data_block_size)
    if not avb.verify_vbmeta_signature(header, blob):
        raise SystemExit(f'{path}: vbmeta signature does not verify')
    at = header.SIZE + header.authentication_data_block_size + header.public_key_offset
    return footer, header, descriptors, blob[at:at + header.public_key_size]


def replace_file(raw, target, payload):
    data = bytearray(raw.read_bytes())
    info = subprocess.run(['dump.erofs', '--path=' + target, str(raw)], capture_output=True, check=True).stdout.decode()
    nid = int(re.search(r'NID:\s*(\d+)', info).group(1))
    if struct.unpack_from('<I', data, 1024)[0] != EROFS_MAGIC or data[1024 + 12] != 12:
        raise SystemExit('not a 4 KiB-block EROFS image')
    ino = struct.unpack_from('<I', data, 1024 + 40)[0] * BLK + nid * 32
    fmt, _, mode = struct.unpack_from('<HHH', data, ino)
    if fmt & 1 or (fmt >> 1) & 7 != 0 or mode & 0o170000 != 0o100000:
        raise SystemExit(f'{target}: only compact FLAT_PLAIN regular files are supported')
    old_size, blkaddr = struct.unpack_from('<I', data, ino + 8)[0], struct.unpack_from('<I', data, ino + 16)[0]
    nblk = -(-old_size // BLK)
    if -(-len(payload) // BLK) > nblk:
        raise SystemExit(f'{target}: payload needs {-(-len(payload) // BLK)} blocks, extent has {nblk}')
    start = blkaddr * BLK
    before = bytes(data)
    data[start:start + nblk * BLK] = payload + bytes(nblk * BLK - len(payload))
    struct.pack_into('<I', data, ino + 8, len(payload))
    raw.write_bytes(bytes(data))
    changed = {i for i in range(0, len(data), BLK) if data[i:i + BLK] != before[i:i + BLK]}
    allowed = set(range(start, start + nblk * BLK, BLK)) | {ino - ino % BLK}
    if not changed <= allowed:
        raise SystemExit('unexpected blocks changed')
    if subprocess.run(['dump.erofs', '--cat', '--path=' + target, str(raw)], capture_output=True, check=True).stdout != payload:
        raise SystemExit('readback mismatch')
    subprocess.run(['fsck.erofs', str(raw)], check=True, capture_output=True)
    return {'nid': nid, 'old_size': old_size, 'new_size': len(payload), 'extent_blocks': nblk, 'changed_blocks': len(changed)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--image', required=True, type=Path, help='AVB-footered EROFS partition image')
    ap.add_argument('--vbmeta', required=True, type=Path, help='chained vbmeta image that holds this partition descriptor')
    ap.add_argument('--path', required=True, help='file path inside the filesystem, e.g. /bin/hw/mfp-daemon')
    ap.add_argument('--payload', required=True, type=Path)
    ap.add_argument('--key', required=True, type=Path, help='AVB signing key used for both images')
    ap.add_argument('--avbtool', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path, help='output directory (must not exist)')
    a = ap.parse_args(argv)
    for tool in ('dump.erofs', 'fsck.erofs', 'fec'):
        if not shutil.which(tool):
            raise SystemExit(f'{tool} not found on PATH')
    avb = load_avbtool(a.avbtool)
    footer, header, descriptors, pubkey = parse(avb, a.image)
    child = parse(avb, a.vbmeta)
    tree = next(d for d in descriptors if isinstance(d, avb.AvbHashtreeDescriptor))
    a.out.mkdir(parents=True)
    out_image = a.out / a.image.name
    with a.image.open('rb') as src, out_image.open('wb') as dst:
        left = footer.original_image_size
        while left:
            b = src.read(min(8 << 20, left))
            dst.write(b)
            left -= len(b)
    result = replace_file(out_image, a.path, a.payload.read_bytes())
    args = [sys.executable, '-B', str(a.avbtool), 'add_hashtree_footer', '--image', str(out_image),
            '--partition_size', str(os.path.getsize(a.image)), '--partition_name', tree.partition_name,
            '--hash_algorithm', tree.hash_algorithm, '--block_size', str(tree.data_block_size),
            '--fec_num_roots', str(tree.fec_num_roots), '--salt', tree.salt.hex(), '--algorithm', avb.lookup_algorithm_by_type(header.algorithm_type)[0],
            '--key', str(a.key), '--flags', str(header.flags), '--rollback_index', str(header.rollback_index),
            '--rollback_index_location', str(header.rollback_index_location)]
    for d in descriptors:
        if isinstance(d, avb.AvbPropertyDescriptor):
            args += ['--prop', d.key + ':' + d.value.decode()]
    subprocess.run(args, check=True)
    new_footer, _, new_descriptors, new_pubkey = parse(avb, out_image)
    new_tree = next(d for d in new_descriptors if isinstance(d, avb.AvbHashtreeDescriptor))
    if new_pubkey != pubkey:
        raise SystemExit('--key differs from the key that signed the original image')
    descs = [new_tree if isinstance(d, avb.AvbHashtreeDescriptor) and d.partition_name == tree.partition_name else d for d in child[2]]
    blob = avb.Avb()._generate_vbmeta_blob(
        algorithm_name=avb.lookup_algorithm_by_type(child[1].algorithm_type)[0], key_path=str(a.key), public_key_metadata_path=None,
        descriptors=descs, chain_partitions_use_ab=None, chain_partitions_do_not_use_ab=None,
        rollback_index=child[1].rollback_index, flags=child[1].flags, rollback_index_location=child[1].rollback_index_location,
        props=None, props_from_file=None, kernel_cmdlines=None, setup_rootfs_from_kernel=None, ht_desc_to_setup=None,
        include_descriptors_from_image=None, signing_helper=None, signing_helper_with_files=None,
        release_string=child[1].release_string, append_to_release_string=None,
        required_libavb_version_minor=child[1].required_libavb_version_minor)
    size = os.path.getsize(a.vbmeta)
    out_vbmeta = a.out / a.vbmeta.name
    out_vbmeta.write_bytes(blob + bytes(size - len(blob)))
    if parse(avb, out_vbmeta)[3] != child[3]:
        raise SystemExit('--key differs from the key that signed the chained vbmeta')
    for p in (out_image, out_vbmeta):
        subprocess.run([sys.executable, '-B', str(a.avbtool), 'verify_image', '--image', str(p)], check=True, capture_output=True)
    result.update(image=str(out_image), image_sha256=sha(out_image), vbmeta=str(out_vbmeta), vbmeta_sha256=sha(out_vbmeta))
    for k, v in result.items():
        print(f'{k}: {v}')


if __name__ == '__main__':
    main()
