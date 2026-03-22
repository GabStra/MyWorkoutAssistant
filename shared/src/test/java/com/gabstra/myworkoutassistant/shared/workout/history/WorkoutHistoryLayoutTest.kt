package com.gabstra.myworkoutassistant.shared.workout.history

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.RestHistoryScope
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import java.time.LocalDate
import java.time.LocalDateTime
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class WorkoutHistoryLayoutTest {

    private val whId: UUID = UUID.fromString("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

    @Test
    fun buildWorkoutHistoryLayout_interleavesRestSectionBetweenWorkoutComponents() {
        val ex1 = UUID.fromString("10000000-0000-0000-0000-000000000001")
        val restMid = UUID.fromString("10000000-0000-0000-0000-000000000002")
        val ex2 = UUID.fromString("10000000-0000-0000-0000-000000000003")

        val workout = Workout(
            id = UUID.randomUUID(),
            name = "w",
            description = "",
            workoutComponents = listOf(
                minimalExercise(ex1, "Ex1"),
                Rest(restMid, true, 90),
                minimalExercise(ex2, "Ex2")
            ),
            order = 0,
            creationDate = LocalDate.of(2026, 3, 22),
            globalId = UUID.randomUUID(),
            type = 0
        )

        val setHistoriesByExerciseId = mapOf(
            ex1 to listOf(sampleSetHistory(exerciseId = ex1, id = 1, seq = 1u)),
            ex2 to listOf(sampleSetHistory(exerciseId = ex2, id = 2, seq = 2u))
        )
        val betweenH = betweenRestHistory(restMid, seq = 1u)

        val layout = buildWorkoutHistoryLayout(
            workout,
            setHistoriesByExerciseId,
            listOf(betweenH)
        )

        assertEquals(3, layout.size)
        val a = layout[0] as WorkoutHistoryLayoutItem.ExerciseSection
        val b = layout[1] as WorkoutHistoryLayoutItem.RestSection
        val c = layout[2] as WorkoutHistoryLayoutItem.ExerciseSection
        assertEquals(ex1, a.exerciseId)
        assertEquals(restMid, b.restComponentId)
        assertEquals(betweenH.id, b.history.id)
        assertEquals(ex2, c.exerciseId)
    }

    @Test
    fun buildWorkoutHistoryLayout_throwsWhenDuplicateRestHistoryForSameTemplateRest() {
        val ex1 = UUID.fromString("10000000-0000-0000-0000-000000000001")
        val restMid = UUID.fromString("10000000-0000-0000-0000-000000000002")
        val ex2 = UUID.fromString("10000000-0000-0000-0000-000000000003")

        val workout = Workout(
            id = UUID.randomUUID(),
            name = "w",
            description = "",
            workoutComponents = listOf(
                minimalExercise(ex1, "Ex1"),
                Rest(restMid, true, 90),
                minimalExercise(ex2, "Ex2")
            ),
            order = 0,
            creationDate = LocalDate.of(2026, 3, 22),
            globalId = UUID.randomUUID(),
            type = 0
        )

        val setHistoriesByExerciseId = mapOf(
            ex1 to listOf(sampleSetHistory(exerciseId = ex1, id = 1, seq = 1u)),
            ex2 to listOf(sampleSetHistory(exerciseId = ex2, id = 2, seq = 2u))
        )
        val h1 = betweenRestHistory(restMid, seq = 1u, uuid = UUID.fromString("60000000-0000-0000-0000-000000000001"))
        val h2 = betweenRestHistory(restMid, seq = 2u, uuid = UUID.fromString("60000000-0000-0000-0000-000000000002"))

        try {
            buildWorkoutHistoryLayout(workout, setHistoriesByExerciseId, listOf(h1, h2))
            fail("expected IllegalStateException")
        } catch (e: IllegalStateException) {
            assertTrue(e.message!!.contains(restMid.toString()))
        }
    }

    private fun minimalExercise(id: UUID, name: String): Exercise {
        val setId = UUID.randomUUID()
        return Exercise(
            id = id,
            enabled = true,
            name = name,
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(WeightSet(setId, 5, 50.0)),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 1,
            maxReps = 10,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = ProgressionMode.OFF,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null,
            muscleGroups = null,
            secondaryMuscleGroups = null,
            requiredAccessoryEquipmentIds = null,
            requiresLoadCalibration = false,
            exerciseCategory = null
        )
    }

    private fun t(s: String): LocalDateTime = LocalDateTime.parse(s)

    private fun sampleSetHistory(
        exerciseId: UUID,
        id: Int,
        seq: UInt?,
    ): SetHistory = SetHistory(
        id = UUID.nameUUIDFromBytes("set-$id".toByteArray()),
        workoutHistoryId = whId,
        exerciseId = exerciseId,
        equipmentIdSnapshot = null,
        equipmentNameSnapshot = null,
        equipmentTypeSnapshot = null,
        setId = UUID.randomUUID(),
        order = id.toUInt(),
        startTime = LocalDateTime.of(2026, 3, 22, 10, id, 0),
        endTime = LocalDateTime.of(2026, 3, 22, 10, id, 1),
        setData = WeightSetData(10, 50.0, 50.0, SetSubCategory.WorkSet),
        skipped = false,
        executionSequence = seq
    )

    private fun betweenRestHistory(
        componentId: UUID,
        seq: UInt?,
        uuid: UUID = UUID.nameUUIDFromBytes("between-$componentId-$seq".toByteArray()),
    ): RestHistory = RestHistory(
        id = uuid,
        workoutHistoryId = whId,
        scope = RestHistoryScope.BETWEEN_WORKOUT_COMPONENTS,
        executionSequence = seq,
        setData = RestSetData(60, 60, SetSubCategory.WorkSet),
        startTime = t("2026-03-22T10:15:00"),
        endTime = t("2026-03-22T10:16:00"),
        workoutComponentId = componentId,
        exerciseId = UUID.randomUUID(),
        restSetId = UUID.randomUUID(),
        order = 0u
    )
}
