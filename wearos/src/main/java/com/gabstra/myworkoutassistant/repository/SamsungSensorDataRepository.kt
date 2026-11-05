package com.gabstra.myworkoutassistant.repository

import android.content.Context
import android.content.pm.PackageManager
import android.util.Log
import androidx.core.content.edit
import com.gabstra.myworkoutassistant.samsung.SamsungConnectionState
import com.gabstra.myworkoutassistant.samsung.SamsungHealthTrackerClient
import com.gabstra.myworkoutassistant.samsung.SamsungSample
import com.gabstra.myworkoutassistant.samsung.SamsungTrackerType
import com.gabstra.myworkoutassistant.samsung.TrackerProfile
import com.gabstra.myworkoutassistant.samsung.createSamsungHealthTrackerClient
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import java.io.IOException
import java.util.Calendar
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Samsung Health Tracking Service backed implementation of the sensor data surface used by
 * [SensorDataViewModel]. Mirrors the public API of [SensorDataRepository] so the two can be
 * swapped at runtime (see [SamsungHeartRatePreferences]).
 *
 * The underlying [SamsungHealthTrackerClient] is owned by this repository, connected lazily on
 * the first collected flow and disconnected again once no flow is active anymore.
 */
class SamsungSensorDataRepository(
    context: Context
) {
    private val applicationContext = context.applicationContext

    private val client: SamsungHealthTrackerClient by lazy {
        createSamsungHealthTrackerClient(applicationContext)
    }

    /** Number of currently collected tracker flows; drives the connect/disconnect lifecycle. */
    private val activeFlowCount = AtomicInteger(0)

    /** Serializes connect attempts when several flows start at the same time. */
    private val connectMutex = Mutex()

    /**
     * Checks if the Samsung Health Tracking Service (HealthPlatform) is present on this device.
     */
    fun hasHeartRateCapability(): Boolean = try {
        applicationContext.packageManager.getPackageInfo(HEALTH_PLATFORM_PACKAGE, 0)
        true
    } catch (_: PackageManager.NameNotFoundException) {
        Log.i(TAG, "Samsung Health Platform ($HEALTH_PLATFORM_PACKAGE) not available")
        false
    }

    /**
     * Returns a cold flow that emits heart rate data from the continuous Samsung heart rate
     * tracker, wrapped in the same [MeasureMessageSensor.MeasureData] type the stock sensor
     * repository emits, so consumers need no changes.
     */
    @ExperimentalCoroutinesApi
    fun heartBeatMeasureFlow(): Flow<MeasureMessageSensor.MeasureData> =
        trackerFlow(SamsungTrackerType.HEART_RATE_CONTINUOUS) { sample ->
            when (sample) {
                is SamsungSample.HeartRate -> MeasureMessageSensor.MeasureData(
                    bpm = sample.bpm,
                    ibiList = sample.ibiList,
                    heartRateStatus = sample.status,
                    timestampMs = sample.timestampMs,
                )
                else -> null
            }
        }

    // Plumbing for additional Samsung trackers; no UI consumes these yet.

    /** Raw continuous heart rate samples, including IBI intervals and quality status. */
    fun heartRateSamples(): Flow<SamsungSample.HeartRate> =
        typedSamples(SamsungTrackerType.HEART_RATE_CONTINUOUS)

    /** Raw continuous PPG samples (green/IR/red channels). */
    fun ppgSamples(): Flow<SamsungSample.Ppg> =
        typedSamples(SamsungTrackerType.PPG_CONTINUOUS)

    /** Continuous SpO2 samples. */
    fun spo2Samples(): Flow<SamsungSample.SpO2> =
        typedSamples(SamsungTrackerType.SPO2_CONTINUOUS)

    /** Sweat loss samples. */
    fun sweatLossSamples(): Flow<SamsungSample.SweatLoss> =
        typedSamples(SamsungTrackerType.SWEAT_LOSS)

    /** Continuous accelerometer samples. */
    fun accelerometerSamples(): Flow<SamsungSample.Accelerometer> =
        typedSamples(SamsungTrackerType.ACCELEROMETER_CONTINUOUS)

    /** On-demand ECG snapshot (needs finger contact on the bezel). */
    fun ecgSamples(): Flow<SamsungSample.Ecg> =
        typedSamples(SamsungTrackerType.ECG_ON_DEMAND)

    /** On-demand BIA samples — needs connect(TrackerProfile), else the client refuses. */
    fun biaSamples(): Flow<SamsungSample.Bia> =
        typedSamples(SamsungTrackerType.BIA_ON_DEMAND)

    /** Continuous EDA (skin conductance) samples. */
    fun edaSamples(): Flow<SamsungSample.Eda> =
        typedSamples(SamsungTrackerType.EDA_CONTINUOUS)

    /** On-demand skin temperature samples. */
    fun skinTemperatureSamples(): Flow<SamsungSample.SkinTemperature> =
        typedSamples(SamsungTrackerType.SKIN_TEMPERATURE_ON_DEMAND)

    private inline fun <reified T : SamsungSample> typedSamples(type: SamsungTrackerType): Flow<T> =
        trackerFlow(type) { it as? T }

    private fun <T> trackerFlow(
        type: SamsungTrackerType,
        transform: (SamsungSample) -> T?
    ): Flow<T> = flow {
        ensureConnected()
        try {
            client.samples(type).collect { sample ->
                transform(sample)?.let { emit(it) }
            }
        } finally {
            releaseConnection()
        }
    }

    private suspend fun ensureConnected() {
        activeFlowCount.incrementAndGet()
        try {
            if (client.connectionState.value is SamsungConnectionState.Connected) return
            connectMutex.withLock {
                // Another flow may have completed the connection while we waited.
                if (client.connectionState.value is SamsungConnectionState.Connected) return
                Log.i(TAG, "Connecting to Samsung Health Tracking Service")
                val profile = trackerProfileFromWorkoutStore()
                if (profile == null) {
                    Log.i(TAG, "profile incomplete — sweat loss/BIA unavailable")
                }
                client.connect(profile)
                val outcome = withTimeoutOrNull(CONNECTION_TIMEOUT_MS) {
                    client.connectionState.first {
                        it is SamsungConnectionState.Connected ||
                            it is SamsungConnectionState.Failed
                    }
                }
                when (outcome) {
                    is SamsungConnectionState.Connected -> Unit
                    is SamsungConnectionState.Failed -> throw IOException(
                        "Samsung Health connection failed: ${outcome.message}"
                    )
                    else -> throw IOException("Timed out connecting to Samsung Health")
                }
            }
        } catch (throwable: Throwable) {
            // This collection never produced samples; give the slot back.
            releaseConnection()
            throw throwable
        }
    }

    /**
     * Builds a [TrackerProfile] from the phone-synced WorkoutStore, read fresh at connect time so
     * profile edits made on the phone apply to the next connection. Returns null when the store is
     * unreadable or the profile is incomplete/implausible — the profile-less connection keeps
     * working; only SWEAT_LOSS and BIA_ON_DEMAND need a profile.
     */
    private suspend fun trackerProfileFromWorkoutStore(): TrackerProfile? {
        val store = try {
            withContext(Dispatchers.IO) {
                WorkoutStoreRepository(applicationContext.filesDir).getWorkoutStore()
            }
        } catch (throwable: Throwable) {
            Log.w(TAG, "Unreadable WorkoutStore — connecting without TrackerProfile", throwable)
            return null
        }
        val heightCm = store.heightCm ?: return null
        val weightKg = store.weightKg // non-null Double; legacy 0.0 default means unset
        val gender = store.gender ?: return null
        val age = Calendar.getInstance().get(Calendar.YEAR) - store.birthDateYear
        if (age !in MIN_PROFILE_AGE..MAX_PROFILE_AGE) return null
        // Mirror SamsungHealthClientImpl.validateProfile so an out-of-range store value can never
        // produce an invalid profile (the client would refuse SWEAT_LOSS/BIA with an error).
        if (heightCm !in 20..300 || weightKg < 2.0 || weightKg > 500.0 || gender !in 0..1) return null
        return TrackerProfile(heightCm, weightKg.toFloat(), age, gender)
    }

    private suspend fun releaseConnection() {
        if (activeFlowCount.decrementAndGet() != 0) return
        // NonCancellable: flow cancellation (stopMeasuringHeartRate) must not skip disconnect.
        withContext(NonCancellable) {
            try {
                Log.i(TAG, "No active flows; disconnecting from Samsung Health Tracking Service")
                client.disconnect()
            } catch (throwable: Throwable) {
                Log.w(TAG, "Error disconnecting Samsung Health client", throwable)
            }
        }
    }

    private companion object {
        const val TAG = "SamsungSensorDataRepository"
        const val HEALTH_PLATFORM_PACKAGE = "com.samsung.android.service.health"
        const val CONNECTION_TIMEOUT_MS = 10_000L
        const val MIN_PROFILE_AGE = 5
        const val MAX_PROFILE_AGE = 120
    }
}

/**
 * Persistence for the runtime switch between [SensorDataRepository] (stock Android sensor) and
 * [SamsungSensorDataRepository]. Defaults to OFF, which keeps 100% of the previous behavior.
 */
object SamsungHeartRatePreferences {
    private const val PREFS_NAME = "samsung_sensor_prefs"
    private const val KEY_USE_SAMSUNG_HEART_RATE = "use_samsung_heart_rate"
    const val DEFAULT_USE_SAMSUNG_HEART_RATE = false

    fun isSamsungHeartRateEnabled(context: Context): Boolean =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getBoolean(KEY_USE_SAMSUNG_HEART_RATE, DEFAULT_USE_SAMSUNG_HEART_RATE)

    fun setSamsungHeartRateEnabled(context: Context, enabled: Boolean) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit(commit = true) {
            putBoolean(KEY_USE_SAMSUNG_HEART_RATE, enabled)
        }
    }
}
