#!/usr/bin/env python3
"""Match each mainline DTB to the factory board selector, avoiding broken no-op DTO.

ABL only merges an overlay when its hardware match weight exceeds the base DTB's.
The h2 driver trees are preserved while matching each factory board selector.
Kernel, ramdisk and recovery policy remain identical to boot-safe.
"""
import hashlib
from pathlib import Path
import re
import shlex
import struct
import subprocess
import sys
import tempfile

WORK = Path('/var/tmp/pixel4xl/ramtest/rescue-safe')
OVERLAY_SHA = 'b2fd720ac0b48260ac6024023c64f9afbadb80bd6c01799eb2f0caffa0b69722'


def run(*args, **kwargs):
    # timeout-policy: PROBE
    return subprocess.check_output(list(map(str, args)), timeout=10, **kwargs)


def split_dtbs(data):
    trees = []
    while data:
        if len(data) < 40 or data[:4] != bytes.fromhex('d00dfeed'):
            raise ValueError('Invalid concatenated FDT header')
        size = struct.unpack_from('>I', data, 4)[0]
        if not 40 <= size <= len(data):
            raise ValueError('Invalid FDT size')
        trees.append(data[:size])
        data = data[size:]
    return trees


def main():
    existing = sys.argv[1:] == ['--verify-existing']
    if sys.argv[1:] and not existing:
        raise ValueError('Only --verify-existing is supported')
    run('python3', '-I', WORK / 'pixel4xl_rescue_verify.py')
    image = WORK / 'boot-matched.img'
    if not existing and image.exists():
        raise FileExistsError(f'Refusing to replace {image}')
    overlay = (WORK.parent / 'dtbo-empty-matched.img').read_bytes()
    assert hashlib.sha256(overlay).hexdigest() == OVERLAY_SHA
    header = struct.unpack_from('>8I', overlay)
    assert header[:3] == (0xd7b7ab1e, 310838, 32) and header[3:6] == (32, 12, 32)
    with tempfile.TemporaryDirectory(dir=WORK) as tmp:
        out = Path(tmp)
        originals = {}
        for i, tree in enumerate(split_dtbs((WORK.parent / 'h2-coral-dt1/dtb').read_bytes())):
            path = out / f'original{i}.dtb'
            path.write_bytes(tree)
            originals[run('fdtget', '-tx', path, '/', 'qcom,msm-id').strip()] = path
        matched = []
        for i in range(header[4]):
            size, offset = struct.unpack_from('>II', overlay, 32 + i * 32)
            fragment = overlay[offset:offset + size]
            assert len(split_dtbs(fragment)) == 1
            ov = out / f'overlay{i}.dtbo'
            ov.write_bytes(fragment)
            msm = run('fdtget', '-tx', ov, '/', 'qcom,msm-id').strip()
            board = run('fdtget', '-tx', ov, '/', 'qcom,board-id').decode().split()
            assert len(board) == 2 and all(re.fullmatch('[0-9a-f]+', x) for x in board)
            original = originals[msm]
            path = out / f'matched{i}.dtb'
            path.write_bytes(original.read_bytes())
            run('fdtput', '-tx', path, '/', 'qcom,board-id', *board)
            # Semantic comparison proves that no driver or reserved-memory node changed.
            dts = lambda p: re.sub(rb'\s*qcom,board-id = [^;]+;', b'',
                                  run('dtc', '-q', '-I', 'dtb', '-O', 'dts', p))
            assert dts(path) == dts(original), i
            matched.append(path.read_bytes())
        dtb = b''.join(matched)
        args = shlex.split(run('unpack_bootimg', '--boot_img', WORK / 'boot-safe.img',
                               '--out', out, '--format', 'mkbootimg').decode())
        (out / 'dtb').write_bytes(dtb)
        if not existing:
            run('mkbootimg', *args, '--output', image)
            run('avbtool', 'add_hash_footer', '--image', image, '--partition_size', '67108864',
                '--partition_name', 'boot', '--algorithm', 'NONE',
                '--prop', 'com.android.build.boot.os_version:13',
                '--prop', 'com.android.build.boot.fingerprint:google/coral/coral:13/TP1A.221005.002.B2/9382335:user/release-keys',
                '--prop', 'com.android.build.boot.security_patch:2022-10-05')
        baseline_kernel, baseline_ramdisk = (out / 'kernel').read_bytes(), (out / 'ramdisk').read_bytes()
        run('unpack_bootimg', '--boot_img', image, '--out', out)
        assert image.stat().st_size == 67108864
        assert (out / 'kernel').read_bytes() == baseline_kernel
        assert (out / 'ramdisk').read_bytes() == baseline_ramdisk
        assert (out / 'dtb').read_bytes() == dtb
        (out / 'boot.img').symlink_to(image)
        run('avbtool', 'verify_image', '--image', out / 'boot.img')
    print('SHA256', hashlib.sha256(image.read_bytes()).hexdigest(), flush=True)
    print('MATCHED_OFFLINE_PROOF_DONE: only board selectors changed; 12 driver trees identical', flush=True)


if __name__ == '__main__':
    main()
