#!/usr/bin/env python3
"""QUP/GENI/I2C inventory: only nodes inside QUP wrappers (+ CCI / camera i2c separately)."""
import sys, os, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fdtparse import build, pstr, cells, reg_pairs

TXT = ('compatible', 'status', 'clock-names', 'pinctrl-names', 'interconnect-names',
       'label', 'qcom,i2c-touch-active', 'interrupt-names', 'qcom,rtl_se')
NUM1 = ('#address-cells', '#size-cells', 'clock-frequency', 'bus-frequency')
PROPS = ['compatible', 'reg', 'status', 'clocks', 'clock-names', 'clock-frequency',
         'pinctrl-names', 'pinctrl-0', 'pinctrl-1', 'interrupts', 'interrupt-names',
         'interconnects', 'interconnect-names', 'power-domains', 'required-opps',
         'operating-points-v2', 'dma-names', 'dmas', '#address-cells', '#size-cells',
         'label', 'qcom,i2c-touch-active', 'qcom,rtl_se']

def val(name, v):
    if name in TXT: return pstr(v)
    if name in NUM1:
        c = cells(v); return str(c[0]) if c else ''
    return ' '.join(f'0x{x:x}' for x in cells(v))

def main(path, outcsv, outtxt):
    root = build(path)
    rows = []

    def reg_str(node, ac, sc):
        v = node['props'].get('reg')
        if not v: return ''
        return ' '.join(f'0x{a:x}+0x{s:x}' for a, s in reg_pairs(v, ac, sc))

    def rec(node, p, ac, sc, level, mode):
        props = node['props']
        cac = cells(props['#address-cells'])[0] if '#address-cells' in props else ac
        csc = cells(props['#size-cells'])[0] if '#size-cells' in props else sc
        comp = pstr(props.get('compatible', b'')) if 'compatible' in props else ''
        nm = node['name']
        if 'pinctrl@' in nm:
            return
        if 'geni-se' in comp or 'geniqup' in nm or 'geni_se' in nm or 'qupv3' in nm:
            mode = 'qup'
        if 'cci' in nm.lower() or 'cci' in comp:
            mode = 'cci'
        if mode:
            nm_base = nm.split('@')[0]
            if 'geni-se-qup' in comp or nm_base in ('geniqup', 'qcom,qupv3_1_geni_se', 'qcom,qupv3_2_geni_se',
                                                   'qcom,qupv3_i2c_geni_se'):
                kind = 'WRAPPER'
            elif nm_base in ('i2c', 'spi', 'uart', 'serial', 'i3c-master', 'qcom,qup_uart'):
                kind = 'SE'
            else:
                kind = 'DEVICE'
            r = {'path': p, 'kind': kind, 'level': level, 'name': nm}
            for pr in PROPS:
                r[pr] = val(pr, props[pr]) if pr in props else ''
            r['reg_resolved'] = reg_str(node, ac, sc)
            r['n_children'] = len(node['children'])
            rows.append(r)
        for ch in node['children']:
            rec(ch, p.rstrip('/') + '/' + ch['name'], cac, csc, level + 1, mode)

    for top in root['children']:
        rec(top, '/' + top['name'], 2, 2, 1, None)

    fields = ['path', 'kind', 'level', 'name', 'compatible', 'reg_resolved', 'reg', 'status',
              'clocks', 'clock-names', 'clock-frequency', 'pinctrl-names', 'pinctrl-0',
              'interrupts', 'interconnect-names', 'interconnects', 'power-domains',
              'required-opps', 'operating-points-v2', 'dma-names', 'label', 'n_children']
    with open(outcsv, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        for r in rows: w.writerow(r)
    with open(outtxt, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(f"[{r['kind']}] {r['path']}\n")
            f.write(f"    compatible = {r['compatible'] or '(none)'}\n")
            if r['reg_resolved']: f.write(f"    reg = {r['reg_resolved']}\n")
            f.write(f"    status = {r['status'] or '(unset=>enabled)'}\n")
            for k in ('clocks', 'clock-names', 'clock-frequency', 'pinctrl-names', 'pinctrl-0',
                      'interrupts', 'interconnect-names', 'interconnects', 'power-domains',
                      'required-opps', 'dma-names'):
                if r.get(k): f.write(f"    {k} = {r[k]}\n")
    print(f'{len(rows)} rows -> {outcsv}')

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3])
