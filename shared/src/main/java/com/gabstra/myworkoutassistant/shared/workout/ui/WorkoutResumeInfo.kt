package com.gabstra.myworkoutassistant.shared.workout.ui

import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.model.WorkoutSessionStatus
import java.time.LocalDateTime

/**
 * Locale-independent identity of the set a resume card points at.
 *
 * [setNumber] counts sets of the same [type] up to the resume position, while the underlying
 * resume position remains the stable workout record's exercise id and set index. REST has no
 * ordinal, matching the existing resume-card presentation.
 */
data class WorkoutResumeSetLabel(
    val type: WorkoutResumeSetType,
    val setNumber: Int? = null,
)

enum class WorkoutResumeSetType {
    WORK,
    WARM_UP,
    BACK_OFF,
    REST_PAUSE,
    CALIBRATION,
    REST,
}

/**
 * Resolves a structured, locale-independent resume set label from the workout template.
 *
 * The label is derived from the exercise's set at [setIndex]; no stored text is inspected or
 * rewritten. Missing exercises or indices resolve to the first work set, preserving the previous
 * fallback behavior without generating English UI text in shared code.
 */
fun resolveWorkoutResumeSetLabel(sets: List<Set>?, setIndex: UInt): WorkoutResumeSetLabel {
    val fallback = WorkoutResumeSetLabel(WorkoutResumeSetType.WORK, setNumber = 1)
    val availableSets = sets ?: return fallback
    val currentSetIndex = setIndex.toInt()
    val currentSet = availableSets.getOrNull(currentSetIndex) ?: return fallback
    val type = currentSet.resumeSetType()
    if (type == WorkoutResumeSetType.REST) {
        return WorkoutResumeSetLabel(type)
    }

    val setNumber = availableSets
        .take(currentSetIndex + 1)
        .count { set -> set.resumeSetType() == type }
        .coerceAtLeast(1)
    return WorkoutResumeSetLabel(type, setNumber = setNumber)
}

private fun Set.resumeSetType(): WorkoutResumeSetType {
    if (this is RestSet) return WorkoutResumeSetType.REST

    val subCategory = when (this) {
        is WeightSet -> subCategory
        is BodyWeightSet -> subCategory
        else -> SetSubCategory.WorkSet
    }
    return when (subCategory) {
        SetSubCategory.WarmupSet -> WorkoutResumeSetType.WARM_UP
        SetSubCategory.BackOffSet -> WorkoutResumeSetType.BACK_OFF
        SetSubCategory.RestPauseSet -> WorkoutResumeSetType.REST_PAUSE
        SetSubCategory.CalibrationPendingSet,
        SetSubCategory.CalibrationSet -> WorkoutResumeSetType.CALIBRATION
        SetSubCategory.WorkSet -> WorkoutResumeSetType.WORK
    }
}

data class WorkoutResumeInfo(
    /** User-authored exercise name, or null when the template no longer contains the exercise. */
    val exerciseName: String?,
    val setLabel: WorkoutResumeSetLabel,
    val startedAt: LocalDateTime?,
    val sessionStatus: WorkoutSessionStatus,
    val lastActiveSyncAt: LocalDateTime?,
    /** Live motion-recording state reported by a watch session; null when unknown. */
    val motionCaptureEnabled: Boolean? = null,
)
