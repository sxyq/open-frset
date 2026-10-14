// inj_kt3.m — SecItem* + legacy SecKeychain* 双代钩子，抓取全部钥匙串访问
#import <Foundation/Foundation.h>
#import <Security/Security.h>
#include <dlfcn.h>
#include <mach-o/dyld.h>
#include <string.h>

typedef OSStatus (*SecItemCopyMatching_t)(CFDictionaryRef, CFTypeRef *);
typedef OSStatus (*SecItemAdd_t)(CFDictionaryRef, CFTypeRef *);
typedef OSStatus (*SecItemUpdate_t)(CFDictionaryRef, CFDictionaryRef);
typedef OSStatus (*SecItemDelete_t)(CFDictionaryRef);
typedef OSStatus (*SecKeychainFindGenericPassword_t)(SecKeychainRef, UInt32, const char *, UInt32, const char *, UInt32 *, void **, SecKeychainItemRef *);
typedef OSStatus (*SecKeychainFindInternetPassword_t)(SecKeychainRef, UInt32, const char *, UInt32, const char *, UInt32, const char *, UInt32, const char *, UInt32, const char *, UInt32, const char *, void **, SecKeychainItemRef *);

static SecItemCopyMatching_t orig_copy;
static SecItemAdd_t orig_add;
static SecItemUpdate_t orig_update;
static SecItemDelete_t orig_delete;
static SecKeychainFindGenericPassword_t orig_findgen;
static SecKeychainFindInternetPassword_t orig_findnet;
static uintptr_t g_slide = 0;

static void hexdump(const char *tag, const void *data, UInt32 len) {
    if (!data || !len) { NSLog(@"[KT3] %s (empty)", tag); return; }
    const uint8_t *b = data;
    NSMutableString *hex = [NSMutableString string];
    for (UInt32 i = 0; i < len && i < 256; i++) [hex appendFormat:@"%02x", b[i]];
    NSString *utf8 = [[NSString alloc] initWithBytes:data length:len encoding:NSUTF8StringEncoding];
    NSLog(@"[KT3] %s len=%u hex=%@ utf8=%@", tag, len, hex, utf8 ?: @"<非UTF8>");
}

static void logq(const char *op, CFDictionaryRef q) {
    if (!q) { NSLog(@"[KT3] %s (nil)", op); return; }
    CFTypeRef svc = CFDictionaryGetValue(q, kSecAttrService);
    CFTypeRef acct = CFDictionaryGetValue(q, kSecAttrAccount);
    CFTypeRef srv = CFDictionaryGetValue(q, kSecAttrServer);
    NSLog(@"[KT3] %s service=%@ account=%@ server=%@", op, svc, acct, srv);
}

