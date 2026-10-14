// inject_tccchk.m v2 — 从 Frset 进程内部查询其自身的 TCC 权限状态（preflight，不弹窗）
#import <Cocoa/Cocoa.h>
#import <CoreGraphics/CoreGraphics.h>
#import <ApplicationServices/ApplicationServices.h>

__attribute__((constructor)) static void injected_init(void) {
    NSLog(@"[tccchk] loaded pid=%d", getpid());
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(3 * NSEC_PER_SEC)),
                   dispatch_get_main_queue(), ^{
        BOOL sr = CGPreflightScreenCaptureAccess();
        BOOL listen = CGPreflightListenEventAccess();
        BOOL post = CGPreflightPostEventAccess();
        BOOL ax = AXIsProcessTrusted();
        NSLog(@"[tccchk] ScreenRecording(preflight) = %@", sr ? @"GRANTED" : @"NOT_GRANTED");
        NSLog(@"[tccchk] ListenEvent(preflight)     = %@", listen ? @"GRANTED" : @"NOT_GRANTED");
        NSLog(@"[tccchk] PostEvent(preflight)       = %@", post ? @"GRANTED" : @"NOT_GRANTED");
        NSLog(@"[tccchk] Accessibility(trusted)     = %@", ax ? @"GRANTED" : @"NOT_GRANTED");
        NSLog(@"[tccchk] done");
    });
}
