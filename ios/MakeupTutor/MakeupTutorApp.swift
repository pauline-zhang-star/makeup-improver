import SwiftUI
import PhotosUI
import UIKit

@main
struct MakeupTutorApp: App {
    var body: some Scene { WindowGroup { TutorView() } }
}

@MainActor
final class TutorModel: ObservableObject {
    @Published var photo: UIImage?
    @Published var before: UIImage?
    @Published var after: UIImage?
    @Published var result: Generation?
    @Published var busy = false
    @Published var guidanceBusy = false
    @Published var disliked = false
    @Published var previewWaitSeconds: Double?
    @Published var guidanceWaitSeconds: Double?
    @Published var error: String?
    @Published var startedAt: Date?
    private let session: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 300
        config.timeoutIntervalForResource = 330
        config.httpCookieStorage = .shared
        return URLSession(configuration: config)
    }()
    func select(_ data: Data) throws {
        guard let source = UIImage(data: data) else { throw Failure("无法读取照片 / Could not read photo") }
        let scale = min(1, 1536 / max(source.size.width, source.size.height))
        let size = CGSize(width: source.size.width * scale, height: source.size.height * scale)
        let format = UIGraphicsImageRendererFormat(); format.scale = 1
        photo = UIGraphicsImageRenderer(size: size, format: format).image { _ in source.draw(in: CGRect(origin: .zero, size: size)) }
        before = nil; after = nil; result = nil; error = nil; disliked = false
        previewWaitSeconds = nil; guidanceWaitSeconds = nil
    }
    func generate(endpoint: String, style: String, subscriptionToken: String) async {
        guard !busy, let photo else { return }
        guard let base = URL(string: endpoint.trimmingCharacters(in: .whitespacesAndNewlines)),
              base.scheme == "https", base.host != nil, base.user == nil, base.password == nil,
              base.query == nil, base.fragment == nil, base.path.isEmpty || base.path == "/" else {
            error = "服务暂不可用，请稍后再试 / The service is unavailable. Please try again later."; return
        }
        busy = true; disliked = false; startedAt = Date(); error = nil; result = nil; before = nil; after = nil
        previewWaitSeconds = nil; guidanceWaitSeconds = nil
        defer { busy = false }
        do {
            var jpeg: Data?
            for quality in [0.9, 0.8, 0.65, 0.5] {
                if let data = photo.jpegData(compressionQuality: quality), data.count < 2_400_000 { jpeg = data; break }
            }
            guard let jpeg else { throw Failure("照片太大，请换一张 / Photo is too large") }
            var request = URLRequest(url: base.appendingPathComponent("api/generate"))
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.setValue("Bearer " + subscriptionToken, forHTTPHeaderField: "Authorization")
            request.setValue("ios", forHTTPHeaderField: "X-Mirror-Client")
            request.setValue(UUID().uuidString, forHTTPHeaderField: "Idempotency-Key")
            request.httpBody = try JSONSerialization.data(withJSONObject: ["image": jpeg.base64EncodedString(), "style": style])
            // Never automatically retry: the first attempt may already have incurred an AI charge.
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse else { throw Failure("服务器响应无效 / Invalid response") }
            guard (200..<300).contains(http.statusCode) else {
                throw Failure((try? JSONDecoder().decode(ServerError.self, from: data).error) ?? "服务器错误 / Server error (\(http.statusCode))")
            }
            let job = try JSONDecoder().decode(Generation.self, from: data)
            let original = decodeImage(job.originalUrl)
            let enhanced = decodeImage(job.afterUrl)
            if job.outcome == .success && (original == nil || enhanced == nil) {
                throw Failure("无法读取效果图，请重试 / Could not load the comparison images")
            }
            before = original; after = enhanced; result = job
            previewWaitSeconds = Date().timeIntervalSince(startedAt ?? Date())
        } catch { self.error = error.localizedDescription }
    }
    func like(endpoint: String, subscriptionToken: String?) async {
        #if DEBUG
        if result?.id == "local-ui-fixture" {
            let payload: [String: Any] = ["id": "local-ui-fixture", "status": "completed", "steps": [["area": "lips", "instruction": "Blend the lip color inward.", "instruction_zh": "先勾勒唇形，再将唇色向内轻轻晕染。"]], "callouts": [["number": 1, "area": "lips", "label": [0.18, 0.5], "end": [0.38, 0.58], "source": "observed"]]]
            result = try? JSONDecoder().decode(Generation.self, from: JSONSerialization.data(withJSONObject: payload))
            return
        }
        #endif
        guard !busy, let current = result, let token = current.guidanceToken,
              let beforeURL = current.originalUrl, let afterURL = current.afterUrl,
              let base = URL(string: endpoint), base.scheme == "https" else { return }
        busy = true; guidanceBusy = true; error = nil
        let guidanceStartedAt = Date()
        defer { busy = false; guidanceBusy = false }
        do {
            var request = URLRequest(url: base.appendingPathComponent("api/guidance"))
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            guard let subscriptionToken else { throw Failure("请刷新订阅状态 / Please refresh your subscription") }
            request.setValue("Bearer " + subscriptionToken, forHTTPHeaderField: "Authorization")
            request.setValue("ios", forHTTPHeaderField: "X-Mirror-Client")
            request.httpBody = try JSONSerialization.data(withJSONObject: ["guidanceToken": token, "originalUrl": beforeURL, "afterUrl": afterURL])
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse else { throw Failure("服务器响应无效 / Invalid response") }
            guard (200..<300).contains(http.statusCode) else {
                throw Failure((try? JSONDecoder().decode(ServerError.self, from: data).error) ?? "指导暂不可用 / Tutorial unavailable")
            }
            let job = try JSONDecoder().decode(Generation.self, from: data)
            guidanceWaitSeconds = Date().timeIntervalSince(guidanceStartedAt)
            // Keep the signed preview token for an explicit retry if comparison fails.
            if job.status == "instructions_unavailable" {
                error = "暂时无法核实化妆步骤，请重试 / Could not verify the steps. Please try again."
            } else { result = job }
        } catch { self.error = error.localizedDescription }
    }
    init() {
        #if DEBUG
        // Local UI fixtures never upload photos or call a provider; excluded from Release.
        if let flag = ProcessInfo.processInfo.arguments.firstIndex(of: "--mirror-ui-fixture"),
           ProcessInfo.processInfo.arguments.count > flag + 1 {
            let status = ProcessInfo.processInfo.arguments[flag + 1]
            func sample(_ changed: Bool) -> UIImage {
                let format = UIGraphicsImageRendererFormat(); format.scale = 1
                return UIGraphicsImageRenderer(size: CGSize(width: 600, height: 750), format: format).image { ctx in
                    UIColor(red: changed ? 0.90 : 0.78, green: 0.78, blue: 0.72, alpha: 1).setFill()
                    ctx.fill(CGRect(x: 0, y: 0, width: 600, height: 750))
                    UIColor(red: changed ? 0.55 : 0.38, green: 0.30, blue: 0.33, alpha: 1).setFill()
                    UIBezierPath(ovalIn: CGRect(x: 160, y: 175, width: 280, height: 360)).fill()
                    let label = changed ? "AFTER · UI FIXTURE" : "BEFORE · UI FIXTURE"
                    (label as NSString).draw(at: CGPoint(x: 80, y: 630), withAttributes: [.font: UIFont.systemFont(ofSize: 28), .foregroundColor: UIColor.white])
                }
            }
            photo = sample(false)
            if status == "progress" { busy = true; startedAt = Date(); return }
            before = sample(false); after = sample(true)
            let payload: [String: Any] = ["id": "local-ui-fixture", "status": status, "diagnostic": status == "rejected",
                "callouts": [["number": 1, "area": "lips", "label": [0.18, 0.5], "end": [0.38, 0.58], "source": "observed"]],
                "steps": status == "completed" ? [["area": "lips", "instruction": "Blend the lip color inward.", "instruction_zh": "先勾勒唇形，再将唇色向内轻轻晕染。"]] : []]
            result = try? JSONDecoder().decode(Generation.self, from: JSONSerialization.data(withJSONObject: payload))
        }
        #endif
    }

    private func decodeImage(_ value: String?) -> UIImage? {
        guard let value, value.hasPrefix("data:image/"), let comma = value.firstIndex(of: ","),
              let bytes = Data(base64Encoded: String(value[value.index(after: comma)...])) else { return nil }
        return UIImage(data: bytes)
    }
}
struct Failure: LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}

