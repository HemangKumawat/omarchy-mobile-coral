# omarchy-mobile-coral — Google Pixel 4 XL (`coral`) Mainline Linux Sources

Kernel device trees, kernel patches, userspace patches, initramfs scripts, and packaging recipes for the **Google Pixel 4 XL (`coral`, Qualcomm SM8150 / Snapdragon 855)** running mainline Linux (`6.17.0-sm8150`) + Arch Linux ARM / Omarchy Mobile (`Hyprland`), accompanying [`derekross/omarchy-mobile` PR #52](https://github.com/derekross/omarchy-mobile/pull/52).

**What the phone actually runs, and which commit built each part, is in [`PROVENANCE.md`](PROVENANCE.md).** The installed kernel and DTB are proven against the patch series in [`kernel/series/`](kernel/series).

This repository contains **source code, device trees, patches, and build/initramfs scripts only**—no proprietary firmware or binary blobs are included. All vendor firmware is read at runtime from the handset's factory partitions (`vendor_a`/`vendor_b`, `modem_a`/`modem_b`, `persist`) mounted strictly read-only (`blockdev --setro`).

---

## Status

The status row, with the omarchy-mobile legend, is in [`DEVICES.md`](DEVICES.md). The per-subsystem
detail, dated results and the kernel build each result ran on are in
[`device/coral/NOTES.md`](https://github.com/HemangKumawat/omarchy-mobile/blob/coral-bringup-docs/device/coral/NOTES.md) in the omarchy-mobile pull request; the boot method, slots,
backups and gates are in [`device/coral/BRINGUP-M1.md`](https://github.com/HemangKumawat/omarchy-mobile/blob/coral-bringup-docs/device/coral/BRINGUP-M1.md).

---

## Base Upstream Trees

- **Kernel tree:** [the SM8150 kernel tree](https://gitlab.postmarketos.org/soc/qualcomm-sm8150/linux) at commit `6963e3800a8e`, three commits past the tag `v6.17.0-sm8150` (`379d8fe35c7c`), plus [`kernel/series/coral-30`](kernel/series/coral-30) for the installed `Image` and [`kernel/series/coral-fec40357`](kernel/series/coral-fec40357) for the DTB and the camera, audio and SLPI modules.
- **`hexagonrpcd` (SLPI sensor daemon):** [`linux-msm/hexagonrpc`](https://github.com/linux-msm/hexagonrpc) at commit `da7a3742ab8d5273a281b70ee11f16fb2cb6a690`.
- **`tqftpserv` (QMI TFTP server for MPSS MCFG):** [`linux-msm/tqftpserv`](https://github.com/linux-msm/tqftpserv) at commit `128cd6e0a39734fefd0f0bf0aad5e997c29e2445`.
- **`rmtfs` (QMI remote filesystem service):** [`linux-msm/rmtfs`](https://github.com/linux-msm/rmtfs) run with `-r -P -s` (`-r`: EFS served from RAM, nothing written back; `-P`: partitions found by name; `-s`: `rmtfs` starts and stops the modem).

---

## Repository Layout

### 1. Kernel Device Trees (`kernel/dts/`)
- [`kernel/dts/sm8150-google-coral.dts`](kernel/dts/sm8150-google-coral.dts) — Mainline device tree for Google Pixel 4 XL (`compatible = "google,coral", "qcom,sm8150"`), derived from `sm8150-google-flame.dts` with Coral-specific reserved-memory (`ramoops` at `0xa0c00000`), Samsung S6E3HC2 1440x3040 DSC panel (`panel-samsung-s6e3hc2`), STMicroelectronics FTM5 touchscreen (`st,fts` with `st,disable-auto-fw-update`), PM8150B charger (`4.20 V` / `500 mA`), MAX1720x/MAX1730x fuel gauge, CS40L25A haptics, WCN3990 Wi-Fi (`Google_coral`) / Bluetooth (`crnv21.bin` + `crbtfw21.tlv`), and remoteprocs (`mpss`, `adsp`, `cdsp`, `slpi`).
- [`kernel/dts/sm8150-google-coral-audio.dtsi`](kernel/dts/sm8150-google-coral-audio.dtsi) — SLIMbus (`171c0000.slim` + `171d0000.slim-ngd`), WCD9340 (`tavil`), dual CS35L36 (`0x40` bottom, `0x41` top with `cirrus,boost-ctl-millivolt = <4500>` and `cirrus,boost-peak-milliamp = <1600>`), and Knowles IA8508 (`spi11.0`) audio topology.
- [`kernel/dts/sm8150-google-coral-cameras.dtsi`](kernel/dts/sm8150-google-coral-cameras.dtsi) — CCI0/CCI1, MAX77826 PMIC rails, CAMSS CSIPHY0/1/2/3, and sensor nodes (`imx363` rear wide, `imx481` rear tele, `imx520` front NIR, `ov7251` front IR left/right).

### 2. Kernel Patches (`kernel/series/`, `kernel/patches/` and `kernel/audio/`)
- **Authoritative:** [`kernel/series/`](kernel/series), applied in order on `6963e3800a8e` (`coral-30`, then `coral-fec40357`; `tools/build-kernel.sh` does both). Together they built the installed `Image`, the DTB and the loadable modules.
- **Per-topic review copies:** the files below split the same work by subsystem for reading. Where they differ from the series, the series is what ran.
- **Base DTS & panel driver:**
  - [`0001-coral-base-dts-and-s6e3hc2-panel.patch`](kernel/patches/0001-coral-base-dts-and-s6e3hc2-panel.patch) — Initial `sm8150-google-coral.dts` and `panel-samsung-s6e3hc2.c` DSC driver.
  - [`0002-coral-wifi-bt-firmware-dts.patch`](kernel/patches/0002-coral-wifi-bt-firmware-dts.patch) — WCN3990 board calibration and Bluetooth firmware DT properties.
  - [`coral-dt1.patch`](kernel/patches/coral-dt1.patch), [`coral-daily-dt.patch`](kernel/patches/coral-daily-dt.patch), [`coral-safety-dt.patch`](kernel/patches/coral-safety-dt.patch) — Extra SPI controller guards, PMIC alarm, and daily DT updates.
- **Boot safety & PON reboot latch:**
  - [`qcom-pon-recovery.patch`](kernel/patches/qcom-pon-recovery.patch) — In `drivers/power/reset/qcom-pon.c` (`qcom_pon_probe`), arms `PON_SOFT_RB_SPARE` (`0x88f`) to `2` (bootloader/Fastboot) at kernel probe when `of_machine_is_compatible("google,coral")` and exposes `coral_healthy` so any crash, watchdog bite, or reboot before userspace health confirmation lands in Fastboot.
- **Display (DSI 6G & Samsung S6E3HC2):**
  - [`coral-dsi-clock.patch`](kernel/patches/coral-dsi-clock.patch) & [`coral-dsi-transfer-clocks.patch`](kernel/patches/coral-dsi-transfer-clocks.patch) — Sets `DSI_6G_FIFO_TIMING` (`0x0bc`) and keeps DSI link clocks enabled around `msm_dsi_host_xfer_prepare()` / `unprepare()`.
  - [`coral-panel-brightness.patch`](kernel/patches/coral-panel-brightness.patch), [`coral-panel-daily.patch`](kernel/patches/coral-panel-daily.patch), [`coral-panel-power-mode-daily.patch`](kernel/patches/coral-panel-power-mode-daily.patch) — S6E3HC2 10-bit big-endian brightness, LP mode, and DCS power-mode `0x9c` verification.
- **Touchscreen read-only flash guard & wake (`drivers/input/touchscreen/fts_touch/`):**
  - [`coral-fts-readonly.patch`](kernel/patches/coral-fts-readonly.patch) — Blocks all non-volatile flash and calibration write paths in ST's FTM5 driver (`fts_fw_update` skips CRC/auto-reflash and calls `fts_init_sensing` directly; `fts_chip_initialization` returns `ERROR_OP_NOT_ALLOW`; `writeSysCmd` blocks `SYS_CMD_SAVE_FLASH`, `SPECIAL_PANEL_INIT`, `SPECIAL_FULL_PANEL_INIT`, and `SPECIAL_WRITE_HOST_MEM_TO_FLASH`; `flash_unlock` returns `ERROR_OP_NOT_ALLOW`; `/proc/fts` and sysfs `fwupdate`, `autotune`, `stm_fts_cmd`, `infoblock_getdata` are removed).
  - [`coral-touch-wake.patch`](kernel/patches/coral-touch-wake.patch) — Wake-irq and gesture handling across suspend/resume.
- **Battery, PM8150B SMB5 charger & fuel gauge:**
  - [`coral-charge.patch`](kernel/patches/coral-charge.patch) — Fixes `qcom_smbx.c` to use SMB5 step math on PM8150B (`3.60 V + N * 10 mV` at `0x1070`, `50 mA` steps at `0x1061`) instead of PMI8998/SMB2 math, clamping float voltage to `0x3c` (`4.20 V`) and fast-charge current to `0x0a` (`500 mA`) in kernel probe while leaving stock JEITA (`0x1090 = 0xdf`) untouched.
  - [`coral-fg-temp.patch`](kernel/patches/coral-fg-temp.patch) — GEN4 FG SRAM word 328 temperature read and `MEM_INTF_DMA_STS` (`0x4370`) check in `qcom_fg.c`.
  - [`coral-gauge1730x.patch`](kernel/patches/coral-gauge1730x.patch) — MAX1720x/MAX1730x fuel gauge read-only telemetry.
- **Haptics, SLPI & Audio:**
  - [`coral-cs40l2x-port.patch`](kernel/patches/coral-cs40l2x-port.patch) — Cirrus Logic CS40L25A (`0x43` on `i2c9`) haptic driver port for Linux 6.17.
  - [`coral-slpi.patch`](kernel/patches/coral-slpi.patch) — SLPI FastRPC contexts and `smp2p-slpi` `sleepstate` gating.
  - [`coral-audio.patch`](kernel/patches/coral-audio.patch) & [`kernel/audio/sm8150-coral.h`](kernel/audio/sm8150-coral.h) — Coral sound card and CS35L36 driver patch enforcing `CORAL_DIGITAL_MAX = 608` (`-26.0 dB`), read-only `0 dB` analog gain (`CORAL_ANALOG_SAFE = 0`), and `4.5 V` / `1600 mA` boost converter clamps.
- **Cameras & IR safety (`kernel/patches/camera/` and `kernel/patches/face/`):**
  - [`camera/001-ovti,ov7251.yaml.patch`](kernel/patches/camera/001-ovti,ov7251.yaml.patch) .. [`camera/033-max77826-regulator.c.patch`](kernel/patches/camera/033-max77826-regulator.c.patch) — 33 patches for SM8150 CAMSS (`csiphy-3ph-1-0`, `csid-gen2`, `vfe-17x` CAMNOC QoS, 4-VC routing), `imx363`, `imx481`, `imx520`, `ov7251`, and `max77826`.
  - [`face/leds-lm3601x-coral-off.h`](kernel/patches/face/leds-lm3601x-coral-off.h) — Read-only / OFF-only verification header for the `LM36011` (`0x64` flood / `0x65` dot projector) laser drivers; refuses any non-zero brightness and keeps the drivers unbound in production.

### 3. Userspace Patches & Runtime Config (`userspace/`)
- [`userspace/hexagonrpc/hexagonrpc-ram-registry.patch`](userspace/hexagonrpc/hexagonrpc-ram-registry.patch) — Seeds `/run/coral-qcom/sensors/registry` in `tmpfs` from read-only `/run/coral-persist/sensors/registry/registry` and confines `hexagonrpcd` registry file operations with `openat2(..., RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS)`.
- [`userspace/tqftpserv/0001-translate-serve-readonly-vendor-mbn-Pixel-MCFG-from-.patch`](userspace/tqftpserv/0001-translate-serve-readonly-vendor-mbn-Pixel-MCFG-from-.patch) — Translates `/readonly/vendor/mbn/` QMI requests from MPSS to `<rproc fw dir>/mbn/` in read-only mode.
- [`userspace/audio/`](userspace/audio/) — ALSA UCM2 profile (`ucm2/Pixel4XL/HiFi.conf`), `ia8508.conf`, and `audio-firmware.sha256` (names and hashes of the ADSP and IA8508 firmware read from the phone, like `tools/slpi.sha256`).
- [`userspace/services/`](userspace/services/) — Systemd service units and read-only vendor/sensor runtime helpers (`vendor-runtime.sh`, `sensor-runtime.sh`).

### 4. Initramfs & Packaging Tools (`initramfs/` and `tools/`)
- [`initramfs/init`](initramfs/init) — Early PID 1 script (the installed one): starts BusyBox `watchdog -T 20 -t 5 /dev/watchdog0`, configures the USB ConfigFS gadget (CDC ACM + CDC ECM, `172.16.42.1/30`) and a root shell on the USB serial port, and after a 120-second lease writes `1` to `/sys/bus/platform/drivers/qcom-pon/*/coral_healthy` once `systemd` is PID 1 and `sshd` is alive. Since 22 October the check no longer needs a USB host; it was tested with the build host's USB port switched off (cable attached), and a cold boot without a cable is not yet recorded. Then it sources `omarchy-userspace.sh`.
- [`initramfs/omarchy-userspace.sh`](initramfs/omarchy-userspace.sh) — Forces all `/dev/sd*`, `/dev/vd*`, and `/dev/mmcblk*` block devices read-only via `blockdev --setro`, locates root via `findfs LABEL=omarchy-root`, mounts `/lower` (`ro,noload`) with a `tmpfs` overlay (`upperdir=/run/overlay/upper`), verifies and bind-mounts read-only radio/vendor firmware, runs a second `blockdev --setro` pass, and transitions into Arch via `exec chroot /newroot /usr/lib/systemd/systemd --unit=graphical.target` (keeping PID 1's initramfs watchdog feeder alive).
- [`tools/build-kernel.sh`](tools/build-kernel.sh) — Applies `kernel/series/coral-30` and `kernel/series/coral-fec40357` to `6963e3800a8e`, checks the resulting tree hash, and builds `Image`, modules and the 12-entry `dtb-12` (`sha256: 3efe241aa349ff260ef0312e1b0a3a611943f71b0939261729c42e3842c90058`).

The tools write under `$CORAL_WORK` (default `./work`). `tools/build-rootfs.py` reads `pin.json`, `dependencies.json`, `lock-off.patch`, `battery-status.patch`, `session-start.sh`, `phone-session.sh`, `sensor-rpc-pin.json`, `slpi.sha256`, and `device/coral/device.conf` from `tools/` (and service/audio configs from `userspace/`).
- [`tools/pack-matched-dtb.py`](tools/pack-matched-dtb.py) — Matches 12 copies of `sm8150-google-coral.dtb` to the 12 factory `dtbo.img` board selectors (`qcom,msm-id` + `qcom,board-id`) alongside the 12-entry no-op `dtbo.img`.
- [`tools/pack-bootimg.py`](tools/pack-bootimg.py) — Sets the ARM64 `Image` header `text_offset` at byte offset `8` to `0x80000` (`struct.pack_into('<Q', raw, 8, 0x80000)`), compresses with `lz4 -9` frame format (`0x184d2204`), verifies touch read-only symbols/DTB properties, packs the boot image v2 (`header_version=2`, `base=0x00000000`, `dtb_offset=0x01f00000`), and appends the 64 MiB AVB hash footer (`--algorithm NONE`).
- [`tools/build-rootfs.py`](tools/build-rootfs.py) — Stages the mobile userspace overlay onto the Arch Linux ARM `omarchy-root` image.

---

## Licence

- Scripts, tools, initramfs and userspace configuration: MIT ([`LICENSE`](LICENSE)); each file carries an SPDX line.
- Kernel patches and series (`kernel/series/`, `kernel/patches/`, `kernel/audio/`): GPL-2.0-only, as the kernel ([`LICENSES/GPL-2.0-only.txt`](LICENSES/GPL-2.0-only.txt)). The device trees keep their own SPDX lines.
- Patches to third-party projects (`userspace/hexagonrpc/`, `userspace/tqftpserv/`) are under those projects' licences.
- `kernel/dts/sm8150-google-coral.dts` is derived from `sm8150-google-flame.dts` (BSD-3-Clause) and keeps its copyright line; `kernel/dts/sm8150-google-coral-cameras.dtsi` follows Google's `sm8150-coral-camera-sensor.dtsi` (GPL-2.0-only) and keeps The Linux Foundation's copyright line. The same DTS inside the `kernel/series/` patches does not carry these lines yet; they will be added before the DTS goes to a kernel tree.
- `kernel/patches/camera/013-imx481-coral-tables.h.patch` and `017-imx520-coral-tables.h.patch` hold sensor mode tables decoded from the handset's vendor `metric_imx481.bin` / `metric_imx520.bin` files. Whether that is acceptable, or the tables need a GPL source, is an open question to the omarchy-mobile maintainer.

## Not yet published

- The `coral-phone` userspace service: `tools/build-rootfs.py` installs it as a prebuilt binary (`/usr/local/bin/coral-phone`); its Rust source is not in this repository yet.
- The `cs40l2x` base driver files that `kernel/patches/coral-cs40l2x-port.patch` applies to (Cirrus Logic, GPL-2.0; source commit not recorded).
- The original RAM-test rescue init and the no-op `dtbo` generator.
- The private network payload appended to the installed ramdisk (Wi-Fi profile, Tailscale state, a userspace-mode Tailscale unit and an `sshd` on `127.0.0.1`); see [`PROVENANCE.md`](PROVENANCE.md).

## Development handset, as it is (do not copy)

- Our image is on slot A, and `vbmeta_a` was written with verification disabled.
- No raw copy of any partition was taken before the first flash, `persist` included; the owner approved skipping that backup.
- Stock Android on slot B cannot boot with the ext4 `userdata`, so the handset has no stock slot to fall back to.
- Recovery means Fastboot (Volume Down + Power) plus a factory image, which wipes the Arch root.
- The image keeps an unauthenticated root shell on the USB serial gadget and gives root an empty password in the RAM copy of `/etc/shadow`. SSH is key-only, but anyone with a cable has root.

See [`device/coral/BRINGUP-M1.md`](https://github.com/HemangKumawat/omarchy-mobile/blob/coral-bringup-docs/device/coral/BRINGUP-M1.md) in the omarchy-mobile pull request.
