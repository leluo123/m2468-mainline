import lz4.frame, lz4.block, io, os, sys

src = "/mnt/c/Users/Administrator/AppData/Local/Temp/ksuwork/vb_a.img"
off, size = 4096, 10691372
ram = open(src, "rb").read()[off:off+size]
print("slice:", len(ram), ram[:4].hex())

out = b""
# LZ4 legacy: sequence of [u32 LE compressed_len][block]
if ram[:4] == bytes.fromhex("02214c18"):
    i = 0
    while i < len(ram):
        if ram[i:i+4] == bytes.fromhex("02214c18"):
            i += 4
            continue
        if i + 4 > len(ram):
            break
        blen = int.from_bytes(ram[i:i+4], "little")
        i += 4
        if blen == 0 or i + blen > len(ram):
            break
        try:
            out += lz4.block.decompress(ram[i:i+blen], uncompressed_size=8*1024*1024)
        except Exception as e:
            print("block fail at", i, e)
            break
        i += blen
print("decompressed:", len(out), out[:6])

if out[:6] == b"070701":
    open("/tmp/vb_ram.cpio", "wb").write(out)
    print("wrote /tmp/vb_ram.cpio")
else:
    print("not cpio:", out[:16].hex())
