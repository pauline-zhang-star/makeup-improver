import SwiftUI
import StoreKit
import Security

struct MirrorPlan: Identifiable {
    let id: String
    let allowance: Int
    let title: String
    static let all = [MirrorPlan(id: "basic", allowance: 1, title: "Basic"),
                      MirrorPlan(id: "plus", allowance: 2, title: "Plus"),
                      MirrorPlan(id: "premium", allowance: 3, title: "Premium")]
    func productID(_ weekly: Bool) -> String {
        "com.makeuptutor.app.\(id).\(weekly ? "weekly" : "monthly")"
    }
    static let productIDs = all.flatMap { [$0.productID(false), $0.productID(true)] }
}

struct SubscriptionAccess: Decodable {
    let sessionToken: String?
    let active: Bool
    let productId: String?
    let dailyLimit: Int
    let remaining: Int
    let used: Int
    let resetAt: String
    let expiresAt: Double
    let isTrial: Bool
    let environment: String
}

private enum PurchaseStorage {
    static func read(_ name: String) -> String? {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "com.makeuptutor.app.purchases", kSecAttrAccount as String: name,
            kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }
    static func write(_ name: String, _ value: String) throws {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "com.makeuptutor.app.purchases", kSecAttrAccount as String: name]
        let attributes: [String: Any] = [kSecValueData as String: Data(value.utf8),
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
        let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            var new = query
            attributes.forEach { new[$0.key] = $0.value }
            guard SecItemAdd(new as CFDictionary, nil) == errSecSuccess else {
                throw Failure("无法保存购买记录 / Could not save purchase information")
            }
        } else if status != errSecSuccess {
            throw Failure("无法保存购买记录 / Could not save purchase information")
        }
    }
}

