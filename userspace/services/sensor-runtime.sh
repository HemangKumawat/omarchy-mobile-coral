#!/bin/bash
# SPDX-License-Identifier: MIT
# Stock sensor firmware/calibration stay read-only; DSP scratch files live in RAM.
set -euo pipefail

sensor_firmware_check() {
    local source=$1 manifest=$2 digest name extra count=0
    local -A seen=()
    while read -r digest name extra; do
        [[ $digest =~ ^[0-9a-f]{64}$ && -z $extra && $name =~ ^slpi\.(mdt|b(0[0-9]|1[0-9]|2[0-2]))$ ]] || return 1
        [[ ! ${seen[$name]+present} ]] || return 1
        seen[$name]=1
        [[ -f "$source/$name" && ! -L "$source/$name" ]] || return 1
        printf '%s  %s\n' "$digest" "$source/$name" | sha256sum -c || return 1
        count=$((count + 1))
    done < "$manifest"
    [[ $count = 24 ]]
}

sensor_socinfo() {
    local output=$1 soc=$2 debug=$3 platform subtype version name
    platform=$(cat "$debug/hardware_platform")
    subtype=$(cat "$debug/hardware_platform_subtype")
    version=$(cat "$debug/platform_version")
    # Measured SMEM; Google kernel/msm 82a738b3 drivers/soc/qcom/socinfo.c names.
    [[ $platform = 5 && $subtype = 2 && $version =~ ^[0-9]{1,10}$ ]] &&
        (( 10#$version <= 4294967295 )) || {
        echo 'sensors: unsupported or invalid SMEM platform metadata' >&2; return 1;
    }
    [[ ! -e $output && ! -L $output ]] || return 1
    mkdir "$output"
    for name in soc_id revision; do
        [[ -f "$soc/$name" ]] || return 1
        ln -s "$soc/$name" "$output/$name"
    done
    printf 'OEM\n' > "$output/hw_platform"
    printf 'strange\n' > "$output/platform_subtype"
    printf '%s\n' "$subtype" > "$output/platform_subtype_id"
    printf '%s\n' "$version" > "$output/platform_version"
}

sensor_prepare() {
    local root=/run/coral-qcom vendor=/run/coral-vendor persist=/run/coral-persist
    local part found='' firmware=/usr/lib/firmware/updates/qcom/sm8150/google/coral name digest extra
    [[ $(id -u) = 0 ]] || { echo 'sensors: preparation requires root' >&2; return 1; }
    mountpoint -q "$vendor" || { echo 'sensors: read-only vendor mount missing' >&2; return 1; }
    [[ ,$(findmnt -n -o OPTIONS --target "$vendor"), = *,ro,* ]] || return 1
    sensor_firmware_check "$vendor/firmware" /etc/coral-phone/slpi.sha256 || {
        echo 'sensors: stock SLPI firmware differs from measured manifest' >&2; return 1;
    }
    for part in /sys/class/block/*; do
        if grep -qx 'PARTNAME=persist' "$part/uevent"; then
            [[ -z $found ]] || { echo 'sensors: ambiguous persist partition' >&2; return 1; }
            found="/dev/${part##*/}"
        fi
    done
    [[ -b $found && $(blockdev --getro "$found") = 1 ]] || return 1
    if ! mountpoint -q "$persist"; then
        [[ ! -L $persist ]] || return 1
        mkdir -p "$persist"
        mount -t ext4 -o ro,noload,nodev,nosuid,noexec "$found" "$persist"
    fi
    [[ $(findmnt -n -o SOURCE --target "$persist") = "$found" ]] || return 1
    [[ ,$(findmnt -n -o OPTIONS --target "$persist"), = *,ro,* ]] || return 1
    [[ ! -e $root && ! -L $root ]] || { echo 'sensors: runtime root already exists' >&2; return 1; }
    [[ -d "$persist/sensors/registry/registry" && -d "$vendor/dsp/sdsp" ]] || return 1
    mkdir -m 700 "$root"
    mkdir -p "$root/sensors" "$root/dsp" "$firmware"
    # Copy only calibration/registry, never firmware. This copy is inside /run.
    cp -a "$persist/sensors/registry/registry" "$root/sensors/registry"
    cp -a "$persist/sensors/registry/sns_reg_version" "$root/sensors/sns_reg_version"
    ln -s "$vendor/etc/sensors/config" "$root/sensors/config"
    ln -s "$vendor/dsp/sdsp" "$root/dsp/sdsp"
    mountpoint -q /sys/kernel/debug ||
        mount -t debugfs -o nodev,nosuid,noexec debugfs /sys/kernel/debug
    sensor_socinfo "$root/socinfo" /sys/devices/soc0 /sys/kernel/debug/qcom_socinfo
    while read -r digest name extra; do
        ln -s "$vendor/firmware/$name" "$firmware/$name"
    done < /etc/coral-phone/slpi.sha256
    touch /run/coral-sensors-ready
    echo 'sensors: measured SLPI linked; read-only persist registry copied into RAM'
}

if [[ ${BASH_SOURCE[0]} = "$0" ]]; then
    [[ $# = 1 && $1 = --prepare ]] || { echo 'usage: coral-sensors --prepare' >&2; exit 2; }
    sensor_prepare
fi
