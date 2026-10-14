// inject_frset8.m — 终验：截图初始页 + 重开窗口样本
#import <Cocoa/Cocoa.h>
#import <ImageIO/ImageIO.h>

static void SaveLayerShot(NSWindow *w, NSString *tag) {
    NSView *v = w.contentView;
    if (!v) return;
    NSRect bounds = v.bounds;
    if (bounds.size.width < 40 || bounds.size.height < 40) return;
    NSUInteger wpx = (NSUInteger)(bounds.size.width * 2.0);
    NSUInteger hpx = (NSUInteger)(bounds.size.height * 2.0);
    CGColorSpaceRef cs = CGColorSpaceCreateDeviceRGB();
    CGContextRef ctx = CGBitmapContextCreate(NULL, wpx, hpx, 8, 0, cs,
        kCGImageAlphaPremultipliedFirst | kCGBitmapByteOrder32Little);
    if (!ctx) { CGColorSpaceRelease(cs); return; }
    CGContextScaleCTM(ctx, 2.0, 2.0);
    CGContextSetRGBFillColor(ctx, 1, 1, 1, 1);
    CGContextFillRect(ctx, CGRectMake(0, 0, bounds.size.width, bounds.size.height));
    CGContextTranslateCTM(ctx, 0, bounds.size.height);
    CGContextScaleCTM(ctx, 1.0, -1.0);
    @try { CALayer *l = v.layer; if (l) [l renderInContext:ctx]; } @catch (NSException *e) {}
    CGImageRef img = CGBitmapContextCreateImage(ctx);
    if (img) {
        NSURL *url = [NSURL fileURLWithPath:[NSString stringWithFormat:@"/tmp/inj_%@.png", tag]];
        CGImageDestinationRef dst = CGImageDestinationCreateWithURL(
            (__bridge CFURLRef)url, CFSTR("public.png"), 1, NULL);
        if (dst) { CGImageDestinationAddImage(dst, img, NULL); CGImageDestinationFinalize(dst); CFRelease(dst); }
        CGImageRelease(img);
    }
    CGContextRelease(ctx);
    CGColorSpaceRelease(cs);
    NSLog(@"[inj8] shot %@", tag);
}

static NSWindow *FindSettingsWindow(void) {
    for (NSWindow *w in [NSApp windows]) {
        if (w.isVisible && [NSStringFromClass(w.class) isEqualToString:@"NSWindow"]
            && w.frame.size.width > 700) return w;
    }
    return nil;
}

static void TryOpenSettings(void) {
    [NSApp activateIgnoringOtherApps:YES];
    SEL s1 = NSSelectorFromString(@"showSettingsWindow:");
    if ([NSApp respondsToSelector:s1]) {
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Warc-performSelector-leaks"
        [NSApp performSelector:s1 withObject:nil];
#pragma clang diagnostic pop
    }
    for (NSMenuItem *item in NSApp.mainMenu.itemArray)
        for (NSMenuItem *mi in item.submenu.itemArray)
            if (mi.action && ([NSStringFromSelector(mi.action) containsString:@"Settings"]
                              || [mi.title containsString:@"设置"]))
                [NSApp sendAction:mi.action to:mi.target from:mi];
}

__attribute__((constructor)) static void injected_init(void) {
    NSLog(@"[inj8] loaded pid=%d", getpid());
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(7 * NSEC_PER_SEC)),
                   dispatch_get_main_queue(), ^{
        TryOpenSettings();
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(4 * NSEC_PER_SEC)),
                       dispatch_get_main_queue(), ^{
            NSWindow *w = FindSettingsWindow();
            if (!w) { NSLog(@"[inj8] no window"); return; }
            SaveLayerShot(w, @"v8_s1");
            // 关窗 → 重开 → 截 s2
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(2 * NSEC_PER_SEC)),
                           dispatch_get_main_queue(), ^{
                [w performClose:nil];
                dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(2.5 * NSEC_PER_SEC)),
                               dispatch_get_main_queue(), ^{
                    TryOpenSettings();
                    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(3.5 * NSEC_PER_SEC)),
                                   dispatch_get_main_queue(), ^{
                        NSWindow *w2 = FindSettingsWindow();
                        if (w2) {
                            SaveLayerShot(w2, @"v8_s2");
                            [w2 performClose:nil];
                        } else NSLog(@"[inj8] reopen1 fail");
                        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(2.5 * NSEC_PER_SEC)),
                                       dispatch_get_main_queue(), ^{
                            TryOpenSettings();
                            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(3.5 * NSEC_PER_SEC)),
                                           dispatch_get_main_queue(), ^{
                                NSWindow *w3 = FindSettingsWindow();
                                if (w3) SaveLayerShot(w3, @"v8_s3");
                                else NSLog(@"[inj8] reopen2 fail");
                                NSLog(@"[inj8] done");
                            });
                        });
                    });
                });
            });
        });
    });
}
