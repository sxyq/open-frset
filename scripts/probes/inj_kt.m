// inj_kt.m — keychain 访问清单记录（interpose SecItem*）
#import <Foundation/Foundation.h>
#import <Security/Security.h>
#include <dlfcn.h>

typedef OSStatus (*SecItemCopyMatching_t)(CFDictionaryRef, CFTypeRef *);
typedef OSStatus (*SecItemAdd_t)(CFDictionaryRef, CFTypeRef *);
typedef OSStatus (*SecItemUpdate_t)(CFDictionaryRef, CFDictionaryRef);
typedef OSStatus (*SecItemDelete_t)(CFDictionaryRef);

static SecItemCopyMatching_t orig_copy;
static SecItemAdd_t orig_add;
static SecItemUpdate_t orig_update;
static SecItemDelete_t orig_delete;

static void logq(const char *op, CFDictionaryRef q) {
    if (!q) { NSLog(@"[KT] %s (nil)", op); return; }
    CFTypeRef svc = CFDictionaryGetValue(q, kSecAttrService);
    CFTypeRef acct = CFDictionaryGetValue(q, kSecAttrAccount);
    CFTypeRef cls = CFDictionaryGetValue(q, kSecClass);
    NSLog(@"[KT] %s class=%@ service=%@ account=%@", op, cls, svc, acct);
}

static OSStatus my_copy(CFDictionaryRef q, CFTypeRef *r) {
    logq("CopyMatching", q);
    OSStatus s = orig_copy(q, r);
    NSLog(@"[KT] CopyMatching -> %d", (int)s);
    return s;
}
static OSStatus my_add(CFDictionaryRef q, CFTypeRef *r) {
    logq("Add", q);
    OSStatus s = orig_add(q, r);
    NSLog(@"[KT] Add -> %d", (int)s);
    return s;
}
static OSStatus my_update(CFDictionaryRef q, CFDictionaryRef a) {
    logq("Update", q);
    OSStatus s = orig_update(q, a);
    NSLog(@"[KT] Update -> %d", (int)s);
    return s;
}
static OSStatus my_delete(CFDictionaryRef q) {
    logq("Delete", q);
    OSStatus s = orig_delete(q);
    NSLog(@"[KT] Delete -> %d", (int)s);
    return s;
}

#define DYLD_INTERPOSE(_repl, _orig) \
  __attribute__((used)) static struct { const void *r; const void *o; } \
  _interpose_##_orig __attribute__((section("__DATA,__interpose"))) = \
  { (const void *)(unsigned long)&_repl, (const void *)(unsigned long)&_orig };

DYLD_INTERPOSE(my_copy, SecItemCopyMatching)
DYLD_INTERPOSE(my_add, SecItemAdd)
DYLD_INTERPOSE(my_update, SecItemUpdate)
DYLD_INTERPOSE(my_delete, SecItemDelete)

__attribute__((constructor)) static void kt_init(void) {
    orig_copy   = (SecItemCopyMatching_t)dlsym(RTLD_NEXT, "SecItemCopyMatching");
    orig_add    = (SecItemAdd_t)dlsym(RTLD_NEXT, "SecItemAdd");
    orig_update = (SecItemUpdate_t)dlsym(RTLD_NEXT, "SecItemUpdate");
    orig_delete = (SecItemDelete_t)dlsym(RTLD_NEXT, "SecItemDelete");
    NSLog(@"[KT] interpose loaded pid=%d (copy=%p add=%p)", getpid(), orig_copy, orig_add);
}
