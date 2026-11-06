#!/usr/bin/env python3
import sys, json, struct, csv, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fdtparse import build, pstr, cells, reg_pairs

KEY = ('i2c', 'spi', 'qup', 'geni_se', 'qupv3', 'i3c', 'uart@', 'serial@')

def reg_of(node, ac, sc):
    v = node['props'].get('reg')
    if not v: return ''
    out = []
    for a, sz in reg_pairs(v, ac, sc):
        out.append(f'0x{a:x}' + (f'(0x{sz:x})' if sz else ''))
    return ','.join(out)

def walk(node, path, ac=2, sc=2, res=None, depth=0):
    nm = node['name']
    props = node['props']
    nac = props.get('#address-cells'); nsc = props.get('#size-cells')
    cac = cells(nac)[0] if nac else ac
    csc = cells(nsc)[0] if nsc else sc
    comp = pstr(props.get('compatible', b'')) if 'compatible' in props else ''
    if depth > 0 and any(k in nm for k in KEY):
        res.append({
            'path': path,
            'name': nm,
            'reg': reg_of(node, ac, sc),
            'compatible': comp,
            'status': pstr(props.get('status', b'<none>')),
            'clocks': str(cells(props['clocks'])) if 'clocks' in props else '',
            'clock-names': pstr(props.get('clock-names', b'')) if 'clock-names' in props else '',
            'pinctrl-names': pstr(props.get('pinctrl-names', b'')) if 'pinctrl-names' in props else '',
            'pinctrl-0': str(cells(props['pinctrl-0'])) if 'pinctrl-0' in props else '',
            'interrupts': str(cells(props['interrupts'])) if 'interrupts' in props else '',
            'interconnects': str(cells(props['interconnects'])) if 'interconnects' in props else '',
            'power-domains': str(cells(props['power-domains'])) if 'power-domains' in props else '',
            'operating-points-v2': str(cells(props['operating-points-v2'])) if 'operating-points-v2' in props else '',
            'required-opps': str(cells(props['required-opps'])) if 'required-opps' in props else '',
            'dma-names': pstr(props.get('dma-names', b'')) if 'dma-names' in props else '',
            'label': pstr(props.get('label', b'')) if 'label' in props else '',
            'parent': path.rsplit('/', 1)[0] or '/',
        })
    for ch in node['children']:
        walk(ch, path.rstrip('/') + '/' + ch['name'], cac, csc, res, depth + 1)
    return res

if __name__ == '__main__':
    root = build(sys.argv[1])
    rows = walk(root, '/', 2, 2, [], 0)
    if len(sys.argv) > 2 and sys.argv[2] == 'csv':
        w = csv.DictWriter(sys.stdout, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    else:
        for r in rows:
            print(f"{r['path']}\n    compatible={r['compatible']}\n    reg={r['reg']} status={r['status']}")