@MainActor
final class SubscriptionModel: ObservableObject {
    @Published var products: [Product] = []
    @Published var eligible: Set<String> = []
    @Published var access: SubscriptionAccess?
    @Published var loading = false
    @Published var purchasing = false
    @Published var error: String?
    @Published var notice: String?
    private(set) var sessionToken: String?
    private let endpoint: URL?
    private var updates: Task<Void, Never>?
    private let session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 45
        config.timeoutIntervalForResource = 60
        return URLSession(configuration: config)
    }()

    init() {
        let value = Bundle.main.object(forInfoDictionaryKey: "MakeupBackendURL") as? String ?? ""
        endpoint = URL(string: value)
        updates = Task { [weak self] in
            for await result in StoreKit.Transaction.updates {
                guard let self else { return }
                do {
                    guard case .verified(let transaction) = result else {
                        throw Failure("购买验证失败 / Purchase could not be verified")
                    }
                    guard MirrorPlan.productIDs.contains(transaction.productID) else { continue }
                    try await self.accept(result)
                } catch { self.error = error.localizedDescription }
            }
        }
    }
    deinit { updates?.cancel() }

    func load() async {
        guard !loading else { return }
        loading = true; error = nil
        defer { loading = false }
        do {
            products = try await Product.products(for: MirrorPlan.productIDs)
            eligible = []
            for product in products {
                if let subscription = product.subscription,
                   subscription.introductoryOffer?.paymentMode == .freeTrial,
                   subscription.introductoryOffer?.period.unit == .day,
                   subscription.introductoryOffer?.period.value == 3,
                   await subscription.isEligibleForIntroOffer {
                    eligible.insert(product.id)
                }
            }
            if products.count != MirrorPlan.productIDs.count {
                error = "部分订阅暂不可用，请稍后重试 / Some plans are unavailable. Please retry later."
            }
        } catch { self.error = error.localizedDescription }
        await refresh()
    }

    func refresh() async {
        do {
            var newest: VerificationResult<StoreKit.Transaction>?
            var latest = Date.distantPast
            for await result in StoreKit.Transaction.currentEntitlements {
                if case .verified(let tx) = result, MirrorPlan.productIDs.contains(tx.productID), tx.purchaseDate > latest {
                    latest = tx.purchaseDate; newest = result
                }
            }
            if let newest {
                try await synchronize(newest.jwsRepresentation)
            } else {
                // Ask StoreKit for the current Apple Account's transaction;
                // a saved receipt from a previous Apple Account must not grant
                // this device that old account's subscription access.
                var latestResult: VerificationResult<StoreKit.Transaction>?
                var latestDate = Date.distantPast
                for id in MirrorPlan.productIDs {
                    if let result = await StoreKit.Transaction.latest(for: id), case .verified(let tx) = result,
                       tx.purchaseDate > latestDate {
                        latestDate = tx.purchaseDate; latestResult = result
                    }
                }
                if let latestResult { try await synchronize(latestResult.jwsRepresentation) }
                else { access = nil; sessionToken = nil }
            }
        } catch {
            // No cached client entitlement grants generation on a network failure.
            access = nil; sessionToken = nil
            self.error = error.localizedDescription
        }
    }

    func buy(_ product: Product) async {
        guard !purchasing else { return }
        purchasing = true; error = nil; notice = nil
        defer { purchasing = false }
        do {
            let token: UUID
            if let saved = PurchaseStorage.read("accountToken"), let uuid = UUID(uuidString: saved) { token = uuid }
            else {
                token = UUID()
                try PurchaseStorage.write("accountToken", token.uuidString)
            }
            switch try await product.purchase(options: [.appAccountToken(token)]) {
            case .success(let result):
                try await accept(result)
                notice = "订阅已更新 / Subscription updated"
            case .pending:
                notice = "购买等待 Apple 确认，暂未解锁 / Purchase pending Apple approval"
            case .userCancelled: break
            @unknown default: throw Failure("购买暂不可用 / Purchase unavailable")
            }
        } catch { self.error = error.localizedDescription }
    }

    private func accept(_ result: VerificationResult<StoreKit.Transaction>) async throws {
        guard case .verified(let tx) = result, MirrorPlan.productIDs.contains(tx.productID) else {
            throw Failure("购买验证失败 / Purchase could not be verified")
        }
        try PurchaseStorage.write("transaction", result.jwsRepresentation)
        try await synchronize(result.jwsRepresentation)
        // Finish only after the backend has acknowledged the purchase. If it
        // is unavailable, Transaction.updates/restore can redeliver it safely.
        await tx.finish()
    }

    private func synchronize(_ signed: String) async throws {
        guard let endpoint, endpoint.scheme == "https", endpoint.host != nil else {
            throw Failure("订阅服务未配置 / Subscription service is not configured")
        }
        var request = URLRequest(url: endpoint.appendingPathComponent("api/subscription/sync"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["signedTransaction": signed])
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw Failure((try? JSONDecoder().decode(ServerError.self, from: data).error)
                          ?? "订阅验证暂不可用 / Subscription verification unavailable")
        }
        let value = try JSONDecoder().decode(SubscriptionAccess.self, from: data)
        guard let token = value.sessionToken else { throw Failure("订阅响应无效 / Invalid subscription response") }
        access = value; sessionToken = token
    }

    func restore() async {
        guard !purchasing else { return }
        purchasing = true; error = nil; notice = nil
        defer { purchasing = false }
        do {
            try await AppStore.sync()
            await refresh()
            if error == nil { notice = access?.active == true ? "已恢复订阅 / Purchases restored" : "没有有效订阅 / No active subscription found" }
        } catch { self.error = error.localizedDescription }
    }

    func authorizeGeneration() async -> String? {
        await refresh()
        guard let access, access.active, access.remaining > 0, let sessionToken else { return nil }
        return sessionToken
    }
}

