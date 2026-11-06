#!/bin/bash
# Flash the CX-floor kernel ESP (rawdump) to m2468 and verify the boot.
# Device must be reachable over SSH first; this script asks it to reboot into
# fastboot, then flashes and reboots back.
set -u
SER=<DEVICE-SERIAL>
ESP="/mnt/c/Users/Administrator/AppData/Local/Temp/ksuwork/esp_cxfloor.img"
FB="fastboot -s $SER"
SSHK="$HOME/.ssh/m2468"

echo "=== 0. checks ==="
[ -f "$ESP" ] || { echo "!! $ESP missing"; exit 1; }
ls -la "$ESP"
echo "esp md5: $(md5sum "$ESP" | cut -d' ' -f1)"

echo "=== 1. ask the device to reboot into fastboot over SSH ==="
ssh -i "$SSHK" -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=12 \
    root@192.168.137.76 'sync; (sleep 2; reboot bootloader) >/dev/null 2>&1 &' || {
      echo "!! SSH failed"; exit 1; }

echo "=== 2. wait for fastboot ==="
for i in $(seq 1 30); do
  sleep 5
  if command -v fastboot >/dev/null 2>&1; then
    devs=$(fastboot devices 2>/dev/null | grep -c "$SER")
    [ "$devs" = "1" ] && { echo "fastboot up after $((i*5))s"; break; }
  fi
  echo "  wait $((i*5))s"
done

fastboot devices | grep -q "$SER" || { echo "!! device not in fastboot"; exit 1; }

echo "=== 3. flash rawdump (ESP) ==="
fastboot -s "$SER" flash rawdump "$ESP" 2>&1 | tail -4

echo "=== 4. keep slot a ==="
fastboot -s "$SER" --set-active=a 2>&1 | tail -2

echo "=== 5. reboot ==="
fastboot -s "$SER" reboot 2>&1 | tail -2
echo "rebooted at $(date +%H:%M:%S)"
