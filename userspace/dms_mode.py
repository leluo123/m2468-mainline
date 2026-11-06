#!/usr/bin/env python3
"""Read/set DMS operating mode and dump the raw mode byte."""
import ctypes, select, struct, subprocess, sys, time

AF_QIPCRTR = 42


class SA(ctypes.Structure):
    _fields_ = [("f", ctypes.c_uint16), ("n", ctypes.c_uint32), ("p", ctypes.c_uint32)]


libc = ctypes.CDLL("libc.so.6", use_errno=True)


def ports():
    out = subprocess.run(["qrtr-lookup"], capture_output=True, text=True, timeout=10).stdout
    d = {}
    for line in out.splitlines()[1:]:
        f = line.split()
        if len(f) >= 5 and f[3] == "0":
            try:
                d.setdefault(int(f[0]), int(f[4]))
            except ValueError:
                pass
    return d


fd = libc.socket(AF_QIPCRTR, 2, 0)
sa = SA()
ln = ctypes.c_uint(12)
libc.getsockname(fd, ctypes.byref(sa), ctypes.byref(ln))
sa.p = 0
libc.bind(fd, ctypes.byref(sa), 12)
P = ports()
tid = 0x5000
MODE = {0: "low-power", 1: "online", 2: "shutting-down", 3: "persistent-low-power",
        4: "mode-only-low-power", 5: "reset", 6: "offline"}


def call(svc, mid, tlvs, timeout=8):
    global tid
    tid += 1
    pkt = struct.pack("<BHHH", 0, tid, mid, len(tlvs)) + tlvs
    d = SA(AF_QIPCRTR, 0, P[svc])
    libc.sendto(fd, pkt, len(pkt), 0, ctypes.byref(d), ctypes.sizeof(d))
    dl = time.time() + timeout
    while time.time() < dl:
        r, _, _ = select.select([fd], [], [], max(0.1, dl - time.time()))
        if not r:
            break
        b = ctypes.create_string_buffer(16384)
        s = SA()
        l = ctypes.c_uint(12)
        n = libc.recvfrom(fd, b, 16384, 0, ctypes.byref(s), ctypes.byref(l))
        if n < 7:
            continue
        data = b.raw[:n]
        typ, rtid, rmid, hl = struct.unpack("<BHHH", data[:7])
        if rtid != tid:
            continue
        body = data[7:7 + hl]
        out = []
        i = 0
        while i + 3 <= len(body):
            t, ll = struct.unpack("<BH", body[i:i + 3])
            out.append((t, body[i + 3:i + 3 + ll]))
            i += 3 + ll
        return out
    return None


def show(tag, res):
    if res is None:
        print("%-18s no response" % tag)
        return
    for t, v in res:
        if t == 0x02:
            print("%-18s result=%d err=%d" % (tag, struct.unpack("<H", v[:2])[0], struct.unpack("<H", v[2:4])[0]))
        elif t == 0x01 and len(v) == 1:
            print("%-18s MODE=0x%02x (%s)" % (tag, v[0], MODE.get(v[0], "?")))
        else:
            print("%-18s TLV 0x%02x len=%d %s" % (tag, t, len(v), v[:12].hex(" ")))


show("GET before", call(2, 0x002D, b""))
print("--- set online ---")
show("SET online", call(2, 0x002E, struct.pack("<BHB", 0x01, 1, 0x01)))
time.sleep(3)
show("GET after 3s", call(2, 0x002D, b""))
