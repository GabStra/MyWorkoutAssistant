# Production Release Plan (Mobile + Wear OS)

## Scope
- Modules: `mobile` (phone), `wearos` (watch), shared code in `shared`.
- Goal: ship production-ready releases for both platforms via Play Console.

## Current state snapshot (from repo)
- `mobile` uses `compileSdk=36`, `targetSdk=35`, `minSdk=34`, version values from `version.properties`.
- `wearos` uses `compileSdk=36`, `targetSdk=35`, `minSdk=34`, version values from `version.properties`.
- Release signing is loaded from `keystore.properties` or `MWA_*` environment variables.
- Release build types enable minification and resource shrinking; Compose BOM is pinned.
- `wearos/version.properties.wear` exists but is not wired into the Gradle config.

## Plan of changes

### 1) Release strategy and package identity
- [x] Ship phone + watch under the same `applicationId` and the same Play listing.
- [ ] Confirm the listing uses a single app entry with device-specific delivery (phone + Wear) and a coordinated release track.
- [x] Define a unified versioning scheme (semver + build code) and wire Gradle to `version.properties` so version codes stay aligned.
- [ ] Update `version.properties` values before each release.

### 2) Signing and secret management
- [x] Remove hard-coded keystore path and passwords from `mobile/build.gradle.kts` and `wearos/build.gradle.kts`.
- [x] Use `keystore.properties` (or environment variables) to load signing credentials at build time.
- [x] Restore standard debug signing for debug builds; use release signing only for release builds.
- [x] Add keystore files and properties to `.gitignore` and document provisioning (`keystore.properties.example`).
- [ ] Document CI secrets mapping for `MWA_STORE_FILE`, `MWA_STORE_PASSWORD`, `MWA_KEY_ALIAS`, `MWA_KEY_PASSWORD`.

### 3) Build and release configuration
- [x] Enable release optimizations (`isMinifyEnabled=true`, `isShrinkResources=true`) for release builds in both modules.
- [ ] Verify and expand `proguard-rules.pro` for Compose/Room/serialization as needed.
- [x] Pin Compose BOM to `2025.12.01` (replace `compose-bom:+`).
- [ ] Review alpha dependencies (Wear Compose, Horologist) and decide whether to upgrade to stable versions or accept alpha risk for production.
- [x] Align `targetSdk` in `wearos` with `mobile`.
- [ ] Confirm `compileSdk` is a stable, supported value for the current AGP.
- [x] Add `applicationIdSuffix` and `versionNameSuffix` for debug builds to prevent accidental release installs.

### 4) Manifest, permissions, and policy compliance
- Audit permissions and remove any that are not strictly required:
  - Pay special attention to `SCHEDULE_EXACT_ALARM`, `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`, `USE_FULL_SCREEN_INTENT`, and location/BT permissions.
- Provide clear in-app rationale screens for sensitive permissions (health data, sensors, location, notifications).
- Confirm all exported components have the minimum required exposure and correct intent filters.
- Decide backup behavior (`android:allowBackup` + `fullBackupContent`) and ensure it matches the privacy policy.
- Prepare Play Console declarations for health data access, exact alarms, and background behavior.

### 5) Data safety, privacy, and legal
- Create a privacy policy and make it accessible from the app and the Play listing.
- Complete Play Console Data Safety form (health data, sensors, workout history, error logs).
- Add OSS license notices for bundled libraries (either in-app or in a `NOTICE` file).

### 6) Quality gates and testing
- Unit tests: `./gradlew test`.
- Instrumentation tests (phone if present): add/maintain a minimal smoke suite for critical flows.
- Wear E2E tests (mandatory): run `pwsh ./scripts/run_wear_e2e.ps1` with the maximum available timeout.
- Manual regression checklist for both platforms:
  - Onboarding/permission flows, workout selection, start/resume, rest timers, completion, sync, and error log handling.
  - Watch-only paths (alarm launch, Polar flow, sensor permissions).
- Performance and battery checks on representative devices.

### 7) Release packaging and rollout
- Produce release artifacts:
  - `./gradlew :mobile:bundleRelease`
  - `./gradlew :wearos:bundleRelease`
- Verify signatures and version codes before upload.
- Upload to internal testing tracks; verify Play pre-launch reports.
- Staged rollout with crash monitoring and rollback plan.

### 8) Observability and support readiness
- Add crash reporting (for example, Firebase Crashlytics) and basic analytics for release monitoring.
- Ensure user-facing support contact info is present in-app and on the listing.

## Deliverables
- Updated Gradle configs (signing, versions, build types) in both modules.
- Manifest and permission rationale updates.
- Privacy policy + Data Safety declarations.
- Release artifacts verified and tested.
- A repeatable release checklist documented for future releases.
