#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Rebuild the installed coral kernel (#30, 19 Oct 2026) and 12-entry DTB:
# - Kernel Image (#30): public SM8150 tree at 6963e3800a8e (3 commits past tag
#   v6.17.0-sm8150 at 379d8fe35c7c) + kernel/series/coral-30 (7 patches, tree 21eb1828b205).
# - 12-entry DTB & loadable modules: + kernel/series/coral-fec40357 (4 more patches,
#   tree 6d4115553ae5), compiled with cpp + dtc -@ and stamped with the 12 factory
#   dtbo board selectors (reproducing sha256 3efe241aa349ff260ef0312e1b0a3a611943f71b0939261729c42e3842c90058).
# Usage: tools/build-kernel.sh <kernel-source-at-6963e3800a8e> <new-output-dir> [--with-fec40357]
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SERIES_30=$HERE/kernel/series/coral-30
SERIES_FEC=$HERE/kernel/series/coral-fec40357
[ "$#" -ge 2 ] && [ "$#" -le 3 ] || {
    echo 'usage: build-kernel.sh KERNEL_SOURCE NEW_OUTPUT [--with-fec40357]' >&2
    exit 1
}
SRC=$1
OUT=$2
WITH_FEC=${3:-}
BASE=6963e3800a8e
TREE_30=21eb1828b205f86d87333e77179e03a8f5b930b3
TREE_FEC=6d4115553ae5a9aec7b9e4ae23f77b2e4c4d7c4e

if [ "$(git -C "$SRC" rev-parse HEAD)" = "$(git -C "$SRC" rev-parse "$BASE^{commit}")" ]; then
    while read -r patch; do
        [ -z "$patch" ] || git -C "$SRC" am -q "$SERIES_30/$patch"
    done < "$SERIES_30/series"
fi
[ "$(git -C "$SRC" rev-parse 'HEAD^{tree}')" = "$TREE_30" ] || {
    echo 'source is not 6963e3800a8e + coral-30' >&2
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
make -C "$SRC" O="$OUT" LOCALVERSION= -j"$(nproc)" Image modules dtbs
test "$(cat "$OUT/include/config/kernel.release")" = 6.17.0-sm8150

# Dual DTB (SM8150 v2 + v1) for the 2-entry baseline
DTB=$OUT/arch/arm64/boot/dts/qcom/sm8150-google-coral.dtb
cp "$DTB" "$OUT/coral-v2.dtb"
fdtput -tx "$OUT/coral-v2.dtb" / qcom,board-id 0 0
cp "$OUT/coral-v2.dtb" "$OUT/coral-v1.dtb"
fdtput -tx "$OUT/coral-v1.dtb" / qcom,msm-id 153 10000
cat "$OUT/coral-v2.dtb" "$OUT/coral-v1.dtb" > "$OUT/dtb"
sha256sum "$OUT/arch/arm64/boot/Image" "$OUT/dtb"

if [ "$WITH_FEC" = "--with-fec40357" ]; then
    while read -r patch; do
        [ -z "$patch" ] || git -C "$SRC" am -q "$SERIES_FEC/$patch"
    done < "$SERIES_FEC/series"
    [ "$(git -C "$SRC" rev-parse 'HEAD^{tree}')" = "$TREE_FEC" ] || {
        echo 'source is not 6963e3800a8e + coral-30 + coral-fec40357' >&2
        exit 1
    }
    cp "$SERIES_FEC/config" "$OUT/.config"
    make -C "$SRC" O="$OUT" LOCALVERSION= olddefconfig
    make -C "$SRC" O="$OUT" LOCALVERSION= -j"$(nproc)" modules
    cpp -nostdinc \
        -I "$SRC/arch/arm64/boot/dts/qcom" \
        -I "$SRC/include" \
        -I "$SRC/scripts/dtc/include-prefixes" \
        -undef -D__DTS__ -x assembler-with-cpp \
        "$SRC/arch/arm64/boot/dts/qcom/sm8150-google-coral.dts" > "$OUT/coral-fec.pre.dts"
    dtc -q -@ -I dts -O dtb -o "$OUT/coral-fec-base.dtb" "$OUT/coral-fec.pre.dts"
    : > "$OUT/dtb-12"
    for pair in \
        "20000 51405" "20000 60a05" "20000 50a05" "20000 60b05" \
        "20000 61405" "20000 60105" "10000 50005" "20000 50105" \
        "20000 60205" "20000 50b05" "20000 51e05" "20000 61e05"; do
        msm=${pair% *}
        board=${pair#* }
        cp "$OUT/coral-fec-base.dtb" "$OUT/coral-fec-entry.dtb"
        fdtput -tx "$OUT/coral-fec-entry.dtb" / qcom,msm-id 153 "$msm"
        fdtput -tx "$OUT/coral-fec-entry.dtb" / qcom,board-id "$board" 0
        cat "$OUT/coral-fec-entry.dtb" >> "$OUT/dtb-12"
    done
    rm -f "$OUT/coral-fec-entry.dtb"
    sha256sum "$OUT/dtb-12"
fi
