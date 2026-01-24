package com.gabstra.myworkoutassistant.composables

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.CircularProgressIndicator
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ProgressIndicatorDefaults
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.Red
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

    // Auto-dismiss after 3 seconds for success/failure
    LaunchedEffect(syncStatus) {
        when (syncStatus) {
            AppViewModel.SyncStatus.Success, AppViewModel.SyncStatus.Failure -> {
                // Store the initial status to check if it changed during delay
                val initialStatus = syncStatus
                delay(3000)
                // Only reset if status hasn't changed (e.g., new sync started)
                // This ensures we don't reset if a new sync started during the delay
                val currentStatus = viewModel.syncStatus.value
                if (currentStatus == initialStatus && currentStatus != AppViewModel.SyncStatus.Syncing) {
                    viewModel.resetSyncStatus()
                }
            }
            else -> {
                // When status changes to Syncing or Idle, the effect restarts
                // This ensures any pending auto-dismiss is cancelled
            }
        }
    }

    if (syncStatus != AppViewModel.SyncStatus.Idle) {
        Box(
            modifier = modifier
                .fillMaxWidth()
                .alpha(alpha)
                .padding(top = 15.dp),
            contentAlignment = Alignment.TopCenter
        ) {
            val borderColor = when (syncStatus) {
                AppViewModel.SyncStatus.Syncing -> MaterialTheme.colorScheme.primary
                AppViewModel.SyncStatus.Success -> Green
                AppViewModel.SyncStatus.Failure -> Red
                AppViewModel.SyncStatus.Idle -> Color.Transparent
            }

            val textColor = when (syncStatus) {
                AppViewModel.SyncStatus.Syncing -> MaterialTheme.colorScheme.primary
                AppViewModel.SyncStatus.Success -> Green
                AppViewModel.SyncStatus.Failure -> Red
                AppViewModel.SyncStatus.Idle -> Color.Transparent
            }

            Box(
                modifier = Modifier
                    .background(
                        color = MaterialTheme.colorScheme.background,
                        shape = RoundedCornerShape(12.dp)
                    )
                    .border(
                        BorderStroke(1.dp, borderColor),
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
                                strokeWidth = 2.dp,
                                colors = ProgressIndicatorDefaults.colors(
                                    indicatorColor = MaterialTheme.colorScheme.primary,
                                    trackColor = MaterialTheme.colorScheme.background
                                )
                            )
                            Spacer(modifier = Modifier.size(8.dp))
                            LoadingText(
                                baseText = "Syncing",
                                style = MaterialTheme.typography.bodySmall,
                                color = textColor
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
