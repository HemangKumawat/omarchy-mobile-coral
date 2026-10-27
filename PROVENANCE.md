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
1. `ac44cb016300` — `power: supply: qcom_fg: silence unused variable warning`
2. `a2b20090fc1c` — `power: supply: Add driver for IDT P9418 WPC Qi wireless power receiver`
3. `6963e3800a8e` — `power: supply: idtp9418: remove unused variable`

## The installed boot image

| Part | Source | Status |
| --- | --- | --- |
| Kernel `Image`: `6.17.0-sm8150 #30 SMP PREEMPT Mon Oct 19 21:29:48 CEST 2026`, GCC 16.1.0, binutils 2.47 | `6963e3800a8e` + [`kernel/series/coral-30`](kernel/series/coral-30) (patches `0001`..`0007`), config [`coral-30/config`](kernel/series/coral-30/config) | **Proven.** The build output equals the installed `Image` except byte 10, the `text_offset` field that `tools/pack-bootimg.py` sets to `0x80000`. The build tree was clean, and no source file was newer than the build. Applying the series to `6963e3800a8e` gives the build tree exactly (git tree `21eb1828b205f86d87333e77179e03a8f5b930b3`). |
| DTB: 12 entries, one per factory `dtbo` board selector | [`kernel/dts/`](kernel/dts) compiled against `6963e3800a8e` + `coral-30` + [`kernel/series/coral-fec40357`](kernel/series/coral-fec40357) (patches `0008`..`0011`: SLPI, audio, cameras, DSI clocks) | **Proven.** Applying `coral-fec40357` on top of `coral-30` gives git tree `6d4115553ae5a9aec7b9e4ae23f77b2e4c4d7c4e` exactly, and `tools/build-kernel.sh <src> <out> --with-fec40357` reproduces all 12 installed DTB entries byte-for-byte (`sha256: 3efe241aa349ff260ef0312e1b0a3a611943f71b0939261729c42e3842c90058`). |
| Loadable modules (cameras, audio, SLPI) | Built from the `coral-fec40357` tree (`6d4115553ae5`) | **Partly checked.** The staged `imx363.ko` and `fastrpc.ko` equal the debug-stripped build outputs. The staged `qcom-camss.ko` does not; it comes from a camera experiment variant. A full per-module manifest is still to do. |
| `initramfs/init` | This repository | Equal to the installed init, except the SPDX line and the USB serial number, which is a parameter here. |
| `initramfs/omarchy-userspace.sh` | This repository | Equal to the installed script, except the user name, which is a parameter here (`OMARCHY_INSTALL_USER`). |

A byte-exact rebuild of the `Image` from this repository has not been demonstrated yet. The build
host's compiler has since moved to GCC 16.2. `tools/build-kernel.sh` sets the banner timestamp and
version values used by `#30` and reproduces the 12-entry `dtb-12` byte-for-byte.

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
| `#3` | 18 Oct 00:34 | `5a951e9017ef` (`0001`..`0002`) with uncommitted local display/touch/PON changes later committed in `472bb39eac2a` (`0005`) | First rescue kernel (`out-rescue-safe`). Not on the phone any more. Its working tree changed after the build, so its exact source is not byte-proven. |
| `#25` | 19 Oct 06:07 | audio and SLPI experiment trees (`65adbcf4ac89`..`52f2c29b0a60`, `0001`..`0009`) | Booted from RAM only (`out-audio-20261019`). Its working tree changed after the build, so its exact source is not byte-proven. Superseded by the series above. |
| `#27` | 19 Oct 12:31 | camera experiment trees (`d3dd05299ff8`..`fec403571c23`, `0001`..`0011`) | Booted from RAM only (`out-cameras-20261019`). Same caveat. Superseded by the series above. |

