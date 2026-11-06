#!/usr/bin/env python3
"""Minimal FDT parser -> tree for QUP/I2C inventory."""
import struct, sys, json

class FDT:
    def __init__(self, path):
        self.b = open(path, 'rb').read()
        magic, tot, off_struct, off_strings, off_rsv, ver, lastcomp, bootcpu, size_strings, size_struct = \
            struct.unpack('>10I', self.b[:40])
        assert magic == 0xd00dfeed, hex(magic)
        self.off_struct = off_struct
        self.off_strings = off_strings
        self.size_struct = size_struct

    def s(self, off):
        e = self.b.index(b'\x00', self.off_strings + off)
        return self.b[self.off_strings + off:e].decode('utf-8', 'replace')

    def walk(self):
        pos = self.off_struct
        end = pos + self.size_struct
        depth = 0
        while pos < end:
            tok, = struct.unpack('>I', self.b[pos:pos+4]); pos += 4
            if tok == 1:
                e = self.b.index(b'\x00', pos)
                name = self.b[pos:e].decode('utf-8', 'replace'); pos = (e + 1 + 3) & ~3
                depth += 1
                yield ('BEGIN', depth, name)
            elif tok == 2:
                yield ('END', depth, None)
                depth -= 1
            elif tok == 3:
                ln, noff = struct.unpack('>II', self.b[pos:pos+8]); pos += 8
                # name string offset is relative to off_strings
                name = self.s(noff)
                val = self.b[pos:pos+ln]; pos += ln
                pos = (pos + 3) & ~3
                yield ('PROP', depth, name, val)
            elif tok == 4:
                pass
            elif tok == 9:
                break
            else:
                raise SystemExit(f'bad token {tok} at {pos}')

def build(path):
    f = FDT(path)
    root = {'name': '/', 'path': '/', 'props': {}, 'children': []}
    stack = [root]
    for item in f.walk():
        if item[0] == 'BEGIN':
            node = {'name': item[2], 'path': (stack[-1]['path'].rstrip('/') + '/' + item[2]), 'props': {}, 'children': []}
            stack[-1]['children'].append(node)
            stack.append(node)
        elif item[0] == 'END':
            if len(stack) > 1: stack.pop()
        elif item[0] == 'PROP':
            stack[-1]['props'][item[2]] = item[3]
    return root

def pstr(v):
    try: return v.rstrip(b'\x00').decode('utf-8')
    except: return repr(v)

def cells(v):
    return [struct.unpack('>I', v[i:i+4])[0] for i in range(0, len(v) - len(v) % 4, 4)]

def reg_pairs(v, ac, sc):
    c = cells(v); out = []; i = 0
    while i + ac + sc <= len(c) and ac + sc > 0:
        a = 0
        for k in range(ac): a = (a << 32) | c[i+k]
        sz = 0
        for k in range(sc): sz = (sz << 32) | c[i+ac+k]
        out.append((a, sz)); i += ac + sc
    return out

if __name__ == '__main__':
    json.dump(build(sys.argv[1]), sys.stdout)
