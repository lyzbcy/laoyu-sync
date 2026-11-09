"""Draw the sprite above Tk's transparent Aqua canvas."""

from AppKit import (
    NSApplication, NSBitmapImageRep, NSBox, NSBoxCustom, NSColor, NSData, NSFont,
    NSImage, NSImageScaleNone, NSImageView, NSLineBreakByTruncatingTail, NSNoBorder,
    NSTextAlignmentCenter, NSTextField,
)
from Quartz import CGImageCreateWithImageInRect


class SpriteView(NSImageView):
    def hitTest_(self, point):
        # Leave clicks, dragging and context menus to the Tk canvas underneath.
        return None


def _color(rgb):
    return NSColor.colorWithSRGBRed_green_blue_alpha_(*(channel / 255 for channel in rgb), 1)


class MacSprite:
    def __init__(self, title, art_dir, names, frame_size):
        self.size = frame_size
        self.atlases = {}
        for name in names:
            data = NSData.dataWithContentsOfFile_(str(art_dir / f'{name}.png'))
            atlas = NSBitmapImageRep.alloc().initWithData_(data) if data is not None else None
            if atlas is None:
                raise RuntimeError(f'Cannot load pet sprite atlas: {name}')
            self.atlases[name] = atlas.CGImage()

        window = next(window for window in NSApplication.sharedApplication().windows()
                      if window.title() == title)
        self.content = window.contentView()
        self.view = SpriteView.alloc().initWithFrame_(((0, 0), (frame_size, frame_size)))
        self.view.setImageScaling_(NSImageScaleNone)
        self.content.addSubview_(self.view)

    def add_caption(self, width, height, bottom):
        badge = NSBox.alloc().initWithFrame_((((self.size - width) / 2, bottom), (width, height)))
        badge.setBoxType_(NSBoxCustom)
        badge.setBorderType_(NSNoBorder)
        badge.setCornerRadius_(8)
        badge.setContentViewMargins_((0, 0))
        badge.setFillColor_(_color((247, 248, 243)))
        self.view.addSubview_(badge)
        self.title = NSTextField.labelWithString_('')
        self.detail = NSTextField.labelWithString_('')
        self.title.setFont_(NSFont.boldSystemFontOfSize_(10))
        self.detail.setFont_(NSFont.systemFontOfSize_(9))
        self.detail.setTextColor_(_color((82, 102, 90)))
        for label, y, line_height in ((self.title, 12, 14), (self.detail, 2, 11)):
            label.setFrame_(((4, y), (width - 8, line_height)))
            label.setAlignment_(NSTextAlignmentCenter)
            label.setMaximumNumberOfLines_(1)
            label.setLineBreakMode_(NSLineBreakByTruncatingTail)
            badge.contentView().addSubview_(label)

    def set_caption(self, title, detail, error):
        self.title.setTextColor_(_color((159, 38, 34) if error else (24, 46, 37)))
        self.title.setStringValue_(title)
        self.detail.setStringValue_(detail)

    def set_frame(self, name, index):
        size = self.size
        origin = (index % 7 * size, index // 7 * size)
        crop = CGImageCreateWithImageInRect(self.atlases[name], (origin, (size, size)))
        self.view.setImage_(NSImage.alloc().initWithCGImage_size_(crop, (size, size)))

    def move(self, center_x, top):
        y = top if self.content.isFlipped() else self.content.bounds().size.height - top - self.size
        self.view.setFrameOrigin_((center_x - self.size // 2, y))
