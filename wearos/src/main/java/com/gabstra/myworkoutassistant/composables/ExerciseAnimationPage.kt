package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import androidx.wear.tooling.preview.devices.WearDevices
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.presentation.theme.MyWorkoutAssistantTheme
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
                orbitView = true,
            )
        }

        isInspectionMode -> {
            WearSkeletonMotionPreview(
                skeletonJson = rememberInspectionSkeletonJson(),
                modifier = modifier.fillMaxSize(),
                animated = true,
                orbitView = true,
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
private fun rememberInspectionSkeletonJson(): String {
    val context = LocalContext.current
    return remember(context) {
        runCatching {
            context.resources.openRawResource(R.raw.pull_up_preview_skeleton)
                .bufferedReader()
                .use { it.readText() }
        }.getOrDefault(InspectionSkeletonJson)
    }
}

private const val InspectionSkeletonJson = """
{
  "fps": 3,
  "bounds": { "minX": -0.55, "maxX": 0.55, "minY": 0.0, "maxY": 1.8, "minZ": -0.35, "maxZ": 0.35 },
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
    },
    {
      "joints": {
        "pelvis": [0.0, 0.78, 0.02],
        "neck": [0.0, 1.30, 0.06],
        "head": [0.0, 1.54, 0.08],
        "left_shoulder": [-0.22, 1.22, 0.06],
        "right_shoulder": [0.22, 1.22, 0.06],
        "left_elbow": [-0.32, 0.98, 0.03],
        "right_elbow": [0.32, 0.98, 0.03],
        "left_wrist": [-0.34, 0.78, 0.0],
        "right_wrist": [0.34, 0.78, 0.0],
        "left_hip": [-0.13, 0.72, 0.02],
        "right_hip": [0.13, 0.72, 0.02],
        "left_knee": [-0.16, 0.42, 0.15],
        "right_knee": [0.16, 0.42, 0.15],
        "left_ankle": [-0.14, 0.08, 0.0],
        "right_ankle": [0.14, 0.08, 0.0]
      }
    },
    {
      "joints": {
        "pelvis": [0.0, 0.66, 0.04],
        "neck": [0.0, 1.15, 0.12],
        "head": [0.0, 1.40, 0.13],
        "left_shoulder": [-0.23, 1.08, 0.12],
        "right_shoulder": [0.23, 1.08, 0.12],
        "left_elbow": [-0.33, 0.92, 0.08],
        "right_elbow": [0.33, 0.92, 0.08],
        "left_wrist": [-0.34, 0.78, 0.0],
        "right_wrist": [0.34, 0.78, 0.0],
        "left_hip": [-0.13, 0.62, 0.04],
        "right_hip": [0.13, 0.62, 0.04],
        "left_knee": [-0.18, 0.38, 0.24],
        "right_knee": [0.18, 0.38, 0.24],
        "left_ankle": [-0.14, 0.08, 0.0],
        "right_ankle": [0.14, 0.08, 0.0]
      }
    },
    {
      "joints": {
        "pelvis": [0.0, 0.78, 0.02],
        "neck": [0.0, 1.30, 0.06],
        "head": [0.0, 1.54, 0.08],
        "left_shoulder": [-0.22, 1.22, 0.06],
        "right_shoulder": [0.22, 1.22, 0.06],
        "left_elbow": [-0.32, 0.98, 0.03],
        "right_elbow": [0.32, 0.98, 0.03],
        "left_wrist": [-0.34, 0.78, 0.0],
        "right_wrist": [0.34, 0.78, 0.0],
        "left_hip": [-0.13, 0.72, 0.02],
        "right_hip": [0.13, 0.72, 0.02],
        "left_knee": [-0.16, 0.42, 0.15],
        "right_knee": [0.16, 0.42, 0.15],
        "left_ankle": [-0.14, 0.08, 0.0],
        "right_ankle": [0.14, 0.08, 0.0]
      }
    },
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

@Preview(
    name = "Wear Movement Preview",
    group = "Exercise Animation",
    device = WearDevices.SMALL_ROUND,
    showBackground = true,
)
@Composable
private fun ExerciseAnimationPageWearPreview() {
    MyWorkoutAssistantTheme {
        WearSkeletonMotionPreview(
            skeletonJson = rememberInspectionSkeletonJson(),
            modifier = Modifier.fillMaxSize(),
            animated = true,
            orbitView = true,
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
