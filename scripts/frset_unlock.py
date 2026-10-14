#!/usr/bin/env python3
"""
frset_unlock.py — Frset.app 内购解锁一体化工具（唯一有效脚本）

子命令：
  xrefs     扫描 arm64 反汇编，定位引用指定 vaddr 的函数（默认：4 个内购产品 ID）
  callers   定位调用指定 StoreKit 符号（stub）的函数
  func      导出指定地址函数（到下一个 ret 为止）的反汇编
  strings   列出二进制中与内购相关的字符串及文件偏移
  forge     激活：伪造本地权益记录（ISO8601 JSON），使 App 认为自己是终身会员
  patch     对 arm64 slice 应用二进制补丁（从补丁清单 JSON 读取）
  sign      对 app 做 ad-hoc 重签名（带 get-task-allow；内置补丁校验防呆）
  package   把 app 重新封装为 DMG（内置补丁校验防呆）

说明：正版原 DMG 与解包副本已按“只保留唯一版本”清理；
      APP 默认指向 /Applications/Frset.app（手动安装解锁版后的标准位置）。
"""
import argparse, json, os, re, subprocess, sys, shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = "/Applications/Frset.app"
BIN = os.path.join(APP, "Contents", "MacOS", "Frset")
SLICE = "/tmp/Frset-arm64"          # arm64 薄片（分析/补丁用）
DISASM = "/tmp/frset-disasm.txt"    # otool -tV 输出
SECTIONS = "/tmp/frset-sections.json"
VADDR_BASE = 0x100000000            # 本二进制 vaddr = base + fileoff

# 两处解锁补丁的校验字节（arm64 slice, vaddr → 文件偏移 = vaddr - 0x100000000）
# 注意：补丁A 曾用 case 0(verifiedActive)，消费者会解引用其 nil 载荷导致快捷键闪退，
#       改为 case 3(inconclusive) 后刷新保留原状态、不崩溃（2026-10-14 实测）。
PATCH_MARKERS = {
    0x10031c190: "63008052",   # 补丁A: mov w1, #0x3 (inconclusive，刷新不清状态)
    0x100314e60: "1f2003d5",   # 补丁B: nop（启动决策不再因 cache=false 直接返回）
}

# 遥测斩断补丁校验字节（2026-10-14 追加，补丁D/E/F）：PostHog/Sentry 全部外传域名
# 已替换为 .invalid 死域名（RFC 2606 保留 TLD，永不解析），斩断
# 「钥匙串锚点 → PostHog 心跳/事件」与「Sentry 崩溃上报」两条外传链路。
# ⚠️ 字符串补丁铁律：必须等长且【零 NUL】——Swift 常量字符串自带长度头，NUL 填充会被
#    算入字符串本体，使 URL(string:) 解析失败 → 强解包崩溃（实证：Frset-2026-10-14-122856.ips）。
# 格式：{vaddr: (期望字节hex, 字节数)}
TELEMETRY_MARKERS = {
    0x100b4bde9: ("6e6f2e74656c656d657472792e686572652e657665722e73656e7472792e696e76616c6964", 37),  # Sentry DSN host
    0x100b4c820: ("68747470733a2f2f70682d6c6f63616c2e696e76616c6964", 24),  # PostHog US host
    0x100b59c40: ("68747470733a2f2f70682d6c6f63616c2e696e76616c6964", 24),  # PostHog EU host
    0x100b59c60: ("68747470733a2f2f70682d6173736574732d6c6f63616c2e696e76616c6964", 31),  # PostHog EU assets
    0x100b59c80: ("68747470733a2f2f70682d6173736574732d6c6f63616c2e696e76616c6964", 31),  # PostHog US assets
}

# Pro UI 清理补丁（2026-10-14 追加，补丁G）：订阅管理页 URL → 死链；
# 另配合全部 22 语言 Localizable.strings 中 Pro/订阅文案清空（资源层，不入二进制校验）
# 2026-10-14 追加（Pro 清理套装2，字节级）：
#   - "Pro"列头文本 → 零宽空格 U+200B（表格列头不可见）
#   - "gift" SF Symbol → "zzzz"（Redeem 按钮图标渲染为空）
#   - "settings_pro_logo" → "settings_pr0_logo"（图片名失效 → 徽章不加载）
#   另配合 Assets.car 内 6 个 settings_pro* 资源名统一改坏（settings_pr0*，24 处）
PROUI_MARKERS = {
    0x100b52ac0: ("68747470733a2f2f737562736372697074696f6e732d706167652d69732d676f6e6578782e696e76616c6964", 44),  # subscriptions URL → dead
    0x100637754: ("401c9052", 4),  # mov w0,#0x80E2 (ZWSP首段)
    0x100637758: ("6011a072", 4),  # movk w0,#0x8b,lsl16
    0x100639ca8: ("404f8f52", 4),  # mov w0,#0x7a7a ("zz")
    0x100639cac: ("404faf72", 4),  # movk w0,#0x7a7a,lsl16 ("zzzz")
    0x100b52d30: ("73657474696e67735f7072305f6c6f676f", 17),  # "settings_pr0_logo"
}

