#!/bin/bash
# SPDX-License-Identifier: MIT
# Runs inside the logged-in user's Wayland session; all configuration is in RAM.
set -euo pipefail
export PHONE_EDGE_TOP='omarchy-shell omamobile.bar pullDown'
export PHONE_EDGE_BOTTOM="omarchy-shell shell summon omamobile.launcher '{}'"
gsettings set org.gnome.desktop.a11y.applications screen-keyboard-enabled true
# coral-phone.service owns touch edges, haptics and wake as one Rust process.
exec squeekboard
