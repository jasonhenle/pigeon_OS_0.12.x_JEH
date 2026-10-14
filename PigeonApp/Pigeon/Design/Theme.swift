import SwiftUI

/// Design tokens taken from PigeonOS (settings pages): black canvas, #231F20 tiles,
/// #4EA6F7 default accent, Digital-7 for LCD-style labels, Sharp Sans for UI text.
enum Theme {
    static let canvas = Color.black
    static let tile = Color(hex: 0x231F20)
    static let tileRaised = Color(hex: 0x2E2A2B)
    static let inactive = Color(hex: 0x404040)
    static let accent = Color(hex: 0x4EA6F7)
    static let ok = Color(hex: 0x58FF00)
    static let bad = Color(hex: 0xFF0000)
    static let secondaryText = Color(hex: 0x9A9A9A)

    static let corner: CGFloat = 16
    static let gutter: CGFloat = 16

    static func lcd(_ size: CGFloat) -> Font { .custom("Digital-7", size: size) }
    static func ui(_ size: CGFloat) -> Font { .custom("SharpSans-Medium", size: size) }
    static func uiBold(_ size: CGFloat) -> Font { .custom("SharpSans-Semibold", size: size) }
}

extension Color {
    init(hex: UInt32) {
        self.init(
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255
        )
    }
}

struct TileBackground: ViewModifier {
    var selected = false
    func body(content: Content) -> some View {
        content
            .padding(14)
            .background(Theme.tile, in: RoundedRectangle(cornerRadius: Theme.corner, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: Theme.corner, style: .continuous)
                    .stroke(selected ? Color.white : .clear, lineWidth: 3)
            )
    }
}

extension View {
    func tile(selected: Bool = false) -> some View { modifier(TileBackground(selected: selected)) }
}

struct LCDLabel: View {
    let text: String
    var size: CGFloat = 20
    var color: Color = .white
    var body: some View {
        Text(text.uppercased()).font(Theme.lcd(size)).foregroundStyle(color)
    }
}
