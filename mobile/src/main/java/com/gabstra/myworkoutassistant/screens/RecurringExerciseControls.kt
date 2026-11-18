package com.gabstra.myworkoutassistant.screens

import android.content.Context
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.ContentSubtitle
import com.gabstra.myworkoutassistant.composables.FormSectionTitle
import com.gabstra.myworkoutassistant.composables.StandardFilterDropdown
import com.gabstra.myworkoutassistant.composables.StandardFilterDropdownItem
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.shared.RecurringTrackChoice
import com.gabstra.myworkoutassistant.shared.RecurringWorkoutAuthoring
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.LoadHistoryPolicy
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import java.util.UUID

enum class RecurringTrackMode { NEW_TRACK, UNLINKED, EXISTING_TRACK }

data class RecurringTrackSelection(
    val mode: RecurringTrackMode,
    val trackId: UUID? = null,
)

data class RecurringExerciseEdit(
    val trackSelection: RecurringTrackSelection,
    val loadHistoryPolicy: LoadHistoryPolicy,
)

internal fun initialRecurringTrackSelection(
    exercise: Exercise?,
    isNewPrescription: Boolean,
): RecurringTrackSelection = if (isNewPrescription) {
    RecurringTrackSelection(RecurringTrackMode.NEW_TRACK)
} else {
    exercise?.recurringExerciseId?.let { RecurringTrackSelection(RecurringTrackMode.EXISTING_TRACK, it) }
        ?: RecurringTrackSelection(RecurringTrackMode.UNLINKED)
}

internal fun initialRecurringLoadPolicy(
    existingPolicy: LoadHistoryPolicy?,
    isNewPrescription: Boolean,
    isRecurringWorkout: Boolean,
    exerciseType: ExerciseType,
): LoadHistoryPolicy = if (
    isNewPrescription &&
    isRecurringWorkout &&
    exerciseType in setOf(ExerciseType.WEIGHT, ExerciseType.BODY_WEIGHT)
) {
    LoadHistoryPolicy.PRESCRIBED_WEIGHT
} else {
    existingPolicy ?: LoadHistoryPolicy.NONE
}

private data class TrackOption(
    val selection: RecurringTrackSelection,
    val label: String,
)

internal fun normalizeRecurringTrackSelection(
    selection: RecurringTrackSelection,
    availableTrackIds: Set<UUID>,
): RecurringTrackSelection = when (selection.mode) {
    RecurringTrackMode.NEW_TRACK -> RecurringTrackSelection(RecurringTrackMode.NEW_TRACK)
    RecurringTrackMode.UNLINKED -> RecurringTrackSelection(RecurringTrackMode.UNLINKED)
    RecurringTrackMode.EXISTING_TRACK -> selection.trackId
        ?.takeIf { it in availableTrackIds }
        ?.let { RecurringTrackSelection(RecurringTrackMode.EXISTING_TRACK, it) }
        ?: RecurringTrackSelection(RecurringTrackMode.NEW_TRACK)
}

internal fun recurringLoadPolicyFor(
    requestedPolicy: LoadHistoryPolicy,
    exerciseType: ExerciseType,
    trackSelection: RecurringTrackSelection,
    hasLoadableWorkingSet: Boolean,
): LoadHistoryPolicy = if (
    requestedPolicy == LoadHistoryPolicy.PRESCRIBED_WEIGHT &&
    exerciseType in setOf(ExerciseType.WEIGHT, ExerciseType.BODY_WEIGHT)
) {
    LoadHistoryPolicy.PRESCRIBED_WEIGHT
} else if (
    requestedPolicy == LoadHistoryPolicy.LAST_WORKING_LOAD &&
    exerciseType in setOf(ExerciseType.WEIGHT, ExerciseType.BODY_WEIGHT) &&
    hasLoadableWorkingSet &&
    trackSelection.mode != RecurringTrackMode.UNLINKED
) {
    LoadHistoryPolicy.LAST_WORKING_LOAD
} else {
    LoadHistoryPolicy.NONE
}

internal fun applyRecurringExerciseEdit(
    exercise: Exercise,
    edit: RecurringExerciseEdit?,
    family: List<Workout>,
): Exercise {
    if (edit == null) return exercise
    return when (edit.trackSelection.mode) {
        RecurringTrackMode.NEW_TRACK -> RecurringWorkoutAuthoring.createExerciseTrack(
            exercise,
            edit.loadHistoryPolicy,
            family,
        )
        RecurringTrackMode.UNLINKED -> RecurringWorkoutAuthoring.unlinkExerciseTrack(
            exercise.copy(loadHistoryPolicy = edit.loadHistoryPolicy),
        )
        RecurringTrackMode.EXISTING_TRACK -> RecurringWorkoutAuthoring.linkExerciseTrack(
            exercise,
            requireNotNull(edit.trackSelection.trackId) { "Choose a compatible history slot." },
            edit.loadHistoryPolicy,
            family,
        )
    }
}

