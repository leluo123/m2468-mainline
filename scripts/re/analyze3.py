import re, collections
p = "/mnt/c/Users/Administrator/Desktop/meizu21note_Mu/modem_re/modem.b19"
d = open(p,'rb').read()
strs = [s.decode('ascii','replace') for s in re.findall(rb'[ -~]{4,220}', d)]

def grep(pat, n=40, label=None):
    rx = re.compile(pat, re.I)
    seen, out = set(), []
    for s in strs:
        if rx.search(s) and s not in seen:
            seen.add(s); out.append(s)
    print(f"\n===== {label or pat} ({len(out)}) =====")
    for s in out[:n]: print("  ", s[:170])

grep(r'mink', 40, 'mink')
grep(r'rfs.*(name|svc|service|server)|(name|svc|service|server).*rfs', 30, 'rfs/service')
grep(r'efs_sync|efssync|efs_service', 20, 'efs_sync')
grep(r'qrtr', 30, 'qrtr')
grep(r'^/rfs', 40, 'RFS 绝对路径')

print("\n===== 数字常量式服务名（svc_/SVC_/port）=====")
for s in strs:
    if re.search(r'(svc|service|port)[_ ]?\d', s, re.I) and len(s) < 90:
        print("  ", s[:150])
