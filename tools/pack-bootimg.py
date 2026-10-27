#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Derive a bounded, read-only Omarchy boot from the USB-proven rescue image."""
import argparse
import gzip
import hashlib
import importlib.util
import json
import lzma
import os
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import tempfile

WORK = Path(os.environ.get('CORAL_WORK', 'work')) / 'ramtest/rescue-safe'
RELEASE = '6.17.0-sm8150'
RADIO_MODULES = {
    'algif_hash', 'algif_skcipher', 'ath', 'ath10k_core', 'ath10k_snoc',
    'bluetooth', 'btbcm', 'btqca', 'camcc-sm8150', 'cfg80211', 'coral-cs40l2x', 'ecc', 'ecdh_generic',
    'hci_uart', 'leds-qcom-flash', 'libarc4', 'mac80211', 'pwrseq-core',
    'qcom_common', 'qcom_glink_smem',
    'qcom_pd_mapper', 'qcom_pil_info', 'qcom_q6v5', 'qcom_q6v5_pas',
    'qcom_sysmon', 'qrtr', 'qrtr-smd', 'rfkill', 'rtc-pm8xxx',
}
RADIO_DRIVERS = ('ath10k_snoc', 'qcom_q6v5_pas', 'qrtr_smd',
                 'qcom_pd_mapper', 'algif_hash', 'algif_skcipher',
                 'hci_uart', 'leds-qcom-flash', 'coral-cs40l2x', 'rtc-pm8xxx', 'camcc-sm8150')
AUDIO_DRIVERS = ('q6core', 'q6afe', 'q6afe_dai', 'q6asm', 'q6asm_dai',
                 'q6adm', 'q6routing', 'snd_soc_cs35l36', 'snd_soc_sm8150', 'spidev')
AUDIO_MODULES = {
    'q6core', 'q6afe', 'q6afe-dai', 'q6asm', 'q6asm-dai', 'q6adm', 'q6routing',
    'soundcore', 'snd', 'snd-timer', 'snd-pcm', 'snd-compress', 'snd-q6dsp-common',
    'snd-soc-core', 'snd-soc-cs35l36', 'snd-soc-qcom-common', 'soundwire-bus',
    'snd-soc-sm8150', 'spidev',
}
CAMERA_DRIVERS = ('i2c_qcom_cci', 'qcom_camss', 'ov7251', 'imx363', 'imx481', 'imx520', 'at24')
CAMERA_MODULES = {
    'i2c-qcom-cci', 'qcom-camss', 'ov7251', 'imx363', 'imx481', 'imx520', 'at24',
    'mc', 'videodev', 'v4l2-async', 'v4l2-fwnode', 'v4l2-cci', 'videobuf2-common',
    'videobuf2-v4l2', 'videobuf2-memops', 'videobuf2-dma-sg',
}


def run(*args, **kwargs):
    # timeout-policy: PROBE
    return subprocess.check_output(list(map(str, args)), timeout=10, **kwargs)


def startup_script(source, expected):
    """Require the reviewed source, rather than trusting a previously staged copy."""
    if source is None or expected is None:
        raise ValueError('Building requires --startup-script and --startup-sha256')
    source = Path(source)
    if not source.is_absolute() or source.is_symlink() or not source.is_file():
        raise ValueError('Startup source must be an absolute regular file, not a symlink')
    data = source.read_bytes()
    if len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected):
        raise ValueError('Startup SHA256 must be 64 lowercase hexadecimal characters')
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('Startup source does not match the reviewed SHA256')
    return data


def stage_startup(data):
    target = WORK / 'omarchy-userspace.sh'
    if target.exists() and target.read_bytes() != data:
        previous = target.read_bytes()
        backup = target.with_name(target.name + '.before-' + hashlib.sha256(previous).hexdigest())
        if backup.exists():
            assert backup.read_bytes() == previous, 'Startup backup changed'
        else:
            shutil.copy2(target, backup)
    with tempfile.NamedTemporaryFile(dir=WORK, prefix='.omarchy-userspace-', delete=False) as staged:
        staged.write(data)
        staged_path = Path(staged.name)
    staged_path.chmod(0o644)
    staged_path.replace(target)