# 页签移除补丁（2026-10-14 追加）：设置页签列表是编译期【静态数组】，
# 直接改数据即可（比改 SwiftUI 视图代码安全得多）：
#   count 6 → 5；元素 [00 01 02 03 04 05] → [00 02 03 04 05]（移除 .pro，值 = 1）
# 两处数组：0x100c81c10（标签栏 ForEach 数据源）/ 0x100c81c60（另一处页签逻辑）
TAB_REMOVAL_MARKERS = {
    0x100c81c20: ("0500000000000000", 8),   # 数组1 count
    0x100c81c30: ("0002030405000000", 8),   # 数组1 元素（无 .pro）
    0x100c81c70: ("0500000000000000", 8),   # 数组2 count
    0x100c81c80: ("0002030405000000", 8),   # 数组2 元素（无 .pro）
}

# 钥匙串中和补丁（2026-10-14 追加，补丁 J）：
# App 启动时确保设备锚点 genp/com.maoux.frset.anchor/primary_token 存在（读→建→写），
# 其 ACL 绑定签名指纹——每次 ad-hoc 重签后 ACL 不匹配 → 弹窗；无人响应时读失败 →
# 高频重试 → SIGBUS 崩溃（均已实证）。
# 根治：读写两头+更新全部中和，App 全程零 keychain 交互（与签名无关，任何构建永久生效）：
#   0x100785e58: bl _SecItemCopyMatching → movn w0,#0x62d4（永远返回 errSecItemNotFound=-25300）
#                （后续 mov x20,x0 保留 → 读函数走 not-found 分支返回 nil，外层转创建）
#   0x100785be0: bl _SecItemAdd          → mov w0,#0（创建永远"成功"，不实际写入）
#                （后续 mov x23,x0 保留 → cbz w23 走成功路径）
#   0x100786264: bl _SecItemUpdate       → mov w0,#0（更新永远"成功"）
#                （关键：不打这条会陷入 Update-not-found 重试循环，实测 10992 次后 SIGBUS）
KEYCHAIN_MARKERS = {
    0x100785e58: ("605a8c12", 4),   # 读: movn w0,#0x62d3
    0x100785be0: ("00008052", 4),   # 创建: mov w0,#0
    0x100786264: ("00008052", 4),   # 更新: mov w0,#0
}

PRODUCT_IDS = {
    "lifetime":  "com.frset.pro.lifetime",
    "yearly":    "com.frset.pro.yearly",
    "quarterly": "com.frset.pro.quarterly",
    "monthly":   "com.frset.pro.monthly",
}

def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)

def load_dasm():
    if not os.path.exists(DISASM):
        print("反汇编不存在，生成中…", file=sys.stderr)
        run(["otool", "-tV", "-arch", "arm64", SLICE], stdout=open(DISASM, "w"))
    lines = open(DISASM, errors="replace").read().splitlines()
    # 解析为 (addr, text) 列表；文本行格式: "0000000100002810\tinstr"
    insns = []
    rx = re.compile(r"^([0-9a-f]{16})\t(.*)$")
    for ln in lines:
        m = rx.match(ln)
        if m:
            insns.append((int(m.group(1), 16), m.group(2)))
    return insns

def find_string_vaddr(s):
    """返回字符串字面量在二进制中的 vaddr（首个匹配）"""
    out = run(["strings", "-t", "x", "-n", "4", SLICE]).stdout
    for ln in out.splitlines():
        parts = ln.strip().split(None, 1)
        if len(parts) == 2 and parts[1] == s:
            return VADDR_BASE + int(parts[0], 16)
    return None

def func_starts(insns):
    """启发式识别函数起点：ret/b 之后、或地址不连续处"""
    starts = set()
    prev_end = None
    for i, (addr, text) in enumerate(insns):
        if prev_end is not None and addr != prev_end:
            starts.add(addr)
        if re.match(r"^(ret|retaa|retab|b)\b", text):
            if i + 1 < len(insns):
                starts.add(insns[i + 1][0])
        prev_end = addr + 4
    return sorted(starts)

