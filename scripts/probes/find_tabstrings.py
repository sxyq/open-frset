#!/usr/bin/env python3
# 扫描反汇编：找出短字符串（Small String 内联立即数）的代码构造点
# 原理：Swift 短字符串(<=15B)通过 movz/movk 立即数拼装；跟踪寄存器值，匹配目标字符串字节
import re, sys
from collections import defaultdict

TARGETS = [b"General", b"Search", b"Tools", b"Tool", b"Shortcuts", b"Shortcut",
           b"About", b"Pro", b"ProBadge", b"Settings", b"Window"]

FMT = r'^([0-9a-f]{16})\t([^\n;]*)(?:;(.*))?$'
insns = []
for ln in open('/tmp/disasm_live.txt', errors='replace'):
    m = re.match(FMT, ln.rstrip('\n'))
    if m:
        insns.append((int(m.group(1), 16), m.group(2).strip(), (m.group(3) or '').strip()))
print(f"总指令数: {len(insns)}", file=sys.stderr)

M64 = (1 << 64) - 1
regs = {}   # regnum -> (value, mask)

def regnum(name):
    n = name.strip()
    if not n or n[0] not in 'xw' or not n[1:].isdigit():
        return None
    return int(n[1:])

def invalidate(dst):
    regs.pop(dst, None)

hits = defaultdict(list)  # target -> [(addr, reg, inst)]
lo_masks = {}
for t in TARGETS:
    lo_masks[t] = (1 << (8 * len(t))) - 1
    lo_vals = None

target_int = {t: int.from_bytes(t, 'little') for t in TARGETS}

IMM_RE = re.compile(r'#(-?0x[0-9a-f]+|-?\d+)')
SHIFT_RE = re.compile(r'lsl\s+#(\d+)')

for addr, text, comment in insns:
    t = text.replace(',', ' ')
    parts = t.split()
    if not parts:
        continue
    op = parts[0]
    handled = False
    if op in ('movz', 'mov') and len(parts) >= 3:
        d = regnum(parts[1]); 
        if d is not None:
            m = IMM_RE.search(t)
            if m:
                imm = int(m.group(1), 0) & 0xFFFF
                sh = SHIFT_RE.search(t)
                shift = int(sh.group(1)) if sh else 0
                val = (imm << shift) & M64
                mask = (0xFFFF << shift) & M64
                wform = parts[1].startswith('w')
                if wform:
                    val &= 0xFFFFFFFF; mask = 0xFFFFFFFF & mask if mask & ~0xFFFFFFFF == 0 else mask
                    # w 写入：高 32 位清零
                    mask = mask if mask <= 0xFFFFFFFF else 0xFFFFFFFF
                    mask |= 0  # 高32位为0已知
                    regs[d] = (val & 0xFFFFFFFF, 0xFFFFFFFF)
                else:
                    regs[d] = (val, mask)
                handled = True
            else:
                # mov xN, xM 形式
                if len(parts) >= 3:
                    s = regnum(parts[2])
                    if s is not None:
                        if s in regs:
                            v, mk = regs[s]
                            if parts[1].startswith('w'):
                                regs[d] = (v & 0xFFFFFFFF, 0xFFFFFFFF)
                            else:
                                regs[d] = (v, mk)
                        else:
                            invalidate(d)
                        handled = True
                    else:
                        invalidate(d); handled = True
        else:
            handled = True
    elif op == 'movk' and len(parts) >= 3:
        d = regnum(parts[1])
        if d is not None:
            m = IMM_RE.search(t)
            if m:
                imm = int(m.group(1), 0) & 0xFFFF
                sh = SHIFT_RE.search(t)
                shift = int(sh.group(1)) if sh else 0
                if d in regs:
                    v, mk = regs[d]
                    nm = mk | ((0xFFFF << shift) & M64)
                    if parts[1].startswith('w'):
                        nm = 0xFFFFFFFF
                    v = (v & M64 & ~((0xFFFF << shift) & M64)) | ((imm << shift) & M64)
                    regs[d] = (v & M64, nm)
                    handled = True
                else:
                    handled = True
            handled = True
        else:
            handled = True
    if not handled:
        # 其他指令：若写了寄存器（第一个操作数），使其失效
        if len(parts) >= 2:
            d = regnum(parts[1])
            if d is not None:
                invalidate(d)
    # 匹配检查
    for d, (v, mk) in list(regs.items()):
        for tg in TARGETS:
            L = len(tg)
            lm = lo_masks[tg]
            if (mk & lm) == lm:
                if (v & lm) == target_int[tg]:
                    hits[tg].append((addr, f"x{d}", text, comment))

print("\n=== 匹配结果 ===")
for tg in TARGETS:
    hs = hits[tg]
    print(f"\n--- {tg.decode()} : {len(hs)} 处 ---")
    for addr, reg, text, comment in hs[:40]:
        print(f"  0x{addr:x}  [{reg}]  {text}   {('; ' + comment) if comment else ''}")