def verify_touch_readonly(system_map, dtb, out):
    forbidden = {'fwupdate_store', 'autotune_store', 'stm_fts_cmd_store',
                 'infoblock_getdata_show'}
    symbols = {line.split()[-1] for line in system_map.read_text().splitlines() if line.split()}
    assert not forbidden & symbols, 'Touch maintenance handlers remain compiled'
    spec = importlib.util.spec_from_file_location(
        'matched', Path(__file__).with_name('pixel4xl_rescue_matched.py'))
    matched = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(matched)
    trees = matched.split_dtbs(dtb)
    assert trees, 'No DTB trees'
    node = '/soc@0/geniqup@8c0000/spi@890000/touchscreen@0'
    for i, tree in enumerate(trees):
        path = out / f'touch-guard-{i}.dtb'
        path.write_bytes(tree)
        assert run('fdtget', '-ts', path, node, 'compatible').strip() == b'st,fts'
        assert run('fdtget', path, node, 'st,disable-auto-fw-update').strip() == b''
    print(f'FTS_PACK_GUARDS_DONE: maintenance symbols absent; {len(trees)} DTBs guarded', flush=True)


def radio_payload(root, existing):
    """Copy only the measured closure; modem segments stay on the RO partition."""
    stage = WORK / 'modules-stage'
    source = WORK.parents[1] / 'daily/radio-overlay'
    radio = root / 'coral-radio'
    manifest = json.loads((WORK.parents[1] / 'omamobile/manifest.json').read_text())
    sensors = manifest.get('sensors', False)
    assert type(sensors) is bool, 'Invalid sensor profile declaration'
    audio = manifest.get('audio', False)
    assert type(audio) is bool, 'Invalid audio profile declaration'
    cameras = manifest.get('cameras', False)
    assert type(cameras) is bool, 'Invalid camera profile declaration'
    drivers = (RADIO_DRIVERS + (('fastrpc',) if sensors else ())
               + (AUDIO_DRIVERS if audio else ()) + (CAMERA_DRIVERS if cameras else ()))
    expected_modules = (RADIO_MODULES | ({'fastrpc'} if sensors else set())
                        | (AUDIO_MODULES if audio else set()) | (CAMERA_MODULES if cameras else set()))
    dependencies = run('modprobe', '-C', '/dev/null', '-a', '-S', RELEASE, '-d', stage,
                       '--show-depends', *drivers).decode().splitlines()
    modules = {Path(line.split()[1]) for line in dependencies if line.startswith('insmod ')}
    # hci_qca is linked into hci_uart; include its measured btqca closure.
    assert len(modules) == len(expected_modules) and {p.stem for p in modules} == expected_modules, 'Radio module closure changed'
    files = {}
    for path in modules:
        relative = path.relative_to(stage / 'lib/modules' / RELEASE)
        assert '..' not in relative.parts and path.is_file()
        files[Path('usr/lib/modules') / RELEASE / relative] = path
    for name in ('modules.order', 'modules.builtin', 'modules.builtin.modinfo'):
        files[Path('usr/lib/modules') / RELEASE / name] = stage / 'lib/modules' / RELEASE / name
    for name in ('regulatory.db', 'regulatory.db.p7s'):
        files[Path('usr/lib/firmware') / name] = Path('/usr/lib/firmware') / name
    files[Path('usr/lib/firmware/updates/ath10k/WCN3990/hw1.0/board-2.bin')] = (
        source / 'usr/lib/firmware/ath10k/WCN3990/hw1.0/coral/board-2.bin')
    for path in ('usr/local/bin/tqftpserv', 'etc/systemd/system/tqftpserv.service.d/coral-mbn.conf'):
        files[Path(path)] = source / path
    mbn = source / 'usr/lib/firmware/qcom/sm8150/google/coral/mbn'
    assert mbn.is_dir() and any(mbn.rglob('*.mbn')), 'MCFG payload missing'
    for path in mbn.rglob('*'):
        if path.is_file():
            files[Path('usr/lib/firmware/updates/qcom/sm8150/google/coral/mbn') / path.relative_to(mbn)] = path
    for relative, path in files.items():
        dest = radio / relative
        if not existing:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
        assert dest.read_bytes() == path.read_bytes(), f'Stale radio payload: {relative}'
    packed = set((radio / 'usr/lib/modules' / RELEASE).rglob('*.ko'))
    assert len(packed) == len(expected_modules) and {p.stem for p in packed} == expected_modules
    for path in packed:
        assert run('modinfo', '-F', 'vermagic', path).decode().strip() == (
            RELEASE + ' SMP preempt mod_unload aarch64'), f'Mismatched module: {path}'
    expected = hashlib.sha256((WORK.parents[1] / 'daily/modem/fw/modem.mdt').read_bytes()).hexdigest()
    if not existing:
        (radio / 'modem.sha256').write_text(expected + '\n')
        (radio / 'lib').symlink_to('usr/lib')
        run('depmod', '-b', radio, RELEASE)
        load = radio / 'etc/modules-load.d/coral-radio.conf'
        load.parent.mkdir(parents=True, exist_ok=True)
        load.write_text('\n'.join(drivers) + '\n')
    assert (radio / 'etc/modules-load.d/coral-radio.conf').read_text() == '\n'.join(drivers) + '\n', 'Module load roots changed'
    assert (radio / 'modem.sha256').read_text().strip() == expected
    resolved = run('modprobe', '-C', '/dev/null', '-a', '-S', RELEASE, '-d', radio,
                   '--show-depends', *drivers).decode().splitlines()
    assert {Path(line.split()[1]).resolve() for line in resolved if line.startswith('insmod ')} == {
        path.resolve() for path in packed}, 'Packed depmod closure is incomplete'
    assert not list(radio.rglob('modem.b*')), 'Modem segments must not be packed'
    print(f'RADIO_PACK_PROOF_DONE: {len(packed)} exact-release modules; MCFG; regulatory DB; modem={expected}', flush=True)