def enclosing_func(starts, addr):
    import bisect
    i = bisect.bisect_right(starts, addr) - 1
    if i < 0:
        return None
    return starts[i]

def cmd_xrefs(args):
    insns = load_dasm()
    starts = func_starts(insns)
    targets = {}
    if args.product_ids or args.all:
        for name, pid in PRODUCT_IDS.items():
            va = find_string_vaddr(pid)
            if va: targets[pid] = va
    for s in args.string or []:
        va = find_string_vaddr(s)
        if va: targets[s] = va
    if not targets:
        print("未找到任何目标字符串"); return 1
    # 建立 page -> [(low, vaddr)] 索引
    pages = {}
    for s, va in targets.items():
        pages.setdefault(va & ~0xFFF, []).append((va & 0xFFF, va, s))
    hits = {}   # func_start -> [(vaddr, string)]
    for idx, (addr, text) in enumerate(insns):
        m = re.match(r"adrp\s+[xw]\d+, (\d+) ; (0x[0-9a-f]+)", text)
        if not m: continue
        page = int(m.group(2), 16)
        if page not in pages: continue
        reg = re.match(r"adrp\s+([xw]\d+),", text).group(1)
        # 向后看 3 条，找 add/ldr 引用同一寄存器的低 12 位
        for j in range(idx + 1, min(idx + 4, len(insns))):
            t = insns[j][1]
            m2 = re.match(rf"add\s+{reg}, {reg}, #(0x[0-9a-f]+|\d+)", t)
            if m2:
                low = int(m2.group(1), 16) if m2.group(1).startswith("0x") else int(m2.group(1))
                for (L, va, s) in pages[page]:
                    if L == low:
                        fs = enclosing_func(starts, addr)
                        hits.setdefault(fs, []).append((va, s))
                break
            m3 = re.match(rf"ldr\s+{reg}, \[{reg}, #(0x[0-9a-f]+|\d+)\]", t)
            if m3: break
    if not hits:
        print("未找到引用"); return 1
    for fs in sorted(hits):
        refs = hits[fs]
        print(f"函数 0x{fs:x}:")
        for va, s in refs:
            print(f"    引用 {s}  (vaddr 0x{va:x})")
    return 0

STUB_RX = re.compile(r"symbol stub for: (\$s[0-9A-Za-z_$.]+|_[A-Za-z0-9_]+)")

def cmd_callers(args):
    insns = load_dasm()
    starts = func_starts(insns)
    key = args.symbol
    # otool 把 stub 符号名注释在调用点上：直接按注释检索
    callers = {}
    for addr, text in insns:
        m = re.search(r"symbol stub for: ([^\s;]+)", text)
        if m and key in m.group(1):
            fs = enclosing_func(starts, addr)
            callers.setdefault(fs, []).append((addr, m.group(1)))
    if not callers:
        print(f"未找到符号调用: {key}"); return 1
    for fs, sites in sorted(callers.items()):
        print(f"函数 0x{fs:x}:")
        for addr, sym in sites:
            print(f"    调用点 0x{addr:x}  ->  {sym}")
    return 0

def cmd_func(args):
    insns = load_dasm()
    start = args.start
    out = []
    for addr, text in insns:
        if addr < start: continue
        if args.end and addr > args.end: break
        out.append(f"{addr:016x}\t{text}")
        if len(out) > 1 and re.match(r"^(ret|retaa|retab)\b", text):
            break
    print("\n".join(out))
    return 0

def cmd_strings(args):
    data = open(SLICE, "rb").read()
    rx = re.compile(rb"[\x20-\x7e]{%d,}" % (args.min or 6))
    pat = re.compile(args.pattern, re.I)
    seen = set()
    for m in rx.finditer(data):
        s = m.group().decode()
        if pat.search(s) and s not in seen:
            seen.add(s)
            print(f"0x{m.start():x}\t{s}")
    return 0

def cmd_forge(args):
    """伪造 pro_last_verified_entitlement_record（JSON, ISO8601 日期，实测可被 App 解码信任）"""
    import plistlib, datetime
    path = os.path.expanduser("~/Library/Preferences/com.maoux.frset.plist")
    try:
        with open(path, "rb") as f:
            prefs = plistlib.load(f)
    except FileNotFoundError:
        prefs = {}
    now = datetime.datetime.utcnow().replace(microsecond=0)
    far = now + datetime.timedelta(days=3650)
    iso = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    record = {
        "pendingLoss": False,
        "productID": args.product or "com.frset.pro.lifetime",
        "expirationDate": iso(far),
        "verifiedAt": iso(now),
        "isFreeTrial": False,
    }
    prefs["pro_last_verified_entitlement_record"] = json.dumps(record).encode()
    prefs["pro_lifetime_purchased_cache"] = True
    with open(path, "wb") as f:
        plistlib.dump(prefs, f)
    subprocess.run(["killall", "cfprefsd"], capture_output=True)
    print("已写入伪造记录(ISO8601):", json.dumps(record))
    print("提示: 如 App 正在运行需重启生效; cfprefsd 已刷新")
    return 0

