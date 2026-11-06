#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import csv, struct, os

OUT = '/mnt/c/Users/Administrator/Desktop/meizu21note_Mu'
D = '/mnt/c/Users/Administrator/AppData/Local/Temp/ksuwork/dtbo_dump'

V = list(csv.DictReader(open('/tmp/q_merged.csv', encoding='utf-8-sig')))
N = list(csv.DictReader(open('/tmp/q_nura.csv', encoding='utf-8-sig')))
M = list(csv.DictReader(open('/tmp/q_21note.csv', encoding='utf-8-sig')))

# ---------- 1) 原厂dtbo结构.txt ----------
lines = []
lines.append('原厂 dtbo.img / dtbo_b.img 结构（魅族 21 Note m2468 / SM8550）')
lines.append('=' * 78)
for img in ('dtbo_a.img', 'dtbo_b.img'):
    p = os.path.join(D, img)
    d = open(p, 'rb').read(64)
    magic, total, hsz, esz, cnt, off, pgsz, ver = struct.unpack('>8I', d[:32])
    lines.append(f'\n### {img}  文件大小={os.path.getsize(os.path.join(D,img)):,} B')
    lines.append(f'  magic            = 0x{magic:08x}')
    lines.append(f'  total_size       = {total:,}')
    lines.append(f'  header_size      = {hsz}')
    lines.append(f'  dt_entry_size    = {esz}')
    lines.append(f'  dt_entry_count   = {cnt}')
    lines.append(f'  dt_entries_offset= {off}')
    lines.append(f'  page_size        = {pgsz}')
    lines.append(f'  version          = {ver}')
    fh = open(os.path.join(D, img), 'rb')
    lines.append('  idx  dt_size   dt_offset   id          rev         name  (根 meizu,board-id / chip-version)')
    meta = [('0x03 0x01', 'M2468 B1'), ('0x03 0x02', 'M2468 B1.1'), ('0x03 0x03', 'M2468 B2'),
            ('0x03 0x04', 'M2468 B2.1'), ('0x03 0x05', 'M2468 MP')]
    frags = [798, 801, 804, 812, 791]
    for i in range(cnt):
        fh.seek(off + i * esz)
        e = fh.read(esz)
        sz, o, idv, rev = struct.unpack('>4I', e[:16])
        name = e[16:144].split(b'\x00')[0].decode('utf-8', 'replace')
        lines.append(f'  [{i}]  {sz:>7,}  {o:>10,}  0x{idv:08x}  0x{rev:08x}  {name!r:<6} '
                     f'board-id=<{meta[i][0]}>  {meta[i][1]}  fragments={frags[i]}')
lines.append('''
说明
----
* 5 个 entry 的 id 全 0、name 全空 → bootloader 不做 id/name 匹配，按
  androidboot.dtbo_idx=<0..4> 选择；本机运行时 DT 为 meizu,board-id=<0x03 0x05>
  = M2468 MP = index 4。
* 每个 entry 是 798~812 个 fragment@N 组成的 overlay，target=<0xffffffff> 占位，
  真实目标由 __fixups__ 里的标签名在应用时替换。
* base DTB 来自 vendor_boot.img 里的 base_vb_0.dtb（518,252 B，
  model="Qualcomm Technologies, Inc. Kalama v2 SoC"，根下有 /soc）。
* dtbo_b.img 24 MiB 只是分区容量，内容与 dtbo_a.img 的 5 个 entry 完全相同。

原厂 aliases（SE 编号 ↔ 地址，实测）
-----------------------------------
se0  = 0xa80000   se1  = 0xa84000   se2  = 0xa88000   se3  = 0xa8c000
se4  = 0xa90000   se5  = 0xa94000   se6  = 0xa98000   se7  = 0xa9c000 (2uart/console)
se8  = 0x880000   se9  = 0x884000   se10 = 0x888000   se11 = 0x88c000
se12 = 0x890000   se13 = 0x894000   se14 = 0x898000 (4uart/BT)   se15 = 0x89c000
hub_i2c0..9 = 0x980000 0x984000 0x988000 0x98c000 0x990000 0x994000 0x998000 0x99c000 0x9a0000 0x9a4000
wrapper: qupv3_1 = 0xac0000 (se0-7) / qupv3_2 = 0x8c0000 (se8-15) / qupv3_0_i2c_hub = 0x9c0000 (hub0-9)
与 mainline sm8550.dtsi 的 i2c0..i2c15 / uart7 / serial@898000 / i2c_hub_0..9 编号完全一致。
''')
open(os.path.join(OUT, '原厂dtbo结构.txt'), 'w', encoding='utf-8').write('\n'.join(lines))

# ---------- 2) 差集（按 reg+功能，而非仅 reg） ----------
def key(rows, only_enabled):
    d = {}
    for r in rows:
        if r['kind'] != 'SE':
            continue
        if 'geni-se-qup' in r['compatible'] or 'geni-se-i2c-master-hub' in r['compatible']:
            continue
        if only_enabled and r['status'] not in ('ok', 'okay'):
            continue
        for part in r['reg_resolved'].split():
            if part.startswith('0x'):
                a = int(part.split('+')[0], 16)
                fn = r['name'].split('@')[0]
                if 'uart' in fn or 'serial' in fn:
                    fn = 'uart'
                elif fn.startswith('i3c'):
                    fn = 'i3c'
                d.setdefault((a, fn), r)
    return d

vk, nk, mk = key(V, True), key(N, True), key(M, True)
out = []
out.append('# 以 (reg基址, 功能) 为单位的启用差集：nura = sm8550-meizu-nura.dts(m2381 mainline)，'
           '原厂 = m2468 base+dtbo')
out.append('')
out.append('## A. nura 启用、原厂 m2468 未启用（照抄会点亮一条空总线/被别的功能占用的块）')
for k in sorted(nk):
    if k not in vk:
        r = nk[k]
        same = [x for x in vk if x[0] == k[0]]
        note = f'  ← 同址原厂启用的是 {same[0][1]}' if same else ''
        out.append(f'  0x{k[0]:x}  {r["name"]:22s} {r["compatible"]:30s}{note}')
out.append('')
out.append('## B. 原厂 m2468 启用、nura 未启用（m2468 独有，必须自己补）')
for k in sorted(vk):
    if k not in nk:
        r = vk[k]
        same = [x for x in nk if x[0] == k[0]]
        note = f'  ← 同址 nura 启用的是 {same[0][1]}' if same else ''
        out.append(f'  0x{k[0]:x}  {r["name"]:22s} {r["compatible"]:30s}{note}')
out.append('')
out.append('## C. 同一 reg 块，两边都启用但功能类型不同（同一 SE 不能同时是 I2C 和 SPI）')
addrs = {}
for a, f in list(nk) + list(vk):
    addrs.setdefault(a, {'nura': set(), 'vendor': set()})
    addrs[a]['nura' if (a, f) in nk else 'vendor'].add(f)
for a in sorted(addrs):
    d = addrs[a]
    if d['nura'] and d['vendor'] and (d['nura'] | d['vendor']) != (d['nura'] & d['vendor']):
        out.append(f'  0x{a:x}: nura={"/".join(sorted(d["nura"]))}   原厂={"/".join(sorted(d["vendor"]))}')
open(os.path.join(OUT, '差集_m2381mainline相对原厂m2468.txt'), 'w', encoding='utf-8').write('\n'.join(out))
print('\n'.join(out[:40]))
print('\nOK')
