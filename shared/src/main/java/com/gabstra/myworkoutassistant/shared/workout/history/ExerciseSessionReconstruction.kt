package com.gabstra.myworkoutassistant.shared.workout.history

import com.gabstra.myworkoutassistant.shared.ExerciseSessionSnapshot
import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.RestHistoryScope
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.buildExerciseSessionSnapshot
import com.gabstra.myworkoutassistant.shared.sanitizeRestPlacementInSetHistories
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.toSets
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.LoadHistoryPolicy
import java.util.UUID

/**
 * Result of merging completed session data onto the programmed template for one exercise.
 * See [ExerciseSessionReconstruction.mergeCompletedSession].
 */
data class CompletedExerciseSessionMerge(
    val snapshot: ExerciseSessionSnapshot,
    /** Sanitized set histories (progression volume, simple-set metrics, etc.). */
    val preparedSetHistories: List<SetHistory>,
) {
    fun mergedSets(): List<Set> = snapshot.toSets()
}

object ExerciseSessionReconstruction {

    fun shouldPreservePrescription(exercise: Exercise): Boolean =
        exercise.recurringExerciseId != null ||
            exercise.loadHistoryPolicy == LoadHistoryPolicy.PRESCRIBED_WEIGHT

    /**
     * Overlays set + intra-exercise rest execution onto the programmed [templateSets].
     * Single API for watch completion and phone sync.
     */
    fun mergeCompletedSession(
        templateSets: List<Set>,
        rawSetHistoriesForExercise: List<SetHistory>,
        allRestHistories: List<RestHistory>,
        exerciseId: UUID,
        preservePrescription: Boolean = false,
    ): CompletedExerciseSessionMerge {
        val preparedSetHistories = prepareSetHistoriesForSnapshot(rawSetHistoriesForExercise)
        val intraExerciseRests = allRestHistories.filter {
            it.exerciseId == exerciseId && it.scope == RestHistoryScope.INTRA_EXERCISE
        }
        val snapshot = buildExerciseSessionSnapshot(
            currentSets = templateSets,
            setHistories = preparedSetHistories,
            restHistories = intraExerciseRests,
            preservePrescription = preservePrescription,
        )
        return CompletedExerciseSessionMerge(snapshot, preparedSetHistories)
    }

    /** Sanitize + order; used when only [SetHistory] is needed (e.g. prior-session lookup). */
    fun prepareSetHistoriesForSnapshot(rawSetHistoriesForExercise: List<SetHistory>): List<SetHistory> {
        return sanitizeRestPlacementInSetHistories(
            rawSetHistoriesForExercise.sortedBy { it.order },
        ).filter { setHistory ->
            when (val sd = setHistory.setData) {
                is BodyWeightSetData ->
                    sd.subCategory != SetSubCategory.RestPauseSet && sd.subCategory != SetSubCategory.CalibrationSet
                is WeightSetData ->
                    sd.subCategory != SetSubCategory.RestPauseSet && sd.subCategory != SetSubCategory.CalibrationSet
                is RestSetData ->
                    sd.subCategory != SetSubCategory.RestPauseSet && sd.subCategory != SetSubCategory.CalibrationSet
                else -> true
            }
        }
    }
}
