# Samsung Health Tracking Service — binder protocol notes

Derived from the jadx decompile of **HealthPlatform 1.7.00.05** (`com.samsung.android.service.health`)
on **Galaxy Watch 7 (SM-L310)**. Client code lives in
`wearos/src/main/java/com/samsung/android/service/health/tracking/` and the facade in
`wearos/src/main/java/com/gabstra/myworkoutassistant/samsung/`.

## Service

- Component: `com.samsung.android.service.health/.tracking.requesthandler.WearTrackerService`
- **EXPORTED**, bindable via action `com.samsung.android.service.health.wear.sts.ACTION_SERVICE`
  (bind with explicit `setPackage("com.samsung.android.service.health")`, flags `BIND_AUTO_CREATE`).
- `onBind` returns the `IClientEventListener.Stub` only after its `sdkPolicy` finished initializing
  (up to a 2 s await in `onCreate`); otherwise it returns **null** (client sees `onNullBinding`).
- `onUnbind` → `stopForeground(1)` + `stopSelf()`, so the service only stays alive while bound.
- Samsung's own connector refuses to bind when `versionCode < 150407000` (errors:
  `0 = PACKAGE_NOT_INSTALLED`, `1 = OLD_PLATFORM_VERSION`); our impl replicates the check.

## Auth gate (why this works)

`TrackerRequestHandler.handleMessage` case `1` (setEventListener) checks
`FeatureList.Key.COMMON_DEVELOPER_MODE`; when **developer mode is enabled** it logs
"Common Developer Mode, No need to check service policy" and registers the listener directly.
With developer mode off, an SDK policy check (signature whitelist keyed by `appId` =
`context.packageName`) runs and failures come back as `onThrowException(SDK_POLICY_ERROR)`.
Runtime permissions remain enforced **in both modes** (see Permissions).

## Binder interface: IClientEventListener (client → service)

Descriptor: `com.samsung.android.service.health.tracking.IClientEventListener`.
All calls are synchronous two-way (`transact(..., 0)` + `readException()`).
Transaction codes are declaration-order derived; exact order:

| # | method | parcel layout |
|---|--------|----------------|
| 1 | `void createHealthTracker(String appId, String trackertype, TrackerUserProfile userProfile, String exerciseType)` | String, String, typedObject(int present flag + 4 fields: float height, float weight, int gender, int age), String |
| 2 | `void setEventListener(String appId, String trackertype, IServiceEventListener listener)` | String, String, writeStrongInterface |
| 3 | `void unsetEventListener(String appId, String trackertype)` | String, String |
| 4 | `void flush(String appId, String trackertype)` | String, String |
| 5 | `List<String> getSupportedHealthTrackerTypes()` | reply: writeNoException, writeStringList |
| 6 | `void setExerciseState(String appId, String trackertype, String exerciseState)` | String, String, String |
| 7 | `void setExerciseData(String appId, String trackertype, String dataType, float[] data, long[] timestamp)` | String, String, String, createFloatArray, createLongArray |
| 8 | `void setPpgType(String appId, String trackertype, List<String> ppgTypes)` | String, String, writeStringList/createStringArrayList |

`exerciseState` is `"START"` / `"STOP"`; `dataType` is `"SPM"` (steps per minute, exercise only);
`exerciseType` is `"WALKING"` / `"RUNNING"` or null. Internally each call becomes a
`Message(what = 0..6, obj = ClientParams)` on the service's `requestHandlerThread` —
`ClientParams` is a plain object (never parceled), so it is **not** part of the wire format.

## Binder interface: IServiceEventListener (service → client)

Descriptor: `com.samsung.android.service.health.tracking.IServiceEventListener`.
The client implements the Stub; the service wraps it in the Proxy:

| # | method | parcel layout |
|---|--------|----------------|
| 1 | `void onDataUpdated(List<ServiceDataPoint> dataPoints)` | AIDL typed list: int size, then per element int present flag + fields |
| 2 | `void onThrowException(int errorCode)` | int — `HealthTracker.TrackerError.ordinal()`: 0 = `PERMISSION_ERROR`, 1 = `SDK_POLICY_ERROR` |
| 3 | `void onFlushCompleted()` | — |

### Payload parcelables

- `ServiceDataPoint` (`...tracking.data.ServiceDataPoint`): `long timestamp` (epoch **milliseconds**,
  set with `System.currentTimeMillis()` server-side), then `List<ServiceValue>` written with
  `Parcel.writeList` — self-describing, so our local `ServiceValue` must keep the exact
  fully-qualified name and field order (`int integerValue, float floatValue, long longValue`).
  Each `ServiceValue` is a tagged union; which field is meaningful depends on the position in the
  list (see table below).
