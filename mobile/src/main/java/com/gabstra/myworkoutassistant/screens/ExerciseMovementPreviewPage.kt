package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.outlined.MotionPhotosOff
import androidx.compose.material3.CircularProgressIndicator
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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.StandardDialog
import com.gabstra.myworkoutassistant.motionrenderer.SkeletonMotionPreview
import com.gabstra.myworkoutassistant.shared.motion.ExerciseMovementRef
import com.gabstra.myworkoutassistant.shared.motion.ExerciseMovementStorage
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext

private const val InitialMovementRetryDelayMillis = 100L
private const val MaximumMovementRetryDelayMillis = 1_000L
private const val MaximumMovementLoadAttempts = 6

private sealed interface MovementLoadState {
    data object Loading : MovementLoadState
    data object Unavailable : MovementLoadState
    data class Available(val json: String) : MovementLoadState
}

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
    ExerciseMovementPreviewPage(
        movementRef = exercise.movementRef,
        modifier = modifier,
    )
}

@Composable
fun ExerciseMovementPreviewPage(
    movementRef: ExerciseMovementRef?,
    modifier: Modifier = Modifier,
    dragRotationEnabled: Boolean = true,
    compactStatusIcons: Boolean = false,
    listThumbnail: Boolean = false,
) {
    if (movementRef == null) {
        MovementStatus(
            text = "No movement available",
            loading = false,
            compactStatusIcons = compactStatusIcons,
            modifier = modifier,
        )
        return
    }

    val context = LocalContext.current
    val movementState by produceState<MovementLoadState>(MovementLoadState.Loading, movementRef) {
        var retryDelayMillis = InitialMovementRetryDelayMillis
        repeat(MaximumMovementLoadAttempts) { attempt ->
            val loadedJson = withContext(Dispatchers.IO) {
                ExerciseMovementStorage.readMovementJson(context, movementRef)
            }
            if (loadedJson != null) {
                value = MovementLoadState.Available(loadedJson)
                return@produceState
            }
            if (attempt == MaximumMovementLoadAttempts - 1) return@repeat
            delay(retryDelayMillis)
            retryDelayMillis = (retryDelayMillis * 2).coerceAtMost(MaximumMovementRetryDelayMillis)
        }
        value = MovementLoadState.Unavailable
    }
    when (val state = movementState) {
        MovementLoadState.Loading -> MovementStatus(
            text = "Loading movement",
            loading = true,
            compactStatusIcons = compactStatusIcons,
            modifier = modifier,
        )
        MovementLoadState.Unavailable -> MovementStatus(
            text = "Movement unavailable",
            loading = false,
            compactStatusIcons = compactStatusIcons,
            modifier = modifier,
        )
        is MovementLoadState.Available -> ExerciseMovementPreviewPage(
            movementJson = state.json,
            modifier = modifier,
            dragRotationEnabled = dragRotationEnabled,
            listThumbnail = listThumbnail,
        )
    }
}

@Composable
private fun MovementStatus(
    text: String,
    loading: Boolean,
    compactStatusIcons: Boolean,
    modifier: Modifier = Modifier,
) {
    if (!compactStatusIcons) {
        MovementStatusMessage(text, modifier)
        return
    }
    Box(modifier = modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        if (loading) {
            CircularProgressIndicator(
                modifier = Modifier.size(22.dp),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                strokeWidth = 2.dp,
            )
        } else {
            Icon(
                imageVector = Icons.Outlined.MotionPhotosOff,
                contentDescription = text,
                modifier = Modifier.size(24.dp),
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
fun ExerciseMovementPreviewPage(
    movementJson: String?,
    modifier: Modifier = Modifier,
    dragRotationEnabled: Boolean = true,
    listThumbnail: Boolean = false,
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
            dragRotationEnabled = dragRotationEnabled,
            listThumbnail = listThumbnail,
        )
    } else {
        MovementStatusMessage(
            text = "Movement unavailable",
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
