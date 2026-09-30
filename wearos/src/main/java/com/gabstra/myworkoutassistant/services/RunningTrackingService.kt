package com.gabstra.myworkoutassistant.services

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.content.pm.ServiceInfo
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.SystemClock
import android.os.Looper
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.health.services.client.ExerciseClient
import androidx.health.services.client.ExerciseUpdateCallback
import androidx.health.services.client.HealthServices
import androidx.health.services.client.data.DataType
import androidx.health.services.client.data.ExerciseConfig
import androidx.health.services.client.data.ExerciseLapSummary
import androidx.health.services.client.data.ExerciseType
import androidx.health.services.client.data.ExerciseUpdate
import androidx.health.services.client.endExercise
import androidx.health.services.client.getCapabilities
import androidx.health.services.client.pauseExercise
import androidx.health.services.client.resumeExercise
import androidx.health.services.client.startExercise
import com.gabstra.myworkoutassistant.shared.running.RunningRoutePoint
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.concurrent.CopyOnWriteArrayList

data class RunningTrackingState(
    val running: Boolean = false,
    val paused: Boolean = false,
    val elapsedTimeMillis: Long = 0L,
    val distanceMeters: Double? = null,
    val heartRates: List<Int> = emptyList(),
    val route: List<RunningRoutePoint> = emptyList(),
    val locationAvailable: Boolean = false,
    val errorMessage: String? = null,
)

