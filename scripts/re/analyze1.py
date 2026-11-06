import re, collections, sys

p = "/mnt/c/Users/Administrator/Desktop/meizu21note_Mu/modem_re/modem.b19"
d = open(p, 'rb').read()
print("大小:", len(d))

strs = re.findall(rb'[ -~]{4,200}', d)
strs = [s.decode('ascii', 'replace') for s in strs]
print("可读串总数:", len(strs))

def grep(pat, n=40, label=None):
    rx = re.compile(pat, re.I)
    hits = [s for s in strs if rx.search(s)]
    seen, out = set(), []
    for s in hits:
        if s not in seen:
            seen.add(s); out.append(s)
    print(f"\n===== {label or pat}  ({len(out)} 个唯一) =====")
    for s in out[:n]:
        print("  ", s[:170])
    return out

grep(r'rfsa', 30, 'rfsa (GLINK 通道名)')
grep(r'^rfs|rfs_', 45, 'rfs_ 前缀')
grep(r'tftp', 35, 'tftp')

print("\n===== 全大写标识符候选（可能是通道名）=====")
caps = collections.Counter(s for s in strs if re.fullmatch(r'[A-Z][A-Z0-9_]{3,19}', s))
for s, c in caps.most_common(50):
    print(f"  {s:26s} x{c}")
