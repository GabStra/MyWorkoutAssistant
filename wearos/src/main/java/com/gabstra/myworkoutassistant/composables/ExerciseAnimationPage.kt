package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.text.style.TextAlign
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.shared.motion.ExerciseMovementStorage
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext

@Composable
fun ExerciseAnimationPage(
    exercise: Exercise,
    modifier: Modifier = Modifier,
) {
    val movementRef = exercise.movementRef
    if (movementRef == null) {
        MovementStatusMessage(
            text = "No movement",
            modifier = modifier,
        )
        return
    }

    val context = LocalContext.current
    val isInspectionMode = LocalInspectionMode.current
    val movementJson by produceState<String?>(initialValue = null, movementRef) {
        while (true) {
            val loadedJson = withContext(Dispatchers.IO) {
                ExerciseMovementStorage.readMovementJson(context, movementRef)
            }
            if (loadedJson != null) {
                value = loadedJson
                return@produceState
            }
            delay(1_000)
        }
    }

    when {
        movementJson != null -> {
            WearSkeletonMotionPreview(
                skeletonJson = movementJson.orEmpty(),
                modifier = modifier.fillMaxSize(),
                animated = true,
                orbitView = false,
            )
        }

        isInspectionMode -> {
            WearSkeletonMotionPreview(
                modifier = modifier.fillMaxSize(),
                animated = true,
                orbitView = false,
            )
        }

        else -> {
            MovementStatusMessage(
                text = "Movement syncing",
                modifier = modifier,
            )
        }
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