- `TrackerUserProfile` (`...tracking.data.TrackerUserProfile`): `float height` (cm), `float weight`
  (kg), `int gender` (0 male / 1 female), `int age`. Validation used by BIA/SWEAT_LOSS:
  height 20..300, weight 2..500, gender 0..1, age 0..200.

## Tracker type strings (wire constant → facade enum)

Server tracker strings come from `HealthTrackingService.l.convertTrackerTypeToString`;
one string can back several SDK constants:

| wire string | facade type | notes |
|---|---|---|
| `HEART_RATE` | HEART_RATE_CONTINUOUS | |
| `PPG_CONTINUOUS` | PPG_CONTINUOUS | green+ir+red per sample; `setPpgType` only affects Samsung logging |
| `SPO2` | SPO2_CONTINUOUS | same server tracker serves `SPO2` and `SPO2_ON_DEMAND` |
| `SKIN_TEMPERATURE` | SKIN_TEMPERATURE_ON_DEMAND | continuous variant is `SKIN_TEMPERATURE_CONTINUOUS` |
| `SWEAT_LOSS` | SWEAT_LOSS | requires profile + `createHealthTracker(..., exerciseType)` + `setExerciseState("START")`; auto-stop ends measurement |
| `ACCELEROMETER` | ACCELEROMETER_CONTINUOUS | |
| `ECG` | ECG_ON_DEMAND | waits for fingers on the bezel (lead-off via `EcgSet.LEAD_OFF`) |
| `BIA` | BIA_ON_DEMAND | requires profile; measurement triggers on the hardware gesture |
| `EDA_CONTINUOUS` | EDA_CONTINUOUS | |
| `PPG_GREEN`, `PPG_RED`, `PPG_IR`, `PPG_ON_DEMAND`, `MFBIA_ON_DEMAND`, `BIA` (continuous), `SKIN_TEMPERATURE_CONTINUOUS` | — | not exposed by our facade |

Capability: transaction 5 returns strings derived from Samsung sensor-type availability
(`TrackerCapability.trackerMap`: sensor 24→HEART_RATE, 27→ECG, 26→PPG_GREEN+ACCELEROMETER,
35→PPG_IR+PPG_RED+SPO2, 38→BIA, 39→SWEAT_LOSS (version-gated), 50→SKIN_TEMPERATURE(+CONTINUOUS),
60→PPG_CONTINUOUS, 61→PPG_ON_DEMAND, 68→EDA_CONTINUOUS, 71→MFBIA_ON_DEMAND).

## ValueKey layout per tracker (from `ServiceDataPoint.convert*ToDataPoint`)

These methods are Samsung's own decoders and are copied verbatim into our
`ServiceDataPoint.java`; they are authoritative for HealthPlatform 1.7.00.05.

- **HEART_RATE** (`convertHrToDataPoint`): [0]=HEART_RATE int, [1]=raw int (unused), [2]=HEART_RATE_STATUS int,
  [3]=IBI count N, then N×(ibi, ibiStatus) pairs starting at index 4 → IBI_LIST / IBI_STATUS_LIST (ms).
- **PPG_CONTINUOUS** (`convertPpgToDataPoint`): [0]=PPG_GREEN, [1]=GREEN_STATUS, [2]=PPG_RED,
  [3]=RED_STATUS, [4]=PPG_IR, [5]=IR_STATUS (all int). Status 0 = ok.
- **SPO2** (`convertSpO2ToDataPoint`): [0]=STATUS int, [1]=SPO2 int (%), [2]=HEART_RATE int, [3]=ACCURACY_FLAG int.
- **SKIN_TEMPERATURE** (`convertSkinTemperatureToDataPoint`): [0]=OBJECT_TEMPERATURE float (°C, skin/skin-contact temp),
  [1]=AMBIENT_TEMPERATURE float, [2]=STATUS int.
- **SWEAT_LOSS** (`convertSweatLossToDataPoint`): [0]=SWEAT_LOSS float (ml), [1]=STATUS int.
- **ACCELEROMETER** (`convertAccToDataPoint`): [0..2]=X,Y,Z ints (raw sensor values, facade converts to Float).
- **ECG** (`convertEcgToDataPoint`): [0]=ECG_MV float, [1]=PPG_GREEN int, [2]=LEAD_OFF int, [3]=SEQUENCE int,
  [4]=MAX_THRESHOLD_MV float, [5]=MIN_THRESHOLD_MV float.
- **BIA** (`convertBiaToDataPoint`): [0]=STATUS int, then floats [1]=BODY_FAT_RATIO, [2]=BODY_FAT_MASS,
  [3]=TOTAL_BODY_WATER, [4]=SKELETAL_MUSCLE_RATIO, [5]=SKELETAL_MUSCLE_MASS, [6]=BASAL_METABOLIC_RATE,
  [7]=FAT_FREE_RATIO, [8]=FAT_FREE_MASS, [9]=PROGRESS, [10]=BODY_IMPEDANCE_MAGNITUDE (Ω),
  [11]=BODY_IMPEDANCE_DEGREE.
