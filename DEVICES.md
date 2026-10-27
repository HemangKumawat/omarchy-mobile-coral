<!-- SPDX-License-Identifier: MIT -->
# Google Pixel 4 XL (`coral`) — device status

The `coral` row of `docs/DEVICES.md` in [`derekross/omarchy-mobile` PR #52](https://github.com/derekross/omarchy-mobile/pull/52), copied here unchanged. The per-subsystem detail and dated results are in [`device/coral/NOTES.md`](https://github.com/HemangKumawat/omarchy-mobile/blob/coral-bringup-docs/device/coral/NOTES.md).

**Legend:**

- **works**: verified on the phone, on by default;
- **testing**: works by hand, not yet on by default;
- **partial**: works on by default, with a known gap that the notes name;
- **WIP**: bring-up in progress, some gates passed;
- **built**: driver and DT written and built, not yet run on the phone;
- **boots**: the block's firmware runs, but nothing user-facing uses it yet;
- **no**: not started, or blocked;
- **-**: the hardware doesn't exist on this device.

| Device | Codename | SoC | Boot | Storage | Display | GPU | Touch | Buttons | USB net | Wi-Fi | Bluetooth | Battery | Charging | Haptics | Torch | GNSS | AoC | Speakers/mics | Sensors | Modem | NFC | Cameras | Suspend | Fingerprint |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Pixel 4 XL ([notes](https://github.com/HemangKumawat/omarchy-mobile/blob/coral-bringup-docs/device/coral/NOTES.md)) | coral | SM8150 (Snapdragon 855) | WIP ([#52](https://github.com/derekross/omarchy-mobile/pull/52): direct ABL v2 boot on the test handset's slot A; slot-B install and §3.1 entry pending; [notes](https://github.com/HemangKumawat/omarchy-mobile/blob/coral-bringup-docs/device/coral/BRINGUP-M1.md)) | testing (in review: read-only `blockdev` guard + RAM `overlayfs`) | testing (in review: 1440x3040@60Hz S6E3HC2 DSC 1.1 KMS, DPMS, brightness) | testing (in review: Adreno 640 / FD640 Mesa Freedreno, Hyprland) | testing (in review: FTS SPI multitouch + read-only flash guard) | testing (in review: power via `qcom-pon` + volume via `gpio-keys`) | testing (in review: CDC ECM + ACM + SSH; stays up with host USB switched off) | testing (in review: `WCN3990` `ath10k_snoc` + `rmtfs -r`, WPA2/DHCP/HTTPS; radio sessions ran before the modem baseline) | WIP (in review: `WCN3990` `hci_qca` `hci0` up + BLE scan; audio/pairing open) | WIP (in review: PM8150B ADC `VBAT_SNS` voltage + FG temp; aftermarket pack on test unit: no reply from `1-0036`) | testing (in review: PM8150B SMB5 charger with `4.20 V` / `500 mA` kernel clamp) | testing (in review: `CS40L25A` I2C click waveform) | testing (in review: PM8150L flash LEDs + quick-settings tile) | no | - | testing (in review: QDSP6 + dual `CS35L36` amps capped at `-26 dB` + `IA8508` SPI mic DSP) | testing (in review: `SLPI` + `fastrpc` + RAM-backed `hexagonrpcd` + QMI SSC: 7 sensors + Soli radar) | WIP (in review: `MPSS` boots with `rmtfs -r` + patched `tqftpserv`, SIM detected; no IPA/voice yet; radio sessions ran before the modem baseline) | no | testing (in review: `CAMSS` + `IMX363`, `IMX481`, `IMX520`, dual `OV7251` NIR; `libcamera` softISP) | no | - |
