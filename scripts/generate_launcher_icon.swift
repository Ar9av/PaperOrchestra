#!/usr/bin/env swift

import AppKit

struct Palette {
    let backgroundTop = NSColor(calibratedRed: 0.11, green: 0.16, blue: 0.28, alpha: 1.0)
    let backgroundBottom = NSColor(calibratedRed: 0.04, green: 0.07, blue: 0.14, alpha: 1.0)
    let ambientBlue = NSColor(calibratedRed: 0.41, green: 0.68, blue: 0.97, alpha: 0.20)
    let ambientGold = NSColor(calibratedRed: 0.93, green: 0.75, blue: 0.48, alpha: 0.10)
    let stageFill = NSColor(calibratedRed: 0.13, green: 0.18, blue: 0.30, alpha: 0.94)
    let stageInner = NSColor(calibratedRed: 0.08, green: 0.12, blue: 0.22, alpha: 0.92)
    let ring = NSColor(calibratedRed: 0.87, green: 0.92, blue: 1.0, alpha: 0.24)
    let ringHighlight = NSColor(calibratedRed: 0.96, green: 0.98, blue: 1.0, alpha: 0.68)
    let orbit = NSColor(calibratedRed: 0.85, green: 0.91, blue: 1.0, alpha: 0.12)
    let baton = NSColor(calibratedRed: 0.98, green: 0.99, blue: 1.0, alpha: 0.96)
    let batonGrip = NSColor(calibratedRed: 0.95, green: 0.78, blue: 0.52, alpha: 1.0)
    let tileOutline = NSColor(calibratedRed: 1.0, green: 1.0, blue: 1.0, alpha: 0.08)
    let shadow = NSColor(calibratedWhite: 0.0, alpha: 0.28)
    let laneBlue = NSColor(calibratedRed: 0.39, green: 0.66, blue: 0.98, alpha: 1.0)
    let laneTeal = NSColor(calibratedRed: 0.23, green: 0.84, blue: 0.76, alpha: 1.0)
    let laneAmber = NSColor(calibratedRed: 1.00, green: 0.72, blue: 0.29, alpha: 1.0)
    let laneRose = NSColor(calibratedRed: 0.94, green: 0.42, blue: 0.60, alpha: 1.0)
    let laneViolet = NSColor(calibratedRed: 0.71, green: 0.54, blue: 0.97, alpha: 1.0)
}

struct LightPalette {
    let backgroundTop = NSColor(calibratedRed: 0.97, green: 0.98, blue: 1.0, alpha: 1.0)
    let backgroundBottom = NSColor(calibratedRed: 0.84, green: 0.90, blue: 0.98, alpha: 1.0)
    let ambientBlue = NSColor(calibratedRed: 0.33, green: 0.61, blue: 0.99, alpha: 0.18)
    let ambientGold = NSColor(calibratedRed: 0.96, green: 0.79, blue: 0.49, alpha: 0.12)
    let stageFill = NSColor(calibratedRed: 0.88, green: 0.92, blue: 0.98, alpha: 0.95)
    let stageInner = NSColor(calibratedRed: 0.96, green: 0.98, blue: 1.0, alpha: 0.96)
    let ring = NSColor(calibratedRed: 0.36, green: 0.44, blue: 0.63, alpha: 0.22)
    let ringHighlight = NSColor(calibratedRed: 0.31, green: 0.42, blue: 0.65, alpha: 0.72)
    let orbit = NSColor(calibratedRed: 0.33, green: 0.43, blue: 0.62, alpha: 0.12)
    let baton = NSColor(calibratedRed: 0.18, green: 0.27, blue: 0.46, alpha: 0.96)
    let batonGrip = NSColor(calibratedRed: 0.95, green: 0.78, blue: 0.52, alpha: 1.0)
    let tileOutline = NSColor(calibratedRed: 1.0, green: 1.0, blue: 1.0, alpha: 0.40)
    let shadow = NSColor(calibratedRed: 0.19, green: 0.28, blue: 0.45, alpha: 0.16)
    let laneBlue = NSColor(calibratedRed: 0.39, green: 0.66, blue: 0.98, alpha: 1.0)
    let laneTeal = NSColor(calibratedRed: 0.23, green: 0.84, blue: 0.76, alpha: 1.0)
    let laneAmber = NSColor(calibratedRed: 1.00, green: 0.72, blue: 0.29, alpha: 1.0)
    let laneRose = NSColor(calibratedRed: 0.94, green: 0.42, blue: 0.60, alpha: 1.0)
    let laneViolet = NSColor(calibratedRed: 0.71, green: 0.54, blue: 0.97, alpha: 1.0)
}

