#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Usage: ./apply-patches.sh <lineage-source-root>
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$1" && pwd)
while IFS=$'\t' read -r path name base _url; do
  head=$(git -C "$root/$path" rev-parse HEAD)
  [ "$head" = "$base" ] || echo "warning: $path is at $head, series was made on $base" >&2
  git -C "$root/$path" am --3way "$here/patches/$name"/*.patch
done < "$here/patches/BASES.tsv"
