import Foundation

let statuses = ["completed", "completed_no_visible_changes", "instructions_unavailable", "rejected", "failed", "completed_no_changes", "planning_rejected", "unknown"]
for status in statuses {
    for diagnostic in [true, false] {
        let payload: [String: Any] = ["status": status, "diagnostic": diagnostic,
            "steps": [["area": "lips", "instruction": "Blend inward", "instruction_zh": "向内晕染"]]]
        let result = try JSONDecoder().decode(Generation.self, from: JSONSerialization.data(withJSONObject: payload))
        let accepted = !diagnostic && ["completed", "instructions_unavailable"].contains(status)
        precondition(result.accepted == accepted)
        precondition(result.verifiedSteps.count == (!diagnostic && status == "completed" ? 1 : 0))
        if !diagnostic && ["completed_no_changes", "completed_no_visible_changes", "planning_rejected"].contains(status) {
            precondition(result.outcome == .noChanges)
        }
        if diagnostic { precondition(result.outcome == .rejected) }
    }
}
func decode(_ json: String) throws -> Generation { try JSONDecoder().decode(Generation.self, from: Data(json.utf8)) }
let partial = try decode(#"{"status":"instructions_unavailable","afterUrl":"data:image/jpeg;base64,YQ=="}"#)
precondition(partial.outcome == .instructionsUnavailable && partial.verifiedSteps.isEmpty)
let empty = try decode(#"{"status":"completed","steps":[]}"#)
precondition(empty.outcome == .noChanges && !empty.accepted)
let input = try decode(#"{"status":"failed","inputRejected":true,"errorCode":"PHOTO_QUALITY"}"#)
precondition(input.outcome == .inputRejected)
let legacy = try JSONDecoder().decode(Step.self, from: Data(#"{"area":"lips","instruction":"Blend inward"}"#.utf8))
precondition(legacy.instruction_zh == nil)
precondition(partial.title(chinese: true) != empty.title(chinese: true))
print("Passed: result safety matrix, distinct no-change/partial/rejected/input-error outcomes, empty-step results, and legacy English steps")
let annotated = try decode(#"{"status":"completed","steps":[{"area":"lips","instruction":"Blend"}],"callouts":[{"number":1,"area":"lips","label":[0.1,0.5],"end":[0.3,0.55],"source":"observed"},{"number":2,"area":"lips","label":[0.1,0.5],"end":[0.3,0.55],"source":"observed"},{"number":1,"area":"lips","label":[-1,0.5],"end":[0.3,0.55],"source":"observed"},{"number":1,"area":"lips","label":[0.1,0.5],"end":[0.3,0.55],"source":"planned"},{"number":1,"area":"blush","label":[0.1,0.5],"end":[0.3,0.55],"source":"observed"}]}"#)
precondition(annotated.verifiedCallouts.count == 1)
let rejectedAnnotation = try decode(#"{"status":"rejected","callouts":[{"number":1,"area":"lips","label":[0.1,0.5],"end":[0.3,0.55],"source":"observed"}]}"#)
precondition(rejectedAnnotation.verifiedCallouts.isEmpty)
precondition(partial.verifiedCallouts.isEmpty && empty.verifiedCallouts.isEmpty)
print("Passed: normalized arrow coordinates, step numbering, observed-only filtering, and rejected-result suppression")

let preview = try JSONDecoder().decode(Generation.self, from: Data("{\"status\":\"preview_ready\",\"steps\":[{\"area\":\"lips\",\"instruction\":\"Hidden\"}],\"callouts\":[]}".utf8))
assert(preview.outcome == .preview && preview.verifiedSteps.isEmpty && preview.verifiedCallouts.isEmpty)
print("Passed: preview hides tutorial until liked and compared")