let darkPalette = Palette()
let lightPalette = LightPalette()

func withSavedGraphicsState(_ block: () -> Void) {
    NSGraphicsContext.saveGraphicsState()
    block()
    NSGraphicsContext.restoreGraphicsState()
}

func drawRoundedRect(_ rect: NSRect, radius: CGFloat, fill: NSColor) {
    fill.setFill()
    NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius).fill()
}

func fillCircle(center: CGPoint, radius: CGFloat, color: NSColor) {
    color.setFill()
    let rect = NSRect(x: center.x - radius, y: center.y - radius, width: radius * 2, height: radius * 2)
    NSBezierPath(ovalIn: rect).fill()
}

func strokeCircle(center: CGPoint, radius: CGFloat, color: NSColor, width: CGFloat) {
    color.setStroke()
    let rect = NSRect(x: center.x - radius, y: center.y - radius, width: radius * 2, height: radius * 2)
    let path = NSBezierPath(ovalIn: rect)
    path.lineWidth = width
    path.stroke()
}

func drawArc(center: CGPoint, radius: CGFloat, start: CGFloat, end: CGFloat, color: NSColor, width: CGFloat) {
    let path = NSBezierPath()
    path.appendArc(withCenter: center, radius: radius, startAngle: start, endAngle: end, clockwise: false)
    path.lineWidth = width
    path.lineCapStyle = .round
    color.setStroke()
    path.stroke()
}

func drawLine(from start: CGPoint, to end: CGPoint, color: NSColor, width: CGFloat) {
    let path = NSBezierPath()
    path.move(to: start)
    path.line(to: end)
    path.lineWidth = width
    path.lineCapStyle = .round
    color.setStroke()
    path.stroke()
}

