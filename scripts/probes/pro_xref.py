#!/usr/bin/env python3
"""Pro UI 字符串交叉引用分析（当前构建）"""
import re, bisect, sys

data = open('/tmp/frset_cur_arm64','rb').read()
insns = []
for ln in open('/tmp/disasm_pro.txt', errors='replace'):
    m = re.match(r'^([0-9a-f]{16})\t(.*)$', ln.rstrip('\n'))
    if m:
        insns.append((int(m.group(1),16), m.group(2)))
print("insns:", len(insns))

def va_of(s):
    i = data.find(s.encode())
    return 0x100000000 + i if i >= 0 else None

# 函数起点启发式
starts = set()
prev_end = None
for i,(addr,text) in enumerate(insns):
    if prev_end is not None and addr != prev_end:
        starts.add(addr)
    if re.match(r'^(ret|retaa|retab|b)\b', text):
        if i+1 < len(insns):
            starts.add(insns[i+1][0])
    prev_end = addr+4
starts = sorted(starts)

def enclosing(a):
    i = bisect.bisect_right(starts, a)-1
    return starts[i] if i>=0 else None

# 预收集所有 adrp
adrps = []
rx = re.compile(r'adrp\s+([xw]\d+), (\d+) ; (0x[0-9a-f]+)')
for idx,(addr,text) in enumerate(insns):
    if 'adrp' in text:
        m = rx.match(text)
        if m: adrps.append((idx, addr, m.group(1), int(m.group(3),16)))

by_page = {}
for idx, addr, reg, page in adrps:
    by_page.setdefault(page, []).append((idx, addr, reg))

def xref_sites(va):
    page = va & ~0xFFF; lo = va & 0xFFF
    sites = []
    for idx, addr, reg in by_page.get(page, []):
        for j in range(idx+1, min(idx+5, len(insns))):
            t = insns[j][1]
            m2 = re.match(rf'add\s+{reg}, {reg}, #(0x[0-9a-f]+|\d+)', t)
            if m2:
                low = int(m2.group(1), 16) if m2.group(1).startswith('0x') else int(m2.group(1))
                if low == lo:
                    sites.append(addr)
                break
            if re.match(rf'ldr\s+{reg},', t): break
    return sites

targets = sys.argv[1:] if len(sys.argv) > 1 else [
 "Lifetime Access Active", "Manage Subscription", "Lifetime Member Day %d",
 "Restore Purchase", "Subscription Details Unavailable", "Annual Renewal Active",
 "Monthly Renewal Active", "Quarterly Renewal Active", "Renewal Canceled Until %@",
 "Renewal Price Unavailable", "Lifetime Renewal Reminder",
 "Upgrade to Pro", "Buy Lifetime Access", "Start Free Trial", "Subscribe for %@",
 "com.frset.pro.lifetime",
]
for s in targets:
    va = va_of(s)
    if va is None:
        print(f"\n### [NOT-FOUND] {s}"); continue
    sites = xref_sites(va)
    funcs = {}
    for site in sites:
        funcs.setdefault(enclosing(site), []).append(site)
    print(f"\n### [{s}] va=0x{va:x}  引用 {len(sites)} 处")
    for fs, ss in sorted(funcs.items()):
        print(f"   func 0x{fs:x}:  {[hex(x) for x in ss]}")
