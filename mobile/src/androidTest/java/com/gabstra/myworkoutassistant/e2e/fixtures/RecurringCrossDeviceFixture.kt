package com.gabstra.myworkoutassistant.e2e.fixtures

import com.gabstra.myworkoutassistant.shared.ExerciseDefinition
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.LoadHistoryPolicy
import java.nio.charset.StandardCharsets
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID

/**
 * Cross-device contract mirrored by the phone instrumentation fixture. Every value is scoped to
 * the runner's run_id so concurrent or repeated runs never reuse a profile or history identity.
 */
object RecurringCrossDeviceFixture {
    const val UUID_NAMESPACE = "mwa-recurring-sync"
    const val PROFILE_PREFIX = "recurring_sync_"
    const val PROFILE_NAME = "Recurring sync E2E"
    const val PLAN_NAME = "Recurring sync cycle"
    const val FAMILY_NAME = "Recurring sync session"
    const val FOUNDATION_LABEL = "Foundation"
    const val PROGRESSION_LABEL = "Progression"

    const val FOUNDATION_ORDINAL = 1
    const val PROGRESSION_ORDINAL = 2
    const val HISTORY_REPS = 7
    const val HISTORY_WEIGHT = 47.5

    fun profileId(runId: String): String {
        require(runId.matches(Regex("[A-Za-z0-9_-]{1,48}"))) { "Invalid recurring sync run_id" }
        return "$PROFILE_PREFIX$runId"
    }

    fun uuid(runId: String, key: String): UUID {
        require(runId.matches(Regex("[A-Za-z0-9_-]{1,48}"))) { "Invalid recurring sync run_id" }
        return UUID.nameUUIDFromBytes("$UUID_NAMESPACE/$runId/$key".toByteArray(StandardCharsets.UTF_8))
    }

    fun createWorkoutStore(runId: String): WorkoutStore {
        val planId = uuid(runId, "plan")
        val sessionId = uuid(runId, "session")
        val foundationId = uuid(runId, "foundation.workout")
        val progressionId = uuid(runId, "progression.workout")
        val definitions = Slot.entries.map { slot ->
            ExerciseDefinition(
                id = definitionId(runId, slot),
                name = slot.displayName,
                exerciseType = ExerciseType.WEIGHT,
            )
        }
        val foundation = createWorkout(
            runId = runId,
            sessionId = sessionId,
            planId = planId,
            workoutId = foundationId,
            ordinal = FOUNDATION_ORDINAL,
            label = FOUNDATION_LABEL,
            isActive = true,
            prefix = "foundation",
        )
        val progression = createWorkout(
            runId = runId,
            sessionId = sessionId,
            planId = planId,
            workoutId = progressionId,
            ordinal = PROGRESSION_ORDINAL,
            label = PROGRESSION_LABEL,
            isActive = true,
            prefix = "progression",
        )
        return WorkoutStore(
            exerciseDefinitions = definitions,
            workouts = listOf(foundation, progression),
            workoutPlans = listOf(
                WorkoutPlan(
                    id = planId,
                    name = PLAN_NAME,
                    workoutIds = listOf(foundation.id, progression.id),
                    order = 0,
                    suggestNextPrescription = false,
                )
            ),
            birthDateYear = 1990,
            weightKg = 80.0,
            progressionPercentageAmount = 0.05,
        )
    }

    fun historyId(runId: String): UUID = uuid(runId, "history")
    fun sessionId(runId: String): UUID = uuid(runId, "session")
    fun planId(runId: String): UUID = uuid(runId, "plan")
    fun workoutId(runId: String, ordinal: Int): UUID =
        uuid(runId, if (ordinal == FOUNDATION_ORDINAL) "foundation.workout" else "progression.workout")

    fun trackId(runId: String, slot: Slot): UUID = uuid(runId, "track.${slot.key}")
    fun definitionId(runId: String, slot: Slot): UUID = uuid(runId, "definition.${slot.key}")
    fun exerciseId(runId: String, ordinal: Int, slot: Slot): UUID =
        uuid(runId, "${versionPrefix(ordinal)}.exercise.${slot.key}")
    fun setId(runId: String, ordinal: Int, slot: Slot): UUID =
        uuid(runId, "${versionPrefix(ordinal)}.set.${slot.key}")

