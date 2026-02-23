package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.tooling.preview.devices.WearDevices
import com.airbnb.lottie.compose.LottieAnimation
import com.airbnb.lottie.compose.LottieCompositionSpec
import com.airbnb.lottie.compose.rememberLottieComposition
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.presentation.theme.baseline
import com.gabstra.myworkoutassistant.presentation.theme.darkScheme
import com.gabstra.myworkoutassistant.shared.DarkGray
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.util.UUID
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

@Composable
private fun IsometricGrid(
    modifier: Modifier = Modifier,
    gridColor: Color = Color(0xFF404040),
    gridLineWidth: Float = 2.5f,
    gridSpacing: Float = 40f
) {
    Canvas(modifier = modifier.fillMaxSize()) {
        val width = size.width
        val height = size.height
        val centerX = width / 2f
        val centerY = height / 2f

        // Isometric projection angles (matching pose2lottie_isometric.py defaults)
        val yawDeg = 35f
        val pitchDeg = 22f
        val yaw = (yawDeg * PI / 180.0).toFloat()
        val pitch = (pitchDeg * PI / 180.0).toFloat()

        // Helper to project 3D point to 2D
        fun project3D(x: Float, y: Float, z: Float): Offset {
            // Yaw rotation around Y axis
            val x1 = cos(yaw) * x + sin(yaw) * z
            val z1 = -sin(yaw) * x + cos(yaw) * z
            // Pitch rotation around X axis
            val y2 = cos(pitch) * y - sin(pitch) * z1
            return Offset(x1 + centerX, -y2 + centerY)
        }

        // Draw grid lines in XZ plane at y=0
        val gridExtent = maxOf(width, height) * 2
        val gridSteps = (gridExtent / gridSpacing).toInt()

        // Lines parallel to X axis (varying Z)
        for (i in -gridSteps..gridSteps) {
            val z = i * gridSpacing
            val p0 = project3D(-gridExtent, 0f, z)
            val p1 = project3D(gridExtent, 0f, z)
            drawLine(
                color = gridColor,
                start = p0,
                end = p1,
                strokeWidth = gridLineWidth
            )
        }

        // Lines parallel to Z axis (varying X)
        for (i in -gridSteps..gridSteps) {
            val x = i * gridSpacing
            val p0 = project3D(x, 0f, -gridExtent)
            val p1 = project3D(x, 0f, gridExtent)
            drawLine(
                color = gridColor,
                start = p0,
                end = p1,
                strokeWidth = gridLineWidth
            )
        }
    }
}

@Composable
fun PageMovementAnimation(
    exercise: Exercise
) {
    // For now, we use the squat animation for all exercises
    // In the future, this can be extended to load different animations based on exercise

    val composition by rememberLottieComposition(
        LottieCompositionSpec.RawRes(R.raw.squat)
    )

    IsometricGrid(
        modifier = Modifier.fillMaxSize(),
        gridColor = DarkGray,
        gridLineWidth = 2f,
        gridSpacing = 30f
    )

    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(25.dp),
        contentAlignment = Alignment.Center
    ) {
        // Grid behind the animation

        
        // Lottie animation on top
        LottieAnimation(
            composition = composition,
            modifier = Modifier.fillMaxSize().offset(x= (-15).dp),
            iterations = Int.MAX_VALUE
        )
    }
}

@Preview(device = WearDevices.LARGE_ROUND, showBackground = true)
@Composable
private fun PageMovementAnimationPreview() {
    MaterialTheme(
        colorScheme = darkScheme,
        typography = baseline,
    ) {
        // Create a sample exercise
        val sampleExercise = Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = "Squat",
            doNotStoreHistory = false,
            notes = "",
            sets = emptyList(),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 65.0,
            maxLoadPercent = 85.0,
            minReps = 6,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = com.gabstra.myworkoutassistant.shared.ProgressionMode.OFF,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null,
            muscleGroups = null,
            secondaryMuscleGroups = null
        )

        PageMovementAnimation(exercise = sampleExercise)
    }
}