private enum Studio {
    static let ink = Color(red: 0.21, green: 0.19, blue: 0.18)
    static let rose = Color(red: 0.58, green: 0.28, blue: 0.33)
    static let paper = Color(red: 0.98, green: 0.97, blue: 0.94)
    static let muted = Color(red: 0.48, green: 0.44, blue: 0.41)
}

struct TutorView: View {
    @StateObject private var model = TutorModel()
    @StateObject private var subscriptions = SubscriptionModel()
    @State private var membership = false
    @State private var checkingAccess = false
    @Environment(\.scenePhase) private var scenePhase
    @AppStorage("chinese") private var chinese = true
    @State private var selection: PhotosPickerItem?
    @State private var style = "Auto"
    @AppStorage("photoProcessingConsent.mirrorOpenAI.makeup.v1") private var consent = false
    @State private var privacy = false
    private let endpoint = Bundle.main.object(forInfoDictionaryKey: "MakeupBackendURL") as? String ?? ""
    private let styles = ["Auto", "Natural", "Work / Polished", "Korean Soft", "Fresh", "Date Night", "Sophisticated", "Soft Glam"]
    private let styleZH = ["自动匹配", "自然清透", "通勤精致", "韩系柔和", "元气清新", "约会夜妆", "知性高级", "柔和华丽"]
    private let subtitlesZH = ["让 AI 为你选择", "轻盈日常", "干净利落", "柔雾与层次", "明亮有精神", "更鲜明的妆感", "克制的轮廓", "柔焦光泽"]
    private let subtitlesEN = ["AI chooses for you", "Light, everyday", "Clean and refined", "Soft and layered", "Bright and lively", "A little more defined", "Balanced definition", "Soft-focus glow"]
    private let symbols = ["sparkles", "sun.max", "diamond", "leaf", "sun.haze", "moon.stars", "circle.lefthalf.filled", "star"]
    private let areas = ["eyebrows": "眉毛", "eyeliner": "眼线", "lashes": "睫毛", "eyeshadow": "眼影", "nose_contour": "鼻部修饰", "blush": "腮红", "lips": "唇妆", "complexion": "底妆"]
    private func text(_ zh: String, _ en: String) -> String { chinese ? zh : en }
    var body: some View {
        NavigationStack {
            ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 28) {
                    header
                    hero
                    photoSection.id("photo-stage")
                    if let job = model.result, !model.busy, !job.verifiedSteps.isEmpty { stepsSection(job) }
                    if let job = model.result, !model.busy { outcomeSection(job) }
                    if let error = model.error {
                        Label(error, systemImage: "exclamationmark.circle").font(.subheadline).foregroundStyle(Studio.rose).padding(18).frame(maxWidth: .infinity, alignment: .leading).background(.white, in: RoundedRectangle(cornerRadius: 18))
                    }
                    stylesSection.id("style-options")
                    generateSection.id("generate-options")
                    HStack {
                        Text("mirror / makeup studio").font(.caption)
                        Spacer()
                        Button(text("隐私说明", "Privacy")) { privacy = true }.font(.caption)
                    }.foregroundStyle(Studio.muted).padding(.vertical, 12)
                }.padding(.horizontal, 24).padding(.top, 12)
            }
            .background(Studio.paper).foregroundStyle(Studio.ink).tint(Studio.rose)
            .toolbar(.hidden, for: .navigationBar)
            .sheet(isPresented: $privacy) { privacySheet }
            .sheet(isPresented: $membership) { MembershipView(subscriptions: subscriptions, chinese: chinese) }
            .task { await subscriptions.load() }
            .onChange(of: scenePhase) { _, phase in
                if phase == .active { Task { await subscriptions.refresh() } }
            }
            .safeAreaInset(edge: .bottom) {
                if model.photo != nil {
                    HStack(spacing: 14) {
                        Button {
                            withAnimation { proxy.scrollTo("style-options", anchor: .top) }
                        } label: {
                            VStack(spacing: 4) {
                                Text(text("换风格", "Change style")).font(.system(size: 12, weight: .medium))
                                Text(chinese ? styleZH[styles.firstIndex(of: style) ?? 0] : style).font(.system(size: 10)).foregroundStyle(Studio.muted)
                            }
                        }.disabled(model.busy)
                        Button {
                            if consent { Task { await generateLook() } }
                            else { withAnimation { proxy.scrollTo("generate-options", anchor: .bottom) } }
                        } label: {
                            Text(text(model.busy ? "正在生成…" : consent ? "用原图生成妆容" : "先同意照片处理", model.busy ? "Generating…" : consent ? "Generate from original" : "Review photo consent"))
                                .font(.system(size: 13, weight: .medium)).frame(maxWidth: .infinity).padding(17)
                                .foregroundStyle(.white).background(Studio.rose, in: RoundedRectangle(cornerRadius: 14))
                        }.disabled(model.busy || checkingAccess || endpoint.isEmpty).opacity(model.busy ? 0.5 : 1)
                    }.padding(.horizontal, 24).padding(.vertical, 12).background(Studio.paper)
                }
            }
            .onChange(of: model.busy) { _, _ in
                withAnimation { proxy.scrollTo("photo-stage", anchor: .top) }
            }
            .onChange(of: model.disliked) { _, disliked in
                if disliked { withAnimation { proxy.scrollTo("style-options", anchor: .top) } }
            }
            .onChange(of: selection) { _, item in
                guard let item else { return }
                selection = nil // A later selection of the same asset must trigger a new load.
                Task {
                    do { if let data = try await item.loadTransferable(type: Data.self) { try model.select(data) } }
                    catch { model.error = error.localizedDescription }
                }
            }
            }
        }
    }
    private func generateLook() async {
        guard !checkingAccess, !model.busy else { return }
        checkingAccess = true
        defer { checkingAccess = false }
        guard let token = await subscriptions.authorizeGeneration() else {
            membership = true
            return
        }
        await model.generate(endpoint: endpoint, style: style, subscriptionToken: token)
        await subscriptions.refresh()
    }
    private var header: some View {
        HStack(alignment: .center) {
            HStack(spacing: 7) {
                Image(systemName: "sparkle").font(.system(size: 21, weight: .light)).foregroundStyle(Studio.rose)
                Text("mirror").font(.system(size: 36, weight: .regular, design: .serif)).tracking(-2)
            }.accessibilityLabel("Mirror")
            Spacer()
            Button { membership = true } label: { Image(systemName: "person.crop.circle").font(.system(size: 22)) }
                .accessibilityLabel(text("会员与订阅", "Membership and subscriptions"))
            Button(chinese ? "EN" : "中文") { chinese.toggle() }
                .font(.system(size: 13, weight: .medium)).padding(.horizontal, 14).padding(.vertical, 10)
                .background(.white.opacity(0.8), in: Capsule())
                .accessibilityLabel(chinese ? "Switch to English" : "切换为中文")
        }
    }
    private var hero: some View {
        VStack(alignment: .leading, spacing: 15) {
            Text("YOUR LOOK, MORE YOU.").font(.system(size: 10, weight: .semibold)).tracking(2.5).foregroundStyle(Studio.rose)
            (Text(text("看见更适合\n自己的", "A new look.\nStill ")).foregroundStyle(Studio.ink)
             + Text(text("妆容。", "you.")).foregroundStyle(Studio.rose))
                .font(.system(size: chinese ? 35 : 43, weight: .regular, design: .serif)).tracking(chinese ? -1 : -2).lineSpacing(5).fixedSize(horizontal: false, vertical: true)
            Text(text("一张自拍，探索你的妆容灵感。\n看见效果，也学会怎么化。", "A selfie. A little inspiration.\nSee your look, then learn to make it yours."))
                .font(.system(size: 14)).lineSpacing(5).foregroundStyle(Studio.muted)
            HStack(spacing: 12) {
                feature(text("保留你的样子", "Still you"))
                feature(text("按原妆调整", "Build on your look"))
                feature(text("逐步教你实现", "Step by step"))
            }.padding(.top, 2)
        }
    }
    private func feature(_ label: String) -> some View {
        HStack(spacing: 4) { Circle().fill(Studio.rose.opacity(0.5)).frame(width: 3, height: 3); Text(label).font(.system(size: 10)) }.foregroundStyle(Studio.muted)
    }
    private var photoSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text(model.busy ? text("正在为你设计", "Creating your look") : model.result != nil ? text("本次效果", "Your result") : text("你的照片", "Your photo")).font(.system(size: 17, weight: .medium, design: .serif))
                Spacer()
                if model.photo != nil {
                    PhotosPicker(selection: $selection, matching: .images) { Text(text("更换照片", "Change photo")).font(.caption).underline() }.disabled(model.busy)
                }
            }
            Group {
                if model.busy && !model.guidanceBusy { progressPanel }
                else if model.result?.outcome == .preview, let after = model.after {
                    VStack(spacing: 16) {
                        Image(uiImage: after).resizable().scaledToFit()
                        Text(model.disliked ? text("换一种风格，再试试。", "Choose another style and try again.") : text("喜欢这个妆容吗？", "How does this look feel?"))
                            .font(.system(size: 21, design: .serif))
                        if model.guidanceBusy {
                            ProgressView(text("正在核对变化，准备化妆指导…", "Reviewing changes and preparing your tutorial…"))
                                .font(.caption).padding(.bottom, 20)
                        } else {
                            HStack(spacing: 12) {
                                Button { Task { await subscriptions.refresh(); await model.like(endpoint: endpoint, subscriptionToken: subscriptions.sessionToken) } } label: {
                                    Text(text("♡ 喜欢 · 学怎么化", "♡ Like · Learn"))
                                        .frame(maxWidth: .infinity).padding(.vertical, 15)
                                        .background(Studio.rose, in: RoundedRectangle(cornerRadius: 12)).foregroundStyle(.white)
                                }
                                Button { model.disliked = true } label: {
                                    Text(text("不喜欢 · 换风格", "Try another style"))
                                        .frame(maxWidth: .infinity).padding(.vertical, 15)
                                        .background(Studio.rose.opacity(0.10), in: RoundedRectangle(cornerRadius: 12))
                                }
                            }.font(.system(size: 13)).buttonStyle(.plain).padding(.horizontal, 16).padding(.bottom, 20)
                        }
                    }
                }
                else if let before = model.before, let after = model.after {
                    Comparison(before: before, after: after, chinese: chinese, callouts: model.result?.verifiedCallouts ?? []).id(model.result?.id ?? model.result?.status ?? "result")
                } else if let image = model.photo {
                    Image(uiImage: image).resizable().scaledToFit().frame(maxWidth: .infinity)
                        .background(Studio.ink.opacity(0.04))
                } else {
                    PhotosPicker(selection: $selection, matching: .images) {
                        VStack(spacing: 17) {
                            ZStack {
                                Circle().fill(Color(red: 0.94, green: 0.88, blue: 0.85)).frame(width: 88, height: 88)
                                Image(systemName: "person.crop.rectangle").font(.system(size: 32, weight: .ultraLight)).foregroundStyle(Studio.rose)
                                Image(systemName: "plus.circle.fill").font(.system(size: 23)).foregroundStyle(Studio.rose, Studio.paper).offset(x: 32, y: 28)
                            }
                            Text(text("从一张自拍开始", "Start with a selfie")).font(.system(size: 20, weight: .regular, design: .serif))
                            Text(text("轻点选择照片", "Tap to choose a photo")).font(.system(size: 13)).foregroundStyle(Studio.muted)
                            Text("JPG · PNG · HEIC").font(.system(size: 10)).tracking(2).foregroundStyle(Studio.muted.opacity(0.8))
                        }.frame(maxWidth: .infinity).frame(height: 260).background(.white.opacity(0.6))
                    }.buttonStyle(.plain)
                }
            }.clipShape(RoundedRectangle(cornerRadius: 22))
                .overlay { RoundedRectangle(cornerRadius: 22).strokeBorder(Studio.ink.opacity(0.08), lineWidth: 1) }
            if model.result == nil && !model.busy {
                Text(text("正面、均匀光线，眉眼和嘴唇清楚可见。", "Face the camera in even light, with brows, eyes and lips visible.")).font(.system(size: 11)).foregroundStyle(Studio.muted)
            }
        }
    }
    private var progressPanel: some View {
        ZStack {
            if let image = model.photo { Image(uiImage: image).resizable().scaledToFill().frame(height: 340).clipped().blur(radius: 18).overlay(Studio.paper.opacity(0.88)) }
            VStack(spacing: 18) {
                ProgressView().scaleEffect(1.3).tint(Studio.rose)
                Text(text("为你描绘新的可能", "Reimagining your look")).font(.system(size: 23, weight: .regular, design: .serif))
                Text(text("分析照片并生成妆容，喜欢后再准备教学。", "Analyzing your photo and creating a preview. Like it to get your tutorial.")).font(.system(size: 12)).multilineTextAlignment(.center).foregroundStyle(Studio.muted)
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    let seconds = max(0, Int(context.date.timeIntervalSince(model.startedAt ?? context.date)))
                    Text(String(format: "%02d:%02d", seconds / 60, seconds % 60)).font(.system(size: 12, design: .monospaced)).foregroundStyle(Studio.rose)
                }
                Text(text("通常需要几分钟，请保持 App 打开。", "This can take a few minutes. Keep Mirror open.")).font(.system(size: 11)).foregroundStyle(Studio.muted)
            }.padding(28)
        }.frame(height: 340)
    }
    private var stylesSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text(text("今天，想做哪一种自己？", "What feels like you today?")).font(.system(size: 19, weight: .regular, design: .serif))
                Spacer()
                Text(text("可选", "OPTIONAL")).font(.system(size: 9)).tracking(1).foregroundStyle(Studio.muted)
            }
            Text(text("没有想法？选「自动匹配」，让 Mirror 为你设计。", "Not sure? Let Mirror choose with Auto.")).font(.system(size: 11)).foregroundStyle(Studio.muted)
            LazyVGrid(columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)], spacing: 10) {
                ForEach(Array(styles.enumerated()), id: \.offset) { index, value in
                    let selected = style == value
                    Button { style = value } label: {
                        HStack(alignment: .top, spacing: 9) {
                            Image(systemName: symbols[index]).font(.system(size: 17, weight: .light)).frame(width: 21).padding(.top, 1)
                            VStack(alignment: .leading, spacing: 5) {
                                Text(chinese ? styleZH[index] : value).font(.system(size: 12, weight: .medium))
                                Text(chinese ? subtitlesZH[index] : subtitlesEN[index]).font(.system(size: 10)).foregroundStyle(selected ? Studio.paper.opacity(0.8) : Studio.muted)
                            }
                            Spacer(minLength: 0)
                            if selected { Image(systemName: "checkmark").font(.system(size: 9, weight: .bold)) }
                        }.padding(13).frame(maxWidth: .infinity, minHeight: 68, alignment: .leading)
                            .foregroundStyle(selected ? Studio.paper : Studio.ink)
                            .background(selected ? Studio.rose : Color.white.opacity(0.7), in: RoundedRectangle(cornerRadius: 14))
                            .overlay { RoundedRectangle(cornerRadius: 14).strokeBorder(selected ? Studio.rose : Studio.ink.opacity(0.08), lineWidth: 1) }
                    }.buttonStyle(.plain).disabled(model.busy).accessibilityAddTraits(selected ? .isSelected : [])
                }
            }
        }
    }
    private var generateSection: some View {
        VStack(spacing: 15) {
            if !consent {
                Toggle(isOn: $consent) {
                    Text(text("同意将照片发送至 Mirror 服务及 OpenAI，用于妆容分析与生成。此选择会被记住，可在隐私说明中撤回。", "Allow Mirror and OpenAI to process photos for makeup analysis and generation. Your choice is saved and can be withdrawn in Privacy.")).font(.system(size: 11)).foregroundStyle(Studio.muted)
                }.disabled(model.busy)
            } else {
                HStack(spacing: 5) { Image(systemName: "checkmark.shield"); Text(text("已允许照片处理", "Photo processing permitted")); Spacer(); Button(text("撤回", "Withdraw")) { consent = false }.disabled(model.busy) }.font(.system(size: 11)).foregroundStyle(Studio.muted)
            }
            if model.photo == nil {
            Button { Task { await generateLook() } } label: {
                HStack {
                    Spacer()
                    Text(text(model.busy ? "正在设计你的妆容…" : "生成我的妆容", model.busy ? "Creating your look…" : "Reimagine my look")).font(.system(size: 15, weight: .medium))
                    Spacer()
                    Image(systemName: "arrow.up.right").font(.system(size: 14))
                }.padding(19).foregroundStyle(.white).background(Studio.rose, in: RoundedRectangle(cornerRadius: 16))
            }.buttonStyle(.plain).disabled(model.photo == nil || !consent || model.busy || endpoint.isEmpty)
                .opacity(model.photo == nil || !consent || model.busy ? 0.45 : 1)
            }
            Text(text("为你设计 · 由你决定", "Designed for you. Chosen by you.")).font(.system(size: 10)).foregroundStyle(Studio.muted)
        }
    }
    private func outcomeSection(_ job: Generation) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(job.title(chinese: chinese), systemImage: job.outcome == .success ? "sparkles" : "info.circle").font(.system(size: 17, weight: .medium, design: .serif))
            Text(job.explanation(chinese: chinese)).font(.system(size: 12)).lineSpacing(4).foregroundStyle(Studio.muted)
            if job.outcome != .success || job.apiTiming != nil {
                DisclosureGroup(text("本次详情", "Run details")) {
                    VStack(alignment: .leading, spacing: 6) {
                        if let seconds = model.previewWaitSeconds { Text(text("首次出图实际等待：", "First image wait: ") + String(format: "%.1f s", seconds)) }
                        if let seconds = model.guidanceWaitSeconds { Text(text("喜欢后教学等待：", "Tutorial wait after liking: ") + String(format: "%.1f s", seconds)) }
                        if let total = job.serverDurationSeconds { Text(text("服务端总耗时：", "Server total: ") + String(format: "%.1f s", total)) }
                        ForEach(["planning", "generation", "comparison"], id: \.self) { stage in
                            if let ms = job.apiTiming?[stage] {
                                let names = ["planning": text("照片分析", "Photo analysis"), "generation": text("图片生成", "Image generation"), "comparison": text("审核与步骤", "Review and steps")]
                                Text((names[stage] ?? stage) + String(format: ": %.1f s", ms / 1000))
                            }
                        }
                        if let local = job.nonAPIDurationSeconds { Text(text("本地处理及其他开销：", "Local and other overhead: ") + String(format: "%.1f s", local)) }
                        Text("Status: \(job.status)")
                        if let code = job.errorCode { Text("Code: \(code)") }
                        if let stage = job.timeoutStage { Text("Stage: \(stage)") }
                        if let id = job.id { Text("Run: \(id)") }
                        if let message = job.message { Text(message) }
                    }.font(.caption).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading).padding(.top, 8)
                }.font(.caption)
            }
            if job.accepted, let image = model.after {
                ShareLink(item: Image(uiImage: image), preview: SharePreview("Mirror", image: Image(uiImage: image))) {
                    Label(text("保存或分享妆容", "Save or share your look"), systemImage: "square.and.arrow.up").font(.system(size: 12))
                }
            }
        }.padding(18).frame(maxWidth: .infinity, alignment: .leading).background(.white.opacity(0.7), in: RoundedRectangle(cornerRadius: 18))
    }
    private func stepsSection(_ job: Generation) -> some View {
        VStack(alignment: .leading, spacing: 15) {
            Text("MAKE IT YOURS").font(.system(size: 10, weight: .medium)).tracking(2).foregroundStyle(Studio.rose)
            Text(text("怎样化出这个妆", "Make this look yours")).font(.system(size: 25, weight: .regular, design: .serif))
            ForEach(Array(job.verifiedSteps.enumerated()), id: \.offset) { index, step in
                HStack(alignment: .top, spacing: 16) {
                    Text(String(format: "%02d", index + 1)).font(.system(size: 24, weight: .regular, design: .serif)).foregroundStyle(Studio.rose.opacity(0.7))
                    VStack(alignment: .leading, spacing: 8) {
                        Text(chinese ? areas[step.area] ?? step.area : step.area.capitalized).font(.system(size: 15, weight: .medium))
                        Text(chinese ? step.instruction_zh ?? step.instruction : step.instruction).font(.system(size: 13)).lineSpacing(5).foregroundStyle(Studio.muted)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }.padding(.vertical, 18)
                Rectangle().fill(Studio.ink.opacity(0.1)).frame(height: 1)
            }
        }
    }
    private var privacySheet: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    Text(text("你的照片，由你决定", "Your photo, your choice")).font(.title2)
                    Text(text("只有你选择照片并同意处理、点击生成后，Mirror 才会将照片发送至服务及 OpenAI。", "Mirror sends a photo to its service and OpenAI only after you select it, permit processing and tap Generate."))
                    Text(text("Mirror 服务在请求结束后删除临时照片。OpenAI 的数据保留遵循其自身政策。", "Mirror deletes temporary server photos after the request. OpenAI retention follows its own policies."))
                    Text(text("App 不会自动保存照片或结果。你可以主动保存或分享效果图。", "The app does not automatically save photos or results. You can choose to save or share a look."))
                    Link(text("查看 OpenAI 数据政策", "Read OpenAI data policies"), destination: URL(string: "https://platform.openai.com/docs/guides/your-data")!)
                    Divider()
                    Text(consent ? text("你已允许照片处理。选择会在此设备上保存，无需每次重复同意。", "Photo processing is permitted. Your choice is saved on this device.") : text("你尚未允许照片处理。生成前需要先同意。", "Photo processing is not permitted. Consent is required before generating."))
                    if consent {
                        Button(text("撤回照片处理同意", "Withdraw photo processing consent"), role: .destructive) { consent = false }
                            .disabled(model.busy)
                        if model.busy { Text(text("正在处理的请求结束后，可以撤回后续照片处理同意。", "You can withdraw consent for future processing after the current request finishes.")).font(.caption) }
                    }

                }.font(.subheadline).padding(24)
            }.background(Studio.paper).navigationTitle(text("隐私说明", "Privacy")).navigationBarTitleDisplayMode(.inline)
                .toolbar { Button(text("完成", "Done")) { privacy = false } }
        }.tint(Studio.rose)
    }
}

