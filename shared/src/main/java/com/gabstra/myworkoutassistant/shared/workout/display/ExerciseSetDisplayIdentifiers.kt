package com.gabstra.myworkoutassistant.shared.workout.display

import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import java.util.Locale
import java.util.UUID

/**
 * Maps a zero-based exercise index within a superset to a letter label (A, B, …, Z, AA, …).
 */
fun toSupersetLetter(index: Int): String {
    if (index < 0) return ""
    var value = index
    val builder = StringBuilder()
    do {
        val remainder = value % 26
        builder.append(('A'.code + remainder).toChar())
        value = (value / 26) - 1
    } while (value >= 0)
    return builder.reverse().toString()
}

fun buildSupersetAwareRowLabel(
    supersetPrefix: String?,
    label: String,
): String = supersetPrefix?.let { "$it · $label" } ?: label

fun resolveSupersetExercisePrefix(
    viewModel: WorkoutViewModel,
    exerciseId: UUID,
): String? = viewModel.supersetIdByExerciseId[exerciseId]
    ?.let { supersetId -> viewModel.exercisesBySupersetId[supersetId] }
    ?.indexOfFirst { it.id == exerciseId }
    ?.takeIf { it >= 0 }
    ?.let(::toSupersetLetter)

enum class SetDisplayCounterKind {
    Work,
    Warmup,
    Calibration,
}

fun buildSetDisplayIdentifier(
    current: Int,
    supersetPrefix: String?,
    counterKind: SetDisplayCounterKind,
): String = when (counterKind) {
    SetDisplayCounterKind.Work -> "${supersetPrefix.orEmpty()}$current"
    SetDisplayCounterKind.Warmup -> buildSupersetAwareRowLabel(
        supersetPrefix = supersetPrefix,
        label = "W$current"
    )
    SetDisplayCounterKind.Calibration -> buildSupersetAwareRowLabel(
        supersetPrefix = supersetPrefix,
        label = "CAL"
    )
}

fun displayCounterKindForSet(set: Set): SetDisplayCounterKind? {
    return when (set) {
        is WeightSet -> displayCounterKindForSubCategory(set.subCategory)
        is BodyWeightSet -> displayCounterKindForSubCategory(set.subCategory)
        is TimedDurationSet,
        is EnduranceSet -> SetDisplayCounterKind.Work
        is RestSet -> null
    }
}

fun displayCounterKindForSetState(setState: WorkoutState.Set): SetDisplayCounterKind? {
    return when {
        setState.isWarmupSet -> SetDisplayCounterKind.Warmup
        setState.isCalibrationSet -> SetDisplayCounterKind.Calibration
        else -> displayCounterKindForSet(setState.set)
    }
}

fun displayCounterKindForSubCategory(subCategory: SetSubCategory?): SetDisplayCounterKind {
    return when (subCategory) {
        SetSubCategory.WarmupSet -> SetDisplayCounterKind.Warmup
        SetSubCategory.CalibrationSet -> SetDisplayCounterKind.Calibration
        else -> SetDisplayCounterKind.Work
    }
}

/**
 * Human-readable set label for the exercise set table (e.g. "1", "W2", "A1"), matching Wear OS.
 */
fun buildWorkoutSetDisplayIdentifier(
    viewModel: WorkoutViewModel,
    exerciseId: UUID,
    setState: WorkoutState.Set,
): String? {
    val (current, _) = viewModel.getSetCounterForExercise(exerciseId, setState) ?: return null

    val supersetPrefix = resolveSupersetExercisePrefix(viewModel, exerciseId)

    val counterKind = displayCounterKindForSetState(setState) ?: return null
    return buildSetDisplayIdentifier(
        current = current,
        supersetPrefix = supersetPrefix,
        counterKind = counterKind
    )
}

fun buildUnilateralSideLabel(
    sideIndex: UInt?,
    intraSetTotal: UInt?,
): String? {
    val resolvedSideIndex = sideIndex?.toInt() ?: return null
    val resolvedTotal = intraSetTotal?.toInt() ?: return null
    if (resolvedTotal != 2) return null

    val normalizedSideIndex = resolvedSideIndex.coerceIn(1, resolvedTotal)

    return when (normalizedSideIndex) {
        1 -> "-L"
        2 -> "-R"
        else -> null
    }
}

/** Same formatting as phone/wear workout timers: MM:SS, or HH:MM:SS if hours > 0. */
fun formatWorkoutDurationSecondsForDisplay(seconds: Int): String {
    val hours = seconds / 3600
    val minutes = (seconds % 3600) / 60
    val remainingSeconds = seconds % 60
    return if (hours > 0) {
        String.format(Locale.US, "%02d:%02d:%02d", hours, minutes, remainingSeconds)
    } else {
        String.format(Locale.US, "%02d:%02d", minutes, remainingSeconds)
    }
}

fun buildWorkoutRestRowLabel(restState: WorkoutState.Rest): String {
    val seconds = (restState.set as? RestSet)?.timeInSeconds ?: 0
    return "REST ${formatWorkoutDurationSecondsForDisplay(seconds)}"
}