/** Owns the Health Services exercise beyond the lifetime of the workout screen. */
class RunningTrackingService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private lateinit var exerciseClient: ExerciseClient
    private var outdoor = false
    private var gpsEnabled = false
    private var activeStartedAt = 0L
    private val routePoints = CopyOnWriteArrayList<RunningRoutePoint>()
    private val heartRates = CopyOnWriteArrayList<Int>()
    private val _state get() = mutableState
    private var pausedAccumulatedMillis = 0L
    private var pauseStartedAt: Long? = null
    @Volatile private var lastLocationFixElapsedRealtime = 0L
    private lateinit var locationManager: LocationManager

    private val locationListener = object : LocationListener {
        override fun onLocationChanged(location: Location) {
            appendRoutePoint(
                latitude = location.latitude,
                longitude = location.longitude,
                altitudeMeters = location.altitude.takeIf {
                    location.hasAltitude() && it.isFinite() && it in -10_000.0..10_000.0
                },
            )
        }

        override fun onProviderDisabled(provider: String) {
            if (provider == LocationManager.GPS_PROVIDER) {
                _state.value = _state.value.copy(locationAvailable = false)
            }
        }

        override fun onProviderEnabled(provider: String) = Unit
    }

    private val callback = object : ExerciseUpdateCallback {
        override fun onExerciseUpdateReceived(update: ExerciseUpdate) {
            val metrics = update.latestMetrics
            val hr = metrics.getData(DataType.HEART_RATE_BPM).map { it.value.toInt() }
            heartRates.addAll(hr)
            val elapsed = elapsedNow()
            val distance = metrics.getData(DataType.DISTANCE).lastOrNull()?.value
            val paused = update.exerciseStateInfo.state.toString().contains("PAUSED", ignoreCase = true)
            val ended = update.exerciseStateInfo.state.isEnded
            _state.value = _state.value.copy(
                running = !ended,
                paused = paused,
                elapsedTimeMillis = elapsed,
                distanceMeters = distance ?: _state.value.distanceMeters,
                heartRates = heartRates.toList(),
                route = routePoints.toList(),
                locationAvailable = hasRecentLocationFix(),
            )
        }

        override fun onLapSummaryReceived(lapSummary: ExerciseLapSummary) = Unit
        override fun onRegistered() = Unit
        override fun onRegistrationFailed(throwable: Throwable) {
            _state.value = _state.value.copy(errorMessage = throwable.message ?: "Health tracking failed")
        }
        override fun onAvailabilityChanged(dataType: DataType<*, *>, availability: androidx.health.services.client.data.Availability) = Unit
    }

    override fun onCreate() {
        super.onCreate()
        exerciseClient = HealthServices.getClient(this).exerciseClient
        locationManager = getSystemService(LocationManager::class.java)
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        Log.d(TAG, "onStartCommand action=${intent?.action}")
        when (intent?.action) {
            ACTION_START -> {
                outdoor = intent.getBooleanExtra(EXTRA_OUTDOOR, false)
                gpsEnabled = intent.getBooleanExtra(EXTRA_USE_GPS, outdoor)
                val serviceType = if (outdoor && gpsEnabled) {
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_HEALTH or ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION
                } else {
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_HEALTH
                }
                if (Build.VERSION.SDK_INT >= 34) {
                    startForeground(NOTIFICATION_ID, createNotification(), serviceType)
                } else {
                    startForeground(NOTIFICATION_ID, createNotification())
                }
                scope.launch {
                    startTracking()
                    monitorLocationFixFreshness()
                }
            }
            ACTION_PAUSE -> scope.launch {
                runCatching { exerciseClient.pauseExercise() }
                    .onFailure { Log.e(TAG, "Unable to pause Health Services exercise", it) }
                if (pauseStartedAt == null) pauseStartedAt = SystemClock.elapsedRealtime()
                stopLocationUpdates()
                _state.value = _state.value.copy(paused = true)
            }
            ACTION_RESUME -> scope.launch {
                runCatching { exerciseClient.resumeExercise() }
                    .onFailure { Log.e(TAG, "Unable to resume Health Services exercise", it) }
                pauseStartedAt?.let { pausedAccumulatedMillis += SystemClock.elapsedRealtime() - it }
                pauseStartedAt = null
                startLocationUpdates()
                _state.value = _state.value.copy(paused = false)
            }
            ACTION_STOP -> scope.launch {
                runCatching { exerciseClient.endExercise() }
                exerciseClient.clearUpdateCallbackAsync(callback)
                stopLocationUpdates()
                _state.value = _state.value.copy(running = false, paused = false)
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
        }
        return START_NOT_STICKY
    }

    private suspend fun startTracking() {
        try {
            routePoints.clear()
            heartRates.clear()
            lastLocationFixElapsedRealtime = 0L
            pausedAccumulatedMillis = 0L
            pauseStartedAt = null
            gpsEnabled = outdoor && gpsEnabled &&
                checkSelfPermission(android.Manifest.permission.ACCESS_FINE_LOCATION) == android.content.pm.PackageManager.PERMISSION_GRANTED &&
                runCatching { locationManager.isProviderEnabled(LocationManager.GPS_PROVIDER) }.getOrDefault(false)
            val capabilities = exerciseClient.getCapabilities()
            val runningCapabilities = capabilities.getExerciseTypeCapabilities(ExerciseType.RUNNING)
            val requested = buildSet {
                if (DataType.HEART_RATE_BPM in runningCapabilities.supportedDataTypes) add(DataType.HEART_RATE_BPM)
                if (DataType.DISTANCE in runningCapabilities.supportedDataTypes) add(DataType.DISTANCE)
                if (gpsEnabled && DataType.LOCATION in runningCapabilities.supportedDataTypes) add(DataType.LOCATION)
            }
            exerciseClient.setUpdateCallback(callback)
            activeStartedAt = SystemClock.elapsedRealtime()
            startLocationUpdates()
            exerciseClient.startExercise(
                ExerciseConfig(
                    exerciseType = ExerciseType.RUNNING,
                    dataTypes = requested,
                    isAutoPauseAndResumeEnabled = false,
                    isGpsEnabled = gpsEnabled && DataType.LOCATION in requested,
                )
            )
            _state.value = RunningTrackingState(running = true)
        } catch (exception: Exception) {
            Log.e(TAG, "Unable to start Health Services run", exception)
            _state.value = _state.value.copy(running = false, errorMessage = exception.message ?: "Could not start run tracking")
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    private fun appendRoutePoint(
        latitude: Double,
        longitude: Double,
        altitudeMeters: Double?,
    ) {
        lastLocationFixElapsedRealtime = SystemClock.elapsedRealtime()
        val next = RunningRoutePoint(
            latitude = latitude,
            longitude = longitude,
            elapsedTimeMillis = elapsedNow(),
            altitudeMeters = altitudeMeters,
        )
        val previous = routePoints.lastOrNull()
        if (previous == null || previous.latitude != next.latitude || previous.longitude != next.longitude) {
            routePoints += next
        }
        _state.value = _state.value.copy(
            route = routePoints.toList(),
            locationAvailable = hasRecentLocationFix(),
        )
    }

    private suspend fun monitorLocationFixFreshness() {
        while (_state.value.running) {
            val current = _state.value
            val available = gpsEnabled && !current.paused && hasRecentLocationFix()
            if (current.locationAvailable != available) {
                _state.value = current.copy(locationAvailable = available)
            }
            delay(LOCATION_FIX_STALE_CHECK_INTERVAL_MILLIS)
        }
    }

    private fun hasRecentLocationFix(): Boolean {
        val lastFix = lastLocationFixElapsedRealtime
        return gpsEnabled && lastFix > 0L &&
            SystemClock.elapsedRealtime() - lastFix <= LOCATION_FIX_STALE_AFTER_MILLIS
    }

    private fun startLocationUpdates() {
        if (!gpsEnabled || checkSelfPermission(android.Manifest.permission.ACCESS_FINE_LOCATION) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            return
        }
        runCatching {
            locationManager.requestLocationUpdates(
                LocationManager.GPS_PROVIDER,
                LOCATION_UPDATE_INTERVAL_MILLIS,
                0f,
                locationListener,
                Looper.getMainLooper(),
            )
        }.onFailure { exception ->
            Log.w(TAG, "GPS location updates unavailable; keeping Health Services tracking", exception)
        }
    }

    private fun stopLocationUpdates() {
        runCatching { locationManager.removeUpdates(locationListener) }
    }

    private fun elapsedNow(): Long {
        val now = pauseStartedAt ?: SystemClock.elapsedRealtime()
        return (now - activeStartedAt - pausedAccumulatedMillis).coerceAtLeast(0L)
    }

    private fun createNotification(): Notification = NotificationCompat.Builder(this, CHANNEL_ID)
        .setSmallIcon(android.R.drawable.ic_media_play)
        .setContentTitle("Run in progress")
        .setContentText("Tracking run metrics")
        .setOngoing(true)
        .build()

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            getSystemService(NotificationManager::class.java).createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Run tracking", NotificationManager.IMPORTANCE_LOW)
            )
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        stopLocationUpdates()
        exerciseClient.clearUpdateCallbackAsync(callback)
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        private const val TAG = "RunningTrackingService"
        private const val CHANNEL_ID = "running_tracking"
        private const val NOTIFICATION_ID = 8301
        private const val LOCATION_UPDATE_INTERVAL_MILLIS = 1_000L
        private const val LOCATION_FIX_STALE_AFTER_MILLIS = 5_000L
        private const val LOCATION_FIX_STALE_CHECK_INTERVAL_MILLIS = 1_000L
        private const val ACTION_START = "com.gabstra.myworkoutassistant.RUN_START"
        private const val ACTION_PAUSE = "com.gabstra.myworkoutassistant.RUN_PAUSE"
        private const val ACTION_RESUME = "com.gabstra.myworkoutassistant.RUN_RESUME"
        private const val ACTION_STOP = "com.gabstra.myworkoutassistant.RUN_STOP"
        private const val EXTRA_OUTDOOR = "outdoor"
        private const val EXTRA_USE_GPS = "use_gps"

        private val mutableState = MutableStateFlow(RunningTrackingState())
        val state = mutableState.asStateFlow()

        fun start(context: Context, isOutdoor: Boolean, useGps: Boolean = isOutdoor) {
            val intent = Intent(context, RunningTrackingService::class.java)
                .setAction(ACTION_START)
                .putExtra(EXTRA_OUTDOOR, isOutdoor)
                .putExtra(EXTRA_USE_GPS, useGps)
            androidx.core.content.ContextCompat.startForegroundService(context, intent)
        }
        fun pause(context: Context) = context.startService(Intent(context, RunningTrackingService::class.java).setAction(ACTION_PAUSE))
        fun resume(context: Context) = context.startService(Intent(context, RunningTrackingService::class.java).setAction(ACTION_RESUME))
        fun stop(context: Context) = context.startService(Intent(context, RunningTrackingService::class.java).setAction(ACTION_STOP))

        fun reset() { mutableState.value = RunningTrackingState() }
    }
}
