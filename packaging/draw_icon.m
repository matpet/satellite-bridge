#import <Cocoa/Cocoa.h>

static void stroke(NSBezierPath *path, CGFloat width, NSColor *color) {
    [color setStroke];
    path.lineWidth = width;
    path.lineCapStyle = NSLineCapStyleRound;
    [path stroke];
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) return 1;
        NSImage *image = [[NSImage alloc] initWithSize:NSMakeSize(1024, 1024)];
        [image lockFocus];
        [[NSColor colorWithCalibratedRed:.07 green:.19 blue:.25 alpha:1] setFill];
        [[NSBezierPath bezierPathWithRoundedRect:NSMakeRect(42, 42, 940, 940) xRadius:205 yRadius:205] fill];
        NSColor *cyan = [NSColor colorWithCalibratedRed:.28 green:.86 blue:.80 alpha:1];
        NSBezierPath *link = [NSBezierPath bezierPath];
        [link moveToPoint:NSMakePoint(308, 337)];
        [link lineToPoint:NSMakePoint(696, 725)];
        stroke(link, 30, cyan);
        NSBezierPath *dish = [NSBezierPath bezierPath];
        [dish moveToPoint:NSMakePoint(213, 478)];
        [dish curveToPoint:NSMakePoint(546, 213) controlPoint1:NSMakePoint(161, 255) controlPoint2:NSMakePoint(342, 125)];
        stroke(dish, 52, NSColor.whiteColor);
        NSBezierPath *mount = [NSBezierPath bezierPath];
        [mount moveToPoint:NSMakePoint(349, 244)];
        [mount lineToPoint:NSMakePoint(291, 158)];
        [mount moveToPoint:NSMakePoint(227, 154)];
        [mount lineToPoint:NSMakePoint(400, 154)];
        stroke(mount, 35, NSColor.whiteColor);
        NSBezierPath *satellite = [NSBezierPath bezierPathWithRoundedRect:NSMakeRect(635, 659, 128, 128) xRadius:25 yRadius:25];
        [cyan setFill];
        [satellite fill];
        for (NSNumber *x in @[@493, @789]) {
            [[NSBezierPath bezierPathWithRoundedRect:NSMakeRect(x.doubleValue, 683, 118, 80) xRadius:10 yRadius:10] fill];
        }
        for (NSNumber *radius in @[@110, @177]) {
            NSBezierPath *wave = [NSBezierPath bezierPath];
            [wave appendBezierPathWithArcWithCenter:NSMakePoint(449, 563) radius:radius.doubleValue startAngle:8 endAngle:82 clockwise:NO];
            stroke(wave, 22, NSColor.whiteColor);
        }
        [image unlockFocus];
        NSBitmapImageRep *bitmap = [NSBitmapImageRep imageRepWithData:image.TIFFRepresentation];
        NSData *png = [bitmap representationUsingType:NSBitmapImageFileTypePNG properties:@{}];
        if (![png writeToFile:[NSString stringWithUTF8String:argv[1]] atomically:YES]) return 2;
    }
    return 0;
}
