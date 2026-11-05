package com.gabstra.myworkoutassistant.services

import android.annotation.SuppressLint
import android.app.Service
import android.content.Context
import android.content.Intent
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.IBinder
import android.os.PowerManager
import android.provider.Settings
import androidx.core.content.getSystemService

/**
 * Owns the screen wake lock so it survives process-state changes.
 *
 * A plain (non-foreground) started service pins this process' state to SERVICE
 * (procState <= 11). PowerManagerService.setWakeLockDisabledStateLocked()
 * silently disables screen wake locks owned by *cached* processes
 * (disable_screen_wake_locks_while_cached, default true) and Samsung Freecess
 * does the same for frozen processes — an activity-lifecycle-held lock dies in
 * exactly those states, which is why the screen could turn off while KeepOn
 * believed it held the lock. Holding it here makes that impossible while the
 * service runs.
 *
 * Not tied to workout tracking: KeepOn starts/stops it whenever interactive
 * screen-on mode is active anywhere in the app.
 */
class ScreenWakeService : Service(), SensorEventListener {
    private var wakeLock: PowerManager.WakeLock? = null
    private var sensorManager: SensorManager? = null
    private var ambientWasOn: Int? = null

    override fun onCreate() {
        super.onCreate()
        wakeLock = getSystemService<PowerManager>()?.newWakeLock(
            PowerManager.FULL_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP,
            "MyWorkoutAssistant:ScreenOn"
        )?.apply {
            setReferenceCounted(false)
            acquire()
        }
        startOffBodyWatch()
        disableAmbient()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int =
        START_NOT_STICKY

    override fun onDestroy() {
        stopOffBodyWatch()
        restoreAmbient()
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    @Suppress("DEPRECATION")
    private fun startOffBodyWatch() {
        sensorManager = getSystemService<SensorManager>()?.also { sm ->
            sm.getDefaultSensor(Sensor.TYPE_LOW_LATENCY_OFFBODY_DETECT)?.let {
                sm.registerListener(this, it, SensorManager.SENSOR_DELAY_NORMAL)
            }
        }
    }

    private fun stopOffBodyWatch() {
        sensorManager?.unregisterListener(this)
        sensorManager = null
    }

    // Off-body is when the screen mysteriously dies: re-assert everything.
    override fun onSensorChanged(event: SensorEvent) {
        if (event.sensor.type == Sensor.TYPE_LOW_LATENCY_OFFBODY_DETECT &&
            event.values.firstOrNull() == 0f
        ) {
            wakeLock?.let {
                if (it.isHeld) it.release()
                it.acquire()
            }
            disableAmbient()
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit

    // WRITE_SECURE_SETTINGS is not obtainable at install time (adb grant only),
    // so production builds must work fully without it: wake lock + service-hosted
    // process state + off-body re-assert carry the screen-on behavior alone.
    private fun canWriteSecureSettings(): Boolean =
        checkSelfPermission(android.Manifest.permission.WRITE_SECURE_SETTINGS) ==
            android.content.pm.PackageManager.PERMISSION_GRANTED

    private fun disableAmbient() {
        if (!canWriteSecureSettings()) return
        try {
            val cr = contentResolver
            if (ambientWasOn == null) {
                ambientWasOn = Settings.Global.getInt(cr, "ambient_enabled", 0)
            }
            Settings.Global.putInt(cr, "ambient_enabled", 0)
            Settings.Secure.putInt(cr, "ignore_ambient_policy", 1)
        } catch (_: SecurityException) {
        }
    }

    private fun restoreAmbient() {
        if (ambientWasOn != null && canWriteSecureSettings()) {
            try {
                val cr = contentResolver
                Settings.Global.putInt(cr, "ambient_enabled", ambientWasOn!!)
                Settings.Secure.putInt(cr, "ignore_ambient_policy", 0)
            } catch (_: SecurityException) {
            }
        }
        ambientWasOn = null
    }

    companion object {
        fun start(context: Context) {
            context.startService(Intent(context, ScreenWakeService::class.java))
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, ScreenWakeService::class.java))
        }
    }
}