def cmd_patch(args):
    """从 JSON 补丁清单读取 {vaddr: [old_hex, new_hex]} 应用到 arm64 slice，并合回 app 的 universal 二进制"""
    plan = json.load(open(args.plan))
    data = bytearray(open(SLICE, "rb").read())
    secs = json.load(open(SECTIONS)) if os.path.exists(SECTIONS) else None
    def v2f(va):
        if secs:
            for s in secs:
                if s.get("addr", 0) <= va < s.get("addr", 0) + s.get("size", 0) and s.get("offset"):
                    return s["offset"] + (va - s["addr"])
        return va - VADDR_BASE
    n = 0
    for va_s, (old, new) in plan.items():
        va = int(va_s, 16) if isinstance(va_s, str) else va_s
        off = v2f(va)
        old_b, new_b = bytes.fromhex(old), bytes.fromhex(new)
        assert len(old_b) == len(new_b), f"补丁长度不一致 @0x{va:x}"
        cur = bytes(data[off:off+len(old_b)])
        if cur != old_b:
            print(f"[跳过] 0x{va:x} 当前字节 {cur.hex()} != 预期 {old}")
            continue
        data[off:off+len(new_b)] = new_b
        print(f"[打补丁] 0x{va:x}: {old} -> {new}")
        n += 1
    open(SLICE, "wb").write(bytes(data))
    print(f"薄片完成 {n} 处补丁")
    # 合回 universal 二进制（保留 x86_64 slice）
    if n:
        r = run(["lipo", "-replace", "arm64", SLICE, "-output", BIN, BIN])
        print("lipo rc:", r.returncode, r.stderr.strip()[:200])
    return 0

def check_patched(app):
    """防呆：校验 app 的 arm64 slice 是否带全部解锁补丁（A/B）+ 遥测斩断补丁（D/E/F）；返回 (ok, 详情)"""
    binp = os.path.join(app, "Contents", "MacOS", "Frset")
    if not os.path.exists(binp):
        return False, f"找不到可执行文件: {binp}"
    tmp = "/tmp/_frset_check_slice"
    r = run(["lipo", "-thin", "arm64", binp, "-output", tmp])
    if r.returncode != 0:
        return False, f"lipo 失败: {r.stderr.strip()[:120]}"
    data = open(tmp, "rb").read()
    ok, detail = True, []
    for va, want in PATCH_MARKERS.items():
        got = data[va - VADDR_BASE: va - VADDR_BASE + 4].hex()
        mark = "✓" if got == want else "✗"
        if got != want:
            ok = False
        detail.append(f"  {mark} 0x{va:x}: {got} (期望 {want})")
    for va, (want, n) in {**TELEMETRY_MARKERS, **PROUI_MARKERS}.items():
        got = data[va - VADDR_BASE: va - VADDR_BASE + n].hex()
        mark = "✓" if got == want else "✗"
        if got != want:
            ok = False
        detail.append(f"  {mark} 0x{va:x}: 死链/斩断标记已就位" if got == want
                      else f"  {mark} 0x{va:x}: {got[:36]}… (期望 {want[:36]}…)")
    for va, (want, n) in TAB_REMOVAL_MARKERS.items():
        got = data[va - VADDR_BASE: va - VADDR_BASE + n].hex()
        mark = "✓" if got == want else "✗"
        if got != want:
            ok = False
        detail.append(f"  {mark} 0x{va:x}: 页签数组已移除 Pro" if got == want
                      else f"  {mark} 0x{va:x}: {got} (期望 {want})")
    for va, (want, n) in KEYCHAIN_MARKERS.items():
        got = data[va - VADDR_BASE: va - VADDR_BASE + n].hex()
        mark = "✓" if got == want else "✗"
        if got != want:
            ok = False
        detail.append(f"  {mark} 0x{va:x}: 钥匙串访问已中和（读写均不触达 Security）" if got == want
                      else f"  {mark} 0x{va:x}: {got} (期望 {want})")
    os.remove(tmp)
    return ok, "\n".join(detail)

