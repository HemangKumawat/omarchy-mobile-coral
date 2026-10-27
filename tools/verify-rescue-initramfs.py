#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline payload, recovery policy and AVB proof for the RAM-only coral rescue."""
import gzip
import hashlib
import os
from pathlib import Path
import struct
import subprocess
import tempfile

BASE = Path(os.environ.get('CORAL_WORK', 'work'))
WORK = BASE / 'ramtest/rescue-safe'


def verify():
    image = WORK / 'boot-safe.img'
    assert image.stat().st_size == 67108864
    expected = bytearray((BASE / 'out-rescue-safe/arch/arm64/boot/Image').read_bytes())
    struct.pack_into('<Q', expected, 8, 0x80000)
    assert (WORK / 'Image.offset80000').read_bytes() == expected
    assert (WORK / 'Image.offset80000.lz4').read_bytes()[:4] == bytes.fromhex('04224d18')
    # timeout-policy: PROBE
    raw = subprocess.check_output(['lz4', '-dc', str(WORK / 'Image.offset80000.lz4')], timeout=10)
    assert raw == expected
    config = (BASE / 'out-rescue-safe/.config').read_text().splitlines()
    for name in ('QCOM_WDT', 'WATCHDOG_NOWAYOUT', 'OVERLAY_FS',
                 'SOFTLOCKUP_DETECTOR', 'DETECT_HUNG_TASK'):
        assert f'CONFIG_{name}=y' in config, name
    with tempfile.TemporaryDirectory(dir=WORK) as directory:
        out = Path(directory)
        # timeout-policy: PROBE
        header = subprocess.check_output(['unpack_bootimg', '--boot_img', str(image),
                                          '--out', directory], text=True, timeout=10)
        for flag in ('coral.rescue', 'panic=10', 'panic_on_oops=1',
                     'softlockup_panic=1', 'hung_task_panic=1'):
            assert flag in header, flag
        for name, original in {'kernel': WORK / 'Image.offset80000.lz4',
                               'ramdisk': WORK / 'initramfs.cpio.gz',
                               'dtb': BASE / 'ramtest/h1-symbols/dtb'}.items():
            assert (out / name).read_bytes() == original.read_bytes(), name
        archive = gzip.decompress((out / 'ramdisk').read_bytes())
        # timeout-policy: PROBE
        init = subprocess.check_output(['cpio', '-i', '--to-stdout', 'init'],
                                       input=archive, timeout=10)
        assert init == (WORK / 'init').read_bytes()
        assert b'mount -t ext4' not in init
        assert b'rescue lease expired' in init and b'/bin/reboot-bootloader' in init
        (out / 'boot.img').symlink_to(image)
        # timeout-policy: PROBE
        subprocess.run(['avbtool', 'verify_image', '--image', str(out / 'boot.img')],
                       check=True, timeout=10)
    print('PASS: payloads, watchdog config, recovery cmdline, read-only policy, AVB')
    print('SHA256', hashlib.sha256(image.read_bytes()).hexdigest())


if __name__ == '__main__':
    verify()
