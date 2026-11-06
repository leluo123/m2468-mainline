#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Final tables: comparison + attribute diff (vendor m2468 vs mainline sm8550.dtsi)."""
import csv, os

OUT = '/mnt/c/Users/Administrator/Desktop/meizu21note_Mu'
os.makedirs(OUT, exist_ok=True)
V = list(csv.DictReader(open('/tmp/q_merged.csv', encoding='utf-8-sig')))
L = list(csv.DictReader(open('/tmp/q_live.csv', encoding='utf-8-sig')))
N = list(csv.DictReader(open('/tmp/q_nura.csv', encoding='utf-8-sig')))
M = list(csv.DictReader(open('/tmp/q_21note.csv', encoding='utf-8-sig')))
B = list(csv.DictReader(open('/tmp/q_base.csv', encoding='utf-8-sig')))


def index(rows):
    d = {}
    for r in rows:
        for part in r['reg_resolved'].split():
            if part.startswith('0x'):
                a = int(part.split('+')[0], 16)
                d.setdefault(a, []).append(r)
    return d


vi, li, ni, mi, bi = index(V), index(L), index(N), index(M), index(B)

ML = {
 0x8c0000: 'qupv3_id_1 / geniqup@8c0000', 0x9c0000: 'i2c_master_hub_0 / geniqup@9c0000',
 0xac0000: 'qupv3_id_0 / geniqup@ac0000',
 0x880000: 'i2c8', 0x884000: 'i2c9', 0x888000: 'i2c10', 0x88c000: 'i2c11',
 0x890000: 'i2c12', 0x894000: 'i2c13', 0x898000: 'serial@898000(BT)', 0x89c000: 'i2c15',
 0x980000: 'i2c_hub_0', 0x984000: 'i2c_hub_1', 0x988000: 'i2c_hub_2', 0x98c000: 'i2c_hub_3',
 0x990000: 'i2c_hub_4', 0x994000: 'i2c_hub_5', 0x998000: 'i2c_hub_6', 0x99c000: 'i2c_hub_7',
 0x9a0000: 'i2c_hub_8', 0x9a4000: 'i2c_hub_9',
 0xa80000: 'i2c0', 0xa84000: 'i2c1', 0xa88000: 'i2c2', 0xa8c000: 'i2c3',
 0xa90000: 'i2c4', 0xa94000: 'i2c5', 0xa98000: 'i2c6', 0xa9c000: 'uart7(console)',
}


def pick(lst, kinds=('WRAPPER', 'SE')):
    for r in lst:
        if r['kind'] in kinds:
            return r
    return None


def kids_of(rows, path):
    out = []
    for r in rows:
        if r['path'].startswith(path + '/'):
            rel = r['path'][len(path) + 1:]
            if '/' not in rel:
                out.append(f"{r['name']}({r['compatible'] or '?'},st={r['status'] or 'unset'})")
    return '; '.join(out)


W = csv.writer(open(os.path.join(OUT, 'qup_i2c_对照表.csv'), 'w', newline='', encoding='utf-8-sig'))
W.writerow(['reg基址', 'mainline标签(sm8550.dtsi)', '原厂base(vendor_boot)', '原厂合成后(m2468)',
            '原厂compatible', '原厂status', '原厂子设备', '同址其它功能节点',
            'liveDT', 'nura(m2381)', 'meizu-21note', '判定'])
def status_of(d, a):
    r = pick(d.get(a, []))
    return (r['status'] or 'unset') if r else '—'

for a in sorted(set(list(vi) + list(ML))):
    if a < 0x880000 or a > 0xac0000:
        continue
    vr = pick(vi.get(a, []))
    others = [r for r in vi.get(a, []) if vr and r['path'] != vr['path'] and r['kind'] == 'SE']
    if a in (0x8c0000, 0x9c0000, 0xac0000):
        verdict = 'QUP wrapper(存在)'
    elif not vr:
        verdict = '原厂无此节点'
    elif (vr['status'] or '') in ('ok', 'okay'):
        verdict = '原厂启用=真实在用'
    else:
        verdict = '原厂存在但未启用'
    W.writerow([f'0x{a:x}', ML.get(a, '—'),
                status_of(bi, a), status_of(vi, a),
                vr['compatible'] if vr else '—', status_of(vi, a),
                kids_of(V, vr['path']) if vr else '',
                ' | '.join(f"{r['name']}={r['compatible']},st={r['status']}" for r in others),
                status_of(li, a), status_of(ni, a), status_of(mi, a), verdict])

