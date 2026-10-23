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
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.core.content.ContextCompat
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.shared.HeartRateSource

@Composable
internal fun PermissionRequestDialog(
    title: String,
    message: String,
    continueLabel: String = "Continue",
    onContinue: () -> Unit,
    onDismiss: () -> Unit,
) {
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
                modifier = Modifier.fillMaxSize().padding(horizontal = 24.dp, vertical = 20.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(12.dp, Alignment.CenterVertically),
            ) {
                Text(title, style = MaterialTheme.typography.titleMedium, textAlign = TextAlign.Center)
                Text(
                    modifier = Modifier.fillMaxWidth(),
                    text = message,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                )
                WearPrimaryButton(
                    modifier = Modifier.fillMaxWidth(),
                    text = continueLabel,
                    onClick = onContinue,
                )
                ButtonWithText(
                    modifier = Modifier.fillMaxWidth(),
                    text = "Not now",
                    onClick = onDismiss,
                )
            }
        }
    }
}

internal fun missingWorkoutPermissions(
    context: Context,
    heartRateSource: HeartRateSource,
): List<String> = buildList {
    when (heartRateSource) {
        HeartRateSource.WATCH_SENSOR -> add(
            if (Build.VERSION.SDK_INT >= 36) "android.permission.health.READ_HEART_RATE"
            else Manifest.permission.BODY_SENSORS,
        )
        HeartRateSource.POLAR_BLE, HeartRateSource.WHOOP_BLE -> {
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

internal fun workoutPermissionMessage(permissions: List<String>): String = buildList {
    if (permissions.any {
            it == Manifest.permission.BODY_SENSORS ||
                it == "android.permission.health.READ_HEART_RATE"
        }
    ) add("Heart-rate access lets the workout record your pulse.")
    if (permissions.any {
            it == Manifest.permission.BLUETOOTH_SCAN ||
                it == Manifest.permission.BLUETOOTH_CONNECT
        }
    ) add("Bluetooth access lets the workout connect to your external heart-rate device.")
    if (Manifest.permission.ACCESS_FINE_LOCATION in permissions) {
        add("Location access lets the workout record your route.")
    }
    if (Manifest.permission.POST_NOTIFICATIONS in permissions) {
        add("Notification access lets the workout show its ongoing status.")
    }
    add("You can continue without optional access; the related feature may be unavailable.")
}.joinToString(" ")