struct Comparison: View {
    let before: UIImage
    let after: UIImage
    let chinese: Bool
    let callouts: [Callout]
    @State private var split = 0.5
    var body: some View {
        VStack(spacing: 0) {
            Image(uiImage: before).resizable().scaledToFit().overlay {
                GeometryReader { geometry in
                    ZStack(alignment: .leading) {
                        Image(uiImage: after).resizable().scaledToFit()
                            .frame(width: geometry.size.width, height: geometry.size.height)
                            .mask(alignment: .leading) { Rectangle().frame(width: geometry.size.width * split) }
                        Canvas { context, size in
                            for item in callouts {
                                let start = CGPoint(x: item.label[0] * size.width, y: item.label[1] * size.height)
                                let end = CGPoint(x: item.end[0] * size.width, y: item.end[1] * size.height)
                                var line = Path(); line.move(to: start); line.addLine(to: end)
                                context.stroke(line, with: .color(.white.opacity(0.95)), style: StrokeStyle(lineWidth: 4, lineCap: .round))
                                context.stroke(line, with: .color(Studio.rose), style: StrokeStyle(lineWidth: 1.6, lineCap: .round, dash: [5, 4]))
                                let angle = atan2(end.y - start.y, end.x - start.x)
                                var tip = Path(); tip.move(to: end)
                                tip.addLine(to: CGPoint(x: end.x - 8 * cos(angle - .pi / 6), y: end.y - 8 * sin(angle - .pi / 6)))
                                tip.addLine(to: CGPoint(x: end.x - 8 * cos(angle + .pi / 6), y: end.y - 8 * sin(angle + .pi / 6)))
                                tip.closeSubpath(); context.fill(tip, with: .color(Studio.rose))
                                let circle = CGRect(x: start.x - 12, y: start.y - 12, width: 24, height: 24)
                                context.fill(Path(ellipseIn: circle), with: .color(.white))
                                context.stroke(Path(ellipseIn: circle), with: .color(Studio.rose), lineWidth: 1.2)
                                context.draw(Text(String(item.number)).font(.system(size: 11, weight: .semibold)).foregroundStyle(Studio.rose), at: start)
                            }
                        }
                        .mask(alignment: .leading) { Rectangle().frame(width: geometry.size.width * split) }
                        .allowsHitTesting(false)
                        Rectangle().fill(.white).frame(width: 2, height: geometry.size.height).offset(x: geometry.size.width * split - 1)
                        Image(systemName: "arrow.left.and.right").font(.system(size: 12, weight: .semibold)).foregroundStyle(Studio.ink)
                            .frame(width: 34, height: 34).background(.white, in: Circle()).shadow(color: .black.opacity(0.15), radius: 5)
                            .offset(x: geometry.size.width * split - 17, y: max(0, geometry.size.height / 2 - 44))
                        VStack { HStack {
                            Text(chinese ? "生成图" : "AFTER").padding(8).background(.black.opacity(0.4), in: Capsule())
                            Spacer()
                            Text(chinese ? "原图" : "BEFORE").padding(8).background(.black.opacity(0.4), in: Capsule())
                        }; Spacer() }.font(.system(size: 10, weight: .medium)).foregroundStyle(.white).padding(12)
                    }.contentShape(Rectangle())
                        .gesture(DragGesture(minimumDistance: 0).onChanged { value in split = min(1, max(0, value.location.x / max(1, geometry.size.width))) })
                        .accessibilityElement(children: .ignore)
                        .accessibilityLabel(chinese ? "原图与妆容对比" : "Before and after comparison")
                        .accessibilityValue("\(Int(split * 100))%")
                        .accessibilityAdjustableAction { direction in
                            switch direction { case .increment: split = min(1, split + 0.1); case .decrement: split = max(0, split - 0.1); @unknown default: break }
                        }
                }
            }
            HStack {
                Image(systemName: "hand.draw").font(.system(size: 12))
                Text(chinese ? "左右滑动看变化 · 编号对应下方步骤" : "Slide to compare · Numbers match the steps below")
            }.font(.system(size: 11)).foregroundStyle(Studio.muted).frame(maxWidth: .infinity).padding(13).background(Studio.paper)
        }
    }
}
