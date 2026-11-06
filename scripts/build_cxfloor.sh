#!/bin/bash
set -u
K=/home/shrp/lmp73
echo "=== build start $(date +%H:%M:%S) ==="
cd $K || exit 1
export ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu-
echo "old Image md5: $(md5sum arch/arm64/boot/Image 2>/dev/null | cut -d' ' -f1)"
rm -f arch/arm64/boot/vmlinuz.efi arch/arm64/boot/vmlinuz.o arch/arm64/boot/vmlinuz.efi.elf arch/arm64/boot/zboot-header.o
make -j$(nproc) Image vmlinuz.efi </dev/null > /tmp/m2468_cxfloor_build.log 2>&1
RC=$?
echo "make exit=$RC $(date +%H:%M:%S)"
if [ $RC -ne 0 ]; then
  echo "!! BUILD FAILED"
  grep -E "error:|错误" /tmp/m2468_cxfloor_build.log | head -20
  exit 1
fi
NEW=$(md5sum arch/arm64/boot/Image | cut -d' ' -f1)
echo "new Image md5: $NEW"
ls -la arch/arm64/boot/vmlinuz.efi
echo "vmlinuz md5: $(md5sum arch/arm64/boot/vmlinuz.efi | cut -d' ' -f1)"
echo "=== build done $(date +%H:%M:%S) ==="