struct MembershipView: View {
    @ObservedObject var subscriptions: SubscriptionModel
    let chinese: Bool
    @Environment(\.dismiss) private var dismiss
    @State private var weekly = false
    @State private var selected = "basic"
    @State private var manage = false
    private let rose = Color(red: 0.58, green: 0.28, blue: 0.33)
    private func text(_ zh: String, _ en: String) -> String { chinese ? zh : en }
    private var product: Product? {
        subscriptions.products.first { $0.id == "com.makeuptutor.app.\(selected).\(weekly ? "weekly" : "monthly")" }
    }
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    Text(text("你的美，还有更多可能", "Your beauty, new possibilities"))
                        .font(.system(size: 30, design: .serif))
                    Text(text("先看妆容效果，喜欢后再学怎么化。", "Try your look, then learn the steps."))
                        .foregroundStyle(.secondary)
                    Picker(text("计费周期", "Billing period"), selection: $weekly) {
                        Text(text("按月", "Monthly")).tag(false)
                        Text(text("按周", "Weekly")).tag(true)
                    }.pickerStyle(.segmented).disabled(subscriptions.purchasing)
                    ForEach(MirrorPlan.all) { plan in
                        let item = subscriptions.products.first { $0.id == plan.productID(weekly) }
                        Button { selected = plan.id } label: {
                            HStack {
                                VStack(alignment: .leading, spacing: 8) {
                                    Text(plan.title).font(.headline)
                                    Text(text("每天生成 \(plan.allowance) 次 · 含化妆指导", "\(plan.allowance) look\(plan.allowance == 1 ? "" : "s") daily · Includes guidance"))
                                        .font(.caption)
                                }
                                Spacer()
                                VStack(alignment: .trailing, spacing: 5) {
                                    Text(item?.displayPrice ?? "—").font(.headline)
                                    Text(text(weekly ? "每周" : "每月", weekly ? "per week" : "per month")).font(.caption)
                                }
                                Image(systemName: selected == plan.id ? "checkmark.circle.fill" : "circle")
                            }.padding(18).foregroundStyle(selected == plan.id ? rose : Color.primary)
                                .background(.white, in: RoundedRectangle(cornerRadius: 18))
                                .overlay { RoundedRectangle(cornerRadius: 18).stroke(selected == plan.id ? rose : .gray.opacity(0.2)) }
                        }.buttonStyle(.plain).disabled(subscriptions.purchasing)
                    }
                    if let access = subscriptions.access {
                        Text(access.active
                             ? text("今天剩余 \(access.remaining)／\(access.dailyLimit) 次", "\(access.remaining) of \(access.dailyLimit) generations remaining today")
                             : text("当前没有有效订阅", "No active subscription"))
                        if let reset = ISO8601DateFormatter().date(from: access.resetAt) {
                            Text(text("下次额度重置：", "Allowance resets: ") + reset.formatted(date: .abbreviated, time: .shortened))
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    if let product {
                        let trial = !weekly && subscriptions.eligible.contains(product.id)
                        Text(trial
                             ? text("免费试用三天，之后 \(product.displayPrice)／月，自动续费，除非取消。", "3 days free, then \(product.displayPrice)/month. Automatically renews unless canceled.")
                             : text("\(product.displayPrice)／\(weekly ? "周" : "月")，购买确认时收费，自动续费，除非取消。", "\(product.displayPrice)/\(weekly ? "week" : "month"), charged on confirmation. Automatically renews unless canceled."))
                            .font(.subheadline)
                        Button { Task { await subscriptions.buy(product) } } label: {
                            HStack {
                                Spacer()
                                if subscriptions.purchasing { ProgressView().tint(.white) }
                                Text(text(trial ? "开始三天免费试用" : "订阅", trial ? "Start 3-Day Free Trial" : "Subscribe"))
                                Spacer()
                            }.padding(18).foregroundStyle(.white).background(rose, in: RoundedRectangle(cornerRadius: 16))
                        }.disabled(subscriptions.purchasing || subscriptions.loading)
                    } else {
                        Text(text("订阅正在加载或暂不可用", "Plans are loading or unavailable")).foregroundStyle(.secondary)
                    }
                    Text(text("开始 AI 处理后会扣一次额度，即使结果失败；处理前拒绝的照片不扣次数。每天额度按 UTC 零点重置，未用次数不累积。化妆指导不另外扣生成次数。符合资格的月订阅用户可试用三天；周订阅无试用。同一订阅组仅一次首次优惠。", "Once AI processing starts, the attempt uses an allowance even if it fails. Photos rejected before processing do not count. Daily allowances reset at midnight UTC and do not roll over. Guidance uses no extra generation. Eligible monthly subscribers get 3 days free; weekly plans have no trial. One introductory offer per subscription group."))
                        .font(.caption).foregroundStyle(.secondary)
                    if let error = subscriptions.error { Text(error).font(.caption).foregroundStyle(rose) }
                    if let notice = subscriptions.notice { Text(notice).font(.caption) }
                    HStack {
                        Button(text("恢复购买", "Restore Purchases")) { Task { await subscriptions.restore() } }
                        Spacer()
                        Button(text("管理订阅", "Manage")) { manage = true }
                    }.font(.subheadline).disabled(subscriptions.purchasing)
                    HStack {
                        Link(text("隐私政策", "Privacy Policy"), destination: URL(string: "https://mirror-makeup.vercel.app/privacy")!)
                        Spacer()
                        Link(text("使用条款", "Terms of Use"), destination: URL(string: "https://www.apple.com/legal/internet-services/itunes/dev/stdeula/")!)
                    }.font(.caption)
                }.padding(24)
            }.background(Color(red: 0.98, green: 0.97, blue: 0.94)).tint(rose)
                .navigationTitle(text("Mirror 会员", "Mirror Membership"))
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .topBarLeading) { Button(text("关闭", "Close")) { dismiss() } }
                    ToolbarItem(placement: .topBarTrailing) { Button(text("刷新", "Refresh")) { Task { await subscriptions.load() } }.disabled(subscriptions.loading || subscriptions.purchasing) }
                }
                .manageSubscriptionsSheet(isPresented: $manage)
        }.task { await subscriptions.load() }
    }
}
