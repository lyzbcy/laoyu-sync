"""Draw the sprite above Tk's transparent Aqua canvas."""

from AppKit import NSApplication, NSBitmapImageRep, NSData, NSImage, NSImageScaleNone, NSImageView
from Quartz import CGImageCreateWithImageInRect


class SpriteView(NSImageView):
    def hitTest_(self, point):
        # Leave clicks, dragging and context menus to the Tk canvas underneath.
        return None


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

    def set_frame(self, name, index):
        size = self.size
        origin = (index % 7 * size, index // 7 * size)
        crop = CGImageCreateWithImageInRect(self.atlases[name], (origin, (size, size)))
        self.view.setImage_(NSImage.alloc().initWithCGImage_size_(crop, (size, size)))

    def move(self, center_x, top):
        y = top if self.content.isFlipped() else self.content.bounds().size.height - top - self.size
        self.view.setFrameOrigin_((center_x - self.size // 2, y))
