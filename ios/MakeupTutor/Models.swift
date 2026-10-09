import Foundation

struct Step: Decodable {
    let area: String
    let instruction: String
    let instruction_zh: String?
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
