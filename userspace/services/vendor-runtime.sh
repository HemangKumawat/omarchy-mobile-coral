#!/bin/bash
# SPDX-License-Identifier: MIT
# Measured stock slot-A vendor extents; expose firmware without copying it.
set -euo pipefail

vendor_firmware_check() {
    local source=$1 name
    for name in crbtfw21.tlv crnv21.bin cs40l25a.wmfw cs40l20.bin cs40l25a_exc.bin; do
        [[ -f "$source/$name" && ! -L "$source/$name" ]] || return 1
    done
    sha256sum -c <<EOF
8935c62aa9d0e0e27bafa1544772ba056983e11fc279069566a9d630962fafc9  $source/crbtfw21.tlv
36b04174032a566b9c042e4be3629c753da7693d311e5f7f387ff61da875c8fc  $source/crnv21.bin
0ee06cec8e77dc1541a0e24a57c9e27fc9f7495c1e812c921e4dc99c3501f554  $source/cs40l25a.wmfw
25753900c3127f6bdade4ddbc38ed2b79ad6e51760a3c2a7972e9196dfe4f538  $source/cs40l20.bin
7385034603d3612f6eee1a7ad7071cba7dfaf47bda728c147be4613984a369f0  $source/cs40l25a_exc.bin
EOF
}

vendor_audio_firmware() {
    local source=$1 manifest=$2 target=$3 digest name extra count=0
    local -A seen=()
    # Validate the complete stock set before publishing any firmware link.
    while read -r digest name extra; do
        [[ $digest =~ ^[0-9a-f]{64}$ && -z $extra &&
           $name =~ ^(adsp\.(mdt|b(0[0-9]|1[0-5]))|adsp(r|ua)\.jsn|RomeApp\.bin)$ ]] || return 1
        [[ ! ${seen[$name]+present} && -f "$source/$name" && ! -L "$source/$name" ]] || return 1
        seen[$name]=1
        printf '%s  %s\n' "$digest" "$source/$name" | sha256sum -c || return 1
        count=$((count + 1))
    done < "$manifest"
    [[ $count = 20 && ! -L $target ]] || return 1
    mkdir -p "$target" || return 1
    for name in "${!seen[@]}"; do
        ln -sf "$source/$name" "$target/$name" || return 1
    done
}

