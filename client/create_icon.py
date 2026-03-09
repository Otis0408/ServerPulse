"""Generate a simple app icon for ServerPulse."""
import subprocess
import os
import tempfile

def create_icon():
    """Create an .icns icon using macOS sips and iconutil."""
    iconset_dir = tempfile.mkdtemp(suffix=".iconset")

    # Create a simple icon using Python + AppKit
    from AppKit import (
        NSImage, NSBezierPath, NSColor, NSFont, NSAttributedString,
        NSFontAttributeName, NSForegroundColorAttributeName,
        NSGraphicsContext, NSBitmapImageRep, NSPNGFileType,
    )
    from Foundation import NSSize, NSMakeRect, NSMakePoint

    sizes = [16, 32, 64, 128, 256, 512, 1024]

    for sz in sizes:
        img = NSImage.alloc().initWithSize_(NSSize(sz, sz))
        img.lockFocus()

        # Background circle - dark blue gradient
        bg_color = NSColor.colorWithRed_green_blue_alpha_(0.12, 0.14, 0.25, 1.0)
        bg_color.setFill()
        circle = NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(0, 0, sz, sz))
        circle.fill()

        # Inner glow
        inner_color = NSColor.colorWithRed_green_blue_alpha_(0.15, 0.20, 0.40, 1.0)
        inner_color.setFill()
        margin = sz * 0.08
        inner = NSBezierPath.bezierPathWithOvalInRect_(
            NSMakeRect(margin, margin, sz - 2 * margin, sz - 2 * margin)
        )
        inner.fill()

        # Pulse circle (accent)
        accent = NSColor.colorWithRed_green_blue_alpha_(0.2, 0.8, 0.6, 0.9)
        accent.setStroke()
        ring = NSBezierPath.bezierPathWithOvalInRect_(
            NSMakeRect(sz * 0.18, sz * 0.18, sz * 0.64, sz * 0.64)
        )
        ring.setLineWidth_(sz * 0.03)
        ring.stroke()

        # Center "S" letter
        font_size = sz * 0.38
        font = NSFont.systemFontOfSize_weight_(font_size, 0.3)
        text_color = NSColor.colorWithRed_green_blue_alpha_(0.3, 0.9, 0.7, 1.0)
        attrs = {
            NSFontAttributeName: font,
            NSForegroundColorAttributeName: text_color,
        }
        s = NSAttributedString.alloc().initWithString_attributes_("S", attrs)
        text_size = s.size()
        x = (sz - text_size.width) / 2
        y = (sz - text_size.height) / 2
        s.drawAtPoint_(NSMakePoint(x, y))

        img.unlockFocus()

        # Save as PNG
        tiff = img.TIFFRepresentation()
        rep = NSBitmapImageRep.imageRepWithData_(tiff)
        png_data = rep.representationUsingType_properties_(NSPNGFileType, {})

        # Standard icon filenames
        if sz <= 512:
            filename = f"icon_{sz}x{sz}.png"
            png_data.writeToFile_atomically_(os.path.join(iconset_dir, filename), True)
            # @2x version
            if sz >= 32:
                half = sz // 2
                filename_2x = f"icon_{half}x{half}@2x.png"
                png_data.writeToFile_atomically_(os.path.join(iconset_dir, filename_2x), True)
        if sz == 1024:
            filename = f"icon_512x512@2x.png"
            png_data.writeToFile_atomically_(os.path.join(iconset_dir, filename), True)

    # Convert iconset to icns
    icns_path = os.path.join(os.path.dirname(__file__), "icon.icns")
    subprocess.run(["iconutil", "-c", "icns", iconset_dir, "-o", icns_path], check=True)
    print(f"Icon created: {icns_path}")

    # Cleanup
    import shutil
    shutil.rmtree(iconset_dir)


if __name__ == "__main__":
    create_icon()