static OSStatus my_copy(CFDictionaryRef q, CFTypeRef *r) {
    uintptr_t ra = (uintptr_t)__builtin_return_address(0);
    NSLog(@"[KT3] CALLED-FROM retaddr=%p va=0x%llx", (void*)ra, (unsigned long long)(ra - g_slide));
    logq("SecItemCopyMatching", q);
    OSStatus s = orig_copy(q, r);
    NSLog(@"[KT3] SecItemCopyMatching -> %d", (int)s);
    if (s == 0 && r && *r) {
        CFTypeRef v = *r;
        if (CFGetTypeID(v) == CFDataGetTypeID()) {
            NSData *d = (__bridge NSData *)v;
            hexdump("VALUE", d.bytes, (UInt32)d.length);
        } else if (CFGetTypeID(v) == CFDictionaryGetTypeID()) {
            CFTypeRef data = CFDictionaryGetValue(v, kSecValueData);
            if (data && CFGetTypeID(data) == CFDataGetTypeID()) {
                NSData *d = (__bridge NSData *)data;
                hexdump("VALUE", d.bytes, (UInt32)d.length);
            }
        }
    }
    return s;
}
static OSStatus my_add(CFDictionaryRef q, CFTypeRef *r) {
    logq("SecItemAdd", q);
    OSStatus s = orig_add(q, r);
    NSLog(@"[KT3] SecItemAdd -> %d", (int)s);
    return s;
}
static OSStatus my_update(CFDictionaryRef q, CFDictionaryRef a) {
    uintptr_t ra = (uintptr_t)__builtin_return_address(0);
    NSLog(@"[KT3] UPDATE-CALLED-FROM va=0x%llx", (unsigned long long)(ra - g_slide));
    logq("SecItemUpdate", q);
    OSStatus s = orig_update(q, a);
    NSLog(@"[KT3] SecItemUpdate -> %d", (int)s);
    return s;
}
static OSStatus my_delete(CFDictionaryRef q) {
    logq("SecItemDelete", q);
    OSStatus s = orig_delete(q);
    NSLog(@"[KT3] SecItemDelete -> %d", (int)s);
    return s;
}
static OSStatus my_findgen(SecKeychainRef kc, UInt32 sl, const char *svc, UInt32 al, const char *acct,
                           UInt32 *pl, void **pd, SecKeychainItemRef *item) {
    NSString *s = sl ? [NSString stringWithUTF8String:svc] : nil;
    NSString *a = al ? [NSString stringWithUTF8String:acct] : nil;
    NSLog(@"[KT3] SecKeychainFindGenericPassword service=%@ account=%@", s, a);
    OSStatus st = orig_findgen(kc, sl, svc, al, acct, pl, pd, item);
    NSLog(@"[KT3] SecKeychainFindGenericPassword -> %d", (int)st);
    if (st == 0 && pl && pd && *pd) hexdump("LEGACY-VALUE", *pd, *pl);
    return st;
}
static OSStatus my_findnet(SecKeychainRef kc, UInt32 sl, const char *svc, UInt32 al, const char *acct,
                           UInt32 srl, const char *srv, UInt32 ptl, const char *pt,
                           UInt32 pal, const char *path, UInt32 pl, const char *pwl,
                           void **pd, SecKeychainItemRef *item) {
    NSLog(@"[KT3] SecKeychainFindInternetPassword server=%.*s account=%.*s", srl, srv ? srv : "", al, acct ? acct : "");
    OSStatus st = orig_findnet(kc, sl, svc, al, acct, srl, srv, ptl, pt, pal, path, pl, pwl, pd, item);
    NSLog(@"[KT3] SecKeychainFindInternetPassword -> %d", (int)st);
    return st;
}

#define DYLD_INTERPOSE(_repl, _orig) \
  __attribute__((used)) static struct { const void *r; const void *o; } \
  _interpose_##_orig __attribute__((section("__DATA,__interpose"))) = \
  { (const void *)(unsigned long)&_repl, (const void *)(unsigned long)&_orig };

DYLD_INTERPOSE(my_copy, SecItemCopyMatching)
DYLD_INTERPOSE(my_add, SecItemAdd)
DYLD_INTERPOSE(my_update, SecItemUpdate)
DYLD_INTERPOSE(my_delete, SecItemDelete)
DYLD_INTERPOSE(my_findgen, SecKeychainFindGenericPassword)
DYLD_INTERPOSE(my_findnet, SecKeychainFindInternetPassword)

__attribute__((constructor)) static void kt_init(void) {
    orig_copy   = (SecItemCopyMatching_t)dlsym(RTLD_NEXT, "SecItemCopyMatching");
    orig_add    = (SecItemAdd_t)dlsym(RTLD_NEXT, "SecItemAdd");
    orig_update = (SecItemUpdate_t)dlsym(RTLD_NEXT, "SecItemUpdate");
    orig_delete = (SecItemDelete_t)dlsym(RTLD_NEXT, "SecItemDelete");
    orig_findgen = (SecKeychainFindGenericPassword_t)dlsym(RTLD_NEXT, "SecKeychainFindGenericPassword");
    orig_findnet = (SecKeychainFindInternetPassword_t)dlsym(RTLD_NEXT, "SecKeychainFindInternetPassword");
    // 计算 Frset 主二进制的 ASLR slide
    for (uint32_t i = 0; i < _dyld_image_count(); i++) {
        const char *name = _dyld_get_image_name(i);
        if (name && strstr(name, "Frset.app/Contents/MacOS/Frset")) {
            uintptr_t hdr = (uintptr_t)_dyld_get_image_header(i);
            g_slide = hdr - 0x100000000ULL;
            NSLog(@"[KT3] slide=0x%llx hdr=%p", (unsigned long long)g_slide, (void*)hdr);
            break;
        }
    }
    NSLog(@"[KT3] interpose loaded pid=%d (legacy findgen=%p)", getpid(), orig_findgen);
}
