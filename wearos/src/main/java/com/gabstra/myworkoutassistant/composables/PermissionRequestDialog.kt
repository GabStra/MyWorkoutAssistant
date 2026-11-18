package com.gabstra.myworkoutassistant.composables

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.core.content.ContextCompat
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.shared.HeartRateSource

@Composable
internal fun PermissionRequestDialog(
    title: String,
    message: String,
    continueLabel: String? = null,
    onContinue: () -> Unit,
    onDismiss: () -> Unit,
) {
    val resolvedContinueLabel = continueLabel ?: stringResource(R.string.page_recovery_continue)
    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(
            dismissOnBackPress = true,
            dismissOnClickOutside = false,
            usePlatformDefaultWidth = false,
        ),
    ) {
        Box(
            modifier = Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background),
            contentAlignment = Alignment.Center,
        ) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 24.dp, vertical = 20.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text(title, style = MaterialTheme.typography.titleMedium, textAlign = TextAlign.Center)
                Text(
                    modifier = Modifier.fillMaxWidth(),
                    text = message,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                )
                // Natural button size (like other dialogs) — fillMaxWidth clips
                // at the round bezel edges.
                WearPrimaryButton(
                    text = resolvedContinueLabel,
                    onClick = onContinue,
                )
                ButtonWithText(
                    text = stringResource(R.string.components_action_not_now),
                    onClick = onDismiss,
                )
            }
        }
    }
}

internal fun missingWorkoutPermissions(
    context: Context,
    heartRateSource: HeartRateSource,
    useSamsungHeartRate: Boolean = false,
): List<String> = buildList {
    when {
        // Samsung Health raw trackers need only BODY_SENSORS + ACTIVITY_RECOGNITION
        // on every supported API level (developer-mode HealthPlatform).
        useSamsungHeartRate && heartRateSource == HeartRateSource.WATCH_SENSOR -> {
            if (Build.VERSION.SDK_INT >= 36) {
                // The service switches to its granular permission map when the device runs
                // API 36+: raw PPG/ECG/BIA/EDA then need Samsung's (dangerous-level)
                // READ_ADDITIONAL_HEALTH_DATA and HR need Health Connect grants. Harmless
                // to declare below 36; we only request it where the map actually applies.
                add("com.samsung.android.hardware.sensormanager.permission.READ_ADDITIONAL_HEALTH_DATA")
                add("android.permission.health.READ_HEART_RATE")
                add(Manifest.permission.ACTIVITY_RECOGNITION)
            } else {
                add(Manifest.permission.BODY_SENSORS)
                add(Manifest.permission.ACTIVITY_RECOGNITION)
            }
        }
        heartRateSource == HeartRateSource.WATCH_SENSOR -> add(
            if (Build.VERSION.SDK_INT >= 36) "android.permission.health.READ_HEART_RATE"
            else Manifest.permission.BODY_SENSORS,
        )
        else -> {
            add(Manifest.permission.BLUETOOTH_SCAN)
            add(Manifest.permission.BLUETOOTH_CONNECT)
        }
    }
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
        add(Manifest.permission.POST_NOTIFICATIONS)
    }
}.filter { permission ->
    ContextCompat.checkSelfPermission(context, permission) != PackageManager.PERMISSION_GRANTED
}

@Composable
internal fun workoutPermissionMessage(permissions: List<String>): String {
    val heartRateMessage = stringResource(R.string.components_permission_heart_rate)
    val bluetoothMessage = stringResource(R.string.components_permission_bluetooth)
    val locationMessage = stringResource(R.string.components_permission_location)
    val notificationMessage = stringResource(R.string.components_permission_notifications)
    val optionalFooter = stringResource(R.string.components_permission_optional_footer)
    return buildList {
        if (permissions.any {
                it == Manifest.permission.BODY_SENSORS ||
                    it == "android.permission.health.READ_HEART_RATE" ||
                    it == "com.samsung.android.hardware.sensormanager.permission.READ_ADDITIONAL_HEALTH_DATA"
            }
        ) add(heartRateMessage)
        if (permissions.any {
                it == Manifest.permission.BLUETOOTH_SCAN ||
                    it == Manifest.permission.BLUETOOTH_CONNECT
            }
        ) add(bluetoothMessage)
        if (Manifest.permission.ACCESS_FINE_LOCATION in permissions) {
            add(locationMessage)
        }
        if (Manifest.permission.POST_NOTIFICATIONS in permissions) {
            add(notificationMessage)
        }
        add(optionalFooter)
    }.joinToString(" ")
}