def nested_executables(app):
    """找出 app bundle 内所有嵌套可执行文件（Helpers/Frameworks/XPCServices）"""
    out = []
    for root, dirs, files in os.walk(app):
        for f in files:
            p = os.path.join(root, f)
            if f == "Frset" and root.endswith("MacOS"):
                continue
            # Mach-O 魔数
            try:
                with open(p, "rb") as fh:
                    magic = fh.read(4)
                if magic in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe",
                             b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"):
                    out.append(p)
            except (IsADirectoryError, PermissionError):
                pass
    return out

def cmd_sign(args):
    app = args.app or APP
    ok, detail = check_patched(app)
    print("补丁校验:", "通过" if ok else "未通过")
    print(detail)
    if not ok and not args.force:
        print("拒绝签名：目标不是已解锁版本（可能是正版）。确认请加 --force")
        return 1
    # ad-hoc 重签名：保留 _MASReceipt（收据存在性可能被检查），entitlements 仅调试用
    ent = os.path.join(ROOT, "rea-evidence", "debug-entitlements.plist")
    if not os.path.exists(ent):
        os.makedirs(os.path.dirname(ent), exist_ok=True)
        open(ent, "w").write("""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>com.apple.security.cs.disable-library-validation</key>
	<true/>
	<key>com.apple.security.get-task-allow</key>
	<true/>
</dict>
</plist>
""")
    # 1) 先签所有嵌套可执行文件（否则父签名与子的原 MAS 签名不匹配，
    #    Helper 被 spawn 时会被 dyld/secinit 以 SIGTRAP 击落——OCR/TinyPNG 即失效）
    for p in nested_executables(app):
        r = run(["codesign", "--force", "--sign", "-", "--entitlements", ent, p])
        print(f"嵌套签名 {os.path.relpath(p, app)}: rc={r.returncode} {r.stderr.strip()[:120]}")
    # 2) 再签主 bundle（最外层最后签）
    r = run(["codesign", "--remove-signature", app])
    # 注意：不加 --options（restrict/runtime 都会让 dyld 忽略 DYLD_INSERT_LIBRARIES）
    r2 = run(["codesign", "--force", "--sign", "-", "--entitlements", ent, app])
    print("codesign rc:", r2.returncode, r2.stderr.strip()[:500])
    r3 = run(["codesign", "--verify", "--deep", "--strict", app])
    print("verify rc:", r3.returncode, r3.stderr.strip()[:300])
    return 0

def cmd_package(args):
    app = args.app or APP
    ok, detail = check_patched(app)
    print("补丁校验:", "通过" if ok else "未通过")
    print(detail)
    if not ok and not args.force:
        print("拒绝打包：目标不是已解锁版本（可能是正版）。确认请加 --force")
        return 1
    out = args.output or os.path.join(ROOT, "Frset-unlocked.dmg")
    r = run(["hdiutil", "create", "-volname", "Frset", "-srcfolder", app,
             "-ov", "-format", "UDZO", out])
    print(r.stdout.strip()[-300:], r.stderr.strip()[-300:])
    print("DMG:", out, os.path.getsize(out) if os.path.exists(out) else "失败")
    return 0

def main():
    ap = argparse.ArgumentParser(description="Frset 内购解锁研究工具")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("xrefs"); p.add_argument("--product-ids", action="store_true")
    p.add_argument("--all", action="store_true"); p.add_argument("--string", action="append")
    p = sub.add_parser("callers"); p.add_argument("--symbol", required=True)
    p = sub.add_parser("func"); p.add_argument("--start", type=lambda x: int(x, 0)); p.add_argument("--end", type=lambda x: int(x, 0), default=0)
    p = sub.add_parser("strings"); p.add_argument("--pattern", required=True); p.add_argument("--min", type=int, default=6)
    p = sub.add_parser("forge"); p.add_argument("--product")
    p = sub.add_parser("patch"); p.add_argument("--plan", required=True)
    p = sub.add_parser("sign"); p.add_argument("--runtime", action="store_true"); p.add_argument("--app"); p.add_argument("--force", action="store_true")
    p = sub.add_parser("package"); p.add_argument("--output"); p.add_argument("--app"); p.add_argument("--force", action="store_true")
    args = ap.parse_args()
    return {"xrefs": cmd_xrefs, "callers": cmd_callers, "func": cmd_func,
            "strings": cmd_strings, "forge": cmd_forge, "patch": cmd_patch,
            "sign": cmd_sign, "package": cmd_package}[args.cmd](args)

if __name__ == "__main__":
    sys.exit(main())
