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
                skeletonJson = InspectionSkeletonJson,
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

private const val InspectionSkeletonJson = """
{
  "fps": 30,
  "bounds": { "minX": -0.5, "maxX": 0.5, "minY": 0.0, "maxY": 1.8, "minZ": -0.3, "maxZ": 0.3 },
  "frames": [
    {
      "joints": {
        "pelvis": [0.0, 0.9, 0.0],
        "neck": [0.0, 1.45, 0.0],
        "head": [0.0, 1.68, 0.02],
        "left_shoulder": [-0.22, 1.36, 0.0],
        "right_shoulder": [0.22, 1.36, 0.0],
        "left_elbow": [-0.32, 1.05, 0.0],
        "right_elbow": [0.32, 1.05, 0.0],
        "left_wrist": [-0.34, 0.78, 0.0],
        "right_wrist": [0.34, 0.78, 0.0],
        "left_hip": [-0.13, 0.82, 0.0],
        "right_hip": [0.13, 0.82, 0.0],
        "left_knee": [-0.14, 0.44, 0.02],
        "right_knee": [0.14, 0.44, 0.02],
        "left_ankle": [-0.14, 0.08, 0.0],
        "right_ankle": [0.14, 0.08, 0.0]
      }
    }
  ]
}
"""

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
