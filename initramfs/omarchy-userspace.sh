#!/bin/busybox sh
# SPDX-License-Identifier: MIT
# Sourced by PID 1. Phone partitions stay kernel-read-only; writes land in RAM.
say 'preparing Omarchy on a read-only userdata lower layer'
if grep -q google,coral /sys/firmware/devicetree/base/compatible; then
    set -- /sys/bus/platform/drivers/qcom-pon/*/coral_recovery_reason
    [ "$#" = 1 ] && [ -r "$1" ] && [ "$(cat "$1")" = 2 ] ||
        fail 'kernel Fastboot recovery latch is not armed'
fi
mkdir -p /lower /newroot /run/overlay/upper /run/overlay/work
# USB and UFS enumerate independently. A one-shot findfs can reboot a healthy
# kernel before its userdata partition appears (covered by the QEMU hotplug test).
# timeout-policy: PROBE (six intervals, inside init's overall recovery deadline)
i=0
until DEV=$(findfs LABEL=omarchy-root 2>/dev/null); do
    [ "$i" -lt "$((T_PROBE * 6))" ] || fail 'Omarchy root label absent after storage deadline'
    [ "$i" != 0 ] || say 'waiting for Omarchy storage enumeration'
    sleep 1
    i=$((i + 1))
done
[ -b "$DEV" ] || fail 'Omarchy root is not a block device'
blkid "$DEV" | grep -q ' TYPE="ext4"' || fail 'Omarchy root is not ext4'
# Guard every physical storage device, including raw disks, before systemd starts.
for device in /dev/sd* /dev/vd* /dev/mmcblk*; do
    [ ! -b "$device" ] || blockdev --setro "$device"
done
[ "$(blockdev --getro "$DEV")" = 1 ] || fail 'userdata read-only guard failed'
mount -t ext4 -o ro,noload "$DEV" /lower || fail 'read-only userdata mount failed'
mount -t overlay overlay -o lowerdir=/lower,upperdir=/run/overlay/upper,workdir=/run/overlay/work /newroot
[ -x /newroot/usr/lib/systemd/systemd ] || fail 'systemd missing from userdata'
mkdir -p /newroot/lower
mount --bind /lower /newroot/lower
for path in proc sys dev run; do
    mkdir -p "/newroot/$path"
    mount --rbind "/$path" "/newroot/$path"
    mount --make-rslave "/newroot/$path"
done
mkdir -p /newroot/tmp /newroot/root/.ssh /newroot/etc/ssh /newroot/etc/systemd/system/sshd.service.d
chmod 700 /newroot/root/.ssh
cp /coral-keys/client.pub /newroot/root/.ssh/authorized_keys
chmod 600 /newroot/root/.ssh/authorized_keys
cp /coral-keys/host /newroot/etc/ssh/ssh_host_ed25519_key
chmod 600 /newroot/etc/ssh/ssh_host_ed25519_key
# Unlock only the RAM copy of root's account; password and keyboard auth stay off.
sed 's/^root:[^:]*:/root::/' /lower/etc/shadow > /newroot/etc/shadow
chmod 600 /newroot/etc/shadow
: > /newroot/etc/fstab
cat > /newroot/run/coral-sshd_config <<'SSH'
Port 22
ListenAddress 172.16.42.1
HostKey /etc/ssh/ssh_host_ed25519_key
AuthorizedKeysFile /root/.ssh/authorized_keys
PermitRootLogin prohibit-password
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitEmptyPasswords no
UsePAM no
AllowUsers root
Subsystem sftp /usr/lib/ssh/sftp-server
SSH
cat > /newroot/etc/systemd/system/sshd.service.d/coral.conf <<'UNIT'
[Service]
Type=simple
ExecStart=
ExecStart=/usr/bin/sshd -D -e -f /run/coral-sshd_config
UNIT
# Keep the initramfs gadget/address, and prevent writes and watchdog-stopping sleep.
for unit in usb-gadget.service systemd-networkd.service tailscaled.service pd-mapper.service \
    systemd-fsck-root.service systemd-growfs-root.service fstrim.timer \
    sleep.target suspend.target hibernate.target hybrid-sleep.target; do
    ln -sf /dev/null "/newroot/etc/systemd/system/$unit"
done
coral_radio() {
    cp -a /coral-radio/usr/. /newroot/usr/ || return $?
    cp -a /coral-radio/etc/. /newroot/etc/ || return $?
    # Assert the installed lower's existing USB exclusion before starting NM.
    grep -q '^unmanaged-devices=interface-name:usb0$' \
        /newroot/etc/NetworkManager/conf.d/10-coral.conf || return $?
    grep -Eq '^ExecStart=/usr/bin/rmtfs -r( |$)' \
        /newroot/usr/lib/systemd/system/rmtfs.service || return $?
    mkdir -p /newroot/etc/systemd/system/multi-user.target.wants || return $?
    for unit in iwd.service rmtfs.service tqftpserv.service NetworkManager.service; do
        ln -sf "/usr/lib/systemd/system/$unit" "/newroot/etc/systemd/system/$unit" || return $?
        ln -sf "/usr/lib/systemd/system/$unit" "/newroot/etc/systemd/system/multi-user.target.wants/$unit" || return $?
    done
    # PARTNAME, never a guessed disk number; vfat lower and every symlink stay RO.
    MODEM=''
    for part in /sys/class/block/*; do
        if grep -qx 'PARTNAME=modem_a' "$part/uevent"; then
            [ -z "${MODEM:-}" ] || return 1
            MODEM="/dev/${part##*/}"
        fi
    done
    [ -b "${MODEM:-}" ] || return 1
    mkdir -p /newroot/run/coral-modem || return $?
    mount -t vfat -o ro,nodev,nosuid,noexec "$MODEM" /newroot/run/coral-modem || return $?
    if [ "$(sha256sum /newroot/run/coral-modem/image/modem.mdt | cut -d ' ' -f 1)" != \
         "$(cat /coral-radio/modem.sha256)" ]; then
        say 'radio: modem hash mismatch'
        return 1
    fi
    FW=/newroot/usr/lib/firmware/updates/qcom/sm8150/google/coral
    mkdir -p "$FW" || return $?
    for file in /newroot/run/coral-modem/image/modem.* /newroot/run/coral-modem/image/qdsp6m.qdb; do
        [ -f "$file" ] || return 1
        ln -sf "/run/coral-modem/image/${file##*/}" "$FW/${file##*/}" || return $?
    done
    say 'radio: firmware mounted read-only; RAM modules and services ready'
}
# This function is deliberately conditional: radio failure must not trip init's
# EXIT trap and reboot a healthy USB/touch/GPU boot. Every failing step returns.
coral_radio || say "radio: $?"
mkdir -p /newroot/run/sshd
# Reset inherited extra listeners in RAM, including the stale Docker bridge
# address. The normal loopback DNS stub remains available to local clients.
mkdir -p /newroot/etc/systemd/resolved.conf.d
cat > /newroot/etc/systemd/resolved.conf.d/99-coral.conf <<'RESOLVED'
[Resolve]
DNSStubListenerExtra=
RESOLVED
cp /coral-build-id /newroot/run/coral-build-id
# The pinned touch shell is staged offline; no network/package transaction at
# boot. Copy into the existing RAM overlay, never into the read-only lower.
if [ -d /coral-mobile ]; then
    cp -a /coral-mobile/. /newroot/ || fail 'mobile RAM payload copy failed'
    chroot /newroot /usr/bin/usermod -aG input "${OMARCHY_INSTALL_USER:-omarchy}" || fail 'mobile input group failed'
    chroot /newroot /usr/bin/env OMARCHY_INSTALL_USER="${OMARCHY_INSTALL_USER:-omarchy}" /usr/bin/omarchy-apply-lock ||
        fail 'mobile lock PAM setup failed'
    # Firmware is linked before systemd's module loader probes hci_uart.
    # A BT failure is visible and leaves the proven desktop/recovery usable.
    chroot /newroot /usr/local/bin/coral-vendor --mount || say "vendor: $?"
fi
# Reassert every physical guard after the radio mount, immediately before PID 1.
for device in /dev/sd* /dev/vd* /dev/mmcblk*; do
    [ ! -b "$device" ] || blockdev --setro "$device"
done
say "Omarchy lower=$DEV ro,noload; overlay upper in RAM; starting systemd"
# chroot retains the original rescue root for the watchdog and bounded lease.
# switch_root would delete their reboot helper and device paths.
exec chroot /newroot /usr/lib/systemd/systemd --unit=graphical.target
