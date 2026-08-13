package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.StandardDialog
import com.gabstra.myworkoutassistant.motionrenderer.SkeletonMotionPreview
import com.gabstra.myworkoutassistant.shared.motion.ExerciseMovementStorage
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext

private const val InitialMovementRetryDelayMillis = 100L
private const val MaximumMovementRetryDelayMillis = 1_000L
private const val MovementLoopRestartFadeMillis = 250

@Composable
fun ExerciseMovementAction(
    exercise: Exercise,
    modifier: Modifier = Modifier,
    title: String = "Movement",
) {
    val movementRef = exercise.movementRef ?: return
    var showPreview by remember(exercise.id) { mutableStateOf(false) }

    Column(modifier = modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable { showPreview = true }
                .padding(vertical = Spacing.md),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = title,
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Text(
                    text = "View movement",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Icon(
                imageVector = Icons.AutoMirrored.Filled.ArrowForward,
                contentDescription = "View $title",
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
    }

    if (showPreview) {
        StandardDialog(
            onDismissRequest = { showPreview = false },
            title = title,
            body = {
                ExerciseMovementPreviewPage(
                    exercise = exercise,
                    modifier = Modifier
                        .fillMaxWidth()
                        .aspectRatio(1f),
                )
            },
            dismissText = "Close",
            onDismissButton = { showPreview = false },
            showConfirm = false,
            showDismiss = true,
        )
    }
}

@Composable
fun ExerciseMovementPreviewPage(
    exercise: Exercise,
    modifier: Modifier = Modifier,
) {
    val movementRef = exercise.movementRef
    if (movementRef == null) {
        MovementStatusMessage(text = "No movement available", modifier = modifier)
        return
    }

    val context = LocalContext.current
    val movementJson by produceState<String?>(initialValue = null, movementRef) {
        var retryDelayMillis = InitialMovementRetryDelayMillis
        while (true) {
            val loadedJson = withContext(Dispatchers.IO) {
                ExerciseMovementStorage.readMovementJson(context, movementRef)
            }
            if (loadedJson != null) {
                value = loadedJson
                return@produceState
            }
            delay(retryDelayMillis)
            retryDelayMillis = (retryDelayMillis * 2).coerceAtMost(MaximumMovementRetryDelayMillis)
        }
    }
    ExerciseMovementPreviewPage(movementJson = movementJson, modifier = modifier)
}

@Composable
fun ExerciseMovementPreviewPage(
    movementJson: String?,
    modifier: Modifier = Modifier,
) {
    val backgroundColor = MaterialTheme.colorScheme.background
    val primaryFill = MaterialTheme.colorScheme.primary

    if (movementJson != null) {
        SkeletonMotionPreview(
            skeletonJson = movementJson.orEmpty(),
            modifier = modifier.fillMaxSize(),
            backgroundColor = backgroundColor,
            primaryFill = primaryFill,
            animated = true,
            orbitView = false,
            loopRestartFadeMillis = MovementLoopRestartFadeMillis,
            dragRotationEnabled = true,
        )
    } else {
        MovementStatusMessage(
            text = "Movement syncing",
            modifier = modifier,
        )
    }
}

@Composable
private fun MovementStatusMessage(
    text: String,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier.fillMaxSize(),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center,
        )
    }
}
