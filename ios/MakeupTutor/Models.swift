import Foundation
import CoreLocation
import Combine

struct Step: Decodable {
    let area: String
    let instruction: String
    let instruction_zh: String?
    func localizedInstruction(chinese: Bool) -> String {
        if chinese { return instruction_zh ?? instruction }
        if instruction.unicodeScalars.contains(where: { (0x3400...0x9fff).contains(Int($0.value)) }) {
            return "The English instructions are unavailable for this saved result."
        }
        return instruction
    }
}
struct Callout: Decodable {
    let number: Int
    let area: String
    let label: [Double]
    let end: [Double]
    let source: String?
    var validCoordinates: Bool {
        label.count == 2 && end.count == 2 && (label + end).allSatisfy { $0.isFinite && (0...1).contains($0) }
    }
}
enum Outcome: String {
    case preview, success, noChanges, instructionsUnavailable, rejected, inputRejected, failed
}
struct Generation: Decodable {
    let id: String?
    let status: String
    let originalUrl: String?
    let afterUrl: String?
    let diagnostic: Bool?
    let message: String?
    let errorCode: String?
    let inputRejected: Bool?
    let timeoutStage: String?
    let apiTiming: [String: Double]?
    let serverDurationSeconds: Double?
    let nonAPIDurationSeconds: Double?
    let guidanceToken: String?
    let stylingSuggestion: String?
    let stylingSuggestion_zh: String?
    let steps: [Step]?
    let callouts: [Callout]?
    var outcome: Outcome {
        if inputRejected == true { return .inputRejected }
        if diagnostic == true || status == "rejected" { return .rejected }
        switch status {
        case "preview_ready": return .preview
        case "completed": return (steps ?? []).isEmpty ? .noChanges : .success
        case "completed_no_changes", "completed_no_visible_changes", "planning_rejected": return .noChanges
        case "instructions_unavailable": return .instructionsUnavailable
        default: return .failed
        }
    }
    var accepted: Bool { [.success, .instructionsUnavailable].contains(outcome) }
    var verifiedSteps: [Step] { outcome == .success ? steps ?? [] : [] }
    var verifiedCallouts: [Callout] {
        guard outcome == .success else { return [] }
        return (callouts ?? []).filter { item in
            item.validCoordinates && item.source == "observed" && item.number > 0 && item.number <= verifiedSteps.count
                && verifiedSteps[item.number - 1].area == item.area
        }
    }
    func title(chinese: Bool) -> String {
        switch outcome {
        case .preview: return chinese ? "喜欢这个妆容吗？" : "How does this look feel?"
        case .success: return chinese ? "焕新的你" : "Your look, reimagined"
        case .noChanges: return chinese ? "这次没有确认到妆容变化" : "No makeup changes confirmed"
        case .instructionsUnavailable: return chinese ? "效果图已生成，步骤暂不可用" : "Image ready; steps unavailable"
        case .rejected: return chinese ? "这次效果未通过检查" : "This look did not pass review"
        case .inputRejected: return chinese ? "换一张更清晰的自拍吧" : "Try a clearer selfie"
        case .failed: return chinese ? "这次没有完成生成" : "Generation did not finish"
        }
    }
    func explanation(chinese: Bool) -> String {
        switch outcome {
        case .preview: return chinese ? "喜欢后，再为你核对变化并准备化妆指导。" : "Like it to review the changes and prepare your tutorial."
        case .success: return chinese ? "按住照片左右滑动，看看变化。" : "Slide across the photo to explore the changes."
        case .noChanges: return chinese ? "没有足够明确的变化可生成教学步骤。可以换一种风格或换张照片再试。" : "No clear changes were confirmed for a tutorial. Try a different style or photo."
        case .instructionsUnavailable: return chinese ? "你可以对比效果图，但本次未能核实化妆步骤。" : "Compare the result, but makeup instructions could not be verified for this run."
        case .rejected: return chinese ? "仅供查看本次尝试，不作为最终妆容，也不提供教学步骤。" : "This is an unverified attempt, not a final look or tutorial."
        case .inputRejected: return chinese ? "建议正面、均匀光线，眉眼和嘴唇清楚可见。" : "Use a front-facing photo with even light and visible brows, eyes and lips."
        case .failed: return chinese ? "请检查网络后重试。再次生成会发起新的请求。" : "Check your connection before trying again. A retry starts a new request."
        }
    }
}
struct ServerError: Decodable { let error: String }

