import re, collections

p = "/mnt/c/Users/Administrator/Desktop/meizu21note_Mu/modem_re/modem.b19"
d = open(p, 'rb').read()
strs = [s.decode('ascii','replace') for s in re.findall(rb'[ -~]{4,220}', d)]

def grep(pat, n=45, label=None):
    rx = re.compile(pat, re.I)
    seen, out = set(), []
    for s in strs:
        if rx.search(s) and s not in seen:
            seen.add(s); out.append(s)
    print(f"\n===== {label or pat}  ({len(out)}) =====")
    for s in out[:n]:
        print("  ", s[:180])

grep(r'ipcr', 40, 'ipcr (QRTR)')
grep(r'sock.*(port|svc|service)|(port|svc|service).*sock', 30, 'socket/port/service')
grep(r'tftp.*(option|opt_)|TFTP_PKT_OPTION', 40, 'TFTP options')
grep(r'rfs_cfg|rfs_desc|rfs_nodev|rfs_qdi', 30, 'rfs 内部模块')
grep(r'(discovery_path|rfs_path|root_path|mount)', 30, '路径映射')
grep(r'/pdp|/nv|/efs|/boot|/rfs|/readonly|/readwrite|/hlos|/partition', 45, 'RFS 路径前缀')

# 找形如 "tftp" 的短串 + 数字常量附近
print("\n===== 含 tftp 且带数字的串 =====")
for s in strs:
    if re.search(r'tftp', s, re.I) and re.search(r'\d', s):
        print("  ", s[:180])
