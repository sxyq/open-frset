#!/usr/bin/env python3
# da.py — 反汇编分析工具（函数边界/窗口/调用者/被调用）
import re, sys, bisect

FMT = re.compile(r'^([0-9a-f]{16})\t(.*)$')
insns = []
for ln in open('/tmp/disasm_live.txt', errors='replace'):
    m = FMT.match(ln.rstrip('\n'))
    if m:
        insns.append((int(m.group(1), 16), m.group(2).strip()))
addrs = [a for a, _ in insns]
print(f"# 指令数 {len(insns)}", file=sys.stderr)

def idx(a):
    return bisect.bisect_left(addrs, a)

def win(lo, hi, cap=200):
    out = []
    for a, t in insns:
        if a > hi:
            break
        if a >= lo:
            out.append(f"{a:016x}\t{t}")
            if len(out) >= cap:
                out.append("...(capped)")
                break
    return "\n".join(out)

def fstart(a):
    i = idx(a)
    while i > 0:
        i -= 1
        if re.match(r'^(ret|retaa|retab)\b', insns[i][1]):
            return insns[i + 1][0]
    return insns[0][0]

def callers(target, cap=20):
    out = []
    for a, t in insns:
        if re.search(rf'\b(bl|b)\s+0x{target:x}\b', t):
            out.append((a, t))
            if len(out) >= cap:
                break
    return out

def callees(lo, hi):
    from collections import Counter
    c = Counter()
    for a, t in insns:
        if a > hi:
            break
        if a >= lo:
            m = re.search(r'bl\s+(0x[0-9a-f]+)', t)
            if m:
                c[int(m.group(1), 16)] += 1
    return c

if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'win':
        print(win(int(sys.argv[2], 0), int(sys.argv[3], 0), int(sys.argv[4]) if len(sys.argv) > 4 else 200))
    elif cmd == 'fstart':
        a = int(sys.argv[2], 0)
        s = fstart(a)
        print(f"函数起点: 0x{s:x}")
    elif cmd == 'callers':
        t = int(sys.argv[2], 0)
        rs = callers(t)
        print(f"0x{t:x} 调用者 {len(rs)} 处:")
        for a, txt in rs:
            s = fstart(a)
            print(f"  {a:016x} (函数 0x{s:x})\t{txt[:100]}")
    elif cmd == 'callees':
        lo, hi = int(sys.argv[2], 0), int(sys.argv[3], 0)
        for t, n in sorted(callees(lo, hi).items()):
            print(f"  bl 0x{t:x} × {n}")
    elif cmd == 'fwin':
        # 打印包含该地址的整个函数
        a = int(sys.argv[2], 0)
        s = fstart(a)
        # 找函数结束：下一个 ret
        i = idx(s)
        end = a
        for j in range(i, len(insns)):
            end = insns[j][0]
            if re.match(r'^(ret|retaa|retab)\b', insns[j][1]):
                break
        print(f"# 函数 0x{s:x} - 0x{end:x}", file=sys.stderr)
        print(win(s, end, int(sys.argv[3]) if len(sys.argv) > 3 else 400))
