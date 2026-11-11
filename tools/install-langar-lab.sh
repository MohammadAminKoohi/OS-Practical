#!/bin/sh
set -eu

lab_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
case $(uname -s) in
    Darwin) lab_system=darwin ;;
    Linux) lab_system=linux ;;
    *) echo 'Use install-langar-lab.ps1 on Windows.' >&2; exit 1 ;;
esac
case $(uname -m) in
    x86_64|amd64) lab_arch=amd64 ;;
    aarch64|arm64) lab_arch=arm64 ;;
    *) echo 'Supported CPU architectures: amd64 and arm64.' >&2; exit 1 ;;
esac
command -v curl >/dev/null 2>&1 || { echo 'Install curl first.' >&2; exit 1; }
if command -v sha256sum >/dev/null 2>&1; then
    lab_hash=sha256sum
elif command -v shasum >/dev/null 2>&1; then
    lab_hash=shasum
else
    echo 'Install sha256sum or shasum first.' >&2; exit 1
fi

lab_asset="langar-lab-$lab_system-$lab_arch"
lab_url="https://github.com/MohammadAminKoohi/OS-Practical/releases/download/langar-lab-v0.3.0/$lab_asset"
lab_expected=$(awk -v name="$lab_asset" '$2 == name {print $1}' "$lab_root/tools/langar-lab/SHA256SUMS")
[ ${#lab_expected} -eq 64 ] || { echo 'Missing or invalid checksum.' >&2; exit 1; }
lab_bin="$lab_root/.langar-lab/bin"
mkdir -p "$lab_bin"
lab_tmp=$(mktemp -d "$lab_bin/.install.XXXXXX")
trap 'rm -rf "$lab_tmp"' 0
trap 'exit 1' HUP INT TERM
echo "Downloading $lab_asset..."
curl --fail --location --silent --show-error --proto '=https' --tlsv1.2 \
    --connect-timeout 20 --max-time 180 --retry 2 --output "$lab_tmp/$lab_asset" "$lab_url"
if [ "$lab_hash" = sha256sum ]; then
    lab_actual=$(sha256sum "$lab_tmp/$lab_asset")
else
    lab_actual=$(shasum -a 256 "$lab_tmp/$lab_asset")
fi
[ "${lab_actual%% *}" = "$lab_expected" ] || { echo 'Checksum mismatch; nothing installed.' >&2; exit 1; }
chmod 755 "$lab_tmp/$lab_asset"
"$lab_tmp/$lab_asset" --version
mv -f "$lab_tmp/$lab_asset" "$lab_bin/langar-lab"
printf 'Installed: %s\nNext: ./.langar-lab/bin/langar-lab setup\n' "$lab_bin/langar-lab"
