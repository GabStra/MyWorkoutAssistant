package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Devices
import androidx.compose.ui.tooling.preview.Preview
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.MuscleGroup
import com.gabstra.myworkoutassistant.shared.Orange
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.util.UUID

@Composable
fun PageMuscles(
    exercise: Exercise
) {
    val muscleGroups = exercise.muscleGroups ?: emptySet()
    val secondaryMuscleGroups = exercise.secondaryMuscleGroups ?: emptySet()
    
    // Determine which view mode to use based on available muscles (including secondary)
    val allMuscleGroups = remember(muscleGroups, secondaryMuscleGroups) {
        muscleGroups + secondaryMuscleGroups
    }
    val hasFrontMuscles = remember(allMuscleGroups) {
        allMuscleGroups.any { it.name.startsWith("FRONT_") }
    }
    val hasBackMuscles = remember(allMuscleGroups) {
        allMuscleGroups.any { it.name.startsWith("BACK_") }
    }
    
    // Auto-select view mode based on available muscles
    val effectiveViewMode = remember(hasFrontMuscles, hasBackMuscles) {
        when {
            hasFrontMuscles && hasBackMuscles -> MuscleViewMode.BOTH
            hasFrontMuscles -> MuscleViewMode.FRONT_ONLY
            hasBackMuscles -> MuscleViewMode.BACK_ONLY
            else -> MuscleViewMode.BOTH
        }
    }
    
    Column(
        modifier = Modifier.fillMaxSize(),
    ) {
        if (muscleGroups.isEmpty() && secondaryMuscleGroups.isEmpty()) {
            Text(
                text = "No muscle groups",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        } else {
            MuscleHeatMap(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
                activeMuscles = muscleGroups,
                secondaryMuscles = secondaryMuscleGroups,
                viewMode = effectiveViewMode,
                highlightColor = Orange,
                secondaryHighlightColor = Orange.copy(alpha = 0.6f),
                baseColor = MaterialTheme.colorScheme.surfaceContainerHigh,
                outlineColor = MaterialTheme.colorScheme.surfaceContainerHigh
            )
        }
    }
}

@Preview(device = Devices.WEAR_OS_SMALL_ROUND, showBackground = true)
@Composable
private fun PageMusclesPreview() {
    MaterialTheme {
        // Create a sample exercise with muscle groups
        val sampleExercise = Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = "Bench Press",
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
            enableProgression = false,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null,
            muscleGroups = setOf(
                MuscleGroup.FRONT_CHEST,
                MuscleGroup.FRONT_DELTOIDS,
                MuscleGroup.BACK_LOWER_BACK,
                MuscleGroup.BACK_TRAPEZIUS
            ),
            secondaryMuscleGroups = null
        )
        
        PageMuscles(exercise = sampleExercise)
    }
}

