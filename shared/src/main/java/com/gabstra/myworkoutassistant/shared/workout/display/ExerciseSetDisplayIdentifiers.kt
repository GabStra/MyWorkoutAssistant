package com.gabstra.myworkoutassistant.shared.workout.display

import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.WeightedEffortSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.RunningSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import java.util.Locale
import java.util.UUID

/** Canonical English rest-row wording, used by non-localized callers. */
const val EnglishWorkoutRestRowFormat = "REST %1\$s"

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

/**
 * Label for the active set counter shown next to the exercise name. The warm-up/work
 * distinction is only meaningful when the exercise actually has warm-up sets; otherwise
 * every non-calibration set is just "SET".
 */
fun buildActiveSetCounterLabel(
    counterKind: SetDisplayCounterKind?,
    hasWarmupSets: Boolean,
): String = when (counterKind) {
    SetDisplayCounterKind.Warmup -> "WARM-UP"
    SetDisplayCounterKind.Work -> if (hasWarmupSets) "WORK SET" else "SET"
    SetDisplayCounterKind.Calibration -> "CALIBRATION"
    null -> "SET"
}

fun displayCounterKindForSet(set: Set): SetDisplayCounterKind? {
    return when (set) {
        is WeightSet -> displayCounterKindForSubCategory(set.subCategory)
        is BodyWeightSet -> displayCounterKindForSubCategory(set.subCategory)
        is TimedDurationSet,
        is EnduranceSet,
        is RunningSet,
        is WeightedEffortSet -> SetDisplayCounterKind.Work
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

/**
 * "ROUND A · SET 2/3 · SIDE L" context line for the active-set header.
 * The counter part is omitted when the exercise's flow has a single set of
 * its kind: "SET 1/1" carries no information.
 *
 * Callers that display the label in a localized UI can override the English
 * wording through the format/label parameters (for example, a localized
 * "SERIE 1/2" counter label), while other callers keep the English defaults.
 */
fun buildActiveExerciseContextLabel(
    setCounter: Pair<Int, Int>?,
    setCounterKind: SetDisplayCounterKind?,
    hasWarmupSets: Boolean,
    unilateralSideIndex: UInt?,
    intraSetTotal: UInt?,
    supersetRound: String? = null,
    roundLabelFormat: String = "ROUND %1\$s",
    setCounterFormat: String = "%1\$s %2\$d/%3\$d",
    setCounterLabelOverride: String? = null,
    sideLabelFormat: String = "SIDE %1\$s",
): String? = listOfNotNull(
    supersetRound?.let { String.format(Locale.US, roundLabelFormat, it) },
    setCounter
        ?.takeIf { (_, total) -> total > 1 }
        ?.let { (current, total) ->
            String.format(
                Locale.US,
                setCounterFormat,
                setCounterLabelOverride
                    ?: buildActiveSetCounterLabel(setCounterKind, hasWarmupSets),
                current,
                total,
            )
        },
    buildUnilateralSideLabel(unilateralSideIndex, intraSetTotal)
        ?.removePrefix("-")
        ?.let { side -> String.format(Locale.US, sideLabelFormat, side) }
).takeIf { it.isNotEmpty() }?.joinToString(" · ")

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
    return buildWorkoutRestRowLabel(
        restState = restState,
        labelFormat = EnglishWorkoutRestRowFormat,
    )
}

/**
 * Rest row label using a caller-supplied format (e.g. a localized
 * "RECUPERO %1$s" resource). The default overload above keeps the English
 * wording for non-localized callers.
 */
fun buildWorkoutRestRowLabel(
    restState: WorkoutState.Rest,
    labelFormat: String,
): String {
    val seconds = (restState.set as? RestSet)?.timeInSeconds ?: 0
    return formatWorkoutRestRowLabel(seconds, labelFormat)
}

/**
 * Rest row label for a planned duration that is not attached to a workout
 * state (for example, a superset preview or an intra-set rest).
 */
fun formatWorkoutRestRowLabel(
    seconds: Int,
    labelFormat: String = EnglishWorkoutRestRowFormat,
): String {
    return String.format(
        Locale.US,
        labelFormat,
        formatWorkoutDurationSecondsForDisplay(seconds),
    )
}
