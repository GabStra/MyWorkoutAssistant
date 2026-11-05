package com.gabstra.myworkoutassistant.samsung

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.content.pm.PackageManager
import android.os.Build
import android.os.IBinder
import android.os.RemoteException
import com.samsung.android.service.health.tracking.IClientEventListener
import com.samsung.android.service.health.tracking.IServiceEventListener
import com.samsung.android.service.health.tracking.data.DataPoint
import com.samsung.android.service.health.tracking.data.ServiceDataPoint
import com.samsung.android.service.health.tracking.data.TrackerUserProfile
import com.samsung.android.service.health.tracking.data.ValueKey
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeout
import java.util.concurrent.ConcurrentHashMap
import kotlin.coroutines.resume
import kotlin.math.roundToInt

/**
 * Factory for the app wiring ([com.gabstra.myworkoutassistant.repository.SamsungSensorDataRepository]).
 * Returns the default [SamsungHealthTrackerClient] bound to the on-device Health Tracking Service.
 */
fun createSamsungHealthTrackerClient(context: Context): SamsungHealthTrackerClient =
    SamsungHealthClientImpl(context)

/**
 * Client for Samsung's hidden Health Tracking Service
 * (`com.samsung.android.service.health/.tracking.requesthandler.WearTrackerService`)
 * as shipped in HealthPlatform 1.7.00.05 on Galaxy Watch 7 (SM-L310).
 *
 * Speaks the raw binder protocol reconstructed from the service decompile
 * (see docs/samsung-health-protocol.md). Works on watches where hidden developer
 * mode (COMMON_DEVELOPER_MODE) is enabled: the service skips its partner signature
 * whitelist when developer mode is on, leaving only plain runtime permissions
 * (BODY_SENSORS, ACTIVITY_RECOGNITION) as the gate.
 */
class SamsungHealthClientImpl(context: Context) : SamsungHealthTrackerClient {

    private val appContext: Context = context.applicationContext
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    private val _connectionState =
        MutableStateFlow<SamsungConnectionState>(SamsungConnectionState.Disconnected)
    override val connectionState: StateFlow<SamsungConnectionState> = _connectionState

    private val _errorEvents = MutableSharedFlow<String>(extraBufferCapacity = 32)
    override val errorEvents: SharedFlow<String> = _errorEvents

    @Volatile
    private var service: IClientEventListener? = null

    /** Profile captured at connect(); required by BIA_ON_DEMAND and SWEAT_LOSS. */
    @Volatile
    private var profile: TrackerProfile? = null

    /** Listener binder registered per tracker type, so disconnect() can unset them all. */
    private val activeListeners = ConcurrentHashMap<String, IServiceEventListener>()

