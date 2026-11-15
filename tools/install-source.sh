#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

if [[ $# != 1 || ! -f $1/build/envsetup.sh ]]; then
    echo "Usage: $0 <lineage-source-root containing build/envsetup.sh>" >&2
    exit 2
fi

here=$(cd -- "$(dirname -- "$0")/.." && pwd)
root=$(cd -- "$1" && pwd)
paths=(device/xiaomi/rothko vendor/xiaomi/rothko)
pending=()

# Validate both destinations before creating either device or vendor content.
for path in "${paths[@]}"; do
    src="$here/$path"
    dst="$root/$path"
    parent="$root"
    IFS=/ read -r -a parts <<< "$path"
    for part in "${parts[@]}"; do
        parent="$parent/$part"
        if [[ -L $parent || ( -e $parent && ! -d $parent ) ]]; then
            echo "$parent: destination must be a directory, not a file or symlink" >&2
            exit 1
        fi
    done
    if [[ -d $dst ]]; then
        if ! diff -qr -- "$src" "$dst" >/dev/null; then
            echo "$path: existing directory differs; nothing installed" >&2
            exit 1
        fi
        echo "$path: already identical, keeping existing files"
    else
        pending+=("$path")
    fi
done

run_tmp=$(mktemp -d "$root/.rothko-install.XXXXXX")
trap 'rm -rf -- "$run_tmp"' EXIT
for path in "${pending[@]}"; do
    mkdir -p "$run_tmp/$(dirname -- "$path")"
    cp -a -- "$here/$path" "$run_tmp/$path"
done

for path in "${pending[@]}"; do
    dst="$root/$path"
    mkdir -p -- "$(dirname -- "$dst")"
    if [[ -e $dst || -L $dst ]]; then
        echo "$path: destination appeared after preflight; stop and inspect" >&2
        exit 1
    fi
    mv -T --no-clobber -- "$run_tmp/$path" "$dst"
    if [[ -d $run_tmp/$path ]]; then
        echo "$path: destination changed during installation; nothing overwritten" >&2
        exit 1
    fi
    echo "$path: installed"
done
