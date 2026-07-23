package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
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
import com.gabstra.myworkoutassistant.motionrenderer.SkeletonMotionPreview
import com.gabstra.myworkoutassistant.composables.CollapsibleSection
import com.gabstra.myworkoutassistant.shared.motion.ExerciseMovementStorage
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext

private const val InitialMovementRetryDelayMillis = 100L
private const val MaximumMovementRetryDelayMillis = 1_000L
private const val MovementLoopRestartFadeMillis = 250

@Composable
fun ExerciseMovementCard(
    exercise: Exercise,
    title: String = "Movement",
    modifier: Modifier = Modifier,
) {
    val movementRef = exercise.movementRef ?: return
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

    var expanded by remember(exercise.id) { mutableStateOf(true) }
    CollapsibleSection(
        title = title,
        summary = "Movement: ${movementRef.movementId}",
        expanded = expanded,
        onToggle = { expanded = !expanded },
        modifier = modifier,
    ) {
        ExerciseMovementPreviewPage(
            movementJson = movementJson,
            modifier = Modifier
                .fillMaxWidth()
                .aspectRatio(1f),
        )
    }
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
            orbitView = true,
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
