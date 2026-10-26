#!/usr/bin/env bash
# Build kernel and DTB artifacts; preserve the existing kernel output and prepared images.
set -euo pipefail
TOOLCHAIN="$(readlink -f "$(dirname "${BASH_SOURCE[0]}")/pixel4xl_kernel_toolchain.py")"
python3 -I "$TOOLCHAIN" check
BASE=/var/tmp/pixel4xl
SRC=$BASE/kernel
OUT=$BASE/out-rescue-safe
WORK=$BASE/ramtest/rescue-safe
# Explicit source/output paths let the same recipe reproduce the untouched h1
# export before building h2. Never overwrite either evidence directory.
if [ "${1:-}" = --dtb ]; then
    [ "$#" = 3 ] && [[ "$2" = /* && "$3" = /* ]] || {
        echo 'usage: --dtb /absolute/kernel-source /absolute/new-output' >&2; exit 1;
    }
    SRC=$2
    DT_OUT=$3
    mkdir "$DT_OUT"
    python3 -I "$TOOLCHAIN" tool --source "$SRC" --output "$DT_OUT" --name cpp -- -nostdinc -I "$SRC/scripts/dtc/include-prefixes" -undef -D__DTS__ \
        -x assembler-with-cpp "$SRC/arch/arm64/boot/dts/qcom/sm8150-google-coral.dts" \
        > "$DT_OUT/coral.pre.dts"
    python3 -I "$TOOLCHAIN" tool --source "$SRC" --output "$DT_OUT" --name dtc -- -q -@ -I dts -O dtb -o "$DT_OUT/coral-v2.dtb" "$DT_OUT/coral.pre.dts"
    python3 -I "$TOOLCHAIN" tool --source "$SRC" --output "$DT_OUT" --name fdtput -- -tx "$DT_OUT/coral-v2.dtb" / qcom,board-id 0 0
    cp "$DT_OUT/coral-v2.dtb" "$DT_OUT/coral-v1.dtb"
    python3 -I "$TOOLCHAIN" tool --source "$SRC" --output "$DT_OUT" --name fdtput -- -tx "$DT_OUT/coral-v1.dtb" / qcom,msm-id 153 10000
    python3 -I "$TOOLCHAIN" tool --source "$SRC" --output "$DT_OUT" --name fdtput -- -tx "$DT_OUT/coral-v1.dtb" / qcom,board-id 0 0
    cat "$DT_OUT/coral-v2.dtb" "$DT_OUT/coral-v1.dtb" > "$DT_OUT/dtb"
    sha256sum "$DT_OUT/dtb"
    exit
fi
OMARCHY=0
DAILY=0
if [ "${1:-}" = --omarchy ] || [ "${1:-}" = --daily ]; then
    [ "$#" = 1 ] || { echo 'expected only one build mode' >&2; exit 1; }
    OMARCHY=1
    OUT=$BASE/out-omarchy-safe
    SRC=$BASE/kernel-display-dt1
    if [ "$1" = --daily ]; then
        DAILY=1
        SRC=$BASE/kernel-daily-20261019
        [ -d "$SRC" ] || { echo 'Preserved daily kernel worktree is missing' >&2; exit 1; }
    fi
    if [ ! -d "$SRC" ]; then
        git -c safe.directory="$BASE/kernel" -C "$BASE/kernel" worktree add --detach "$SRC" 5a951e901
    fi
elif [ "$#" != 0 ]; then
    echo 'only --omarchy, --daily or --dtb SOURCE OUTPUT is supported' >&2
    exit 1
fi
mkdir -p "$WORK"
df -h "$BASE"
if [ "$OMARCHY" = 1 ] && [ -e "$WORK/modules-stage" ]; then
    echo 'Preserve modules-stage before rebuilding; refusing stale module installation' >&2
    exit 1
fi
if [ "$DAILY" = 1 ]; then
    # The preserved merge contains all three proven guards. Do not reapply
    # their historical hunks over the newer panel/touch implementation.
    git -C "$SRC" merge-base --is-ancestor 472bb39eac2adea091a8ec681b6b904facc55d32 HEAD
    git -C "$SRC" diff --check
elif [ "$OMARCHY" = 1 ]; then
    for PATCH in "$WORK/qcom-pon-recovery.patch" "$WORK/coral-fts-readonly.patch" "$WORK/coral-dt1.patch"; do
        if patch --dry-run -R -p1 -d "$SRC" -i "$PATCH" >/dev/null 2>&1; then
            echo "$PATCH already applied"
        else
            patch --dry-run -p1 -d "$SRC" -i "$PATCH"
            patch -p1 -d "$SRC" -i "$PATCH"
        fi
    done
fi
if [ ! -d "$OUT" ]; then
    FROM=$BASE/out
    [ "$OMARCHY" != 1 ] || FROM=$BASE/out-rescue-safe
    cp -a --reflink=auto "$FROM" "$OUT"
fi
"$SRC/scripts/config" --file "$OUT/.config" \
    -d LOCALVERSION_AUTO \
    -e QCOM_WDT -e WATCHDOG_NOWAYOUT -e OVERLAY_FS \
    -e LOCKUP_DETECTOR -e SOFTLOCKUP_DETECTOR -e DETECT_HUNG_TASK \
    -e PANIC_ON_OOPS --set-val PANIC_TIMEOUT 10
# Factory ABL's fastboot module substitutes its own header command line.
if [ "$OMARCHY" = 1 ]; then
    "$SRC/scripts/config" --file "$OUT/.config" -e SPI_QCOM_GENI -e DRM_PANEL_SAMSUNG_S6E3HC2
fi
if [ "$DAILY" = 1 ]; then
    # Coral's PMIC RTC counter is not a Unix calendar. Keep alarm wake without
    # importing that counter into wall time or exporting time back to the PMIC.
    "$SRC/scripts/config" --file "$OUT/.config" -d RTC_HCTOSYS -d RTC_SYSTOHC
    # Expose the recorded wake IRQ and suspend diagnostics; logging stays off.
    "$SRC/scripts/config" --file "$OUT/.config" -e PM_DEBUG -e PM_ADVANCED_DEBUG -e QCOM_STATS -m LEDS_QCOM_FLASH \
        -m BT -m BT_QCA -m BT_HCIUART -e BT_HCIUART_QCA \
        -m RTC_DRV_PM8XXX -m SM_CAMCC_8150
fi
"$SRC/scripts/config" --file "$OUT/.config" -e CMDLINE_FORCE \
    --set-str CMDLINE "rootwait ro rdinit=/init console=ttyAMA0,115200 console=ttyMSM0,115200n8 console=tty0 clk_ignore_unused pd_ignore_unused loglevel=7 coral.rescue panic=10 panic_on_oops=1 softlockup_panic=1 hung_task_panic=1 hung_task_timeout_secs=30"
python3 -I "$TOOLCHAIN" make --source "$SRC" --output "$OUT" -- LOCALVERSION= olddefconfig
python3 -I "$TOOLCHAIN" make --source "$SRC" --output "$OUT" -- LOCALVERSION= -j8 Image
for setting in QCOM_WDT WATCHDOG_NOWAYOUT OVERLAY_FS SOFTLOCKUP_DETECTOR DETECT_HUNG_TASK; do
    rg -x "CONFIG_${setting}=y" "$OUT/.config"
done
if [ "$OMARCHY" = 1 ]; then
    rg -x 'CONFIG_SPI_QCOM_GENI=y' "$OUT/.config"
    rg -x 'CONFIG_DRM_PANEL_SAMSUNG_S6E3HC2=y' "$OUT/.config"
    python3 -I "$TOOLCHAIN" make --source "$SRC" --output "$OUT" -- LOCALVERSION= -j8 modules
    mkdir "$WORK/modules-stage"
    python3 -I "$TOOLCHAIN" make --source "$SRC" --output "$OUT" --output "$WORK/modules-stage" -- LOCALVERSION= \
        modules_install INSTALL_MOD_STRIP=1 INSTALL_MOD_PATH="$WORK/modules-stage"
fi
rg -x '# CONFIG_LOCALVERSION_AUTO is not set' "$OUT/.config"
test "$(cat "$OUT/include/config/kernel.release")" = 6.17.0-sm8150
sha256sum "$OUT/arch/arm64/boot/Image"
echo KERNEL_BUILD_DONE