// Weather is prepared during generation; Like never waits for location or a network request.
@MainActor
final class StylingWeather: NSObject, ObservableObject, @preconcurrency CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private var pending = false
    private var requestStarted = Date.distantPast
    private var cachedUntil = Date.distantPast
    private var weatherAt = Date.distantPast
    private var cachedCell = ""
    private var weather: [String: Any]?
    private let session = URLSession(configuration: .ephemeral)
    var context: [String: Any]? { Date() < cachedUntil && Date().timeIntervalSince(weatherAt) < 3600 ? weather : nil }

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyThreeKilometers
    }
    func prepare() {
        guard CLLocationManager.locationServicesEnabled(), !pending else { return }
        pending = true
        requestStarted = Date()
        switch manager.authorizationStatus {
        case .notDetermined: manager.requestWhenInUseAuthorization()
        case .authorizedAlways, .authorizedWhenInUse: manager.requestLocation()
        default: pending = false; weather = nil
        }
    }
    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        guard pending else { return }
        switch manager.authorizationStatus {
        case .authorizedAlways, .authorizedWhenInUse: manager.requestLocation()
        case .denied, .restricted: pending = false; weather = nil
        default: break
        }
    }
    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) { pending = false; weather = nil }
    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard pending else { return }
        pending = false
        guard Date().timeIntervalSince(requestStarted) < 60, let location = locations.last,
              location.horizontalAccuracy >= 0, abs(location.timestamp.timeIntervalSinceNow) < 300 else { return }
        // Round on-device to about 11 km; precise coordinates never leave the device.
        let lat = (location.coordinate.latitude * 10).rounded() / 10
        let lon = (location.coordinate.longitude * 10).rounded() / 10
        let cell = "\(lat),\(lon)"
        if cachedCell == cell, Date() < cachedUntil { return }
        weather = nil
        Task {
            do {
                var url = URLComponents(string: "https://api.met.no/weatherapi/locationforecast/2.0/compact")!
                url.queryItems = [URLQueryItem(name: "lat", value: String(lat)), URLQueryItem(name: "lon", value: String(lon))]
                var request = URLRequest(url: url.url!, timeoutInterval: 4)
                request.setValue("Mirror/1.0 github.com/pauline-zhang-star/makeup-improver", forHTTPHeaderField: "User-Agent")
                let (data, response) = try await session.data(for: request)
                guard let http = response as? HTTPURLResponse, http.statusCode == 200,
                      let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let properties = root["properties"] as? [String: Any],
                      let series = properties["timeseries"] as? [[String: Any]], let first = series.first,
                      let time = first["time"] as? String, let date = ISO8601DateFormatter().date(from: time),
                      abs(date.timeIntervalSinceNow) < 7200,
                      let fields = first["data"] as? [String: Any],
                      let instant = fields["instant"] as? [String: Any],
                      let details = instant["details"] as? [String: Any],
                      let temperature = details["air_temperature"] as? Double, temperature.isFinite,
                      (-90...60).contains(temperature),
                      let next = fields["next_1_hours"] as? [String: Any],
                      let summary = next["summary"] as? [String: Any], let symbol = summary["symbol_code"] as? String else { return }
                let condition = symbol.contains("thunder") ? "thunderstorm" : symbol.contains("sleet") ? "sleet" : symbol.contains("snow") ? "snow" : symbol.contains("rain") ? "rain" : symbol.contains("fog") ? "fog" : symbol.contains("cloud") ? "cloudy" : "clear"
                let formatter = DateFormatter(); formatter.locale = Locale(identifier: "en_US_POSIX")
                formatter.timeZone = TimeZone(secondsFromGMT: 0); formatter.dateFormat = "EEE, dd MMM yyyy HH:mm:ss z"
                guard let expiry = http.value(forHTTPHeaderField: "Expires").flatMap({ formatter.date(from: $0) }), expiry > Date() else { return }
                weather = ["temperatureC": temperature, "condition": condition]
                cachedCell = cell; cachedUntil = expiry; weatherAt = Date()
            } catch { /* Optional weather must never interrupt makeup generation or guidance. */ }
        }
    }
}
