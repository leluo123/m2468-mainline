import struct, sys, os, gzip, io

path = "/mnt/c/Users/Administrator/AppData/Local/Temp/ksuwork/vb_a.img"
data = open(path, "rb").read(4096)
magic = data[:8]
print("magic:", magic)
if magic != b"VNDRBOOT":
    print("not a vendor_boot image")
    sys.exit(1)

ver, page = struct.unpack_from("<II", data, 8)
kernel_addr, ramdisk_addr, ramdisk_size = struct.unpack_from("<III", data, 16)
print("header_version:", ver, "page_size:", page)
print("vendor_ramdisk_size:", ramdisk_size)

# v4 fields
off = 8 + 4 + 4 + 4 + 4 + 4 + 2048 + 4 + 16 + 4 + 4 + 8
tbl_size, tbl_num, tbl_ent = struct.unpack_from("<III", data, off)
print("vendor_ramdisk_table_size:", tbl_size, "entries:", tbl_num, "entry_size:", tbl_ent)

ramdisk_off = ((8 + 4 + 4 + 4 + 4 + 4 + 2048 + 4 + 16 + 4 + 4 + 8 + 12 + 4) + page - 1) // page * page
print("ramdisk offset:", ramdisk_off)

f = open(path, "rb")
f.seek(ramdisk_off)
ram = f.read(ramdisk_size)
print("read:", len(ram), "first bytes:", ram[:4].hex())

if ram[:2] == b"\x1f\x8b":
    dec = gzip.decompress(ram)
    print("gunzip ->", len(dec))
    open("/tmp/vb_ramdisk.cpio", "wb").write(dec)
    print("cpio magic:", dec[:6])
elif ram[:6] == b"070701":
    open("/tmp/vb_ramdisk.cpio", "wb").write(ram)
    print("uncompressed cpio")
else:
    # try to find gzip magic nearby
    idx = ram.find(b"\x1f\x8b\x08")
    print("gzip magic at", idx)
    if idx >= 0:
        dec = gzip.decompress(ram[idx:])
        print("gunzip ->", len(dec))
        open("/tmp/vb_ramdisk.cpio", "wb").write(dec)
        print("cpio magic:", dec[:6])
