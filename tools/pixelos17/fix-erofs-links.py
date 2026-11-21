#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Move EROFS inline symlinks that cross an inode block into appended blocks.

The input image is never modified. --root must be the matching, read-only
mount of that image; its lstat inode numbers identify EROFS nids.
"""
import argparse
import os
from pathlib import Path
import shutil
import stat
import struct
import sys

BLOCK = 4096
EROFS_MAGIC = 0xE0F5E1E2
SB_OFFSET = 1024
SB_SIZE = BLOCK - SB_OFFSET
SB_BLOCKS = 36
SB_META_BLKADDR = 40
SB_CHECKSUM = 4
FMT_EXTENDED = 1
FMT_LAYOUT_SHIFT = 1
FMT_LAYOUT_MASK = 0x7 << FMT_LAYOUT_SHIFT
LAYOUT_FLAT_PLAIN = 0
LAYOUT_INLINE = 2
S_IFMT = 0o170000
S_IFLNK = 0o120000


def crc32c(data):
    crc = 0xffffffff
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0x82f63b78 if crc & 1 else 0)
    return crc


def read_exact(image, offset, size):
    image.seek(offset)
    data = image.read(size)
    if len(data) != size:
        raise ValueError(f"truncated image at offset {offset}")
    return data


def inode_location(image, meta_blkaddr, nid):
    pos = meta_blkaddr * BLOCK + nid * 32
    fmt = struct.unpack('<H', read_exact(image, pos, 2))[0]
    inode_size = 64 if fmt & FMT_EXTENDED else 32
    inode = bytearray(read_exact(image, pos, inode_size))
    mode = struct.unpack_from('<H', inode, 4)[0]
    xattr_count = inode[2] if inode_size == 64 else inode[2]
    xattr_size = 12 + 4 * (xattr_count - 1) if xattr_count else 0
    size = struct.unpack_from('<Q' if inode_size == 64 else '<I', inode, 8)[0]
    return pos, inode, inode_size, mode, xattr_size, size


def require_readonly_erofs_mount(root):
    if not os.path.ismount(root):
        raise ValueError("root must be the read-only EROFS mountpoint")
    wanted = os.path.realpath(root)
    with open('/proc/self/mountinfo', encoding='ascii') as mounts:
        for line in mounts:
            fields = line.rstrip().split()
            separator = fields.index('-')
            mountpoint = fields[4].replace('\\\\040', ' ').replace('\\\\011', '\\t').replace('\\\\134', '\\\\')
            if os.path.realpath(mountpoint) != wanted:
                continue
            fs_type = fields[separator + 1]
            mount_options = fields[5].split(',')
            if fs_type != 'erofs' or 'ro' not in mount_options or 'rw' in mount_options:
                raise ValueError("root must be mounted as read-only EROFS")
            return
    raise ValueError("root mount was not found in /proc/self/mountinfo")


def scan_links(root):
    found = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        # os.walk places symlinked directories in dirs; lstat every entry.
        for name in dirs + files:
            path = Path(directory) / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(os.fsencode(path))
                raw_target = os.fsencode(target)
                if info.st_ino in found and found[info.st_ino] != raw_target:
                    raise ValueError(f"nid {info.st_ino}: conflicting symlink targets")
                found[info.st_ino] = raw_target
    return found


def convert(image_path, root, output_path):
    image_path = Path(image_path)
    root = Path(root)
    output_path = Path(output_path)
    if not image_path.is_file() or not root.is_dir():
        raise ValueError("image must be a file and root must be a mounted directory")
    require_readonly_erofs_mount(root)
    if image_path.resolve() == output_path.resolve():
        raise ValueError("output must be separate from the input image")
    if output_path.exists():
        raise ValueError(f"output already exists: {output_path}")

    with image_path.open('rb') as src:
        sb = bytearray(read_exact(src, SB_OFFSET, SB_SIZE))
        if struct.unpack_from('<I', sb)[0] != EROFS_MAGIC:
            raise ValueError("not an EROFS image")
        if sb[12] != 12:
            raise ValueError("only 4 KiB EROFS blocks are supported")
        blocks = struct.unpack_from('<I', sb, SB_BLOCKS)[0]
        meta_blkaddr = struct.unpack_from('<I', sb, SB_META_BLKADDR)[0]
        if not blocks or blocks * BLOCK > image_path.stat().st_size:
            raise ValueError("inconsistent EROFS block count")

        links = scan_links(root)
        changes = []
        for nid, target in sorted(links.items()):
            inode_pos, inode, inode_size, mode, xattr_size, size = inode_location(src, meta_blkaddr, nid)
            if mode & S_IFMT != S_IFLNK:
                raise ValueError(f"nid {nid}: mounted symlink does not identify a symlink inode")
            fmt = struct.unpack_from('<H', inode)[0]
            layout = (fmt & FMT_LAYOUT_MASK) >> FMT_LAYOUT_SHIFT
            if layout != LAYOUT_INLINE:
                continue
            if size != len(target):
                raise ValueError(f"nid {nid}: mounted target length differs from inode size")
            if len(target) == 0:
                raise ValueError(f"nid {nid}: empty symlink target is invalid")
            if (inode_pos % BLOCK) + inode_size + xattr_size + size <= BLOCK:
                continue
            changes.append((nid, inode_pos, inode, inode_size, target))

        if not changes:
            raise ValueError("no inline symlinks crossing an inode block were found")
        new_blocks = blocks + len(changes)
        if new_blocks > 0xffffffff:
            raise ValueError("EROFS block count would overflow")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(image_path, output_path)
            with output_path.open('r+b') as dst:
                for index, (nid, inode_pos, inode, inode_size, target) in enumerate(changes):
                    block_addr = blocks + index
                    dst.seek(block_addr * BLOCK)
                    dst.write(target + bytes(BLOCK - len(target)))
                    fmt = struct.unpack_from('<H', inode)[0]
                    struct.pack_into('<H', inode, 0, (fmt & ~FMT_LAYOUT_MASK) |
                                     (LAYOUT_FLAT_PLAIN << FMT_LAYOUT_SHIFT))
                    struct.pack_into('<I', inode, 16, block_addr)
                    dst.seek(inode_pos)
                    dst.write(inode)
                struct.pack_into('<I', sb, SB_BLOCKS, new_blocks)
                struct.pack_into('<I', sb, SB_CHECKSUM, 0)
                struct.pack_into('<I', sb, SB_CHECKSUM, crc32c(sb))
                dst.seek(SB_OFFSET)
                dst.write(sb)
                dst.truncate(new_blocks * BLOCK)
                dst.flush()
                os.fsync(dst.fileno())
        except BaseException:
            output_path.unlink(missing_ok=True)
            raise

    return {"converted": len(changes), "old_blocks": blocks,
            "new_blocks": new_blocks, "output": str(output_path)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True, type=Path, help='raw EROFS image')
    parser.add_argument('--root', required=True, type=Path, help='matching read-only mounted root')
    parser.add_argument('--out', required=True, type=Path, help='new output image; must not exist')
    args = parser.parse_args(argv)
    try:
        result = convert(args.image, args.root, args.out)
    except (OSError, ValueError, struct.error) as exc:
        parser.error(str(exc))
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == '__main__':
    main()