func drawIcon(size: CGFloat, isLight: Bool) -> NSImage {
    let image = NSImage(size: NSSize(width: size, height: size))
    image.lockFocus()
    defer { image.unlockFocus() }

    let canvas = NSRect(x: 0, y: 0, width: size, height: size)
    let inset = size * 0.045
    let tileRect = canvas.insetBy(dx: inset, dy: inset)
    let tilePath = NSBezierPath(roundedRect: tileRect, xRadius: size * 0.22, yRadius: size * 0.22)
    let center = CGPoint(x: tileRect.midX, y: tileRect.midY + size * 0.045)
    let stageRadius = size * 0.26

    withSavedGraphicsState {
        tilePath.addClip()

        let background = NSGradient(colors: [
            isLight ? lightPalette.backgroundTop : darkPalette.backgroundTop,
            isLight ? lightPalette.backgroundBottom : darkPalette.backgroundBottom,
        ])!
        background.draw(in: tileRect, angle: -90)

        let ambientTop = NSGradient(colors: [
            (isLight ? lightPalette.ambientBlue : darkPalette.ambientBlue),
            (isLight ? lightPalette.ambientBlue : darkPalette.ambientBlue).withAlphaComponent(0.0),
        ])!
        ambientTop.draw(
            fromCenter: CGPoint(x: tileRect.midX, y: tileRect.maxY - size * 0.10),
            radius: 0,
            toCenter: CGPoint(x: tileRect.midX, y: tileRect.maxY - size * 0.10),
            radius: size * 0.62,
            options: []
        )

        let ambientCorner = NSGradient(colors: [
            (isLight ? lightPalette.ambientGold : darkPalette.ambientGold),
            (isLight ? lightPalette.ambientGold : darkPalette.ambientGold).withAlphaComponent(0.0),
        ])!
        ambientCorner.draw(
            fromCenter: CGPoint(x: tileRect.maxX - size * 0.10, y: tileRect.minY + size * 0.20),
            radius: 0,
            toCenter: CGPoint(x: tileRect.maxX - size * 0.10, y: tileRect.minY + size * 0.20),
            radius: size * 0.36,
            options: []
        )

        drawArc(center: CGPoint(x: center.x, y: center.y + size * 0.01),
                radius: size * 0.32,
                start: 210,
                end: 332,
                color: isLight ? lightPalette.orbit : darkPalette.orbit,
                width: size * 0.003)
        drawArc(center: CGPoint(x: center.x - size * 0.01, y: center.y - size * 0.01),
                radius: size * 0.37,
                start: 26,
                end: 152,
                color: isLight ? lightPalette.orbit : darkPalette.orbit,
                width: size * 0.003)
    }

    withSavedGraphicsState {
        let shadow = NSShadow()
        shadow.shadowBlurRadius = size * 0.05
        shadow.shadowOffset = NSSize(width: 0, height: -size * 0.02)
        shadow.shadowColor = isLight ? lightPalette.shadow : darkPalette.shadow
        shadow.set()
        fillCircle(center: center, radius: stageRadius, color: isLight ? lightPalette.stageFill : darkPalette.stageFill)
    }

    fillCircle(center: CGPoint(x: center.x, y: center.y + size * 0.006),
               radius: stageRadius * 0.80,
               color: isLight ? lightPalette.stageInner : darkPalette.stageInner)

    strokeCircle(center: center, radius: stageRadius, color: isLight ? lightPalette.ring : darkPalette.ring, width: size * 0.024)
    drawArc(center: center,
            radius: stageRadius,
            start: 34,
            end: 148,
            color: isLight ? lightPalette.ringHighlight : darkPalette.ringHighlight,
            width: size * 0.012)
    drawArc(center: center,
            radius: stageRadius * 0.82,
            start: 214,
            end: 326,
            color: isLight ? lightPalette.orbit : darkPalette.orbit,
            width: size * 0.004)

    let ensembleCenter = CGPoint(x: center.x, y: center.y - size * 0.075)
    let bandWidth = size * 0.030
    drawArc(center: ensembleCenter, radius: size * 0.165, start: 205, end: 335, color: isLight ? lightPalette.laneBlue : darkPalette.laneBlue, width: bandWidth)
    drawArc(center: ensembleCenter, radius: size * 0.130, start: 208, end: 332, color: isLight ? lightPalette.laneTeal : darkPalette.laneTeal, width: bandWidth)
    drawArc(center: ensembleCenter, radius: size * 0.095, start: 212, end: 328, color: isLight ? lightPalette.laneAmber : darkPalette.laneAmber, width: bandWidth)
    drawArc(center: ensembleCenter, radius: size * 0.060, start: 218, end: 322, color: isLight ? lightPalette.laneRose : darkPalette.laneRose, width: bandWidth)
    drawArc(center: ensembleCenter, radius: size * 0.028, start: 228, end: 312, color: isLight ? lightPalette.laneViolet : darkPalette.laneViolet, width: bandWidth * 0.92)

    fillCircle(center: CGPoint(x: center.x, y: center.y - size * 0.13),
               radius: size * 0.010,
               color: (isLight ? lightPalette.ringHighlight : darkPalette.ringHighlight).withAlphaComponent(0.85))

    let batonStart = CGPoint(x: center.x - size * 0.02, y: center.y - size * 0.01)
    let batonEnd = CGPoint(x: center.x + size * 0.18, y: center.y + size * 0.22)
    withSavedGraphicsState {
        let shadow = NSShadow()
        shadow.shadowBlurRadius = size * 0.025
        shadow.shadowOffset = NSSize(width: 0, height: -size * 0.01)
        shadow.shadowColor = isLight ? lightPalette.shadow : darkPalette.shadow
        shadow.set()
        drawLine(from: batonStart, to: batonEnd, color: isLight ? lightPalette.baton : darkPalette.baton, width: size * 0.013)
    }
    fillCircle(center: CGPoint(x: center.x - size * 0.028, y: center.y - size * 0.022),
               radius: size * 0.018,
               color: isLight ? lightPalette.batonGrip : darkPalette.batonGrip)
    fillCircle(center: batonEnd,
               radius: size * 0.009,
               color: isLight ? lightPalette.ringHighlight : darkPalette.ringHighlight)

    let tileOutline = NSBezierPath(roundedRect: tileRect, xRadius: size * 0.22, yRadius: size * 0.22)
    tileOutline.lineWidth = size * 0.004
    (isLight ? lightPalette.tileOutline : darkPalette.tileOutline).setStroke()
    tileOutline.stroke()

    return image
}

let arguments = Array(CommandLine.arguments.dropFirst())
var isLight = false
var outputPath = "AppIcon.png"

if arguments.count >= 2, arguments[0] == "--theme" {
    isLight = (arguments[1] == "light")
    if arguments.count >= 3 {
        outputPath = arguments[2]
    }
} else if let first = arguments.first {
    outputPath = first
}

let iconSize: CGFloat = 1024
let image = drawIcon(size: iconSize, isLight: isLight)

guard let tiff = image.tiffRepresentation,
      let rep = NSBitmapImageRep(data: tiff),
      let png = rep.representation(using: .png, properties: [:]) else {
    fputs("Failed to encode PNG icon.\n", stderr)
    exit(1)
}

let outputURL = URL(fileURLWithPath: outputPath)
do {
    try FileManager.default.createDirectory(at: outputURL.deletingLastPathComponent(), withIntermediateDirectories: true)
    try png.write(to: outputURL)
} catch {
    fputs("Failed to write icon to \(outputURL.path): \(error)\n", stderr)
    exit(1)
}
