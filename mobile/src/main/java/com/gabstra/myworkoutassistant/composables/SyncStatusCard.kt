package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.datalayer.SyncPhase
import kotlinx.coroutines.delay

/**
 * Non-modal sync status banner for manual phone→watch sync. Lets the user keep
 * using the app while the transfer runs, unlike the previous full-screen overlay.
 */
@Composable
fun SyncStatusCard(
    phase: SyncPhase?,
    progress: Float?,
    modifier: Modifier = Modifier,
    onCancel: (() -> Unit)? = null,
) {
    val elapsedSeconds by produceState(0, phase) {
        if (phase == SyncPhase.PROCESSING) {
            while (true) {
                delay(1000)
                value++
            }
        } else {
            value = 0
        }
    }

    val label = when (phase) {
        SyncPhase.CONNECTING -> "Connecting to watch…"
        SyncPhase.TRANSFERRING -> progress?.let { "Sending to watch · ${(it * 100).toInt()}%" }
            ?: "Sending to watch…"
        SyncPhase.PROCESSING -> "Watch is processing data · ${elapsedSeconds}s"
        SyncPhase.COMPLETED -> "Sync complete"
        null -> "Preparing sync…"
    }

    Surface(
        modifier = modifier.padding(horizontal = 16.dp, vertical = 8.dp),
        shape = MaterialTheme.shapes.medium,
        color = MaterialTheme.colorScheme.surfaceVariant,
        shadowElevation = 4.dp,
    ) {
        Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = label,
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.weight(1f),
                )
                if (onCancel != null && phase != SyncPhase.COMPLETED) {
                    Spacer(Modifier.width(8.dp))
                    TextButton(onClick = onCancel) {
                        Text("Cancel")
                    }
                }
            }
            Spacer(Modifier.height(4.dp))
            if (progress != null) {
                LinearProgressIndicator(
                    progress = { progress.coerceIn(0f, 1f) },
                    modifier = Modifier.fillMaxWidth().height(4.dp),
                )
            } else {
                LinearProgressIndicator(
                    modifier = Modifier.fillMaxWidth().height(4.dp),
                )
            }
        }
    }
}
