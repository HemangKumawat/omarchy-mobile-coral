#!/bin/bash
# SPDX-License-Identifier: MIT
# Root service -> existing, unprivileged graphical session; never a setuid tool.
set -euo pipefail
[[ $# -gt 0 ]] || { echo 'coral-phone-session: command required' >&2; exit 2; }
SESSION_USER="${OMARCHY_INSTALL_USER:-omarchy}"
# Explicit edge/rotate invocations already inside the desktop session need no
# privilege transition. The root daily service takes the checked path below.
if [[ $(id -u) = 1000 ]]; then exec "$@"; fi
[[ $(id -u) = 0 ]] || { echo 'coral-phone-session: unexpected user' >&2; exit 1; }
runtime=/run/user/1000
user=(/usr/bin/runuser -u "$SESSION_USER" -- /usr/bin/env "HOME=/home/$SESSION_USER"
    XDG_RUNTIME_DIR="$runtime" DBUS_SESSION_BUS_ADDRESS="unix:path=$runtime/bus"
    OMARCHY_PATH=/usr/share/omarchy LANG=C.UTF-8)
instance=$("${user[@]}" /usr/bin/hyprctl instances -j)
read -r signature wayland pid < <(jq -er '
    if length == 1 then .[0] | [.instance, .wl_socket, (.pid | tostring)] | @tsv
    else error("Expected one Hyprland session") end' <<< "$instance")
[[ "$pid" =~ ^[0-9]+$ && $(cat "/proc/$pid/comm") = Hyprland ]]
exec "${user[@]}" HYPRLAND_INSTANCE_SIGNATURE="$signature" WAYLAND_DISPLAY="$wayland" "$@"
