package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import com.gabstra.myworkoutassistant.composables.workout.pages.ExerciseAnimationPage
import com.gabstra.myworkoutassistant.composables.ExerciseNameText
import com.gabstra.myworkoutassistant.composables.workout.pages.TitledLinesPage
import com.gabstra.myworkoutassistant.composables.workout.pages.TitledLinesSection
import com.gabstra.myworkoutassistant.composables.WorkoutPagerLayoutTokens
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.util.UUID

internal fun buildCalibrationExerciseInfoSections(
    viewModel: AppViewModel,
    exercise: Exercise,
    equipmentId: UUID?,
    status: String,
): List<TitledLinesSection> = buildList {
    add(TitledLinesSection("Exercise", listOf(exercise.name)))
    if (
        (exercise.exerciseType == ExerciseType.WEIGHT ||
            exercise.exerciseType == ExerciseType.BODY_WEIGHT) &&
        exercise.minReps > 0 &&
        exercise.maxReps >= exercise.minReps
    ) {
        val target = if (exercise.minReps == exercise.maxReps) {
            exercise.minReps.toString()
        } else {
            "${exercise.minReps}-${exercise.maxReps}"
        }
        add(TitledLinesSection("Target reps", listOf(target)))
    }
    add(TitledLinesSection("Status", listOf(status)))
    equipmentId
        ?.let(viewModel::getEquipmentById)
        ?.let { add(TitledLinesSection("Equipment", listOf(it.name))) }
    val accessories = (exercise.requiredAccessoryEquipmentIds ?: emptyList())
        .mapNotNull(viewModel::getLinkedSupportName)
    if (accessories.isNotEmpty()) {
        add(TitledLinesSection("Accessories", accessories))
    }
    if (exercise.notes.isNotEmpty()) {
        add(TitledLinesSection("Notes", listOf(exercise.notes)))
    }
}

@Composable
internal fun CalibrationExerciseInfoPage(
    sections: List<TitledLinesSection>,
) {
    TitledLinesPage(
        modifier = Modifier.fillMaxSize(),
        sections = sections,
    )
}

@Composable
internal fun CalibrationExerciseMovementPage(
    exercise: Exercise,
    isActive: Boolean,
) {
    Column(modifier = Modifier.fillMaxSize()) {
        ExerciseNameText(
            text = exercise.name,
            modifier = Modifier
                .fillMaxWidth()
                .padding(
                    top = WorkoutPagerLayoutTokens.ExerciseTitleHorizontalPadding,
                    start = 45.dp,
                    end = 45.dp,
                ),
            style = MaterialTheme.typography.titleLarge.copy(
                fontWeight = FontWeight.SemiBold,
            ),
            textAlign = TextAlign.Center,
        )
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f)
                .padding(top = 5.dp, bottom = 12.5.dp),
        ) {
            ExerciseAnimationPage(
                exercise = exercise,
                isActive = isActive,
                dragRotationHorizontalInset = 40.dp,
                modifier = Modifier.fillMaxSize(),
            )
        }
    }
}
