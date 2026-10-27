# What the phone runs, and what built it

Checked on 27 October 2026 against the image installed in `boot_a` of the development handset,
using the copy of that image kept on the build host. Each **proven** line is a byte or value
comparison, not a reconstruction.

## Public base

[The SM8150 kernel tree](https://gitlab.postmarketos.org/soc/qualcomm-sm8150/linux) at commit
`6963e3800a8e` ("power: supply: idtp9418: remove unused variable"). That is three commits past the
tag `v6.17.0-sm8150` (`379d8fe35c7c`); earlier notes named the tag with this commit's hash, which
was wrong.

The three public commits on `sm8150/6.17` between tag `v6.17.0-sm8150` (`379d8fe35c7c`) and `6963e3800a8e` are:
1. `53a8b55839d1` — `dts: qcom: sm8150: xiaomi-nabu: remove wakeup-source from lid gpio`
2. `01fc3dd3c831` — `input: touchscreen: fts_touch: fix compilation with LLVM`
3. `6963e3800a8e` — `power: supply: idtp9418: remove unused variable`

(`v0.2.1` listed `ac44cb016300` and `a2b20090fc1c` here; those ids are not in the public tree, and
the subjects given for them belong to commits before the tag. Checked against the GitLab API:
`53a8b55839d1`'s parent is `379d8fe35c7c`, `01fc3dd3c831`'s parent is `53a8b55839d1`, and
`6963e3800a8e`'s parent is `01fc3dd3c831`.)

## The installed boot image

| Part | Source | Status |
| --- | --- | --- |
| Kernel `Image`: `6.17.0-sm8150 #30 SMP PREEMPT Mon Oct 19 21:29:48 CEST 2026`, GCC 16.1.0, binutils 2.47 | `6963e3800a8e` + [`kernel/series/coral-30`](kernel/series/coral-30) (patches `0001`..`0007`) + [`kernel/series/coral-fec40357`](kernel/series/coral-fec40357) (patches `0008`..`0011`), config [`coral-30/config`](kernel/series/coral-30/config) (identical to `coral-fec40357/config` and to the build directory's `.config`) | **Proven** for the build output: it equals the installed `Image` except byte 10, the `text_offset` field that `tools/pack-bootimg.py` sets to `0x80000`. The build directory compiled a worktree whose content equals git tree `6d4115553ae5a9aec7b9e4ae23f77b2e4c4d7c4e` (patch `0011` was committed 27 minutes after the build). The installed `Image` contains strings from `0010`. `coral-30` alone (tree `21eb1828b205`) does not give this `Image`, because `0010` (`max77826-regulator.c`) and `0011` (`dsi_host.c`) change built-in drivers. `v0.2.2` and earlier said `coral-30` alone; that was wrong. |
| DTB: 12 entries, one per factory `dtbo` board selector | [`kernel/dts/`](kernel/dts) compiled against `6963e3800a8e` + `coral-30` + [`kernel/series/coral-fec40357`](kernel/series/coral-fec40357) (patches `0008`..`0011`: SLPI, audio, cameras, DSI clocks) | **Proven.** Applying `coral-fec40357` on top of `coral-30` gives git tree `6d4115553ae5a9aec7b9e4ae23f77b2e4c4d7c4e` exactly, and `tools/build-kernel.sh` reproduces all 12 installed DTB entries byte-for-byte with `dtc` 1.8.1 (`sha256: 3efe241aa349ff260ef0312e1b0a3a611943f71b0939261729c42e3842c90058`). |
| Loadable modules (cameras, audio, SLPI) | Built from the `coral-fec40357` tree (`6d4115553ae5`) | **Partly checked.** The staged `imx363.ko` and `fastrpc.ko` equal the debug-stripped build outputs. The staged `qcom-camss.ko` does not; it comes from a camera experiment variant. A full per-module manifest is still to do. |
| Loadable `coral-cs40l2x.ko` | Out-of-tree build of the Cirrus Logic `cs40l2x` driver (GPL-2.0; source commit not recorded) + [`kernel/patches/coral-cs40l2x-port.patch`](kernel/patches/coral-cs40l2x-port.patch) | **Not checked.** The base driver files are not published here. |
| Installed ramdisk | `tools/pack-bootimg.py` output (`boot-omarchy.img`, 21 Oct) with a second, uncompressed cpio appended by hand on 22 Oct | **Not reproducible from this repository.** The appended cpio replaces `/init` with `initramfs/init` and adds private network files (a Wi-Fi profile, Tailscale state, a userspace-mode Tailscale unit and an `sshd` on `127.0.0.1`) that are not published. `pack-bootimg.py` still embeds the older init (300 s lease, USB-configured check) and does not take `initramfs/init` as input. |
| `initramfs/init` | This repository | Equal to the installed init, except the SPDX line, the USB serial number (a parameter here) and one comment line. |
| `initramfs/omarchy-userspace.sh` | This repository | Equal to the installed script, except the user name, which is a parameter here (`OMARCHY_INSTALL_USER`). |
| `/usr/local/bin/coral-phone` | Prebuilt by `tools/build-rootfs.py` from a binary; the Rust source is not published yet | **Not checked.** |

A byte-exact rebuild of the `Image` from this repository has not been demonstrated yet. The build
host's compiler has since moved to GCC 16.2. `tools/build-kernel.sh` applies both series, sets the
banner timestamp and version used by `#30`, and reproduces the 12-entry `dtb-12` byte-for-byte. Its
default banner user and host (`builder@localhost`) differ from the installed banner, so a byte-exact
`Image` also needs `KBUILD_BUILD_USER`/`KBUILD_BUILD_HOST` set to the original values and GCC 16.1.0.

## Patch-to-commit mapping (`kernel/series/` and `kernel/patches/series`)

| Patch | Local Commit | Subject |
| --- | --- | --- |
| `coral-30/0001` | `86f51f76752a` | `arm64: dts: qcom: sm8150: add initial Google Pixel 4 XL (coral)` |
| `coral-30/0002` | `5a951e9017ef` | `arm64: dts: coral: touch coords, disable touch fw auto-update, coral firmware paths` |
| `coral-30/0003` | `20203b38f8cb` | `drm/panel: add Samsung S6E3HC2 (Pixel 4 XL coral) DSC cmd-mode panel` |
| `coral-30/0004` | `675e0bec2e2d` | `arm64: dts: coral: wire s6e3hc2 panel, re-enable MDSS` |
| `coral-30/0005` | `472bb39eac2a` | `Preserve verified coral display touch and recovery baseline` |
| `coral-30/0006` | `6315c883538b` | `coral: add calibrated display, wake touch and bounded charging` |
| `coral-30/0007` | `65adbcf4ac89` | `coral: finish display, telemetry and wake diagnostics` (git tree `21eb1828b205`) |
| `coral-fec40357/0008` | `f1613a5f4fd4` | `Enable Coral SLPI and preserve FastRPC pool ownership` |
| `coral-fec40357/0009` | `52f2c29b0a60` | `Enable protected Coral audio and align microphone capture` |
| `coral-fec40357/0010` | `d3dd05299ff8` | `media: bring up five Coral cameras and concurrent rear and IR streams` |
| `coral-fec40357/0011` | `fec403571c23` | `drm/msm/dsi: retain powered link clocks and serialize brightness` (git tree `6d4115553ae5`) |

## Earlier kernels named in the notes

| Build | Date | Tree | Status |
| --- | --- | --- | --- |
| `#3` | 18 Oct 00:34 | `5a951e9017ef` (`0001`..`0002`) plus uncommitted changes, committed later (19 Oct 02:08) as `472bb39eac2a` (`0005`) | First rescue kernel (`out-rescue-safe`). Not on the phone any more. Its working tree changed after the build, so its exact source is not byte-proven. |
| `#25` | 19 Oct 06:07 | uncommitted tree before `65adbcf4ac89` (`0007`, committed 06:18); the SLPI and audio work was committed later as `f1613a5f4fd4` and `52f2c29b0a60` | Installed in `boot_a` on 19 Oct and the kernel for the SLPI and audio sessions, whose modules and DTB came from the `0008`/`0009` trees. Not byte-proven. Replaced. |
| `#27` | 19 Oct 12:30 | uncommitted tree on `52f2c29b0a60`; the camera work was committed later as `d3dd05299ff8` (14:59) | Installed in `boot_a` on 19 Oct; replaced by `#30`. Not byte-proven. |

## Changes in `v0.2.3`

- The `Image` row above: `#30` was built from both series, not `coral-30` alone.
- `tools/build-kernel.sh` applies both series before building, and drops `--with-fec40357`.
- Added `userspace/audio/audio-firmware.sha256` (names and hashes only), which `tools/build-rootfs.py`
  already required.
- Rows for the installed ramdisk, `coral-cs40l2x.ko` and `coral-phone`; corrected the earlier-kernel
  table; copyright lines in `kernel/dts/`; the `tqftpserv` base commit (`128cd6e0a397`); CDC ECM, not
  NCM.

