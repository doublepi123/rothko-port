#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

if [[ $# != 1 || ! -d $1 ]]; then
    echo "Usage: $0 <lineage-source-root>" >&2
    exit 2
fi

here=$(cd -- "$(dirname -- "$0")/.." && pwd)
root=$(cd -- "$1" && pwd)
run_tmp=$(mktemp -d "${TMPDIR:-/tmp}/rothko-patch-check.XXXXXX")
trap 'rm -rf -- "$run_tmp"' EXIT
paths=()
names=()
bases=()

# Check every repository and series before the first git am changes a branch.
while IFS=$'\t' read -r path name base url; do
    if [[ -z $path || -z $name || ! $base =~ ^[0-9a-f]{40}$ || -z $url ||
          $path == /* || $path == *..* || $name == */* ]]; then
        echo "Invalid patch index row: $path" >&2
        exit 1
    fi
    repo="$root/$path"
    top=$(GIT_MASTER=1 git -C "$repo" rev-parse --show-toplevel)
    if [[ $top != "$repo" ]]; then
        echo "$path: expected a repository at this exact path" >&2
        exit 1
    fi
    if [[ -n $(GIT_MASTER=1 git -C "$repo" status --porcelain) ]]; then
        echo "$path: working tree must be clean" >&2
        exit 1
    fi
    head=$(GIT_MASTER=1 git -C "$repo" rev-parse HEAD)
    if [[ $head != "$base" ]]; then
        echo "$path: expected base $base, found $head; nothing applied" >&2
        exit 1
    fi
    GIT_MASTER=1 git -C "$repo" var GIT_COMMITTER_IDENT >/dev/null
    patches=("$here/patches/$name"/*.patch)
    if [[ ! -f ${patches[0]} ]]; then
        echo "$name: no patch files" >&2
        exit 1
    fi
    index="$run_tmp/${#paths[@]}.index"
    GIT_INDEX_FILE="$index" GIT_MASTER=1 git -C "$repo" read-tree "$base"
    for patch in "${patches[@]}"; do
        GIT_INDEX_FILE="$index" GIT_MASTER=1 git -C "$repo" apply --cached "$patch"
    done
    paths+=("$path")
    names+=("$name")
    bases+=("$base")
done < "$here/patches/BASES.tsv"

for i in "${!paths[@]}"; do
    repo="$root/${paths[i]}"
    if [[ $(GIT_MASTER=1 git -C "$repo" rev-parse HEAD) != "${bases[i]}" ||
          -n $(GIT_MASTER=1 git -C "$repo" status --porcelain) ]]; then
        echo "${paths[i]} changed after preflight; stop and inspect" >&2
        exit 1
    fi
    echo "Applying ${names[i]} to ${paths[i]}"
    GIT_MASTER=1 git -C "$repo" am "$here/patches/${names[i]}"/*.patch
done
