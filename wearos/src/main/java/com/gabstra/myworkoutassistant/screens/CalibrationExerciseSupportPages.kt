package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.composables.workout.pages.ExerciseAnimationPage
import com.gabstra.myworkoutassistant.composables.ExerciseNameText
import com.gabstra.myworkoutassistant.composables.workout.pages.TitledLinesPage
import com.gabstra.myworkoutassistant.composables.workout.pages.TitledLinesSection
import com.gabstra.myworkoutassistant.composables.WorkoutPagerLayoutTokens
import com.gabstra.myworkoutassistant.composables.WorkoutPagerPageSafeAreaPadding
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.util.UUID

internal fun Modifier.calibrationPageContent(pageType: CalibrationPageType): Modifier =
    when (pageType) {
        // These pages own their safe-area padding.
        CalibrationPageType.BUTTONS, CalibrationPageType.INFO,
        CalibrationPageType.EXERCISES, CalibrationPageType.MOVEMENT -> fillMaxSize()
        else -> fillMaxSize().padding(WorkoutPagerPageSafeAreaPadding).clipToBounds()
    }

@Composable
internal fun buildCalibrationExerciseInfoSections(
    viewModel: AppViewModel,
    exercise: Exercise,
    equipmentId: UUID?,
    status: String,
): List<TitledLinesSection> {
    val exerciseTitle = stringResource(R.string.wear_info_exercise)
    val targetRepsTitle = stringResource(R.string.wear_info_target_reps)
    val statusTitle = stringResource(R.string.wear_info_status)
    val equipmentTitle = stringResource(R.string.wear_info_equipment)
    val accessoriesTitle = stringResource(R.string.wear_info_accessories)
    val notesTitle = stringResource(R.string.wear_info_notes)

    return buildList {
        add(TitledLinesSection(exerciseTitle, listOf(exercise.name)))
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
            add(TitledLinesSection(targetRepsTitle, listOf(target)))
        }
        add(TitledLinesSection(statusTitle, listOf(status)))
        equipmentId
            ?.let(viewModel::getEquipmentById)
            ?.let { add(TitledLinesSection(equipmentTitle, listOf(it.name))) }
        val accessories = (exercise.requiredAccessoryEquipmentIds ?: emptyList())
            .mapNotNull(viewModel::getLinkedSupportName)
        if (accessories.isNotEmpty()) {
            add(TitledLinesSection(accessoriesTitle, accessories))
        }
        if (exercise.notes.isNotEmpty()) {
            add(TitledLinesSection(notesTitle, listOf(exercise.notes)))
        }
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
                    top = WorkoutPagerPageSafeAreaPadding.calculateTopPadding(),
                    start = WorkoutPagerLayoutTokens.ExerciseTitleHorizontalPadding,
                    end = WorkoutPagerLayoutTokens.ExerciseTitleHorizontalPadding,
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
