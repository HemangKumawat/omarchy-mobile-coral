# omarchy-mobile-coral — Google Pixel 4 XL (`coral`) Mainline Linux Sources

Kernel device trees, kernel patches, userspace patches, initramfs scripts, and packaging recipes for the **Google Pixel 4 XL (`coral`, Qualcomm SM8150 / Snapdragon 855)** running mainline Linux (`6.17.0-sm8150`) + Arch Linux ARM / Omarchy Mobile (`Hyprland`), accompanying [`derekross/omarchy-mobile` PR #52](https://github.com/derekross/omarchy-mobile/pull/52).

**What the phone actually runs, and which commit built each part, is in [`PROVENANCE.md`](PROVENANCE.md).** The installed kernel and DTB are proven against the patch series in [`kernel/series/`](kernel/series).

This repository contains **source code, device trees, patches, and build/initramfs scripts only**—no proprietary firmware or binary blobs are included. All vendor firmware is read at runtime from the handset's factory partitions (`vendor_a`/`vendor_b`, `modem_a`/`modem_b`, `persist`) mounted strictly read-only (`blockdev --setro`).

---

## Pixel 4 XL (`coral`) — What's Working & What's Not Working

See [**`DEVICES.md`**](DEVICES.md) for the full 22-column matrix matching [omamobile.org/devices](https://omamobile.org/devices/).

**Legend:** **testing** = verified on real hardware (runs on our `coral` image built from [the SM8150 kernel tree](https://gitlab.postmarketos.org/soc/qualcomm-sm8150/linux) at `6963e3800a8e` + this repo; see [`PROVENANCE.md`](PROVENANCE.md)) · **WIP** = bring-up in progress, some gates passed · **no** = not started or blocked · **-** = hardware does not exist on this device.

| Subsystem | Status | Working on Hardware | Not Working / Known Gaps | Key Sources |
| --- | --- | --- | --- | --- |
| **Boot** | **testing** | Direct ABL (`c2f2-0.5-8906123`) header-v2 boot without U-Boot (`text_offset=0x80000`, modern LZ4 `04 22 4d 18`, 12-entry board-matched DTB + 12-entry no-op `dtbo.img`); `qcom-wdt` hardware watchdog petted every 5 s; `qcom-pon` kernel Fastboot latch (`reason=2` until `coral_healthy=1`); unplugged battery cold boot & reboot | Built via [`tools/build-kernel.sh`](tools/build-kernel.sh) & [`tools/pack-bootimg.py`](tools/pack-bootimg.py) (not yet integrated into `bin/omamobile`) | [`qcom-pon-recovery.patch`](kernel/patches/qcom-pon-recovery.patch), [`initramfs/init`](initramfs/init), [`pack-bootimg.py`](tools/pack-bootimg.py) |
| **Storage** | **testing** | Two-pass `blockdev --setro` across all 79 UFS nodes (`sda`..`sdf`); `findfs LABEL=omarchy-root` (`userdata`) mounted `ro,noload` under `tmpfs` `overlayfs`; `rmtfs -r -P -s` read-only in RAM; `persist` mounted `ro,noload` (123/123 sensor registry files SHA-256 verified unchanged) | Persistent overlay mode requires clearing parent `sda` `ro` bit in Linux block layer, so default boot stays strictly RAM-overlay (`ro=1` on all 79 nodes) | [`initramfs/omarchy-userspace.sh`](initramfs/omarchy-userspace.sh) |
| **Display** | **testing** | `msm_dpu` + Samsung `S6E3HC2` AMOLED (`1440x3040@60Hz`, DSC 1.1, 2 slices `720x40`), DPMS off/on, 10-bit DCS brightness (`0..1023` on `ae94000.dsi.0`) with active DSI clock vote (`DSI_6G_FIFO_TIMING=0x0bc`, power mode `0x9c`) | 60 Hz is clean (`0` underruns); 90 Hz had startup DSI FIFO underruns before OPP scaling settled and is off by default | [`0001-coral-base-dts-and-s6e3hc2-panel.patch`](kernel/patches/0001-coral-base-dts-and-s6e3hc2-panel.patch), [`coral-dsi-clock.patch`](kernel/patches/coral-dsi-clock.patch), [`coral-dsi-transfer-clocks.patch`](kernel/patches/coral-dsi-transfer-clocks.patch) |
| **GPU** | **testing** | Qualcomm Adreno 640 (`FD640`, `2c00000.gpu` up to 698 MHz) + Mesa `freedreno` running hardware-accelerated Hyprland (`1440x3040@60`, scale `3.2`) | — | [`sm8150-google-coral.dts`](kernel/dts/sm8150-google-coral.dts) |
| **Touch** | **testing** | STMicroelectronics FingerTip S (`st,fts` on `spi0.0`, `0..1439` x `0..3039`) with full flash/calibration write protection (`fts_fw_update`, `fts_chip_initialization`, `writeSysCmd`, `flash_unlock`, `/proc/fts` & sysfs maintenance attrs blocked); double-tap wake (`KEY_WAKEUP`) | — | [`coral-fts-readonly.patch`](kernel/patches/coral-fts-readonly.patch), [`coral-touch-wake.patch`](kernel/patches/coral-touch-wake.patch) |
| **Buttons** | **testing** | Power key (`qcom-pon` `pwrkey`) and Volume Up / Down (`pm8150_resin` + `gpio-keys`) | — | [`sm8150-google-coral.dts`](kernel/dts/sm8150-google-coral.dts) |
| **USB net** | **testing** | ConfigFS gadget (`18d1:4ee3`): CDC NCM (`usb0` at `172.16.42.1/30`) + CDC ACM console + key-only `sshd` | — | [`initramfs/init`](initramfs/init) |
| **Wi-Fi** | **testing** | Qualcomm `WCN3990` (`ath10k_snoc`) + `mpss` + `pd-mapper` + `rmtfs -r -P -s` + patched `tqftpserv` + factory `bdwlan.bin` (`Google_coral`); 2.4/5 GHz scan, WPA2-PSK, DHCPv4, DNS, HTTPS, and auto-reconnect | — | [`0002-coral-wifi-bt-firmware-dts.patch`](kernel/patches/0002-coral-wifi-bt-firmware-dts.patch), [`tqftpserv` patch](userspace/tqftpserv/0001-translate-serve-readonly-vendor-mbn-Pixel-MCFG-from-.patch) |
| **Bluetooth** | **WIP** | Qualcomm `WCN3990` (`hci_qca` on `serial0-0`, `crbtfw21.tlv` + `crnv21.bin`, ROM `0x21`); `hci0` powers up and BLE/BR-EDR scan works | A2DP/HFP audio and persistent pairing across RAM-overlay reboots are still open | [`0002-coral-wifi-bt-firmware-dts.patch`](kernel/patches/0002-coral-wifi-bt-firmware-dts.patch), [`vendor-runtime.sh`](userspace/services/vendor-runtime.sh) |
| **Battery** | **WIP** | PM8150B ADC5 `VBAT_SNS` cell voltage (`4.13–4.21 V`) + GEN4 FG SRAM word 328 thermistor temperature (`31.0 °C`), surfaced in the shell via [`battery-status.patch`](tools/battery-status.patch) | Aftermarket replacement battery installed on the test handset prior to the Omarchy Mobile port omits the OEM Maxim fuel-gauge IC (`max1720x`/`max1730x` at `1-0036` returns `-ENXIO`, which also prevented `%` reporting under stock Android); state-of-charge `%` is unavailable on this pack | [`coral-gauge1730x.patch`](kernel/patches/coral-gauge1730x.patch), [`coral-fg-temp.patch`](kernel/patches/coral-fg-temp.patch), [`battery-status.patch`](tools/battery-status.patch) |
| **Charging** | **testing** | PM8150B SMB5 charger (`qcom_smbx.c`) patched with SMB5 step math and clamped in kernel `smb_probe()` to `FV = 0x3c` (`4.20 V`) and `FCC = 0x0a` (`500 mA`), leaving stock hardware JEITA (`0x1090 = 0xdf`) untouched | Conservative `4.20 V` / `500 mA` ceiling kept intentionally; USB-PD fast charge not enabled | [`coral-charge.patch`](kernel/patches/coral-charge.patch) |
| **Haptics** | **testing** | Cirrus Logic `CS40L25A` (`0x43` on `i2c9`) wavetable click playback | — | [`coral-cs40l2x-port.patch`](kernel/patches/coral-cs40l2x-port.patch) |
| **Torch** | **testing** | PM8150L flash LEDs (`led:torch_0`, `led:torch_1`) verified `0 -> 1 -> 0` with rear-camera optical proof and quick-settings tile | — | [`coral-daily-dt.patch`](kernel/patches/coral-daily-dt.patch) |
| **GNSS** | **no** | Not started | QMI PDS/LOC client not wired | — |
| **AoC** | **-** | Hardware does not exist on SM8150 (uses QDSP6 `adsp`, `cdsp`, and `slpi`) | — | — |
| **Speakers / mics** | **testing** | QDSP6 (`adsp`) + `sm8150-coral` sound card (`Pixel4XL`) + dual `CS35L36` amps (`0x40`/`0x41`) + Knowles `IA8508` mic DSP (`spi11.0`); kernel enforces `-26.0 dB` digital ceiling (`608`), read-only `0 dB` analog gain, and `4.5 V` / `1600 mA` boost clamps; 23-min 48 kHz stereo soak and mic capture verified | No speaker-protection DSP loop yet (hence `-26.0 dB` ceiling); cold-boot ADSP GLINK readiness occasionally needs a service restart | [`coral-audio.patch`](kernel/patches/coral-audio.patch), [`sm8150-coral.h`](kernel/audio/sm8150-coral.h), [`HiFi.conf`](userspace/audio/ucm2/Pixel4XL/HiFi.conf) |
| **Sensors & Soli Radar** | **testing** | `SLPI` (`slpi.mdt`) + `fastrpc` + RAM-backed `hexagonrpcd` (`openat2` confined to `/run`, zero writes to `persist`) + QMI SSC: accel, gyro (`LSM6DSR`), mag, light, prox, baro, Active Edge squeeze ADC (`MAX11261` at 115 Hz), and Infineon `BGT60TR13C` 60 GHz Soli radar | — | [`coral-slpi.patch`](kernel/patches/coral-slpi.patch), [`hexagonrpc-ram-registry.patch`](userspace/hexagonrpc/hexagonrpc-ram-registry.patch) |
| **Modem** | **WIP** | `MPSS` boots with `rmtfs -r -P -s` and patched `tqftpserv` (80 carrier MCFG files); QMI UIM detects SIM (`card present, PIN disabled`) | SM8150 IPA v4.1 mobile data, WWAN netdev, SMS, and voice calls not implemented | [`tqftpserv` patch](userspace/tqftpserv/0001-translate-serve-readonly-vendor-mbn-Pixel-MCFG-from-.patch) |
| **NFC** | **no** | Not started | ST21NFCD driver/DT not enabled | — |
| **Cameras & Face IR** | **testing** | `sm8150-camss` (CAMNOC QoS + 150 MHz floor + 3-phase C-PHY / D-PHY) streaming all 5 sensors >60 s with `0` frame gaps: rear wide `IMX363` (12.2 MP), rear tele `IMX481` (16 MP), front `IMX520` (8 MP), and synced dual front NIR `OV7251` (`5-0072` + `5-0070`, `640x480` stereo depth); colour capture via `libcamera` 0.7.2 software ISP. Both `LM36011` IR laser emitters (`0x64` flood, `0x65` dot projector) remain unbound/unloaded (`ENABLE == 0x00`, strictly `OFF`) | Single-shot ISP tuning is basic (`libcamera` softISP); `LM36011` IR emitters kept disabled (`OFF`) until eye-safety interlocks are proven | [`sm8150-google-coral-cameras.dtsi`](kernel/dts/sm8150-google-coral-cameras.dtsi), [`kernel/patches/camera/`](kernel/patches/camera/), [`leds-lm3601x-coral-off.h`](kernel/patches/face/leds-lm3601x-coral-off.h) |
| **Suspend** | **no** | Screen DPMS off/on + touch wake work | System `s2idle` / deep sleep is inhibited (`nosleep`) | [`wake.conf`](userspace/services/wake.conf) |
| **Fingerprint** | **-** | Hardware does not exist on Pixel 4 XL (uses Face IR instead) | — | — |

---

## Base Upstream Trees

- **Kernel tree:** [the SM8150 kernel tree](https://gitlab.postmarketos.org/soc/qualcomm-sm8150/linux) at commit `6963e3800a8e`, three commits past the tag `v6.17.0-sm8150` (`379d8fe35c7c`), plus [`kernel/series/coral-30`](kernel/series/coral-30) for the installed `Image` and [`kernel/series/coral-fec40357`](kernel/series/coral-fec40357) for the DTB and the camera, audio and SLPI modules.
- **`hexagonrpcd` (SLPI sensor daemon):** [`linux-msm/hexagonrpc`](https://github.com/linux-msm/hexagonrpc) at commit `da7a3742ab8d5273a281b70ee11f16fb2cb6a690`.
- **`tqftpserv` (QMI TFTP server for MPSS MCFG):** [`linux-msm/tqftpserv`](https://github.com/linux-msm/tqftpserv) at commit `a9bde2f`.
- **`rmtfs` (QMI remote filesystem service):** [`linux-msm/rmtfs`](https://github.com/linux-msm/rmtfs) run strictly with `-r -P -s` (read-only mode).

---

## Repository Layout

### 1. Kernel Device Trees (`kernel/dts/`)
- [`kernel/dts/sm8150-google-coral.dts`](kernel/dts/sm8150-google-coral.dts) — Mainline device tree for Google Pixel 4 XL (`compatible = "google,coral", "qcom,sm8150"`), derived from `sm8150-google-flame.dts` with Coral-specific reserved-memory (`ramoops` at `0xa0c00000`), Samsung S6E3HC2 1440x3040 DSC panel (`panel-samsung-s6e3hc2`), STMicroelectronics FTM5 touchscreen (`st,fts` with `st,disable-auto-fw-update`), PM8150B charger (`4.20 V` / `500 mA`), MAX1720x/MAX1730x fuel gauge, CS40L25A haptics, WCN3990 Wi-Fi (`Google_coral`) / Bluetooth (`crnv21.bin` + `crbtfw21.tlv`), and remoteprocs (`mpss`, `adsp`, `cdsp`, `slpi`).
- [`kernel/dts/sm8150-google-coral-audio.dtsi`](kernel/dts/sm8150-google-coral-audio.dtsi) — SLIMbus (`171c0000.slim` + `171d0000.slim-ngd`), WCD9340 (`tavil`), dual CS35L36 (`0x40` bottom, `0x41` top with `cirrus,boost-ctl-millivolt = <4500>` and `cirrus,boost-peak-milliamp = <1600>`), and Knowles IA8508 (`spi11.0`) audio topology.
- [`kernel/dts/sm8150-google-coral-cameras.dtsi`](kernel/dts/sm8150-google-coral-cameras.dtsi) — CCI0/CCI1, MAX77826 PMIC rails, CAMSS CSIPHY0/1/2/3, and sensor nodes (`imx363` rear wide, `imx481` rear tele, `imx520` front NIR, `ov7251` front IR left/right).

### 2. Kernel Patches (`kernel/series/`, `kernel/patches/` and `kernel/audio/`)
- **Authoritative:** [`kernel/series/`](kernel/series), patch series in apply order on `6963e3800a8e` (`git am`, then `tools/build-kernel.sh`). These are what ran on the phone.
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
- [`userspace/audio/`](userspace/audio/) — ALSA UCM2 profile (`ucm2/Pixel4XL/HiFi.conf`) and `ia8508.conf`.
- [`userspace/services/`](userspace/services/) — Systemd service units and read-only vendor/sensor runtime helpers (`vendor-runtime.sh`, `sensor-runtime.sh`).

### 4. Initramfs & Packaging Tools (`initramfs/` and `tools/`)
- [`initramfs/init`](initramfs/init) — Early PID 1 script (the installed one): starts BusyBox `watchdog -T 20 -t 5 /dev/watchdog0`, configures the USB ConfigFS gadget (`172.16.42.1/30`) and a root shell on the USB serial port, and after a 120-second lease writes `1` to `/sys/bus/platform/drivers/qcom-pon/*/coral_healthy` once `systemd` is PID 1 and `sshd` is alive. A USB host is not required since 22 October, so the phone also boots unplugged. Then it sources `omarchy-userspace.sh`.
- [`initramfs/omarchy-userspace.sh`](initramfs/omarchy-userspace.sh) — Forces all `/dev/sd*`, `/dev/vd*`, and `/dev/mmcblk*` block devices read-only via `blockdev --setro`, locates root via `findfs LABEL=omarchy-root`, mounts `/lower` (`ro,noload`) with a `tmpfs` overlay (`upperdir=/run/overlay/upper`), verifies and bind-mounts read-only radio/vendor firmware, runs a second `blockdev --setro` pass, and transitions into Arch via `exec chroot /newroot /usr/lib/systemd/systemd --unit=graphical.target` (keeping PID 1's initramfs watchdog feeder alive).
- [`tools/build-kernel.sh`](tools/build-kernel.sh) — Applies `kernel/series/coral-30` to `6963e3800a8e`, checks the resulting tree hash, and builds `Image`, modules and the dual DTB (`qcom,msm-id` v1 + v2).

The tools write under `$CORAL_WORK` (default `./work`). `tools/build-rootfs.py` reads `pin.json`, `dependencies.json`, `lock-off.patch`, `battery-status.patch`, `session-start.sh`, `phone-session.sh`, `sensor-rpc-pin.json`, `slpi.sha256`, and `device/coral/device.conf` from `tools/` (and service/audio configs from `userspace/`). `tools/build-kernel.sh <src> <out> --with-fec40357` also applies `kernel/series/coral-fec40357` and builds the byte-exact 12-entry `dtb-12` (`sha256: 3efe241aa349ff260ef0312e1b0a3a611943f71b0939261729c42e3842c90058`).
- [`tools/pack-matched-dtb.py`](tools/pack-matched-dtb.py) — Matches 12 copies of `sm8150-google-coral.dtb` to the 12 factory `dtbo.img` board selectors (`qcom,msm-id` + `qcom,board-id`) alongside the 12-entry no-op `dtbo.img`.
- [`tools/pack-bootimg.py`](tools/pack-bootimg.py) — Sets the ARM64 `Image` header `text_offset` at byte offset `8` to `0x80000` (`struct.pack_into('<Q', raw, 8, 0x80000)`), compresses with `lz4 -9` frame format (`0x184d2204`), verifies touch read-only symbols/DTB properties, packs the boot image v2 (`header_version=2`, `base=0x00000000`, `dtb_offset=0x01f00000`), and appends the 64 MiB AVB hash footer (`--algorithm NONE`).
- [`tools/build-rootfs.py`](tools/build-rootfs.py) — Stages the mobile userspace overlay onto the Arch Linux ARM `omarchy-root` image.

---

## Licence

- Scripts, tools, initramfs and userspace configuration: MIT ([`LICENSE`](LICENSE)); each file carries an SPDX line.
- Kernel patches and series (`kernel/series/`, `kernel/patches/`, `kernel/audio/`): GPL-2.0-only, as the kernel ([`LICENSES/GPL-2.0-only.txt`](LICENSES/GPL-2.0-only.txt)). The device trees keep their own SPDX lines.
- Patches to third-party projects (`userspace/hexagonrpc/`, `userspace/tqftpserv/`) are under those projects' licences.

## Development handset, as it is (do not copy)

- Our image is on slot A, and `vbmeta_a` was written with verification disabled.
- Stock Android on slot B cannot boot with the ext4 `userdata`, so the handset has no stock slot to fall back to.
- Recovery means Fastboot plus a factory image, which wipes the Arch root.
- The image keeps an unauthenticated root shell on the USB serial gadget and gives root an empty password in the RAM copy of `/etc/shadow`. SSH is key-only, but anyone with a cable has root.

See `device/coral/BRINGUP-M1.md` in the omarchy-mobile pull request.
