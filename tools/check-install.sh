#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
here=$(cd -- "$(dirname -- "$0")/.." && pwd)
run_tmp=$(mktemp -d "${TMPDIR:-/tmp}/rothko-install-check.XXXXXX")
trap 'rm -rf -- "$run_tmp"' EXIT

for scenario in happy conflict symlink; do
    mkdir -p "$run_tmp/$scenario/build"
    printf '# Android root fixture\n' > "$run_tmp/$scenario/build/envsetup.sh"
done

bash "$here/tools/install-source.sh" "$run_tmp/happy"
diff -qr "$here/device/xiaomi/rothko" "$run_tmp/happy/device/xiaomi/rothko"
diff -qr "$here/vendor/xiaomi/rothko" "$run_tmp/happy/vendor/xiaomi/rothko"
find "$run_tmp/happy" -type f -printf '%P %s %T@\n' | sort > "$run_tmp/before"
bash "$here/tools/install-source.sh" "$run_tmp/happy"
find "$run_tmp/happy" -type f -printf '%P %s %T@\n' | sort > "$run_tmp/after"
cmp "$run_tmp/before" "$run_tmp/after"

mkdir -p "$run_tmp/conflict/vendor/xiaomi/rothko"
printf 'user-owned content\n' > "$run_tmp/conflict/vendor/xiaomi/rothko/keep.txt"
if bash "$here/tools/install-source.sh" "$run_tmp/conflict"; then
    echo "FAIL: conflicting vendor tree was accepted" >&2
    exit 1
else
    test $? = 1
fi
test ! -e "$run_tmp/conflict/device"
grep -qx 'user-owned content' "$run_tmp/conflict/vendor/xiaomi/rothko/keep.txt"

ln -s "$run_tmp/happy/device" "$run_tmp/symlink/device"
if bash "$here/tools/install-source.sh" "$run_tmp/symlink"; then
    echo "FAIL: symlink target was accepted" >&2
    exit 1
else
    test $? = 1
fi
test ! -e "$run_tmp/symlink/vendor"
echo "PASS: install, identical repeat, conflict and symlink rejection"