- **EDA_CONTINUOUS** (`convertEdaToDataPoint`): [0]=SKIN_CONDUCTANCE float (µS), [1]=STATUS int.
  The facade contract exposes EDA as `Int`, so the float is rounded.
- **MFBIA_ON_DEMAND** (`convertMfBiaToDataPoint`, not in facade): per frequency in {5K,10K,50K,250K}
  → (MAGNITUDE, PHASE) float pairs at indexes 0..7, [8]=STATUS int, [9]=PROGRESS float.

## Permissions (still enforced with developer mode on)

Service-side `PermissionUtil` runs `context.enforcePermission(...)` with the **caller's pid/uid**
on `setEventListener` and again before each data callback. Default map (targetSdk < 36):

- `ACCELEROMETER` → `android.permission.ACTIVITY_RECOGNITION`
- everything else → `android.permission.BODY_SENSORS`
- `SWEAT_LOSS` → both `ACTIVITY_RECOGNITION` + `BODY_SENSORS`

(targetSdk ≥ 36 **on the device** (Android ≥ 16) would switch to granular Health
Connect-style permissions via `PermissionUtil.isGranularPermissionRequired` — the condition is
*client targetSdkVersion ≥ 36 AND device SDK_INT ≥ 36*; the app has targetSdk 36 but Galaxy
Watch 7 ships Android 14/15, so the default map above applies. If a tracker unexpectedly
returns `PERMISSION_ERROR` on a future Android-16 watch, re-check the granular map in the
service decompile: PPG/ECG/BIA/EDA/SWEAT_LOSS then map to Samsung
`READ_ADDITIONAL_HEALTH_DATA`, HEART_RATE to `android.permission.health.READ_HEART_RATE`,
SPO2 to `android.permission.health.READ_OXYGEN_SATURATION`, SKIN_TEMPERATURE to
`android.permission.health.READ_SKIN_TEMPERATURE`, ACCELEROMETER stays ACTIVITY_RECOGNITION.)
Missing permission ⇒ `onThrowException(0)` (PERMISSION_ERROR) or a thrown SecurityException.

## Errors surfaced by the facade

- `HealthTrackerException.getErrorCode()`: 0 `PACKAGE_NOT_INSTALLED`, 1 `OLD_PLATFORM_VERSION`
  (connector-level; before binding).
- `onThrowException(int)`: 0 `PERMISSION_ERROR`, 1 `SDK_POLICY_ERROR` (policy check failure —
  not expected with developer mode enabled).
- Null binder from `onBind`, bind failures, timeouts → `SamsungConnectionState.Failed`.

## Version-specific notes (1.7.00.05)

- `getClientProcessMap` remembers the caller pid/uid from `setEventListener` and re-checks
  permissions on every data delivery — revoking BODY_SENSORS mid-stream stops callbacks.
- `getSupportedHealthTrackerTypes` result is cached client-side in Samsung's own SDK
  (`HealthTrackerCapability`); our facade queries fresh each call instead.
- Sweat-loss availability is additionally gated by the sensor-manager version check
  (`Ou.c >= Ou.a`) inside the service's capability scan.
- Samsung's connector serializes the whole bind in a 20 s future; our facade uses 15 s.

## API 36 (granular permission map) readiness

The service's `PermissionUtil` picks the permission map with
`callerTargetSdk >= 36 && Build.VERSION.SDK_INT >= 36`. The app currently targets 35, so the
default map (BODY_SENSORS / ACTIVITY_RECOGNITION) always applies. The granular path is already
wired so a future `targetSdk = 36` bump is safe once an API 36 watch firmware exists:

- Manifest declares `com.samsung.android.hardware.sensormanager.permission.READ_ADDITIONAL_HEALTH_DATA`
  (protectionLevel **dangerous** — runtime-grantable, verified in SemSensorPermission.apk),
  `android.permission.health.READ_HEART_RATE` and `READ_OXYGEN_SATURATION` (Health Connect).
- `PermissionRequestDialog.missingWorkoutPermissions()` requests the granular set when the
  Samsung toggle is on and the watch runs API 36+.
- `SamsungHealthClientImpl.requiredPermissions()` mirrors the service's map selection, so the
  client-side pre-check matches whatever the service will enforce.

Note on API 36: Health Connect permissions (`android.permission.health.*`) are normally granted
through Health Connect's own flow, not the plain runtime dialog; if the plain request is denied
on a real API 36 watch, grant via Health Connect settings or
`adb shell pm grant com.gabstra.myworkoutassistant <permission>`.