    private var connecting: ((IBinder?) -> Unit)? = null

    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, binder: IBinder?) {
            val client = IClientEventListener.Stub.asInterface(binder)
            service = client
            connecting?.invoke(binder)
            connecting = null
            if (client != null) {
                _connectionState.value = SamsungConnectionState.Connected
            } else {
                // Server returned a null interface binder (its sdkPolicy did not finish
                // initializing). Report and retry-able failure.
                _connectionState.value = SamsungConnectionState.Failed(
                    "Service bound but returned null binder (HealthPlatform SDK policy not initialized yet)"
                )
                emitError("onServiceConnected: null binder from WearTrackerService")
            }
        }

        override fun onServiceDisconnected(name: ComponentName?) {
            service = null
            if (_connectionState.value is SamsungConnectionState.Failed) return
            _connectionState.value = SamsungConnectionState.Disconnected
            emitError("Service disconnected (HealthPlatform process died)")
        }

        override fun onNullBinding(name: ComponentName?) {
            service = null
            connecting?.invoke(null)
            connecting = null
            _connectionState.value =
                SamsungConnectionState.Failed("Service returned null binding (onNullBinding)")
            emitError("Service returned null binding (onNullBinding)")
        }

        override fun onBindingDied(name: ComponentName?) {
            service = null
            connecting?.invoke(null)
            connecting = null
            _connectionState.value =
                SamsungConnectionState.Failed("Service binding died (onBindingDied)")
            emitError("Service binding died (onBindingDied)")
        }
    }

    // ------------------------------------------------------------------ connect / disconnect

    override suspend fun connect(profile: TrackerProfile?) {
        if (_connectionState.value == SamsungConnectionState.Connected) return
        this.profile = profile
        _connectionState.value = SamsungConnectionState.Connecting

        // Version gate copied from Samsung's own connector: min HealthPlatform versionCode
        // 150407000 (1.5.04.7000). Fail with the SDK's error code names.
        val packageInfo = try {
            appContext.packageManager.getPackageInfo(HEALTH_PACKAGE, 0)
        } catch (e: PackageManager.NameNotFoundException) {
            _connectionState.value = SamsungConnectionState.Failed(
                "PACKAGE_NOT_INSTALLED (0): $HEALTH_PACKAGE not installed on this device"
            )
            emitError("PACKAGE_NOT_INSTALLED: $HEALTH_PACKAGE not installed")
            return
        }
        if (packageInfo.versionCode < MIN_HEALTH_VERSION_CODE) {
            _connectionState.value = SamsungConnectionState.Failed(
                "OLD_PLATFORM_VERSION (1): HealthPlatform ${packageInfo.versionName} " +
                    "too old, requires versionCode >= $MIN_HEALTH_VERSION_CODE"
            )
            emitError("OLD_PLATFORM_VERSION: ${packageInfo.versionName}")
            return
        }

        val intent = Intent(ACTION_TRACKING_SERVICE).setPackage(HEALTH_PACKAGE)
        val bound = try {
            appContext.bindService(intent, connection, Context.BIND_AUTO_CREATE)
        } catch (e: SecurityException) {
            _connectionState.value = SamsungConnectionState.Failed("bindService failed: ${e.message}")
            emitError("bindService failed: ${e.message}")
            return
        }
        if (!bound) {
            _connectionState.value = SamsungConnectionState.Failed(
                "bindService returned false — WearTrackerService not available/exported"
            )
            emitError("bindService returned false")
            return
        }

        val binder = try {
            withTimeout(CONNECT_TIMEOUT_MS) {
                suspendCancellableCoroutine<IBinder?> { cont ->
                    connecting = { b -> if (cont.isActive) cont.resume(b) }
                }
            }
        } catch (e: Exception) {
            runCatching { appContext.unbindService(connection) }
            service = null
            _connectionState.value =
                SamsungConnectionState.Failed("Timed out connecting to WearTrackerService")
            emitError("connect timeout: ${e.message}")
            return
        }
        if (binder == null && _connectionState.value == SamsungConnectionState.Connecting) {
            // onServiceConnected fired with a binder that produced a null interface.
            _connectionState.value = SamsungConnectionState.Failed(
                "Service connected but returned null client binder"
            )
        }
    }

    override suspend fun disconnect() {
        // Best-effort: release every tracker listener server-side before unbinding, otherwise
        // the service keeps sensor listeners (and its foreground notification) running.
        service?.let { svc ->
            activeListeners.keys.toList().forEach { type ->
                runCatching { if (type == SERVER_SWEAT_LOSS) svc.setExerciseState(appId(), type, "STOP") }
                runCatching { svc.unsetEventListener(appId(), type) }
            }
        }
        activeListeners.clear()
        runCatching { appContext.unbindService(connection) }
        service = null
        connecting = null
        _connectionState.value = SamsungConnectionState.Disconnected
    }

    // ------------------------------------------------------------------------- capabilities

    override suspend fun availableTrackers(): Set<SamsungTrackerType> {
        val svc = requireService()
        val strings = svc.getSupportedHealthTrackerTypes() ?: return emptySet()
        // One server string can back several SDK enum constants (e.g. "HEART_RATE" covers
        // HEART_RATE and HEART_RATE_CONTINUOUS) — map onto our facade enum.
        val supported = HashSet<SamsungTrackerType>()
        for (s in strings) {
            SERVER_TO_FACADE[s]?.let { supported.add(it) }
        }
        return supported
    }

    // --------------------------------------------------------------------------- data flows

    /** Mirrors the service's PermissionUtil.isGranularPermissionRequired(). */
    private fun requiredPermissions(type: SamsungTrackerType): List<String> {
        val granular = Build.VERSION.SDK_INT >= 36 &&
            appContext.applicationInfo.targetSdkVersion >= 36
        return if (granular) {
            GRANULAR_RUNTIME_PERMISSIONS[type].orEmpty()
        } else {
            REQUIRED_RUNTIME_PERMISSION[type]?.let { listOf(it) }.orEmpty()
        }
    }

    override fun samples(type: SamsungTrackerType): Flow<SamsungSample> = callbackFlow {
        val svc = requireServiceOrClose()
        if (svc == null) {
            awaitClose { }
            return@callbackFlow
        }
        val trackerType = SERVER_TRACKER_TYPE[type]!!

        // The service enforces these per-tracker at setEventListener with the caller's
        // uid/pid; failing fast here gives a clearer message than a PERMISSION_ERROR loop.
        val missingPermissions = requiredPermissions(type).filter {
            appContext.checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED
        }
        if (missingPermissions.isNotEmpty()) {
            emitError(
                "${missingPermissions.joinToString()} not granted for $trackerType — " +
                    "request it before collecting"
            )
            close()
            awaitClose { }
            return@callbackFlow
        }

        val needsProfile = type == SamsungTrackerType.BIA_ON_DEMAND ||
            type == SamsungTrackerType.SWEAT_LOSS
        val userProfile: TrackerUserProfile? = if (needsProfile) {
            val p = profile
            if (p == null) {
                emitError(
                    "${type.name} requires a TrackerProfile — pass one to connect()"
                )
                close()
                awaitClose { }
                return@callbackFlow
            }
            val validationError = validateProfile(p)
            if (validationError != null) {
                emitError("Invalid TrackerProfile for ${type.name}: $validationError")
                close()
                awaitClose { }
                return@callbackFlow
            }
            TrackerUserProfile.Builder()
                .setHeight(p.heightCm.toFloat())
                .setWeight(p.weightKg)
                .setGender(p.gender)
                .setAge(p.age)
                .build()
        } else {
            null
        }

        val exerciseType: String? =
            if (type == SamsungTrackerType.SWEAT_LOSS) "WALKING" else null

        val listener = object : IServiceEventListener.Stub() {
            override fun onDataUpdated(dataPoints: MutableList<ServiceDataPoint>?) {
                if (dataPoints == null) return
                for (sdp in dataPoints) {
                    val sample = runCatching { mapToSample(type, sdp) }.getOrNull()
                    if (sample != null) trySend(sample)
                }
            }

            override fun onThrowException(errorCode: Int) {
                val name = when (errorCode) {
                    TRACKER_ERROR_PERMISSION -> "PERMISSION_ERROR"
                    TRACKER_ERROR_SDK_POLICY -> "SDK_POLICY_ERROR"
                    else -> "TRACKER_ERROR($errorCode)"
                }
                emitError("$name (${type.name})")
                // End this collection; the app can inspect errorEvents for the reason.
                close()
            }

            override fun onFlushCompleted() {
                // flush() is not part of the facade; nothing to surface.
            }
        }

        try {
            // Fail fast on trackers this watch doesn't expose, instead of a cryptic
            // service-side error after createHealthTracker.
            val supported = runCatching { svc.getSupportedHealthTrackerTypes() }.getOrNull()
            if (supported != null && trackerType !in supported) {
                emitError("${type.name} not supported on this watch (supported: ${supported.joinToString()})")
                close()
                awaitClose { }
                return@callbackFlow
            }
            svc.createHealthTracker(appId(), trackerType, userProfile, exerciseType)
            svc.setEventListener(appId(), trackerType, listener)
            if (type == SamsungTrackerType.SWEAT_LOSS) {
                // Sweat loss only measures while its pseudo-exercise is running.
                svc.setExerciseState(appId(), trackerType, "START")
            }
        } catch (e: RemoteException) {
            emitError("RemoteException activating ${type.name}: ${e.message}")
            close(e)
            awaitClose { }
            return@callbackFlow
        }
        activeListeners[trackerType] = listener

        awaitClose {
            activeListeners.remove(trackerType)
            runCatching {
                // Push buffered samples out before detaching, or the tail of a session is lost.
                runCatching { svc.flush(appId(), trackerType) }
                if (type == SamsungTrackerType.SWEAT_LOSS) {
                    svc.setExerciseState(appId(), trackerType, "STOP")
                }
                svc.unsetEventListener(appId(), trackerType)
            }.onFailure {
                emitError("Failed to unset ${type.name}: ${it.message}")
            }
        }
    }

    // --------------------------------------------------------------------------- internals

    private fun appId(): String = appContext.packageName

    private fun requireService(): IClientEventListener {
        val svc = service
        if (svc == null) {
            val state = _connectionState.value
            throw IllegalStateException(
                "Not connected to WearTrackerService (state=$state). Call connect() first."
            )
        }
        return svc
    }

    private suspend fun requireServiceOrClose(): IClientEventListener? {
        val svc = service
        if (svc == null) {
            emitError("samples() collected while not connected (state=${_connectionState.value})")
            return null
        }
        return svc
    }

    private fun emitError(message: String) {
        // trySend: never suspend the binder/collector threads; drop when buffer is full.
        _errorEvents.tryEmit(message)
    }

    /** Mirrors HealthTrackingService l.validateUserProfile for BIA / SWEAT_LOSS. */
    private fun validateProfile(p: TrackerProfile): String? {
        if (p.heightCm < 20 || p.heightCm > 300) return "heightCm must be 20..300"
        if (p.weightKg < 2.0f || p.weightKg > 500.0f) return "weightKg must be 2..500"
        if (p.gender < 0 || p.gender > 1) return "gender must be 0 (male) or 1 (female)"
        if (p.age < 0 || p.age > 200) return "age must be 0..200"
        return null
    }

    /**
     * ServiceDataPoint -> SamsungSample using Samsung's own per-tracker decoder
     * (ServiceDataPoint.convert*ToDataPoint) and the matching ValueKeys.
     */
    private fun mapToSample(type: SamsungTrackerType, sdp: ServiceDataPoint): SamsungSample? {
        val dp: DataPoint = when (type) {
            SamsungTrackerType.HEART_RATE_CONTINUOUS -> sdp.convertHrToDataPoint()
            SamsungTrackerType.PPG_CONTINUOUS -> sdp.convertPpgToDataPoint()
            SamsungTrackerType.SPO2_CONTINUOUS -> sdp.convertSpO2ToDataPoint()
            SamsungTrackerType.SKIN_TEMPERATURE_ON_DEMAND -> sdp.convertSkinTemperatureToDataPoint()
            SamsungTrackerType.SWEAT_LOSS -> sdp.convertSweatLossToDataPoint()
            SamsungTrackerType.ACCELEROMETER_CONTINUOUS -> sdp.convertAccToDataPoint()
            SamsungTrackerType.ECG_ON_DEMAND -> sdp.convertEcgToDataPoint()
            SamsungTrackerType.BIA_ON_DEMAND -> sdp.convertBiaToDataPoint()
            SamsungTrackerType.EDA_CONTINUOUS -> sdp.convertEdaToDataPoint()
        }
        val ts = dp.timestamp
        return when (type) {
            SamsungTrackerType.HEART_RATE_CONTINUOUS -> {
                val bpm: Int = dp.getValue(ValueKey.HeartRateSet.HEART_RATE) ?: return null
                val ibi: List<Int> = dp.getValue(ValueKey.HeartRateSet.IBI_LIST) ?: emptyList()
                val status: Int? = dp.getValue(ValueKey.HeartRateSet.HEART_RATE_STATUS)
                SamsungSample.HeartRate(bpm, ibi, status, ts)
            }
            SamsungTrackerType.PPG_CONTINUOUS -> {
                // PPG_CONTINUOUS delivers one sample per data point with all three channels.
                val green: Int = dp.getValue(ValueKey.PpgSet.PPG_GREEN) ?: return null
                val ir: Int? = dp.getValue(ValueKey.PpgSet.PPG_IR)
                val red: Int? = dp.getValue(ValueKey.PpgSet.PPG_RED)
                val status: Int? = dp.getValue(ValueKey.PpgSet.GREEN_STATUS)
                SamsungSample.Ppg(
                    status = status,
                    green = intArrayOf(green),
                    ir = ir?.let { intArrayOf(it) },
                    red = red?.let { intArrayOf(it) },
                    timestampMs = ts
                )
            }
            SamsungTrackerType.SPO2_CONTINUOUS -> {
                val spo2: Int = dp.getValue(ValueKey.SpO2Set.SPO2) ?: return null
                val status: Int? = dp.getValue(ValueKey.SpO2Set.STATUS)
                SamsungSample.SpO2(spo2, status, ts)
            }
            SamsungTrackerType.SKIN_TEMPERATURE_ON_DEMAND -> {
                val obj: Float = dp.getValue(ValueKey.SkinTemperatureSet.OBJECT_TEMPERATURE) ?: return null
                SamsungSample.SkinTemperature(obj, ts)
            }
            SamsungTrackerType.SWEAT_LOSS -> {
                val ml: Float = dp.getValue(ValueKey.SweatLossSet.SWEAT_LOSS) ?: return null
                SamsungSample.SweatLoss(ml.roundToInt(), ts)
            }
            SamsungTrackerType.ACCELEROMETER_CONTINUOUS -> {
                val x: Int = dp.getValue(ValueKey.AccelerometerSet.ACCELEROMETER_X) ?: return null
                val y: Int = dp.getValue(ValueKey.AccelerometerSet.ACCELEROMETER_Y) ?: return null
                val z: Int = dp.getValue(ValueKey.AccelerometerSet.ACCELEROMETER_Z) ?: return null
                SamsungSample.Accelerometer(x.toFloat(), y.toFloat(), z.toFloat(), ts)
            }
            SamsungTrackerType.ECG_ON_DEMAND -> {
                val mv: Float = dp.getValue(ValueKey.EcgSet.ECG_MV) ?: return null
                SamsungSample.Ecg(listOf(mv), ts)
            }
            SamsungTrackerType.BIA_ON_DEMAND -> {
                val magnitude: Float? = dp.getValue(ValueKey.BiaSet.BODY_IMPEDANCE_MAGNITUDE)
                SamsungSample.Bia(magnitude, ts)
            }
            SamsungTrackerType.EDA_CONTINUOUS -> {
                // Service value is a float skin conductance (µS); the facade contract is Int.
                val conductance: Float = dp.getValue(ValueKey.EdaSet.SKIN_CONDUCTANCE) ?: return null
                SamsungSample.Eda(conductance.roundToInt(), ts)
            }
        }
    }

    fun destroy() {
        scope.cancel()
    }

    companion object {
        private const val HEALTH_PACKAGE = "com.samsung.android.service.health"
        private const val ACTION_TRACKING_SERVICE =
            "com.samsung.android.service.health.wear.sts.ACTION_SERVICE"
        private const val MIN_HEALTH_VERSION_CODE = 150407000L
        private const val CONNECT_TIMEOUT_MS = 15_000L

        /** HealthTracker.TrackerError ordinals sent over onThrowException(int). */
        private const val TRACKER_ERROR_PERMISSION = 0
        private const val TRACKER_ERROR_SDK_POLICY = 1

        /** Facade type -> server tracker string (HealthTrackingService.l.convertTrackerTypeToString). */
        private val SERVER_TRACKER_TYPE: Map<SamsungTrackerType, String> = mapOf(
            SamsungTrackerType.HEART_RATE_CONTINUOUS to "HEART_RATE",
            SamsungTrackerType.PPG_CONTINUOUS to "PPG_CONTINUOUS",
            SamsungTrackerType.SPO2_CONTINUOUS to "SPO2",
            SamsungTrackerType.SKIN_TEMPERATURE_ON_DEMAND to "SKIN_TEMPERATURE",
            SamsungTrackerType.SWEAT_LOSS to "SWEAT_LOSS",
            SamsungTrackerType.ACCELEROMETER_CONTINUOUS to "ACCELEROMETER",
            SamsungTrackerType.ECG_ON_DEMAND to "ECG",
            SamsungTrackerType.BIA_ON_DEMAND to "BIA",
            SamsungTrackerType.EDA_CONTINUOUS to "EDA_CONTINUOUS",
        )
        private const val SERVER_SWEAT_LOSS = "SWEAT_LOSS"

        /** Capability string -> facade type (l.convertStringToTrackerType, narrowed to the facade). */
        private val SERVER_TO_FACADE: Map<String, SamsungTrackerType> = mapOf(
            "HEART_RATE" to SamsungTrackerType.HEART_RATE_CONTINUOUS,
            "PPG_CONTINUOUS" to SamsungTrackerType.PPG_CONTINUOUS,
            "SPO2" to SamsungTrackerType.SPO2_CONTINUOUS,
            "SKIN_TEMPERATURE" to SamsungTrackerType.SKIN_TEMPERATURE_ON_DEMAND,
            "SKIN_TEMPERATURE_CONTINUOUS" to SamsungTrackerType.SKIN_TEMPERATURE_ON_DEMAND,
            "SWEAT_LOSS" to SamsungTrackerType.SWEAT_LOSS,
            "ACCELEROMETER" to SamsungTrackerType.ACCELEROMETER_CONTINUOUS,
            "ECG" to SamsungTrackerType.ECG_ON_DEMAND,
            "BIA" to SamsungTrackerType.BIA_ON_DEMAND,
            "EDA_CONTINUOUS" to SamsungTrackerType.EDA_CONTINUOUS,
        )

        /**
         * Default (non-granular) runtime permission map enforced by the service's
         * PermissionUtil. The service switches to a granular Health Connect-style map only
         * when the CLIENT's targetSdkVersion >= 36 AND the device SDK >= 36; on Galaxy
         * Watch 7 (Android 14/15) the default map below applies regardless of targetSdk.
         */
        private val REQUIRED_RUNTIME_PERMISSION: Map<SamsungTrackerType, String> = mapOf(
            SamsungTrackerType.HEART_RATE_CONTINUOUS to "android.permission.BODY_SENSORS",
            SamsungTrackerType.PPG_CONTINUOUS to "android.permission.BODY_SENSORS",
            SamsungTrackerType.SPO2_CONTINUOUS to "android.permission.BODY_SENSORS",
            SamsungTrackerType.SKIN_TEMPERATURE_ON_DEMAND to "android.permission.BODY_SENSORS",
            SamsungTrackerType.ECG_ON_DEMAND to "android.permission.BODY_SENSORS",
            SamsungTrackerType.BIA_ON_DEMAND to "android.permission.BODY_SENSORS",
            SamsungTrackerType.EDA_CONTINUOUS to "android.permission.BODY_SENSORS",
            SamsungTrackerType.ACCELEROMETER_CONTINUOUS to "android.permission.ACTIVITY_RECOGNITION",
            // SWEAT_LOSS needs both; the service enforces them in order, surface the first.
            SamsungTrackerType.SWEAT_LOSS to "android.permission.ACTIVITY_RECOGNITION",
        )

        private const val PERM_READ_ADDITIONAL_HEALTH_DATA =
            "com.samsung.android.hardware.sensormanager.permission.READ_ADDITIONAL_HEALTH_DATA"

        /**
         * Granular map from the service's PermissionUtil.addGranularPermissionMap(): raw
         * PPG/ECG/BIA/EDA move to Samsung's dangerous-level READ_ADDITIONAL_HEALTH_DATA,
         * HR/SpO2/skin-temp to Health Connect permissions. READ_ADDITIONAL_HEALTH_DATA is
         * protectionLevel dangerous (verified in SemSensorPermission.apk), so it is
         * runtime-grantable by third-party apps.
         */
        private val GRANULAR_RUNTIME_PERMISSIONS: Map<SamsungTrackerType, List<String>> = mapOf(
            SamsungTrackerType.HEART_RATE_CONTINUOUS to
                listOf("android.permission.health.READ_HEART_RATE"),
            SamsungTrackerType.PPG_CONTINUOUS to listOf(PERM_READ_ADDITIONAL_HEALTH_DATA),
            SamsungTrackerType.SPO2_CONTINUOUS to
                listOf("android.permission.health.READ_OXYGEN_SATURATION"),
            SamsungTrackerType.SKIN_TEMPERATURE_ON_DEMAND to
                listOf("android.permission.health.READ_SKIN_TEMPERATURE"),
            SamsungTrackerType.ECG_ON_DEMAND to listOf(PERM_READ_ADDITIONAL_HEALTH_DATA),
            SamsungTrackerType.BIA_ON_DEMAND to listOf(PERM_READ_ADDITIONAL_HEALTH_DATA),
            SamsungTrackerType.EDA_CONTINUOUS to listOf(PERM_READ_ADDITIONAL_HEALTH_DATA),
            SamsungTrackerType.ACCELEROMETER_CONTINUOUS to
                listOf("android.permission.ACTIVITY_RECOGNITION"),
            SamsungTrackerType.SWEAT_LOSS to listOf(
                "android.permission.ACTIVITY_RECOGNITION",
                PERM_READ_ADDITIONAL_HEALTH_DATA,
            ),
        )
    }
}
