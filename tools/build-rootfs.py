#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Stage the pinned phone shell; never run upstream's phone installer."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

# The owner's private app launchers (phone_apps.py) are not published; without them the rootfs
# is the same image minus those launchers.
_apps_path = Path(__file__).with_name('phone_apps.py')
phone_apps = None
if _apps_path.exists():
    _apps_spec = importlib.util.spec_from_file_location('phone_apps', _apps_path)
    phone_apps = importlib.util.module_from_spec(_apps_spec)
    _apps_spec.loader.exec_module(phone_apps)

BASE = Path(os.environ.get('CORAL_WORK', 'work')) / 'omamobile'
HERE = Path(__file__).resolve().parent
SERVICES = HERE.parent / 'userspace/services'


def repo_file(name):
    candidate = HERE / name
    return candidate if candidate.exists() else SERVICES / name
LOWER = BASE / 'lower'
SOURCE = BASE / 'upstream'


def run(*args):
    subprocess.run(list(map(str, args)), check=True)


def copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def camera_runtime(manifest_path, digest, binary, output):
    """Stage only a reviewed ARM64 libcamera closure, including its IPA assets."""
    source = Path(manifest_path)
    if (not source.is_absolute() or source.resolve() != source or not source.is_file()
            or not re.fullmatch('[0-9a-f]{64}', digest)
            or hashlib.sha256(source.read_bytes()).hexdigest() != digest):
        raise ValueError('Require a reviewed camera runtime manifest')
    manifest = json.loads(source.read_text())
    if manifest.get('schema') != 1 or manifest.get('loader') != '/lib/ld-linux-aarch64.so.1':
        raise ValueError('Unexpected camera runtime schema or loader')
    if hashlib.sha256(binary.read_bytes()).hexdigest() != manifest['binary']['sha256']:
        raise ValueError('Camera runtime manifest identifies another coral-phone binary')
    files = manifest['files']
    if not isinstance(files, dict) or not files:
        raise ValueError('Camera runtime files missing')
    required = {'usr/local/lib/coral-camera/libcamera.so.0.7',
                'usr/local/lib/coral-camera/libcamera-base.so.0.7',
                'usr/local/lib/coral-camera/libcamera/ipa/ipa_soft_simple.so',
                'usr/local/lib/coral-camera/libcamera/soft_ipa_proxy',
                'usr/local/share/coral-camera/libcamera/ipa/simple/uncalibrated.yaml',
                'usr/share/licenses/libcamera/COPYING.rst'}
    if not required <= files.keys() or manifest.get('pipeline') != 'simple' or manifest.get('software_isp') != 'CPU':
        raise ValueError('Camera runtime requires the complete simple pipeline, CPU ISP and license')
    provided, private, elf_files = set(), set(), [binary]
    public_models = {'usr/local/share/coral-phone/face-models/' + name for name in (
        'face_detection_yunet_2023mar.onnx', 'face_recognition_sface_2021dec.onnx',
        'face_detection_yunet.LICENSE', 'face_recognition_sface.LICENSE')}
    for relative, entry in files.items():
        target = Path(relative)
        if (target.is_absolute() or '..' in target.parts or str(target) != relative
                or not (relative in public_models or any(relative.startswith(prefix) for prefix in (
                    'usr/local/lib/coral-camera/', 'usr/local/share/coral-camera/',
                    'usr/local/etc/coral-camera/', 'usr/share/licenses/libcamera/')))):
            raise ValueError('Unsafe camera runtime destination: ' + relative)
        path = Path(entry['path'])
        if (not path.is_absolute() or path.resolve() != path or not path.is_file()
                or not re.fullmatch('[0-9a-f]{64}', entry['sha256'])
                or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']
                or entry['mode'] not in (0o644, 0o755)):
            raise ValueError('Unreviewed camera runtime file: ' + relative)
        data = path.read_bytes()
        if data.startswith(b'\x7fELF'):
            if data[:6] != b'\x7fELF\x02\x01' or data[18:20] != b'\xb7\x00':
                raise ValueError('Camera runtime must contain ARM64 ELF files only')
            elf_files.append(path)
        if relative.startswith('usr/local/lib/coral-camera/'):
            provided.add(target.name)
            private.add(target.name)
        copy(path, output / target)
        (output / target).chmod(entry['mode'])
    base = manifest['base_dependencies']
    if 'ld-linux-aarch64.so.1' not in base:
        raise ValueError('Camera runtime loader must be pinned to the immutable rootfs')
    for soname, entry in base.items():
        relative = entry['destination']
        path = Path(relative)
        if (not re.fullmatch('[A-Za-z0-9_.+-]+', soname) or path.is_absolute()
                or '..' in path.parts or path.name != soname or not relative.startswith('usr/lib/')
                or Path(entry['path']) != (LOWER / relative).resolve()
                or not re.fullmatch('[0-9a-f]{64}', entry['sha256'])
                or hashlib.sha256((LOWER / relative).read_bytes()).hexdigest() != entry['sha256']):
            raise ValueError('Camera base library differs from the immutable rootfs: ' + relative)
        provided.add(soname)
    for path in elf_files:
        # timeout-policy: PROBE
        dynamic = subprocess.check_output(['readelf', '-d', path], text=True, timeout=10)
        needed = set(re.findall(r'Shared library: \[([^\]]+)\]', dynamic))
        if not needed <= provided:
            raise ValueError(f'Incomplete camera dynamic closure: {path}: {sorted(needed - provided)}')
        if needed & private and '/usr/local/lib/coral-camera' not in dynamic:
            raise ValueError('Camera ELF lacks the reviewed private library search path: ' + str(path))
        # timeout-policy: PROBE
        program = subprocess.check_output(['readelf', '-l', path], text=True, timeout=10)
        loaders = re.findall(r'Requesting program interpreter: ([^\]]+)\]', program)
        if loaders not in ([], ['/lib/ld-linux-aarch64.so.1']):
            raise ValueError('Unexpected camera ELF interpreter')
    copy(source, output / 'usr/share/licenses/libcamera/runtime-manifest.json')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--safety', action='store_true',
                        help='Baseline 60 Hz; inhibit unproved automatic standby')
    parser.add_argument('--refresh-rate', type=int, choices=(60, 90), default=90)
    parser.add_argument('--inhibit-standby', action='store_true')
    parser.add_argument('--sensors', action='store_true')
    parser.add_argument('--audio', action='store_true')
    parser.add_argument('--soli', action='store_true')
    parser.add_argument('--cameras', action='store_true')
    parser.add_argument('--camera-runtime', type=Path)
    parser.add_argument('--camera-runtime-sha256')
    parser.add_argument('--phone-apps', action='store_true')
    args = parser.parse_args()
    if args.soli and not (args.audio and args.sensors):
        raise ValueError('--soli requires --audio and --sensors')
    if bool(args.camera_runtime) != bool(args.camera_runtime_sha256) or (args.camera_runtime and not args.cameras):
        raise ValueError('A camera runtime requires --cameras and its reviewed SHA256')
    refresh = 60 if args.safety else args.refresh_rate
    inhibit = args.safety or args.inhibit_standby
    pin = json.loads((HERE / 'pin.json').read_text())
    for repo, commit in ((SOURCE, pin['commit']), (BASE / 'widgets', pin['widgets_commit'])):
        actual = subprocess.check_output(['git', '-c', f'safe.directory={repo}', '-C', str(repo),
                                          'rev-parse', 'HEAD'], text=True).strip()
        if actual != commit:
            raise ValueError('Source pin mismatch: ' + str(repo))
    if 'ro' not in subprocess.check_output(['findmnt', '-n', '-o', 'OPTIONS', str(LOWER)], text=True).strip().split(','):
        raise ValueError('The source rootfs must be mounted read-only')
    dependencies = json.loads((HERE / 'dependencies.json').read_text())
    expected = {package['file'] for package in dependencies}
    if {path.name for path in (BASE / 'pkgs').iterdir()} != expected:
        raise ValueError('Runtime package directory differs from the pinned inventory')
    for package in dependencies:
        path = BASE / 'pkgs' / package['file']
        if hashlib.sha256(path.read_bytes()).hexdigest() != package['sha256']:
            raise ValueError('Runtime package pin mismatch: ' + package['name'])
    # Runtime directories and generated config must be readable by the phone user,
    # even when the caller keeps its private build receipts under umask 077.
    os.umask(0o022)
    output = BASE / 'payload'
    output.mkdir()  # Preserve every previous build instead of overwriting it.
    stage = BASE / 'patch-root'
    stage.mkdir()
    shutil.copytree(LOWER / 'usr/share/omarchy', stage / 'usr/share/omarchy', symlinks=True)
    db = LOWER / 'var/lib/pacman/local'
    for package in db.glob('omarchy-[0-9]*'):
        shutil.copytree(package, stage / 'var/lib/pacman/local' / package.name)
    # Omarchy's bin symlinks are absolute. Copy their actual lower files inside
    # the isolated root; the upstream patcher rewrites them beneath --root.
    for link in (stage / 'usr/share/omarchy/bin').iterdir():
        if link.is_symlink():
            target = Path(os.readlink(link))
            if target.is_absolute():
                copy(LOWER / str(target).lstrip('/'), stage / str(target).lstrip('/'))
    for name in ('omamobile-shell', 'omamobile-omarchy'):
        run('bash', SOURCE / 'packages' / name / 'install', output)
    run('bash', SOURCE / 'packages/omamobile-firstboot/install', BASE / 'firstboot-artifact')
    run('bash', SOURCE / 'packages/omamobile-owl-widgets/install', output, BASE / 'widgets')
    patcher = SOURCE / 'packages/omamobile-omarchy/bin/omamobile-omarchy-patches'
    series = SOURCE / 'packages/omamobile-omarchy/patches'
    run('python3', patcher, 'apply', '--root', stage, '--series', series)
    run('python3', patcher, 'verify', '--root', stage)
    changed = []
    for top in ('usr/share/omarchy', 'usr/bin'):
        for path in (stage / top).rglob('*'):
            if path.is_file() and not path.is_symlink():
                relative = path.relative_to(stage)
                original = LOWER / relative
                if not original.exists() or original.read_bytes() != path.read_bytes():
                    copy(path, output / relative)
                    changed.append(str(relative))
    copy(LOWER / 'usr/bin/omarchy-system-lock', output / 'usr/bin/omarchy-system-lock')
    run('patch', '--batch', '--forward', '-p1', '-d', output, '-i', HERE / 'lock-off.patch')
    run('patch', '--batch', '--forward', '--fuzz=0', '-p1', '-d', output,
        '-i', HERE / 'battery-status.patch')
    # ALARM packages are pre-fetched with the snapshot repository SHA256.
    # Extract only usr/; package scripts never execute against this host.
    for package in sorted((BASE / 'pkgs').glob('*.pkg.tar.xz')):
        with tarfile.open(package) as archive:
            for member in archive:
                if member.name.startswith('usr/'):
                    archive.extract(member, output, filter='data')
    portal = output / 'etc/xdg/xdg-desktop-portal/hyprland-portals.conf'
    portal.write_text(portal.read_text().replace('FileChooser=gnome;gtk', 'FileChooser=gtk'))
    binary = BASE / 'coral-phone'
    elf = binary.read_bytes()
    if elf[:6] != b'\x7fELF\x02\x01' or elf[18:20] != b'\xb7\x00':
        raise ValueError('coral-phone must be an aarch64 ELF64 binary')
    if args.camera_runtime:
        camera_runtime(args.camera_runtime, args.camera_runtime_sha256, binary, output)
    elif 'INTERP' in subprocess.check_output(['readelf', '-l', binary], text=True):
        raise ValueError('coral-phone must be linked statically without a reviewed camera runtime')
    copy(binary, output / 'usr/local/bin/coral-phone')
    (output / 'usr/local/bin/coral-phone').chmod(0o755)
    for name in ('phone-edge', 'phone-rotate'):
        (output / 'usr/bin' / name).symlink_to('/usr/local/bin/coral-phone')
    copy(HERE / 'session-start.sh', output / 'usr/bin/coral-mobile-start')
    (output / 'usr/bin/coral-mobile-start').chmod(0o755)
    for source, name in (('vendor-runtime.sh', 'coral-vendor'),
                         ('phone-session.sh', 'coral-phone-session')):
        copy(repo_file(source), output / 'usr/local/bin' / name)
        (output / 'usr/local/bin' / name).chmod(0o755)
    copy(repo_file('coral-phone.service'), output / 'etc/systemd/system/coral-phone.service')
    if inhibit:
        unit = output / 'etc/systemd/system/coral-phone.service'
        unit.write_text(unit.read_text().replace('[Service]\n',
            '[Service]\nExecStartPre=/usr/bin/touch /run/coral-phone-inhibit\n', 1))
    wants = output / 'etc/systemd/system/graphical.target.wants'
    wants.mkdir(parents=True, exist_ok=True)
    (wants / 'coral-phone.service').symlink_to('/etc/systemd/system/coral-phone.service')
    # Direct, guarded Rust s2idle owns standby. The generic shell's unguarded
    # suspend menu remains disabled until the separate hardware wake proof.
    for name in ('wake.conf', 'charge.conf', 'haptic.conf'):
        if repo_file(name).exists():
            config = output / 'etc/coral-phone' / name
            copy(repo_file(name), config)
            config.chmod(0o644)
            os.chown(config, 0, 0)
    if args.audio:
        audio = HERE.parent / 'userspace/audio' if (HERE.parent / 'userspace/audio').exists() else HERE.parent / 'audio'
        config = output / 'etc/coral-phone/ia8508.conf'
        copy(audio / 'ia8508.conf', config)
        config.chmod(0o644)
        os.chown(config, 0, 0)
        copy(audio / 'alsa.conf', output / 'etc/coral-phone/alsa.conf')
        copy(audio / 'audio-firmware.sha256', output / 'etc/coral-phone/audio-firmware.sha256')
        shutil.copytree(audio / 'ucm2', output / 'etc/coral-phone/ucm2', dirs_exist_ok=True)
        copy(BASE / 'COPYING.alsa-lib', output / 'usr/share/licenses/alsa-lib/COPYING')
        copy(BASE / 'alsa-build-receipt.json',
             output / 'usr/share/licenses/alsa-lib/build-receipt.json')
    if args.sensors:
        for source, name in (('COPYING.coral-phone', 'COPYING'), ('NOTICE.coral-phone', 'NOTICE'),
                             ('LICENSE-BSD-3-Clause-Clear.coral-phone', 'LICENSE-BSD-3-Clause-Clear')):
            copy(BASE / source, output / 'usr/share/licenses/coral-phone' / name)
        rpc_pin = json.loads((HERE / 'sensor-rpc-pin.json').read_text())
        rpc = BASE.parent / 'sensors-rpc/reviewed-build/hexagonrpcd'
        if hashlib.sha256(rpc.read_bytes()).hexdigest() != rpc_pin['binary_sha256']:
            raise ValueError('hexagonrpcd differs from the reviewed static ARM64 build')
        elf = rpc.read_bytes()
        if elf[:6] != b'\x7fELF\x02\x01' or elf[18:20] != b'\xb7\x00':
            raise ValueError('hexagonrpcd must be an aarch64 ELF64 binary')
        if 'INTERP' in subprocess.check_output(['readelf', '-l', rpc], text=True):
            raise ValueError('hexagonrpcd must be linked statically')
        copy(rpc, output / 'usr/local/bin/hexagonrpcd')
        copy(BASE.parent / 'sensors-rpc/reviewed-build/COPYING.hexagonrpc',
             output / 'usr/share/licenses/hexagonrpc/COPYING')
        copy(repo_file('sensor-runtime.sh'), output / 'usr/local/bin/coral-sensors')
        for name in ('hexagonrpcd', 'coral-sensors'):
            (output / 'usr/local/bin' / name).chmod(0o755)
        for name in ('slpi.sha256', 'sensors.conf'):
            copy(repo_file(name), output / 'etc/coral-phone' / name)
        copy(repo_file('coral-hexagonrpcd.service'),
             output / 'etc/systemd/system/coral-hexagonrpcd.service')
        target = output / 'etc/systemd/system/multi-user.target.wants'
        target.mkdir(parents=True, exist_ok=True)
        (target / 'coral-hexagonrpcd.service').symlink_to('/etc/systemd/system/coral-hexagonrpcd.service')
    if args.soli:
        config = output / 'etc/coral-phone/soli.conf'
        with os.fdopen(os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as gate:
            gate.write('{"enabled":true}\n')
        os.chown(config, 0, 0)
    copy(HERE / 'device/coral/device.conf', output / 'etc/omamobile/device/coral/device.conf')
    device = output / 'etc/omamobile/device/coral/device.conf'
    device.write_text(device.read_text().replace('MODE=1440x3040@90\n', f'MODE=1440x3040@{refresh}\n'))
    copy(HERE / 'pin.json', output / 'etc/omamobile/coral-pin.json')
    home = output / 'home/omarchy'
    hypr = home / '.config/hypr'
    hypr.mkdir(parents=True)
    config = (LOWER / 'home/omarchy/.config/hypr/hyprland.lua').read_text()
    (hypr / 'hyprland.lua').write_text(config)
    (hypr / 'monitors.lua').write_text(
        'hl.env("GDK_SCALE", "2")\n'
        f'hl.monitor({{ output = "DSI-1", mode = "1440x3040@{refresh}", position = "0x0", scale = 3.2 }})\n')
    look = (LOWER / 'home/omarchy/.config/hypr/looknfeel.lua').read_text()
    (hypr / 'looknfeel.lua').write_text(look + '\n'
        'hl.config({ cursor = { invisible = true, hide_on_touch = true } })\n'
        'dofile("/usr/share/omamobile/shell/hypr/phone.lua")\n')
    (hypr / 'autostart.lua').write_text('o.exec_on_start("coral-mobile-start")\n')
    config_dir = home / '.config/omarchy'
    plugins = config_dir / 'plugins'
    plugins.mkdir(parents=True)
    profile = json.loads((output / 'usr/share/omamobile/shell/profile/shell.json').read_text())
    profile['bar']['showBatteryPercent'] = False
    # UPower's synthetic qcom capacity must never become a popup or warning.
    profile['disabledPlugins'] = list(dict.fromkeys(
        profile.get('disabledPlugins', []) + ['omarchy.battery', 'omarchy.power']))
    # Unproved hardware and the persistent updater are outside this RAM desktop.
    profile['plugins'] = [p for p in profile['plugins'] if p['id'] not in (
        'omamobile.fingerprint', 'omamobile.update')]
    (config_dir / 'shell.json').write_text(json.dumps(profile, indent=2) + '\n')
    for path in (output / 'usr/share/omamobile/shell/plugins').iterdir():
        if path.is_dir():
            (plugins / path.name).symlink_to('/usr/share/omamobile/shell/plugins/' + path.name)
    keyboard = home / '.local/share/squeekboard/keyboards/terminal'
    keyboard.mkdir(parents=True)
    (keyboard / 'us.yaml').symlink_to('/usr/share/omamobile/squeekboard/keyboards/terminal/us.yaml')
    toggles = home / '.local/state/omarchy/toggles'
    toggles.mkdir(parents=True)
    # Preserve the existing credential; no PIN, password or hash enters the payload.
    for toggle in ('lock-keypad', 'credential-password', 'suspend-off', 'lock-off'):
        (toggles / toggle).touch()
    done = home / '.local/state/omarchy/done'
    done.mkdir(parents=True)
    (done / 'welcome-keybindings-not-applicable').touch()
    for path in [home, *home.rglob('*')]:
        os.chown(path, 1000, 1000, follow_symlinks=False)
    # No session launch from upstream firstboot; getty -> bash_profile -> uwsm
    # is already installed. No upstream NFC service is enabled on coral.
    manifest = {'pin': pin, 'dependencies': dependencies, 'patched_omarchy': changed,
                'safety_profile': args.safety, 'refresh_rate': refresh,
                'inhibit_standby': inhibit, 'files': {}}
    manifest['sensors'] = args.sensors
    manifest['audio'] = args.audio
    manifest['soli'] = args.soli
    manifest['cameras'] = args.cameras
    manifest['phone_apps'] = args.phone_apps
    if args.phone_apps:
        if not args.camera_runtime:
            raise ValueError('Phone apps require their reviewed complete dynamic runtime')
        if phone_apps:
            phone_apps.stage(HERE, output)
    for path in sorted(output.rglob('*')):
        if path.is_symlink():
            manifest['files'][str(path.relative_to(output))] = {'link': os.readlink(path)}
        elif path.is_file():
            manifest['files'][str(path.relative_to(output))] = {
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'mode': path.stat().st_mode & 0o777, 'bytes': path.stat().st_size}
    (BASE / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    total = sum(v.get('bytes', 0) for v in manifest['files'].values())
    print(f'CORAL_MOBILE_BUILD_DONE: {len(manifest["files"])} entries, {total} file bytes', flush=True)


if __name__ == '__main__':
    main()
