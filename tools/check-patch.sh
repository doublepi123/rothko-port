#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

if [[ $# != 1 ]]; then
    echo "Usage: $0 <patch-directory-name>" >&2
    exit 2
fi
here=$(cd -- "$(dirname -- "$0")/.." && pwd)
selected=()
while IFS=$'\t' read -r path name base url; do
    if [[ $name == "$1" ]]; then
        selected=("$path" "$name" "$base" "$url")
    fi
done < "$here/patches/BASES.tsv"
if [[ ${#selected[@]} != 4 ]]; then
    echo "Unknown patch series: $1" >&2
    exit 2
fi
read -r _path name base url <<< "${selected[*]}"
if [[ ! $base =~ ^[0-9a-f]{40}$ ||
      ( $url != https://github.com/* && $url != https://android.googlesource.com/* ) ]]; then
    echo "Invalid pinned base or upstream URL" >&2
    exit 1
fi

run_tmp=$(mktemp -d "${TMPDIR:-/tmp}/rothko-patch-check.XXXXXX")
trap 'rm -rf -- "$run_tmp"' EXIT
GIT_MASTER=1 git init -q "$run_tmp/repo"
GIT_TERMINAL_PROMPT=0 GIT_MASTER=1 git -C "$run_tmp/repo" \
    -c protocol.version=2 fetch --depth=1 "$url" "$base"
actual=$(GIT_MASTER=1 git -C "$run_tmp/repo" rev-parse FETCH_HEAD)
test "$actual" = "$base"
GIT_MASTER=1 git -C "$run_tmp/repo" read-tree "$base"
patches=("$here/patches/$name"/*.patch)
for patch in "${patches[@]}"; do
    GIT_MASTER=1 git -C "$run_tmp/repo" apply --cached "$patch"
done
GIT_MASTER=1 git -C "$run_tmp/repo" diff --cached "$base" --stat
echo "PASS: $name at $base (${#patches[@]} patches)"
