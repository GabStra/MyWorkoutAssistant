package com.gabstra.myworkoutassistant

import android.app.KeyguardManager
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.media.Ringtone
import android.os.Bundle
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.lifecycle.lifecycleScope
import com.gabstra.myworkoutassistant.composables.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.presentation.theme.MyWorkoutAssistantTheme
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.UUID

class WorkoutAlarmActivity : ComponentActivity() {

    private var ringtone: Ringtone? = null
    private var vibrator: Vibrator? = null

    private var autoStopJob: Job? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Check if a workout is already in progress - if so, dismiss immediately
        val prefs = getSharedPreferences("workout_state", Context.MODE_PRIVATE)
        val isWorkoutInProgress = prefs.getBoolean("isWorkoutInProgress", false)

        if (isWorkoutInProgress) {
            // A workout is active, dismiss the notification and finish
            intent.getStringExtra("SCHEDULE_ID")?.let {
                getSystemService(NotificationManager::class.java)?.cancel(it.hashCode())
            }
            finish()
            return
        }

        // show over lock screen
        setShowWhenLocked(true)
        setTurnScreenOn(true)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        // try to dismiss keyguard for immediate interaction
        getSystemService(KeyguardManager::class.java)
            ?.requestDismissKeyguard(this, null)

        // start alarm sound & vibration
        startAlert()

        autoStopJob = lifecycleScope.launch {
            delay(10_000)
            stopAlertAndFinish()
        }

        // block back press (must choose an action)
        onBackPressedDispatcher.addCallback(
            this,
            object : OnBackPressedCallback(true) { override fun handleOnBackPressed() {} }
        )

        // read data up-front
        val (title, label) = readTitleAndLabel()

        setContent {
            MyWorkoutAssistantTheme {
                AlarmScreen(
                    title = title,
                    subtitle = label ?: "Time for your workout", //getString(R.string.alarm_time_for_your_workout),
                    onStart = { startWorkoutAndDismiss() },
                    onDismiss = { stopAlertAndFinish() }
                )
            }
        }
    }

    // ---- Compose UI ----
    @Composable
    private fun AlarmScreen(
        title: String,
        subtitle: String,
        onStart: () -> Unit,
        onDismiss: () -> Unit
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Color.Black),
            contentAlignment = Alignment.Center
        ) {
            CustomDialogYesOnLongPress(
                show = true,
                title = title,
                message = subtitle,
                handleYesClick = onStart,
                handleNoClick = onDismiss,
                handleOnAutomaticClose = {},
                holdTimeInMillis = 1000,
                onVisibilityChange = {}
            )
        }
    }

    // ---- Alarm sound & vibration ----
    private fun startAlert() {
        // sound
        /*
        val uri: Uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM)
            ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
        ringtone = RingtoneManager.getRingtone(this, uri)?.apply {
            isLooping = true
            audioAttributes = AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_ALARM)
                .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                .build()
            runCatching { play() }
        }
        */

        // vibration
        vibrator =
            getSystemService(VibratorManager::class.java)?.defaultVibrator
        vibrator?.let { vib ->
            if (vib.hasVibrator()) {
                val pattern = longArrayOf(0, 600, 300, 600, 300)
                vib.vibrate(VibrationEffect.createWaveform(pattern, 0)) // repeat
            }
        }
    }

    private fun stopAlert() {
        runCatching { ringtone?.stop() }
        ringtone = null
        runCatching { vibrator?.cancel() }
        vibrator = null

        // also clear the notification that launched us
        intent.getStringExtra("SCHEDULE_ID")?.let {
            getSystemService(NotificationManager::class.java)?.cancel(it.hashCode())
        }
    }

    private fun startWorkoutAndDismiss() {
        val i = Intent(this, MainActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            putExtra("WORKOUT_ID", intent.getStringExtra("WORKOUT_ID"))
            putExtra("SCHEDULE_ID", intent.getStringExtra("SCHEDULE_ID"))
        }
        startActivity(i)
        stopAlertAndFinish()
    }

    private fun stopAlertAndFinish() {
        stopAlert()
        finishAndRemoveTask()
        overridePendingTransition(0, 0)
    }

    // ---- helpers ----
    private fun readTitleAndLabel(): Pair<String, String?> {
        val workoutIdStr = intent.getStringExtra("WORKOUT_ID")
        val name = runCatching {
            if (workoutIdStr.isNullOrBlank()) null
            else {
                val repo = WorkoutStoreRepository(filesDir)
                val ws = repo.getWorkoutStore()
                val uuid = UUID.fromString(workoutIdStr)
                ws.workouts.find { it.globalId == uuid }?.name
            }
        }.getOrNull() ?: getString(R.string.app_name)
        val label = intent.getStringExtra("LABEL")
        return name to label
    }

    override fun onDestroy() {
        super.onDestroy()
        autoStopJob?.cancel()
        stopAlert()
    }
}