internal fun sanitizeRecurringTrackMetadata(
    exercise: Exercise,
    originalExercise: Exercise?,
    isRecurringWorkout: Boolean,
    family: List<Workout>,
): Exercise {
    if (!isRecurringWorkout) return exercise

    val originalSupportsWeightHistory = originalExercise?.exerciseType == ExerciseType.WEIGHT ||
        originalExercise?.exerciseType == ExerciseType.BODY_WEIGHT
    val supportsWeightHistory = exercise.exerciseType in setOf(
        ExerciseType.WEIGHT,
        ExerciseType.BODY_WEIGHT,
    )
    if (originalSupportsWeightHistory && !supportsWeightHistory) {
        return exercise.copy(recurringExerciseId = null, loadHistoryPolicy = LoadHistoryPolicy.NONE)
    }

    val signatureChanged = originalExercise != null && (
        originalExercise.exerciseType != exercise.exerciseType ||
            originalExercise.equipmentId != exercise.equipmentId ||
            originalExercise.exerciseDefinitionId != exercise.exerciseDefinitionId
        )
    val trackId = exercise.recurringExerciseId
    val hasExistingOwner = trackId != null && family.any { workout ->
        workout.isActive && workout.workoutComponents.any { component ->
            when (component) {
                is Exercise -> component.recurringExerciseId == trackId
                is Superset -> component.exercises.any { it.recurringExerciseId == trackId }
                else -> false
            }
        }
    }
    val trackStillCompatible = trackId == null || !signatureChanged || !hasExistingOwner ||
        runCatching {
            RecurringWorkoutAuthoring.compatibleTrackChoices(exercise, family)
                .any { it.trackId == trackId }
        }.getOrDefault(false)
    if (!trackStillCompatible) {
        return exercise.copy(recurringExerciseId = null, loadHistoryPolicy = LoadHistoryPolicy.NONE)
    }

    if (!supportsWeightHistory && exercise.loadHistoryPolicy != LoadHistoryPolicy.NONE) {
        return exercise.copy(loadHistoryPolicy = LoadHistoryPolicy.NONE)
    }
    return exercise
}