def pack_ramdisk(archive, config):
    # XZ fits the licensed face models in boot_a; the accepted kernel must support it.
    if 'CONFIG_RD_XZ=y' not in config.splitlines():
        raise ValueError('Exact kernel must support XZ initramfs')
    return lzma.compress(archive, preset=6, check=lzma.CHECK_CRC32)


def unpack_ramdisk(data):
    # Retain verification of older gzip images and the legacy artifact pathname.
    return gzip.decompress(data) if data.startswith(b'\x1f\x8b') else lzma.decompress(data)


def boot_budget(image):
    """Check actual packed bytes against AVB's maximum, before padding to boot_a."""
    partition = 67_108_864
    maximum = int(run('avbtool', 'add_hash_footer', '--partition_size', partition,
                      '--calc_max_image_size').strip())
    size = image.stat().st_size
    with image.open('rb') as stream:
        stream.seek(-64, 2)
        footer = stream.read(64)
    if footer[:4] == b'AVBf':
        size = struct.unpack_from('>Q', footer, 12)[0]
    if not 0 < size <= maximum:
        raise ValueError(f'boot_a budget exceeded: packed={size}, maximum={maximum}')
    receipt = {'partition_bytes': partition, 'avb_maximum_payload_bytes': maximum,
               'packed_payload_bytes': size, 'spare_bytes': maximum - size,
               'kernel_bytes': (WORK / 'Image.omarchy.offset80000.lz4').stat().st_size,
               'ramdisk_bytes': (WORK / 'omarchy.cpio.gz').stat().st_size}
    (WORK / 'boot-budget.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('BOOT_BUDGET: ' + json.dumps(receipt), flush=True)
    return receipt


def protect_runtime_mount(init):
    old = 'mount -t tmpfs tmpfs /run\n'
    secure = 'mount -t tmpfs -o mode=0755 tmpfs /run\n'
    if init.count(old) + init.count(secure) != 1:
        raise ValueError('Require one explicit private runtime mount')
    return init.replace(old, secure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-existing', action='store_true')
    parser.add_argument('--startup-script', type=Path)
    parser.add_argument('--startup-sha256')
    args = parser.parse_args()
    existing = args.verify_existing
    if existing:
        if args.startup_script is not None or args.startup_sha256 is not None:
            raise ValueError('--verify-existing uses the already staged startup script')
        startup = (WORK / 'omarchy-userspace.sh').read_bytes()
    else:
        startup = startup_script(args.startup_script, args.startup_sha256)
    image = WORK / 'boot-omarchy.img'
    root = WORK / 'initramfs-omarchy'
    config = (WORK.parents[1] / 'out-omarchy-safe/.config').read_text()
    assert 'CONFIG_CMDLINE_FORCE=y\n' in config
    for setting in ('CONFIG_SPI_QCOM_GENI=y', 'CONFIG_DRM_PANEL_SAMSUNG_S6E3HC2=y',
                    '# CONFIG_LOCALVERSION_AUTO is not set'):
        assert setting + '\n' in config
    assert (WORK.parents[1] / 'out-omarchy-safe/include/config/kernel.release').read_text().strip() == '6.17.0-sm8150'
    assert 'msm.separate_gpu_kms=' not in config, 'MDSS requires the shared GPU/KMS device'
    for flag in ('panic=10', 'panic_on_oops=1', 'softlockup_panic=1', 'hung_task_panic=1'):
        assert flag in config
    raw = bytearray((WORK.parents[1] / 'out-omarchy-safe/arch/arm64/boot/Image').read_bytes())
    assert raw[56:60] == b'ARMd'
    assert b'coral Fastboot recovery armed before userspace' in raw
    assert b'coral fts flash-write guard: cfgAfeVer=' in raw
    struct.pack_into('<Q', raw, 8, 0x80000)
    if not existing:
        if image.exists() or root.exists():
            raise FileExistsError('Refusing to overwrite an Omarchy candidate')
        stage_startup(startup)
        run('cp', '-a', WORK / 'initramfs', root)
        init = protect_runtime_mount((WORK / 'init').read_text())
        assert init.count('USB_TIMEOUT=$((T_PROBE * 12))') == 1
        init = init.replace('USB_TIMEOUT=$((T_PROBE * 12))', 'USB_TIMEOUT=$((T_PROBE * 30))')
        init = init.replace('( sleep "$USB_TIMEOUT"; fail "rescue lease expired" ) &',
                            '''( trap - EXIT HUP INT TERM
sleep "$USB_TIMEOUT"
while true; do
    # timeout-policy: PROBE (bounded USB/userspace recovery after resume)
    health_wait=0
    until [ "$(cat /sys/class/udc/*/state)" = configured ] &&
       [ "$(cat /proc/1/comm)" = systemd ] &&
       [ -s /run/sshd.pid ] &&
       [ "$(cat "/proc/$(cat /run/sshd.pid)/comm")" = sshd ] &&
       ip -4 addr show dev usb0 | grep -q 'inet 172.16.42.1/'; do
        [ "$health_wait" -lt "$T_PROBE" ] || fail "USB/userspace health deadline failed"
        [ "$health_wait" != 0 ] || say "USB/userspace health pending; retrying for $T_PROBE seconds"
        sleep 1
        health_wait=$((health_wait + 1))
    done
    for health in /sys/bus/platform/drivers/qcom-pon/*/coral_healthy; do
        [ ! -e "$health" ] || echo 1 > "$health"
    done
    touch /run/coral-usb-confirmed
    sleep "$T_PROBE"
done ) &''')
        assert init.count('while true; do\n    setsid') == 1
        init = init.replace('while true; do\n    setsid', '''( trap - EXIT HUP INT TERM
while true; do
    setsid sh -c 'exec sh +i </dev/ttyGS0 >/dev/ttyGS0 2>&1' || say 'serial not ready'
    sleep 1
done ) &
. /bin/omarchy-userspace
while true; do
    setsid''')
        (root / 'init').write_text(init)
        (root / 'bin/omarchy-userspace').write_bytes(startup)
        (root / 'coral-keys').mkdir(mode=0o700)
        for name in ('client.pub', 'host'):
            run('cp', WORK / 'coral-keys' / name, root / 'coral-keys' / name)
        radio_payload(root, existing=False)
        mobile_payload(root, existing=False)
        archive = subprocess.check_output(['cpio', '-o', '-H', 'newc'], cwd=root,
                                         input=run('find', '.', '-print', cwd=root), timeout=10)
        # A phone must identify its running payload; hashing a host pathname
        # after SSH connects cannot distinguish a stale userspace or another image.
        build_id = hashlib.sha256(raw + (WORK / 'boot-matched.img').read_bytes() + archive).hexdigest()
        (root / 'coral-build-id').write_text(build_id + '\n')
        archive = subprocess.check_output(['cpio', '-o', '-H', 'newc'], cwd=root,
                                         input=run('find', '.', '-print', cwd=root), timeout=10)
        config = (WORK.parents[1] / 'out-omarchy-safe/.config').read_text()
        (WORK / 'omarchy.cpio.gz').write_bytes(pack_ramdisk(archive, config))
        (WORK / 'Image.omarchy.offset80000').write_bytes(raw)
        run('lz4', '-9', '-q', WORK / 'Image.omarchy.offset80000', WORK / 'Image.omarchy.offset80000.lz4')
    else:
        radio_payload(root, existing=True)
        mobile_payload(root, existing=True)
    assert run('lz4', '-dc', WORK / 'Image.omarchy.offset80000.lz4') == raw
    with tempfile.TemporaryDirectory(dir=WORK) as tmp:
        out = Path(tmp)
        args = shlex.split(run('unpack_bootimg', '--boot_img', WORK / 'boot-matched.img',
                               '--out', out, '--format', 'mkbootimg').decode())
        kernel = (WORK / 'Image.omarchy.offset80000.lz4').read_bytes()
        dtb = (out / 'dtb').read_bytes()
        verify_touch_readonly(WORK.parents[1] / 'out-omarchy-safe/System.map', dtb, out)
        (out / 'kernel').write_bytes(kernel)
        (out / 'ramdisk').write_bytes((WORK / 'omarchy.cpio.gz').read_bytes())
        if not existing:
            run('mkbootimg', *args, '--output', image)
            boot_budget(image)
            run('avbtool', 'add_hash_footer', '--image', image, '--partition_size', '67108864',
                '--partition_name', 'boot', '--algorithm', 'NONE',
                '--prop', 'com.android.build.boot.os_version:13',
                '--prop', 'com.android.build.boot.fingerprint:google/coral/coral:13/TP1A.221005.002.B2/9382335:user/release-keys',
                '--prop', 'com.android.build.boot.security_patch:2022-10-05')
        boot_budget(image)
        header = run('unpack_bootimg', '--boot_img', image, '--out', out).decode()
        assert (out / 'kernel').read_bytes() == kernel
        assert (out / 'dtb').read_bytes() == dtb
        assert (out / 'ramdisk').read_bytes() == (WORK / 'omarchy.cpio.gz').read_bytes()
        for flag in ('panic=10', 'panic_on_oops=1', 'softlockup_panic=1', 'hung_task_panic=1'):
            assert flag in header
        assert image.stat().st_size == 67108864
        archive = unpack_ramdisk((out / 'ramdisk').read_bytes())
        entries = run('cpio', '-it', '--quiet', input=archive).decode().splitlines()
        assert './coral-keys/client' not in entries and 'coral-keys/client' not in entries
        init = run('cpio', '-i', '--to-stdout', 'init', input=archive)
        stage = run('cpio', '-i', '--to-stdout', 'bin/omarchy-userspace', input=archive)
        assert init == (root / 'init').read_bytes()
        assert protect_runtime_mount(init.decode()).encode() == init
        assert b'USB_TIMEOUT=$((T_PROBE * 30))' in init and b'coral-usb-confirmed' in init
        assert stage == startup == (WORK / 'omarchy-userspace.sh').read_bytes()
        print('STARTUP_PACK_PROOF_DONE:', hashlib.sha256(stage).hexdigest(), flush=True)
        extracted = out / 'extracted'
        extracted.mkdir()
        run('cpio', '-id', '--quiet', 'coral-radio/*', 'coral-mobile/*', input=archive, cwd=extracted)
        radio_payload(extracted, existing=True)
        mobile_payload(extracted, existing=True)
        assert run('cpio', '-i', '--to-stdout', 'coral-build-id', input=archive) == (root / 'coral-build-id').read_bytes()
        for guard in (b'blockdev --setro', b'mount -t ext4 -o ro,noload', b'upperdir=/run/'):
            assert guard in stage
        assert b'--unit=graphical.target' in stage and b'cp -a /coral-mobile/.' in stage
        (out / 'boot.img').symlink_to(image)
        run('avbtool', 'verify_image', '--image', out / 'boot.img')
    print('SHA256', hashlib.sha256(image.read_bytes()).hexdigest(), flush=True)
    print('OMARCHY_PAYLOAD_PROOF_DONE: forced kernel recovery args; unchanged DTB; guarded userdata; RAM overlay', flush=True)


def mobile_payload(root, existing):
    """Fail on missing, extra, changed or unsafe entries in the pinned overlay."""
    source = WORK.parents[1] / 'omamobile'
    manifest = json.loads((source / 'manifest.json').read_text())
    target = root / 'coral-mobile'
    if not existing:
        run('cp', '-a', source / 'payload', target)
    paths = {str(p.relative_to(target)) for p in target.rglob('*') if p.is_file() or p.is_symlink()}
    assert paths == set(manifest['files']), 'Mobile payload entry set changed'
    for relative, expected in manifest['files'].items():
        path = Path(relative)
        assert not path.is_absolute() and '..' not in path.parts, 'Unsafe mobile path'
        actual = target / path
        if 'link' in expected:
            assert actual.is_symlink() and os.readlink(actual) == expected['link']
        else:
            assert not actual.is_symlink()
            assert hashlib.sha256(actual.read_bytes()).hexdigest() == expected['sha256'], relative
            assert actual.stat().st_mode & 0o777 == expected['mode'], relative
    monitor = (target / 'home/omarchy/.config/hypr/monitors.lua').read_text()
    safety = manifest.get('safety_profile', False)
    assert type(safety) is bool, 'Invalid safety profile declaration'
    assert ('refresh_rate' in manifest) == ('inhibit_standby' in manifest), 'Incomplete mobile profile'
    rate = manifest.get('refresh_rate', 60 if safety else 90)
    inhibit = manifest.get('inhibit_standby', safety)
    assert type(rate) is int and rate in (60, 90), 'Invalid refresh rate'
    assert type(inhibit) is bool, 'Invalid standby declaration'
    assert not safety or (rate == 60 and inhibit), 'Unsafe safety profile'
    assert 'DSI-1' in monitor and f'"1440x3040@{rate}"' in monitor and 'scale = 3.2' in monitor
    assert f'MODE=1440x3040@{rate}\n' in (target / 'etc/omamobile/device/coral/device.conf').read_text()
    unit = (target / 'etc/systemd/system/coral-phone.service').read_text()
    assert unit.count('\nExecStartPre=/usr/bin/touch /run/coral-phone-inhibit\n') == int(inhibit), 'Standby service differs from manifest'
    audio = manifest.get('audio', False)
    assert type(audio) is bool, 'Invalid audio profile declaration'
    assert (target / 'etc/coral-phone/ia8508.conf').is_file() == audio, 'Audio configuration differs from manifest'
    if audio:
        assert (target / 'etc/coral-phone/alsa.conf').is_file(), 'Raw ALSA configuration missing'
        assert (target / 'etc/coral-phone/audio-firmware.sha256').is_file(), 'Audio firmware manifest missing'
        assert (target / 'etc/coral-phone/ucm2/ucm.conf').is_file(), 'Audio routing entry point missing'
        assert (target / 'etc/coral-phone/ucm2/Pixel4XL/HiFi.conf').is_file(), 'Audio routes missing'
        assert (target / 'usr/share/licenses/alsa-lib/COPYING').is_file(), 'ALSA license missing'
        assert (target / 'usr/share/licenses/alsa-lib/build-receipt.json').is_file(), 'ALSA provenance missing'
    soli = manifest.get('soli', False)
    assert type(soli) is bool, 'Invalid Soli profile declaration'
    gate = target / 'etc/coral-phone/soli.conf'
    assert (gate.exists() or gate.is_symlink()) == soli, 'Soli gate differs from manifest'
    if soli:
        assert audio and manifest.get('sensors') is True, 'Soli requires audio and sensors'
        assert gate.is_file() and not gate.is_symlink(), 'Soli gate must be a regular file'
        assert gate.read_bytes() == b'{"enabled":true}\n', 'Unexpected Soli gate content'
        assert gate.stat().st_mode & 0o777 == 0o600, 'Soli gate must be private'
        assert os.lstat(gate).st_uid == 0, 'Soli gate must be root-owned'
    cameras = manifest.get('cameras', False)
    assert type(cameras) is bool, 'Invalid camera profile declaration'
    if cameras:
        runtime = target / 'usr/share/licenses/libcamera/runtime-manifest.json'
        assert runtime.is_file(), 'Reviewed CPU camera runtime missing'
        assert json.loads(runtime.read_text())['binary']['sha256'] == manifest['files'][
            'usr/local/bin/coral-phone']['sha256'], 'Camera runtime differs from binary'
    assert json.loads((target / 'etc/omamobile/coral-pin.json').read_text()) == manifest['pin']
    print(f'MOBILE_PACK_PROOF_DONE: {len(paths)} pinned entries; RAM graphical session', flush=True)


if __name__ == '__main__':
    main()