# attribute diff table
FIELDS = ['compatible', 'status', 'clocks', 'clock-names', 'pinctrl-names', 'pinctrl-0',
          'interrupts', 'interconnects', 'interconnect-names', 'power-domains',
          'operating-points-v2', 'dma-names', 'iommus', 'dma-coherent', 'qcom,clk-freq-out',
          'qcom,i2c-hub']
A = csv.writer(open(os.path.join(OUT, '属性差异_原厂vs主线.csv'), 'w', newline='', encoding='utf-8-sig'))
A.writerow(['节点(reg基址)', '属性', '原厂m2468', 'mainline sm8550.dtsi / 我方dts', '差异说明'])
for a, mlpath in [(0x8c0000, 'geniqup@8c0000'), (0x9c0000, 'geniqup@9c0000'), (0xac0000, 'geniqup@ac0000'),
                  (0xa80000, 'i2c@a80000'), (0x89c000, 'i2c@89c000'), (0x988000, 'i2c@988000')]:
    vr = pick(vi.get(a, []))
    mr = pick(mi.get(a, []))
    for f in FIELDS:
        vv = (vr or {}).get(f, '')
        mv = (mr or {}).get(f, '')
        if not vv and not mv:
            continue
        note = ''
        if f == 'clocks' and vv != mv:
            note = '时钟引用不同(phandle/ID不同属正常)，关注时钟个数'
        elif f == 'clock-names' and vv != mv:
            note = '⚠ 时钟名不同: 原厂用 se-clk/core-clk，主线要 se/core'
        elif f in ('power-domains', 'operating-points-v2') and not vv and mv:
            note = '主线独有(下游由 clock/regulator 框架代替)，缺它会导致寄存器访问前未能上电'
        elif f == 'iommus' and vv and not mv:
            note = '原厂 wrapper 带 SMMU sid，主线 wrapper 无(主线在 SE 上不使用)'
        elif f == 'qcom,i2c-hub' and vv and not mv:
            note = '原厂 hub SE 标记属性，主线用 compatible=qcom,geni-i2c-master-hub 代替'
        A.writerow([f'0x{a:x} {mlpath}', f, vv, mv, note])

# 9c800000 evidence file
with open(os.path.join(OUT, '0x9c800000_查证.txt'), 'w', encoding='utf-8') as f:
    f.write("""0x9c800000 查证结果
====================
1) 原厂 m2468 设备树(base_vb_0 + dtbo 合成, /soc 共 500+ 节点)中：
   没有任何节点的 reg 落在 0x9c8000_00xx 区间 → 0x9c800000 这个地址在原厂树中不存在。
   二进制级验证：对 merged_full.dtb / live.dtb / sm8550-meizu-21note.dtb / 各 dtbo entry 做
   `strings` 查找 "9c800000"，0 命中（DTB 里节点名形如 i2c@9c800000，若存在必然命中）。

2) mainline(6.14.11) arch/arm64/boot/dts/qcom/sm8550*.dtsi 中同样没有 0x9c8000/0x9c800000。
   全树 grep "9c80" → 0 命中。

3) 原厂树里真实存在的"9c"开头 MMIO：
   0x9c0000  qcom,qupv3_i2c_geni_se@9c0000  (compatible=qcom,geni-se-qup, reg 0x9c0000+0x2000, status=ok)
             └─ 10 个 I2C hub SE: 0x980000 0x984000 0x988000 0x98c000 0x990000 0x994000 0x998000
                0x99c000 0x9a0000 0x9a4000（仅 0x988000 status=ok）

4) 0x9c800000 在原厂 m2468 的 reserved-memory 里落在
   cvp_region@9c200000 (0x9c200000 + 0x700000，即 0x9c200000-0x9c900000)，属性 no-map
   —— 即 CVP(视觉处理固件)保留区，被 XPU/TZ 保护，AP 侧任何 ioremap 后的读写都会
   触发 synchronous external abort。

结论：`geni_i2c 9c800000.i2c` 只能来自一份**地址写错的自制 DT**（把 0x9c0000 的量级写错，
或误把某个保留区地址当成 SE 基址）。它不属于原厂 m2468 的硬件拓扑，改任何"节点属性"
都救不了，必须改成真实存在的 SE 基址。
""")
print('done')
