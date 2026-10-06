package com.gabstra.myworkoutassistant.shared.workout.state

import androidx.compose.runtime.mutableStateOf
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDateTime
import java.util.UUID

class WorkoutStateEditorTest {
    @Test
    fun updateWorkSetsWithSelectedLoad_ignoresUnrelatedBodyWeightSetInEarlierSuperset() {
        val pullUpExerciseId = UUID.randomUUID()
        val shrugExerciseId = UUID.randomUUID()
        val pullUpState = createBodyWeightState(pullUpExerciseId, additionalWeight = 5.0)
        val shrugState = createWeightState(shrugExerciseId, weight = 50.0)
        val machine = WorkoutStateMachine.fromSequence(
            sequence = listOf(
                WorkoutStateSequenceItem.Container(
                    WorkoutStateContainer.SupersetState(
                        supersetId = UUID.randomUUID(),
                        childStates = mutableListOf(pullUpState)
                    )
                ),
                WorkoutStateSequenceItem.Container(
                    WorkoutStateContainer.SupersetState(
                        supersetId = UUID.randomUUID(),
                        childStates = mutableListOf(shrugState)
                    )
                )
            ),
            timeProvider = { LocalDateTime.now() },
            startIndex = 0
        )
        val shrugExercise = Exercise(
            id = shrugExerciseId,
            enabled = true,
            name = "Shrug",
            notes = "",
            sets = listOf(shrugState.set),
            exerciseType = ExerciseType.WEIGHT,
            minReps = 12,
            maxReps = 15,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = UUID.randomUUID(),
            bodyWeightPercentage = null
        )

        val updatedMachine = WorkoutStateEditor.updateWorkSetsWithSelectedLoad(
            machine = machine,
            exercise = shrugExercise,
            selectedWeight = 48.0,
            afterInsertIndex = -1,
            bodyWeightKg = 75.0
        )

        val unchangedPullUp = updatedMachine.getStatesForExercise(pullUpExerciseId)
            .single() as WorkoutState.Set
        val updatedShrug = updatedMachine.getStatesForExercise(shrugExerciseId)
            .single() as WorkoutState.Set
        assertEquals(5.0, (unchangedPullUp.currentSetData as BodyWeightSetData).additionalWeight, 0.0)
        assertEquals(48.0, (updatedShrug.currentSetData as WeightSetData).actualWeight, 0.0)
    }

    private fun createBodyWeightState(exerciseId: UUID, additionalWeight: Double): WorkoutState.Set {
        val set = BodyWeightSet(UUID.randomUUID(), reps = 7, additionalWeight = additionalWeight)
        return createSetState(
            exerciseId = exerciseId,
            set = set,
            setData = BodyWeightSetData(
                actualReps = 7,
                additionalWeight = additionalWeight,
                relativeBodyWeightInKg = 75.0,
                bodyWeightPercentageSnapshot = 100.0,
                volume = 560.0
            )
        )
    }

    private fun createWeightState(exerciseId: UUID, weight: Double): WorkoutState.Set =
        createSetState(
            exerciseId = exerciseId,
            set = WeightSet(UUID.randomUUID(), reps = 12, weight = weight),
            setData = WeightSetData(actualReps = 12, actualWeight = weight, volume = weight * 12)
        )

    private fun createSetState(
        exerciseId: UUID,
        set: com.gabstra.myworkoutassistant.shared.sets.Set,
        setData: com.gabstra.myworkoutassistant.shared.setdata.SetData
    ) = WorkoutState.Set(
        exerciseId = exerciseId,
        set = set,
        setIndex = 0u,
        previousSetData = setData,
        currentSetDataState = mutableStateOf(setData),
        hasNoHistory = true,
        startTime = null,
        skipped = false,
        currentBodyWeight = 75.0,
        streak = 0,
        progressionState = null,
        isWarmupSet = false,
        equipmentId = null
    )
}
