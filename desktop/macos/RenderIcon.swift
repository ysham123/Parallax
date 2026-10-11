// Render the existing assets/parallax-icon.svg geometry for macOS icon sizes.
// Usage: swift RenderIcon.swift /absolute/path/Parallax.iconset
import AppKit
import Foundation

guard CommandLine.arguments.count == 2 else { fatalError("Supply an iconset directory") }
let destination = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
try FileManager.default.createDirectory(at: destination, withIntermediateDirectories: true)
let colors: [String: CGColor] = [
    "background": NSColor(srgbRed: 17/255, green: 18/255, blue: 23/255, alpha: 1).cgColor,
    "purple": NSColor(srgbRed: 165/255, green: 154/255, blue: 232/255, alpha: 1).cgColor,
    "teal": NSColor(srgbRed: 104/255, green: 197/255, blue: 186/255, alpha: 1).cgColor,
    "white": NSColor(srgbRed: 240/255, green: 236/255, blue: 255/255, alpha: 1).cgColor,
    "purpleDot": NSColor(srgbRed: 182/255, green: 164/255, blue: 245/255, alpha: 1).cgColor,
    "tealDot": NSColor(srgbRed: 121/255, green: 212/255, blue: 200/255, alpha: 1).cgColor
]
for (name, pixels) in [
    ("icon_16x16.png", 16), ("icon_16x16@2x.png", 32), ("icon_32x32.png", 32), ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128), ("icon_128x128@2x.png", 256), ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512), ("icon_512x512.png", 512), ("icon_512x512@2x.png", 1024)
] {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels,
                                  bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                  colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    let context = NSGraphicsContext(bitmapImageRep: bitmap)!.cgContext
    context.setAllowsAntialiasing(true)
    context.scaleBy(x: CGFloat(pixels)/512, y: CGFloat(pixels)/512)
    context.translateBy(x: 0, y: 512); context.scaleBy(x: 1, y: -1)
    context.setFillColor(colors["background"]!)
    context.addPath(CGPath(roundedRect: CGRect(x: 0, y: 0, width: 512, height: 512), cornerWidth: 116, cornerHeight: 116, transform: nil))
    context.fillPath()
    context.setLineWidth(14)
    context.setStrokeColor(colors["purple"]!)
    context.strokeEllipse(in: CGRect(x: 102, y: 102, width: 308, height: 308))
    context.saveGState()
    context.translateBy(x: 256, y: 256); context.rotate(by: -36 * .pi / 180)
    context.setStrokeColor(colors["teal"]!)
    context.strokeEllipse(in: CGRect(x: -92, y: -172, width: 184, height: 344))
    context.restoreGState()
    context.setFillColor(colors["white"]!)
    context.fillEllipse(in: CGRect(x: 226, y: 226, width: 60, height: 60))
    for (x, y, color) in [(386.0, 173.0, "purpleDot"), (130.0, 351.0, "tealDot")] {
        context.setLineWidth(10); context.setStrokeColor(colors["background"]!)
        context.setFillColor(colors[color]!)
        context.addEllipse(in: CGRect(x: x-22, y: y-22, width: 44, height: 44))
        context.drawPath(using: .fillStroke)
    }
    try bitmap.representation(using: .png, properties: [:])!.write(to: destination.appendingPathComponent(name))
}
