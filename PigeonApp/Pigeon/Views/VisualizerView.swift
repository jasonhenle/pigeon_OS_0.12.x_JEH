import SwiftUI

/// The device's full-screen visualizers: pick the one it shows (as the encoder does),
/// and VIZ LOCK (the visualizer whatever is playing, even with track info).
@MainActor
final class VisualizerModel: ObservableObject {
    @Published private(set) var data: VisualizerState?
    @Published private(set) var busy = false
    @Published var errorText: String?
    let client: PigeonClient
    init(client: PigeonClient) { self.client = client }

    func load() async {
        do { data = try await client.visualizer(); errorText = nil }
        catch { errorText = error.localizedDescription }
    }

    func select(_ preset: VisualizerPreset) async { await send(VisualizerPatch(active: preset.index, vizLock: nil)) }
    func setVizLock(_ on: Bool) async { await send(VisualizerPatch(active: nil, vizLock: on)) }

    private func send(_ patch: VisualizerPatch) async {
        busy = true
        defer { busy = false }
        do { data = try await client.patchVisualizer(patch); errorText = nil }
        catch { errorText = error.localizedDescription }
    }
}

struct VisualizerView: View {
    @StateObject private var model: VisualizerModel

    init(client: PigeonClient) { _model = StateObject(wrappedValue: VisualizerModel(client: client)) }

    var body: some View {
        ZStack {
            Theme.canvas.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if let d = model.data {
                        lock(d)
                        VStack(alignment: .leading, spacing: 8) {
                            LCDLabel(text: "Showing", size: 18, color: Theme.accent)
                            ForEach(d.presets) { row($0, active: $0.index == d.active) }
                        }
                    } else if model.errorText == nil {
                        ProgressView().frame(maxWidth: .infinity)
                    }
                    if let e = model.errorText { Text(e).font(Theme.ui(13)).foregroundStyle(Theme.bad) }
                }
                .padding(Theme.gutter)
            }
            .refreshable { await model.load() }
        }
        .navigationTitle("Visualizer")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { if model.busy { ToolbarItem(placement: .topBarTrailing) { ProgressView() } } }
        .task { await model.load() }
    }

    private func lock(_ d: VisualizerState) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            LCDLabel(text: "Viz Lock", size: 18, color: Theme.accent)
            Picker("Viz Lock", selection: Binding(get: { d.vizLock }, set: { v in Task { await model.setVizLock(v) } })) {
                Text("Auto").tag(false)
                Text("Viz Lock").tag(true)
            }
            .pickerStyle(.segmented)
            Text(d.vizLock
                 ? "The visualizer shows whatever is playing, even with track info."
                 : "The visualizer comes up for audio without track info, or on a long press.")
                .font(Theme.ui(12)).foregroundStyle(Theme.secondaryText)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .tile()
    }

    private func row(_ preset: VisualizerPreset, active: Bool) -> some View {
        Button { Task { await model.select(preset) } } label: {
            HStack {
                Text(preset.name).font(Theme.uiBold(16)).foregroundStyle(.white)
                Spacer()
                Image(systemName: active ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 22))
                    .foregroundStyle(active ? Theme.accent : Theme.inactive)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .tile(selected: active)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(active ? .isSelected : [])
    }
}
