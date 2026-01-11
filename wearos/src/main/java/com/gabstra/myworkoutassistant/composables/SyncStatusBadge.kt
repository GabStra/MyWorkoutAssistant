package com.gabstra.myworkoutassistant.composables

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.CircularProgressIndicator
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import kotlinx.coroutines.delay

@Composable
fun SyncStatusBadge(
    viewModel: AppViewModel,
    modifier: Modifier = Modifier
) {
    val syncStatus by viewModel.syncStatus.collectAsState()
    
    // Animate visibility
    val alpha by animateFloatAsState(
        targetValue = if (syncStatus != AppViewModel.SyncStatus.Idle) 1f else 0f,
        animationSpec = tween(durationMillis = 300),
        label = "syncBadgeAlpha"
    )

    // Auto-dismiss after 5 seconds for success/failure
    LaunchedEffect(syncStatus) {
        when (syncStatus) {
            AppViewModel.SyncStatus.Success, AppViewModel.SyncStatus.Failure -> {
                delay(5000)
                // Only reset if status hasn't changed (e.g., new sync started)
                if (viewModel.syncStatus.value == syncStatus) {
                    viewModel.resetSyncStatus()
                }
            }
            else -> {}
        }
    }

    if (syncStatus != AppViewModel.SyncStatus.Idle) {
        Box(
            modifier = modifier
                .fillMaxWidth()
                .alpha(alpha)
                .padding(horizontal = 8.dp, vertical = 4.dp),
            contentAlignment = Alignment.TopCenter
        ) {
            val backgroundColor = when (syncStatus) {
                AppViewModel.SyncStatus.Syncing -> MaterialTheme.colorScheme.surfaceContainer
                AppViewModel.SyncStatus.Success -> Color(0xFF4CAF50) // Green
                AppViewModel.SyncStatus.Failure -> Color(0xFFF44336) // Red
                AppViewModel.SyncStatus.Idle -> Color.Transparent
            }

            val textColor = when (syncStatus) {
                AppViewModel.SyncStatus.Syncing -> MaterialTheme.colorScheme.onSurface
                AppViewModel.SyncStatus.Success -> Color.White
                AppViewModel.SyncStatus.Failure -> Color.White
                AppViewModel.SyncStatus.Idle -> Color.Transparent
            }

            Box(
                modifier = Modifier
                    .background(
                        color = backgroundColor,
                        shape = RoundedCornerShape(12.dp)
                    )
                    .padding(horizontal = 12.dp, vertical = 8.dp)
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.padding(horizontal = 4.dp)
                ) {
                    when (syncStatus) {
                        AppViewModel.SyncStatus.Syncing -> {
                            CircularProgressIndicator(
                                modifier = Modifier.size(16.dp),
                                strokeWidth = 2.dp
                            )
                            Spacer(modifier = Modifier.size(8.dp))
                            Text(
                                text = "Syncing...",
                                style = MaterialTheme.typography.bodySmall,
                                color = textColor,
                                textAlign = TextAlign.Center
                            )
                        }
                        AppViewModel.SyncStatus.Success -> {
                            // Checkmark using text character
                            Text(
                                text = "✓",
                                style = MaterialTheme.typography.titleMedium,
                                color = textColor,
                                modifier = Modifier.padding(end = 4.dp)
                            )
                            Text(
                                text = "Synced",
                                style = MaterialTheme.typography.bodySmall,
                                color = textColor,
                                textAlign = TextAlign.Center
                            )
                        }
                        AppViewModel.SyncStatus.Failure -> {
                            // Cross using text character
                            Text(
                                text = "✕",
                                style = MaterialTheme.typography.titleMedium,
                                color = textColor,
                                modifier = Modifier.padding(end = 4.dp)
                            )
                            Text(
                                text = "Sync failed",
                                style = MaterialTheme.typography.bodySmall,
                                color = textColor,
                                textAlign = TextAlign.Center
                            )
                        }
                        AppViewModel.SyncStatus.Idle -> {}
                    }
                }
            }
        }
    }
}
