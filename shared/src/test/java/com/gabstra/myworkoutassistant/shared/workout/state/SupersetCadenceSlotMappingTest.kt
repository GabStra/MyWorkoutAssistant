package com.gabstra.myworkoutassistant.shared.workout.state

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.assembly.WorkoutSupersetAssemblyService
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.util.UUID

class SupersetCadenceSlotMappingTest {

    @Test
    fun `member slots rotate through members and repeat cycles`() {
        val superset = supersetOf(memberCount = 2, setsPerMember = 3)
        val machine = machineFor(superset)
        val (first, second) = superset.exercises.map { it.id }

        assertEquals(
            listOf(first, second, first, second, first, second),
            (0 until 6).map { slot -> machine.exerciseIdAtSlot(superset.id, slot) }
        )
        assertNull(machine.findSupersetSetIndexForSlot(superset.id, 6))
    }

    @Test
    fun `custom order shifts the rotation without changing the sets`() {
        val superset = supersetOf(memberCount = 3, setsPerMember = 2)
        val machine = machineFor(superset)
        val (a, b, c) = superset.exercises.map { it.id }

        assertEquals(
            listOf(b, c, a, b, c, a),
            (0 until 6).map { slot -> machine.exerciseIdAtSlot(superset.id, slot, order = listOf(1, 2, 0)) }
        )
        // A shuffled order wraps backwards in flat sequence; slots still move forward.
        assertEquals(
            listOf(c, a, b, c, a, b),
            (0 until 6).map { slot -> machine.exerciseIdAtSlot(superset.id, slot, order = listOf(2, 0, 1)) }
        )
        assertEquals(
            setOf(a, b, c),
            (0 until 6).map { slot -> machine.exerciseIdAtSlot(superset.id, slot, order = listOf(2, 0, 1)) }.toSet()
        )
    }

    @Test
    fun `slot lookup round-trips for every order`() {
        val superset = supersetOf(memberCount = 3, setsPerMember = 2)
        val machine = machineFor(superset)

        for (order in listOf(emptyList(), listOf(1, 2, 0), listOf(2, 0, 1))) {
            for (slot in 0 until 6) {
                val index = machine.findSupersetSetIndexForSlot(superset.id, slot, order)
                assertEquals(slot, machine.findSupersetSlotOfIndex(superset.id, index!!, order))
            }
        }
    }

    @Test
    fun `hold rest fills the remaining slot but not on the last slot`() {
        val superset = supersetOf(memberCount = 2, setsPerMember = 2)
        val machine = machineFor(superset)
        val firstSetIndex = machine.findSupersetSetIndexForSlot(superset.id, 0)!!

        // 3.1s left in a slot -> a 4s hold, rounded up so the boundary always wins.
        assertEquals(4, machine.cadenceHoldSeconds(superset.id, firstSetIndex, emptyList(), 3_100))
        // Finishing within the last second advances normally.
        assertNull(machine.cadenceHoldSeconds(superset.id, firstSetIndex, emptyList(), 900))
        // The last slot has nowhere to hold.
        val lastSetIndex = machine.findSupersetSetIndexForSlot(superset.id, 3)!!
        assertNull(machine.cadenceHoldSeconds(superset.id, lastSetIndex, emptyList(), 3_100))
    }

    private fun WorkoutStateMachine.exerciseIdAtSlot(
        supersetId: UUID,
        slot: Int,
        order: List<Int> = emptyList()
    ): UUID {
        val index = findSupersetSetIndexForSlot(supersetId, slot, order)
        return (allStates[index!!] as WorkoutState.Set).exerciseId
    }

    private fun machineFor(superset: Superset): WorkoutStateMachine {
        val states = WorkoutSupersetAssemblyService().assemblePreviewChildStates(superset)
        return WorkoutStateMachine.fromSequence(
            listOf(
                WorkoutStateSequenceItem.Container(
                    WorkoutStateContainer.SupersetState(superset.id, states.toMutableList())
                )
            )
        )
    }

    private fun supersetOf(memberCount: Int, setsPerMember: Int): Superset {
        val exercises = (1..memberCount).map { memberIndex ->
            Exercise(
                id = UUID.randomUUID(),
                enabled = true,
                name = "Member $memberIndex",
                notes = "",
                sets = (1..setsPerMember).map { WeightSet(UUID.randomUUID(), 5, 20.0) },
                exerciseType = ExerciseType.WEIGHT,
                minReps = 5,
                maxReps = 8,
                lowerBoundMaxHRPercent = null,
                upperBoundMaxHRPercent = null,
                equipmentId = null,
                bodyWeightPercentage = null,
                generateWarmUpSets = false,
                keepScreenOn = false,
                showCountDownTimer = false,
                requiresLoadCalibration = false,
                intraSetRestInSeconds = null
            )
        }
        return Superset(
            id = UUID.randomUUID(),
            enabled = true,
            exercises = exercises,
            restSecondsByExercise = exercises.associate { it.id to 0 },
            roundDurationSeconds = 60,
            cadenceMode = com.gabstra.myworkoutassistant.shared.workoutcomponents.SupersetCadenceMode.MEMBER
        )
    }
}