vendor_bluetooth_address() {
    local source=$1 address first
    [[ -f "$source" && ! -L "$source" && $(wc -c < "$source") = 18 ]] || return 1
    [[ $(tail -c 1 "$source" | od -An -tu1 | tr -d '[:space:]') = 0 ]] || return 1
    address=$(head -c 17 "$source")
    [[ $address =~ ^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$ ]] || return 1
    address=${address^^}
    [[ $address != 00:00:00:00:00:00 && ${address^^} != *00:00:5A:AD ]] || return 1
    first=${address:0:2}
    (( (16#$first & 1) == 0 )) || return 1
    printf '%s\n' "$address"
}

vendor_configure_bluetooth() {
    local address config missing info line actual changed=0 deadline last_error='' status
    # Stock coral's HAL reads this bootloader-provided ASCII property. The
    # upstream driver otherwise detects the generic NVM address as unconfigured.
    address=$(vendor_bluetooth_address "${1:-/sys/firmware/devicetree/base/chosen/cdt/cdb2/bt_addr}") || {
        echo 'bluetooth: missing or invalid factory public address' >&2
        return 1
    }
    # timeout-policy: PROBE; native MGMT configures volatile controller state.
    config=$(timeout "${T_PROBE:-10}" /usr/bin/btmgmt --index 0 config) || {
        echo 'bluetooth: controller configuration read failed' >&2
        return 1
    }
    if [[ $config != *'missing options:'* ]]; then
        echo 'bluetooth: controller configuration unavailable' >&2
        return 1
    fi
    missing=${config##*missing options:}
    missing=${missing%%$'\n'*}
    if [[ " $missing " =~ [[:space:]]public-address[[:space:]] ]]; then
        if ! timeout "${T_PROBE:-10}" /usr/bin/btmgmt --index 0 public-addr "$address"; then
            echo 'bluetooth: factory public-address configuration failed' >&2
            return 1
        fi
        changed=1
    fi
    deadline=$((SECONDS + ${T_PROBE:-10}))
    while :; do
        if info=$(timeout "${T_PROBE:-10}" /usr/bin/btmgmt --index 0 info 2>&1); then
            status=0
        else
            status=$?
            last_error="btmgmt info exited $status: $info"
            if [[ $changed = 1 && $SECONDS -lt $deadline ]]; then
                sleep 1
                continue
            fi
            printf 'bluetooth: controller information read failed: %s\n' "$last_error" >&2
            return 1
        fi
        actual=''
        while IFS= read -r line; do
            if [[ $line =~ ^[[:space:]]*addr[[:space:]]+([0-9A-Fa-f:]+)[[:space:]]+version[[:space:]] ]]; then
                actual=${BASH_REMATCH[1]^^}
            fi
        done <<< "$info"
        if [[ $actual = "$address" ]]; then
            echo 'bluetooth: controller public address matches bootloader factory property'
            return 0
        fi
        [[ -z $actual && $changed = 1 && $SECONDS -lt $deadline ]] || break
        sleep 1
    done
    echo 'bluetooth: controller public address does not match factory property' >&2
    [[ -z $last_error ]] || printf 'bluetooth: %s\n' "$last_error" >&2
    printf '%s\n' "$info" >&2
    return 1
}

vendor_main() {
    local part super='' prefix=/run/coral-super-prefix.bin
    for part in /sys/class/block/*; do
        if grep -qx 'PARTNAME=super' "$part/uevent"; then
            [[ -z "$super" ]] || { echo 'vendor: ambiguous super partition' >&2; return 1; }
            super="/dev/${part##*/}"
        fi
    done
    [[ -b "$super" && $(blockdev --getro "$super") = 1 ]]
    dd if="$super" of="$prefix" bs=4096 count=256 status=none
    # This exact 1MiB capture was parsed by lpdump slot0 (v10.1, 3 slots).
    # A changed OTA layout refuses to map, rather than guessing new offsets.
    echo "01d07ffb14fde93b12ef9ebfae0d513c7e38c63beae5b8e5afb8b5f031b6bca5  $prefix" | sha256sum -c
    [[ ! -e /dev/mapper/coral-vendor ]] || { echo 'vendor: mapper already exists' >&2; return 1; }
    # timeout-policy: PROBE (udev is not running in the initramfs).
    timeout "${T_PROBE:-10}" dmsetup create coral-vendor --readonly --noudevsync \
        --noudevrules --addnodeoncreate --table "$(cat <<EOF
0 1499136 linear $super 11133952
1499136 1024 linear $super 13312
1500160 1024 linear $super 174080
1501184 2048 linear $super 181248
1503232 118784 linear $super 257024
1622016 1024 linear $super 484352
1623040 59392 linear $super 1219584
1682432 5080 linear $super 1283072
EOF
)"
    dmsetup mknodes coral-vendor
    [[ $(blockdev --getro /dev/mapper/coral-vendor) = 1 ]]
    mkdir -p /run/coral-vendor
    mount -t ext4 -o ro,noload,nodev,nosuid,noexec /dev/mapper/coral-vendor /run/coral-vendor
    # A pending Android COW may exist. Only these byte-identical factory
    # files are consumed; journal replay and every disk write stay forbidden.
    vendor_firmware_check /run/coral-vendor/firmware
    local target=/usr/lib/firmware/updates/qca name directory
    mkdir -p "$target/coral"
    for name in crbtfw21.tlv crnv21.bin; do
        for directory in "$target" "$target/coral"; do
            ln -sf "/run/coral-vendor/firmware/$name" "$directory/$name"
        done
    done
    for name in cs40l25a.wmfw cs40l20.bin cs40l25a_exc.bin; do
        ln -sf "/run/coral-vendor/firmware/$name" "/usr/lib/firmware/updates/$name"
    done
    echo 'vendor: exact Bluetooth/haptic firmware linked from read-only stock partition'
    if [[ -f /etc/coral-phone/audio-firmware.sha256 ]]; then
        vendor_audio_firmware /run/coral-vendor/firmware /etc/coral-phone/audio-firmware.sha256 \
            /usr/lib/firmware/updates/qcom/sm8150/google/coral || {
            echo 'audio: stock ADSP/IA8508 firmware preparation failed' >&2
            return 1
        }
        echo 'audio: measured ADSP and IA8508 firmware linked from read-only vendor'
    fi
    if [[ -x /usr/local/bin/coral-sensors ]]; then
        /usr/local/bin/coral-sensors --prepare
    fi
}

if [[ ${BASH_SOURCE[0]} = "$0" ]]; then
    [[ $# = 1 ]] || { echo 'usage: coral-vendor --mount|--bt-address' >&2; exit 2; }
    case $1 in
        --mount) vendor_main ;;
        --bt-address) vendor_configure_bluetooth ;;
        *) echo 'usage: coral-vendor --mount|--bt-address' >&2; exit 2 ;;
    esac
fi
