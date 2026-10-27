#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Rebuild the installed coral kernel (#30, 19 Oct 2026), its modules and the 12-entry DTB:
# - Source: public SM8150 tree at 6963e3800a8e (3 commits past tag v6.17.0-sm8150 at 379d8fe35c7c)
#   + kernel/series/coral-30 (0001..0007) + kernel/series/coral-fec40357 (0008..0011), git tree
#   6d4115553ae5. Kernel #30 was built from this content; coral-30 alone (tree 21eb1828b205) does
#   not give the installed Image, because 0010 and 0011 change built-in drivers.
# - 12-entry DTB: cpp + dtc -@, stamped with the 12 factory dtbo board selectors (reproduces
#   sha256 3efe241aa349ff260ef0312e1b0a3a611943f71b0939261729c42e3842c90058 with dtc 1.8.1).
# - A byte-exact Image also needs GCC 16.1.0 and the original KBUILD_BUILD_USER/KBUILD_BUILD_HOST;
#   the defaults below differ from the installed banner.
# Usage: tools/build-kernel.sh <kernel-source-at-6963e3800a8e> <new-output-dir>
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SERIES_30=$HERE/kernel/series/coral-30
SERIES_FEC=$HERE/kernel/series/coral-fec40357
[ "$#" -eq 2 ] || {
    echo 'usage: build-kernel.sh KERNEL_SOURCE NEW_OUTPUT' >&2
    exit 1
}
SRC=$1
OUT=$2
BASE=6963e3800a8e
TREE_FEC=6d4115553ae5a9aec7b9e4ae23f77b2e4c4d7c4e
[ -d "$SRC/.git" ] || [ -f "$SRC/.git" ] || { echo "not a git checkout: $SRC" >&2; exit 1; }

if [ "$(git -C "$SRC" rev-parse HEAD)" = "$(git -C "$SRC" rev-parse "$BASE^{commit}")" ]; then
    for series in "$SERIES_30" "$SERIES_FEC"; do
        while read -r patch; do
            [ -z "$patch" ] || git -C "$SRC" am -q "$series/$patch"
        done < "$series/series"
    done
fi
[ "$(git -C "$SRC" rev-parse 'HEAD^{tree}')" = "$TREE_FEC" ] || {
    echo 'source is not 6963e3800a8e + coral-30 + coral-fec40357' >&2
    exit 1
}

mkdir -p "$OUT"
cp "$SERIES_30/config" "$OUT/.config"
export ARCH=arm64
export CROSS_COMPILE="${CROSS_COMPILE:-aarch64-linux-gnu-}"
export KBUILD_BUILD_USER="${KBUILD_BUILD_USER:-builder}"
export KBUILD_BUILD_HOST="${KBUILD_BUILD_HOST:-localhost}"
export KBUILD_BUILD_VERSION="${KBUILD_BUILD_VERSION:-30}"
export KBUILD_BUILD_TIMESTAMP="${KBUILD_BUILD_TIMESTAMP:-Mon Oct 19 21:29:48 CEST 2026}"

make -C "$SRC" O="$OUT" LOCALVERSION= olddefconfig
make -C "$SRC" O="$OUT" LOCALVERSION= -j"$(nproc)" Image modules
test "$(cat "$OUT/include/config/kernel.release")" = 6.17.0-sm8150

cpp -nostdinc \
    -I "$SRC/arch/arm64/boot/dts/qcom" \
    -I "$SRC/include" \
    -I "$SRC/scripts/dtc/include-prefixes" \
    -undef -D__DTS__ -x assembler-with-cpp \
    "$SRC/arch/arm64/boot/dts/qcom/sm8150-google-coral.dts" > "$OUT/coral.pre.dts"
dtc -q -@ -I dts -O dtb -o "$OUT/coral-base.dtb" "$OUT/coral.pre.dts"
: > "$OUT/dtb-12"
for pair in \
    "20000 51405" "20000 60a05" "20000 50a05" "20000 60b05" \
    "20000 61405" "20000 60105" "10000 50005" "20000 50105" \
    "20000 60205" "20000 50b05" "20000 51e05" "20000 61e05"; do
    msm=${pair% *}
    board=${pair#* }
    cp "$OUT/coral-base.dtb" "$OUT/coral-entry.dtb"
    fdtput -tx "$OUT/coral-entry.dtb" / qcom,msm-id 153 "$msm"
    fdtput -tx "$OUT/coral-entry.dtb" / qcom,board-id "$board" 0
    cat "$OUT/coral-entry.dtb" >> "$OUT/dtb-12"
done
rm -f "$OUT/coral-entry.dtb"
sha256sum "$OUT/arch/arm64/boot/Image" "$OUT/dtb-12"