    fun completedHistory(runId: String): WorkoutHistory {
        val date = LocalDate.of(2026, 11, 15)
        val time = LocalTime.of(10, 0)
        return WorkoutHistory(
            id = historyId(runId),
            workoutId = workoutId(runId, PROGRESSION_ORDINAL),
            date = date,
            time = time,
            startTime = LocalDateTime.of(date, time),
            duration = 240,
            heartBeatRecords = listOf(98, 105, 112),
            isDone = true,
            hasBeenSentToHealth = false,
            globalId = uuid(runId, "progression.global"),
            recurringSessionId = sessionId(runId),
        )
    }

    fun completedSetHistories(runId: String): List<SetHistory> {
        val history = completedHistory(runId)
        return Slot.entries.mapIndexed { index, slot ->
            val start = history.startTime.plusSeconds(index * 45L)
            SetHistory(
                id = uuid(runId, "history.set.${slot.key}"),
                workoutHistoryId = history.id,
                exerciseId = exerciseId(runId, PROGRESSION_ORDINAL, slot),
                setId = setId(runId, PROGRESSION_ORDINAL, slot),
                order = index.toUInt(),
                startTime = start,
                endTime = start.plusSeconds(30),
                setData = WeightSetData(
                    actualReps = HISTORY_REPS,
                    actualWeight = HISTORY_WEIGHT,
                    volume = HISTORY_REPS * HISTORY_WEIGHT,
                    subCategory = SetSubCategory.WorkSet,
                ),
                skipped = false,
                executionSequence = index.toUInt(),
                recurringExerciseId = trackId(runId, slot),
                exerciseDefinitionIdSnapshot = definitionId(runId, slot),
                exerciseTypeSnapshot = ExerciseType.WEIGHT.name,
            )
        }
    }

    private fun createWorkout(
        runId: String,
        sessionId: UUID,
        planId: UUID,
        workoutId: UUID,
        ordinal: Int,
        label: String,
        isActive: Boolean,
        prefix: String,
    ) = Workout(
        id = workoutId,
        name = FAMILY_NAME,
        description = "Recurring cross-device sync prescription $label",
        workoutComponents = Slot.entries.map { slot ->
            val progressionOffset = if (ordinal == PROGRESSION_ORDINAL) 1 else 0
            Exercise(
                id = exerciseId(runId, ordinal, slot),
                enabled = true,
                name = slot.displayName,
                notes = "${slot.displayName} $label notes",
                sets = listOf(
                    WeightSet(
                        id = setId(runId, ordinal, slot),
                        reps = slot.baseReps + progressionOffset,
                        weight = slot.baseWeight + (5.0 * progressionOffset),
                    )
                ),
                exerciseType = ExerciseType.WEIGHT,
                minReps = 4,
                maxReps = 12,
                lowerBoundMaxHRPercent = null,
                upperBoundMaxHRPercent = null,
                equipmentId = null,
                bodyWeightPercentage = null,
                progressionMode = ProgressionMode.OFF,
                exerciseDefinitionId = definitionId(runId, slot),
                recurringExerciseId = trackId(runId, slot),
                loadHistoryPolicy = slot.policy,
            )
        },
        order = ordinal - 1,
        creationDate = LocalDate.of(2026, 1, 1).plusDays(ordinal.toLong() - 1L),
        isActive = isActive,
        globalId = uuid(runId, "$prefix.global"),
        type = 0,
        workoutPlanId = planId,
        recurringSessionId = sessionId,
        prescriptionOrdinal = ordinal,
        prescriptionLabel = label,
    )

    private fun versionPrefix(ordinal: Int): String =
        if (ordinal == FOUNDATION_ORDINAL) "foundation" else "progression"

    enum class Slot(
        val key: String,
        val displayName: String,
        val policy: LoadHistoryPolicy,
        val baseReps: Int,
        val baseWeight: Double,
    ) {
        NONE("none", "Automatic slot", LoadHistoryPolicy.NONE, 6, 30.0),
        LAST("last", "Last-load slot", LoadHistoryPolicy.LAST_WORKING_LOAD, 8, 40.0),
        FIXED("fixed", "Prescribed slot", LoadHistoryPolicy.PRESCRIBED_WEIGHT, 10, 50.0),
    }
}
