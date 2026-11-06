#!/bin/bash
set -u
K=/home/shrp/lmp73
OUT=/mnt/c/Users/Administrator/AppData/Local/Temp/ksuwork/esp_cxfloor.img
VF=$K/arch/arm64/boot/vmlinuz.efi
INIT=/tmp/e55_init8.cpio.gz

echo "=== ESP packaging $(date +%H:%M:%S) ==="

[ -f "$VF" ] || { echo "!! vmlinuz.efi missing"; exit 1; }
[ -f "$INIT" ] || { echo "!! initramfs missing"; exit 1; }

ISZ=$(stat -c %s "$INIT")
IMD5=$(md5sum "$INIT" | cut -d' ' -f1)
echo "initramfs: $ISZ B  md5 $IMD5"
[ "$ISZ" = "1067119" ] || { echo "!! not the E55 original"; exit 1; }
[ "$IMD5" = "1d2533048d1d2955b66e291d73bf7c5f" ] || { echo "!! initramfs md5 mismatch"; exit 1; }

# sanity: the EFI payload must be the EFI zboot wrapper, not a raw Image
SZ=$(stat -c %s "$VF")
echo "BOOTAA64.EFI source (vmlinuz.efi): $SZ B  md5 $(md5sum "$VF" | cut -d' ' -f1)"
magic=$(head -c 2 "$VF" | od -An -tx1 | tr -d ' \n')
echo "first 2 bytes: $magic (expect 4d5a = 'MZ')"
[ "$magic" = "4d5a" ] || { echo "!! vmlinuz.efi does not start with MZ -- refusing to package"; exit 1; }

echo "=== 128M FAT32 image ==="
rm -f "$OUT"
truncate -s 128M "$OUT"
mkfs.vfat -F 32 -n SYSTEM "$OUT" >/dev/null || { echo "!! mkfs failed"; exit 1; }

mmd -i "$OUT" ::/EFI
mmd -i "$OUT" ::/EFI/BOOT
mcopy -i "$OUT" "$VF" ::/EFI/BOOT/BOOTAA64.EFI
mcopy -i "$OUT" "$INIT" ::/initramfs.cpio.gz

echo "=== contents ==="
mdir -i "$OUT" ::/ 2>/dev/null | head -8
mdir -i "$OUT" ::/EFI/BOOT 2>/dev/null | head -6

echo "=== result ==="
ls -la "$OUT"
echo "esp md5: $(md5sum "$OUT" | cut -d' ' -f1)"
echo "kernel Image md5: $(md5sum $K/arch/arm64/boot/Image | cut -d' ' -f1)"