@Composable
fun RecurringExerciseControls(
    exercise: Exercise,
    family: List<Workout>,
    trackSelection: RecurringTrackSelection,
    onTrackSelectionChange: (RecurringTrackSelection) -> Unit,
    loadHistoryPolicy: LoadHistoryPolicy,
    onLoadHistoryPolicyChange: (LoadHistoryPolicy) -> Unit,
    requiresLoadCalibration: Boolean,
    progressionMode: ProgressionMode,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val supportsWeightHistory = exercise.exerciseType in setOf(ExerciseType.WEIGHT, ExerciseType.BODY_WEIGHT)
    if (!supportsWeightHistory) {
        FormSectionTitle(text = stringResource(R.string.loc_ex_weight_history))
        StyledCard(modifier = modifier.fillMaxWidth()) {
            Text(
                stringResource(R.string.loc_ex_weight_history_unsupported),
                style = MaterialTheme.typography.bodyMedium,
            )
        }
        Spacer(Modifier.height(Spacing.md))
        return
    }

    val trackChoices = remember(exercise, family) {
        RecurringWorkoutAuthoring.compatibleTrackChoices(exercise, family)
    }
    val availableTrackIds = trackChoices.mapTo(mutableSetOf()) { it.trackId }
    val normalizedSelection = normalizeRecurringTrackSelection(trackSelection, availableTrackIds)
    val workingSets = exercise.sets.filterNot { it is RestSet }
    val hasLoadableWorkingSet = workingSets.isNotEmpty() && when (exercise.exerciseType) {
        ExerciseType.WEIGHT -> workingSets.all { it is WeightSet }
        ExerciseType.BODY_WEIGHT -> workingSets.all { it is BodyWeightSet }
        else -> false
    }

    LaunchedEffect(normalizedSelection) {
        if (normalizedSelection != trackSelection) onTrackSelectionChange(normalizedSelection)
    }

    val options = buildList {
        add(
            TrackOption(
                RecurringTrackSelection(RecurringTrackMode.NEW_TRACK),
                context.getString(R.string.loc_ex_create_new_weight_history_slot),
            )
        )
        add(
            TrackOption(
                RecurringTrackSelection(RecurringTrackMode.UNLINKED),
                context.getString(R.string.loc_ex_no_history_link),
            )
        )
        trackChoices.forEach { choice ->
            add(TrackOption(
                RecurringTrackSelection(RecurringTrackMode.EXISTING_TRACK, choice.trackId),
                choice.displayLabel(context),
            ))
        }
    }
    val selectedOption = options.first { it.selection == normalizedSelection }
    val canSelectLastWorkingLoad = hasLoadableWorkingSet && normalizedSelection.mode != RecurringTrackMode.UNLINKED
    val displayedLoadPolicy = recurringLoadPolicyFor(
        loadHistoryPolicy,
        exercise.exerciseType,
        normalizedSelection,
        hasLoadableWorkingSet,
    )

    FormSectionTitle(text = stringResource(R.string.loc_ex_recurring_weight_history))
    StyledCard(modifier = modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(Spacing.md),
            verticalArrangement = Arrangement.spacedBy(Spacing.md),
        ) {
            StandardFilterDropdown(
                label = stringResource(R.string.loc_ex_weight_history_slot),
                selectedText = selectedOption.label,
                items = options.map { StandardFilterDropdownItem(it.selection, it.label) },
                onItemSelected = onTrackSelectionChange,
                selectedValue = normalizedSelection,
                isItemSelected = { it == normalizedSelection },
                modifier = Modifier.fillMaxWidth().testTag("recurring_weight_history_slot"),
                itemMaxLines = 2,
            )
            ContentSubtitle(stringResource(R.string.loc_ex_recurring_slots_hint))
            StandardFilterDropdown(
                label = stringResource(R.string.loc_ex_weight_behavior),
                selectedText = when (displayedLoadPolicy) {
                    LoadHistoryPolicy.NONE -> context.getString(R.string.loc_ex_auto_existing_behavior)
                    LoadHistoryPolicy.PRESCRIBED_WEIGHT -> context.getString(R.string.loc_ex_prescribed_weight)
                    LoadHistoryPolicy.LAST_WORKING_LOAD -> context.getString(R.string.loc_ex_last_working_load)
                },
                items = buildList {
                    add(
                        StandardFilterDropdownItem(
                            LoadHistoryPolicy.NONE,
                            context.getString(R.string.loc_ex_auto_existing_behavior),
                        )
                    )
                    add(
                        StandardFilterDropdownItem(
                            LoadHistoryPolicy.PRESCRIBED_WEIGHT,
                            context.getString(R.string.loc_ex_prescribed_weight),
                        )
                    )
                    if (canSelectLastWorkingLoad) {
                        add(
                            StandardFilterDropdownItem(
                                LoadHistoryPolicy.LAST_WORKING_LOAD,
                                context.getString(R.string.loc_ex_last_working_load),
                            )
                        )
                    }
                },
                onItemSelected = onLoadHistoryPolicyChange,
                selectedValue = displayedLoadPolicy,
                isItemSelected = { it == displayedLoadPolicy },
                modifier = Modifier.fillMaxWidth().testTag("recurring_starting_load"),
            )
            ContentSubtitle(
                when (displayedLoadPolicy) {
                    LoadHistoryPolicy.PRESCRIBED_WEIGHT ->
                        stringResource(R.string.loc_ex_prescribed_weight_hint)
                    LoadHistoryPolicy.NONE ->
                        stringResource(R.string.loc_ex_automatic_behavior_hint)
                    LoadHistoryPolicy.LAST_WORKING_LOAD -> when {
                        workingSets.isEmpty() -> stringResource(R.string.loc_ex_add_work_set_hint)
                        !hasLoadableWorkingSet -> stringResource(R.string.loc_ex_last_load_requires_supported_sets)
                        !canSelectLastWorkingLoad -> stringResource(R.string.loc_ex_choose_history_slot_hint)
                        requiresLoadCalibration || progressionMode != ProgressionMode.OFF ->
                            stringResource(R.string.loc_ex_calibration_precedence_hint)
                        else ->
                            stringResource(R.string.loc_ex_last_load_explanation)
                    }
                }
            )
        }
    }
    Spacer(Modifier.height(Spacing.md))
}

private fun RecurringTrackChoice.displayLabel(context: Context): String {
    val prescription = prescriptionLabel?.takeIf(String::isNotBlank)
        ?: prescriptionOrdinal.takeIf { it > 0 }
            ?.let { context.getString(R.string.loc_scr_prescription_n, it) }
        ?: context.getString(R.string.loc_ex_prescription_unknown)
    return context.getString(
        R.string.loc_ex_track_label,
        exerciseName,
        sourceWorkoutName,
        prescription,
        context.getString(R.string.loc_ex_exercise_n, exercisePosition),
    )
}
