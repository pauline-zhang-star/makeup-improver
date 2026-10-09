# Mirror for iPhone

Native SwiftUI client for the existing Vercel Python backend. Requires iOS 17 or later and Xcode with an iOS SDK. No third-party packages or API keys are included in the app.

## Run

1. Open `MakeupTutor.xcodeproj` in Xcode and select the MakeupTutor scheme.
2. Choose an iPhone simulator and Run. The default backend is `https://mirror-makeup.vercel.app`.
3. For a physical iPhone, select your Apple Developer team under Signing & Capabilities. Keep the registered bundle identifier `com.makeuptutor.app`.
4. Choose a photo, select a style, consent to uploading it to the backend and OpenAI, and generate. Each real generation may incur AI costs.

The production HTTPS URL is configured in `MakeupTutor/Info.plist`. There is no end-user backend configuration screen.

## Behavior

- Native system photo picker; no full photo-library permission or login required. Front-facing camera capture is available with permission; denied permission offers Settings, and devices without a camera retain library selection. Captures are not auto-saved or uploaded.
- English and Chinese interface and saved instructions; older results fall back to English.
- Corrects image orientation by redrawing, proportionally reduces the longest edge to 1536, and JPEG-encodes below 2.4 MB before base64 upload.
- Uses the existing JSON `POST /api/generate` endpoint and Apple-verified subscription sessions and server-enforced daily quotas. No automatic retries of chargeable requests.
- Eight styles appear as directly selectable cards. A single photo area switches from preview to elapsed-time progress to comparison; generating scrolls back to that area.
- Drag or tap directly on the server-returned working comparison images; VoiceOver can adjust the divider. No duplicate original preview or separate slider is displayed.
- Successful results render the backend’s normalized, numbered technique arrows, matching the observed steps. Planned/rejected annotations are suppressed; the overlay does not intercept comparison gestures.
- No-change, rejected, photo-quality and unavailable-instructions outcomes have distinct explanations. No-change outcomes are not presented as successful looks. Instructions are shown only for accepted `completed` results with visible steps. Expand run details for the returned status, code and run ID.
- Allows sharing an accepted result through the system share sheet. No automatic local result history.
- The server deletes request-local files; this does not imply that OpenAI retains no data. The consent screen links to provider retention documentation.

## Verification

Build without signing:

```sh
xcodebuild -project ios/MakeupTutor.xcodeproj -scheme MakeupTutor -sdk iphonesimulator -configuration Debug -derivedDataPath /tmp/makeup-tutor-build CODE_SIGNING_ALLOWED=NO build
```

Check response safety semantics without calling AI (from repository root):

```sh
swiftc ios/MakeupTutor/Models.swift ios/Tests/main.swift -o /tmp/makeup-model-tests
/tmp/makeup-model-tests
```

Before release, test a real photo on a physical iPhone against production, including rejected photos, quota exhaustion, slow generation, network interruption and sharing. Returning from the background may interrupt a long synchronous request; background jobs and result recovery are not implemented.

## App Store preparation still required

- Select the developer team. The App Store Connect record and bundle ID are already registered.
- Verify app icon, app name, minimum iOS version, accessibility and real-device layout.
- Publish an app-specific privacy policy and support page. Complete App Store privacy disclosures based on the actual backend and provider behavior. The bundled required-reason manifest declares app-owned UserDefaults use; it is not a substitute for privacy disclosures.
- Keep server credentials in Vercel environment variables. Do not ship them in this project.
- Configure the subscription backend before TestFlight. See [subscription setup](../docs/APP_STORE_SUBSCRIPTIONS.md). All six StoreKit products and prices load from Apple; the app includes restore and manage subscriptions.
- Upload a signed archive to TestFlight, run real-device testing, and prepare screenshots, age rating, description and review notes before submission.

This is a working client implementation, not an App Store submission or a guarantee of approval.

## Local UI fixtures (Debug builds only)

Launch in the simulator with `--mirror-ui-fixture completed`, `--mirror-ui-fixture completed_no_visible_changes`, `--mirror-ui-fixture rejected`, or `--mirror-ui-fixture progress`. These use synthetic labeled images entirely on-device; they do not generate makeup or call AI. Relaunch without arguments for the real app. The fixture code is excluded from Release builds.

Photo processing consent is saved on-device in a versioned UserDefaults key scoped to Mirror/OpenAI makeup processing. Choosing a new photo and restarting the app do not reset it. Users can withdraw consent from Privacy (or beside Generate); future generation is then disabled until consent is granted again. Change the key/version and consent text if the processing purpose or recipients change.

The arrow overlay shares the generated-image reveal mask, so annotations never appear over the original. After selecting a photo, a fixed bottom bar offers style selection and generation from the retained original. Photo-picker selection is reset after loading, allowing the same library asset to be selected again and clearing the previous result.

## TestFlight build 2

Adds permission-controlled selfie camera capture and explicit App Store loading/retry states. The membership page always offers a primary action: purchase when the selected product is available, or retry when unavailable. Management is shown only with an active entitlement; restore remains available for reinstalls and other devices. Apple standard terms are labeled explicitly.

On October 9, App Store Connect Business showed Paid Apps Agreement as `New`, with a requirement to update legal entity information before signing. This blocks sandbox product availability and must be resolved by the account holder. Check all six products' IDs, prices and localizations if products still do not load after the agreement is active. See Apple's TN3186. This is separate from the backend Apple private-key configuration.

Device QA still required: grant/deny camera permission, return from Settings, cancel capture, retake/confirm, replace an existing comparison, library selection, network failure and retry, and real Sandbox purchase after commerce setup. Simulator builds do not validate actual camera capture or Apple product availability.

## TestFlight build 3: invited testing

A developer-provided test code grants ten shared generation attempts for seven days from first redemption, without Apple purchases. No code or signing secret is embedded in the app. Configure only its SHA-256 digest in `MAKEUP_TEST_CODE_SHA256` on the backend. Empty/remove that variable before public release to disable redemption and existing test sessions. Reinstalling, restoring, changing devices or redeeming again does not reset usage or expiry. Pre-provider rejections refund an attempt; provider-started attempts count. Guidance is included. Tokens are purpose-scoped, signed, and stored in Keychain. Tests remain independent from Apple subscriptions and do not validate StoreKit purchases.
