package com.gabstra.myworkoutassistant.shared.viewmodels

import androidx.compose.runtime.mutableStateOf
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDateTime
import java.util.UUID

class WorkoutStateMachineTest {

    private val exerciseId1 = UUID.randomUUID()
    private val exerciseId2 = UUID.randomUUID()
    private val setId1 = UUID.randomUUID()
    private val setId2 = UUID.randomUUID()
    private val setId3 = UUID.randomUUID()
    private val restSetId1 = UUID.randomUUID()

    private fun createSetState(exerciseId: UUID, setId: UUID, setIndex: UInt): WorkoutState.Set {
        return WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(setId, 10, 100.0),
            setIndex = setIndex,
            previousSetData = null,
            currentSetDataState = mutableStateOf(WeightSetData(10, 100.0, 1000.0)),
            hasNoHistory = true,
            startTime = null,
            skipped = false,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            currentBodyWeight = 70.0,
            plateChangeResult = null,
            streak = 0,
            progressionState = null,
            isWarmupSet = false,
            equipment = null,
            isUnilateral = false,
            intraSetTotal = null,
            intraSetCounter = 0u
        )
    }

    private fun createRestState(setId: UUID): WorkoutState.Rest {
        return WorkoutState.Rest(
            set = RestSet(setId, 90),
            order = 0u,
            currentSetDataState = mutableStateOf(RestSetData(90, 90)),
            exerciseId = null,
            nextState = null,
            startTime = null,
            isIntraSetRest = false
        )
    }

    @Test
    fun testInitialState() {
        val set1 = createSetState(exerciseId1, setId1, 0u)
        val rest1 = createRestState(restSetId1)
        val set2 = createSetState(exerciseId1, setId2, 1u)
        val completed = WorkoutState.Completed(LocalDateTime.now())

        val states = listOf(set1, rest1, set2, completed)
        val machine = WorkoutStateMachine.fromStates(states)

        assertEquals(set1, machine.currentState)
        assertTrue(machine.isAtStart)
        assertFalse(machine.isCompleted)
        assertTrue(machine.isHistoryEmpty)
        assertEquals(rest1, machine.upcomingNext)
        assertEquals(emptyList<WorkoutState>(), machine.history)
        assertEquals(listOf(rest1, set2, completed), machine.nextStates)
    }

    @Test
    fun testNext() {
        val set1 = createSetState(exerciseId1, setId1, 0u)
        val rest1 = createRestState(restSetId1)
        val set2 = createSetState(exerciseId1, setId2, 1u)
        val completed = WorkoutState.Completed(LocalDateTime.now())

        val states = listOf(set1, rest1, set2, completed)
        var machine = WorkoutStateMachine.fromStates(states)

        // Advance to rest
        machine = machine.next()
        assertEquals(rest1, machine.currentState)
        assertEquals(listOf(set1), machine.history)
        assertEquals(set2, machine.upcomingNext)
        assertFalse(machine.isAtStart)
        assertFalse(machine.isCompleted)

        // Advance to set2
        machine = machine.next()
        assertEquals(set2, machine.currentState)
        assertEquals(listOf(set1, rest1), machine.history)
        assertEquals(completed, machine.upcomingNext)

        // Advance to completed
        machine = machine.next()
        assertEquals(completed, machine.currentState)
        assertEquals(listOf(set1, rest1, set2), machine.history)
        assertNull(machine.upcomingNext)
        assertTrue(machine.isCompleted)

        // Verify endWorkoutTime is set
        assertNotNull((machine.currentState as WorkoutState.Completed).endWorkoutTime)
    }

    @Test
    fun testNextOnCompletedDoesNothing() {
        val set1 = createSetState(exerciseId1, setId1, 0u)
        val completed = WorkoutState.Completed(LocalDateTime.now())
        val states = listOf(set1, completed)

        var machine = WorkoutStateMachine.fromStates(states)
        machine = machine.next() // Move to completed
        val beforeNext = machine.currentState

        machine = machine.next() // Try to advance from completed
        assertEquals(beforeNext, machine.currentState)
        assertTrue(machine.isCompleted)
    }

    @Test
    fun testUndo() {
        val set1 = createSetState(exerciseId1, setId1, 0u)
        val rest1 = createRestState(restSetId1)
        val set2 = createSetState(exerciseId1, setId2, 1u)
        val completed = WorkoutState.Completed(LocalDateTime.now())

        val states = listOf(set1, rest1, set2, completed)
        var machine = WorkoutStateMachine.fromStates(states)

        // Advance to set2
        machine = machine.next() // set1 -> rest1
        machine = machine.next() // rest1 -> set2

        assertEquals(set2, machine.currentState)
        assertEquals(listOf(set1, rest1), machine.history)

        // Undo to rest1
        machine = machine.undo()
        assertEquals(rest1, machine.currentState)
        assertEquals(listOf(set1), machine.history)
        assertEquals(set2, machine.upcomingNext)

        // Undo to set1
        machine = machine.undo()
        assertEquals(set1, machine.currentState)
        assertEquals(emptyList<WorkoutState>(), machine.history)
        assertEquals(rest1, machine.upcomingNext)
        assertTrue(machine.isAtStart)
    }

    @Test
    fun testUndoAtStartDoesNothing() {
        val set1 = createSetState(exerciseId1, setId1, 0u)
        val rest1 = createRestState(restSetId1)
        val states = listOf(set1, rest1)

        val machine = WorkoutStateMachine.fromStates(states)
        val beforeUndo = machine.currentState

        val afterUndo = machine.undo()
        assertEquals(beforeUndo, afterUndo.currentState)
        assertTrue(afterUndo.isAtStart)
    }

    @Test
    fun testSkipUntil() {
        val set1 = createSetState(exerciseId1, setId1, 0u)
        val rest1 = createRestState(restSetId1)
        val set2 = createSetState(exerciseId2, setId2, 0u) // Different exercise
        val rest2 = createRestState(UUID.randomUUID())
        val set3 = createSetState(exerciseId2, setId3, 1u)
        val completed = WorkoutState.Completed(LocalDateTime.now())

        val states = listOf(set1, rest1, set2, rest2, set3, completed)
        val machine = WorkoutStateMachine.fromStates(states)

        // Skip until we find a Set with different exerciseId
        val newMachine = machine.skipUntil { state ->
            state is WorkoutState.Set && (state as WorkoutState.Set).exerciseId != exerciseId1
        }

        assertEquals(set2, newMachine.currentState)
        assertEquals(listOf(set1, rest1), newMachine.history)
    }

    @Test
    fun testSkipUntilCompleted() {
        val set1 = createSetState(exerciseId1, setId1, 0u)
        val rest1 = createRestState(restSetId1)
        val completed = WorkoutState.Completed(LocalDateTime.now())

        val states = listOf(set1, rest1, completed)
        val machine = WorkoutStateMachine.fromStates(states)

        // Skip until predicate that never matches (except Completed)
        val newMachine = machine.skipUntil { state ->
            state is WorkoutState.Set && (state as WorkoutState.Set).exerciseId == UUID.randomUUID()
        }

        assertEquals(completed, newMachine.currentState)
        assertTrue(newMachine.isCompleted)
    }

    @Test
    fun testRepositionToSetId() {
        val set1 = createSetState(exerciseId1, setId1, 0u)
        val rest1 = createRestState(restSetId1)
        val set2 = createSetState(exerciseId1, setId2, 1u)
        val rest2 = createRestState(UUID.randomUUID())
        val set3 = createSetState(exerciseId1, setId1, 2u) // Same setId as set1 (unilateral)
        val completed = WorkoutState.Completed(LocalDateTime.now())

        val states = listOf(set1, rest1, set2, rest2, set3, completed)
        val machine = WorkoutStateMachine.fromStates(states)

        // Reposition to setId2 (should find set2)
        val repositioned = machine.repositionToSetId(setId2)
        assertEquals(set2, repositioned.currentState)

        // Reposition to setId1 (should find first occurrence: set1)
        val repositioned2 = machine.repositionToSetId(setId1)
        assertEquals(set1, repositioned2.currentState)
    }

    @Test
    fun testRepositionToSetIdNotFound() {
        val set1 = createSetState(exerciseId1, setId1, 0u)
        val rest1 = createRestState(restSetId1)
        val states = listOf(set1, rest1)

        val machine = WorkoutStateMachine.fromStates(states)
        val notFoundId = UUID.randomUUID()

        val repositioned = machine.repositionToSetId(notFoundId)
        // Should return current position if not found
        assertEquals(machine.currentState, repositioned.currentState)
    }

    @Test
    fun testHistoryAndNextStates() {
        val set1 = createSetState(exerciseId1, setId1, 0u)
        val rest1 = createRestState(restSetId1)
        val set2 = createSetState(exerciseId1, setId2, 1u)
        val completed = WorkoutState.Completed(LocalDateTime.now())

        val states = listOf(set1, rest1, set2, completed)
        var machine = WorkoutStateMachine.fromStates(states)

        // At start
        assertEquals(emptyList<WorkoutState>(), machine.history)
        assertEquals(listOf(rest1, set2, completed), machine.nextStates)

        // After one next
        machine = machine.next()
        assertEquals(listOf(set1), machine.history)
        assertEquals(listOf(set2, completed), machine.nextStates)

        // After two nexts
        machine = machine.next()
        assertEquals(listOf(set1, rest1), machine.history)
        assertEquals(listOf(completed), machine.nextStates)
    }

    @Test(expected = IllegalArgumentException::class)
    fun testEmptyStatesThrows() {
        WorkoutStateMachine.fromStates(emptyList())
    }

    @Test(expected = IllegalArgumentException::class)
    fun testInvalidCurrentIndexThrows() {
        val set1 = createSetState(exerciseId1, setId1, 0u)
        val container = WorkoutStateContainer.ExerciseState(exerciseId1, mutableListOf(set1))
        val sequence = listOf(WorkoutStateSequenceItem.Container(container))
        WorkoutStateMachine.fromSequence(sequence, startIndex = 5) // Index out of bounds
    }

    @Test
    fun testHierarchicalStructure() {
        val set1 = createSetState(exerciseId1, setId1, 0u)
        val rest1 = createRestState(restSetId1)
        val set2 = createSetState(exerciseId1, setId2, 1u)
        val restBetween = createRestState(UUID.randomUUID())
        val set3 = createSetState(exerciseId2, setId3, 0u)
        val completed = WorkoutState.Completed(LocalDateTime.now())

        val exercise1Container = WorkoutStateContainer.ExerciseState(
            exerciseId1,
            mutableListOf(set1, rest1, set2)
        )
        val exercise2Container = WorkoutStateContainer.ExerciseState(
            exerciseId2,
            mutableListOf(set3, completed)
        )
        val sequence = listOf(
            WorkoutStateSequenceItem.Container(exercise1Container),
            WorkoutStateSequenceItem.RestBetweenExercises(restBetween),
            WorkoutStateSequenceItem.Container(exercise2Container)
        )

        val machine = WorkoutStateMachine.fromSequence(sequence)

        // Verify allStates flattens correctly
        assertEquals(listOf(set1, rest1, set2, restBetween, set3, completed), machine.allStates)
        assertEquals(set1, machine.currentState)
    }

    @Test
    fun testInsertStatesIntoExercise() {
        val set1 = createSetState(exerciseId1, setId1, 0u)
        val set2 = createSetState(exerciseId1, setId2, 1u)
        val restBetween = createRestState(UUID.randomUUID())
        val set3 = createSetState(exerciseId2, setId3, 0u)

        val exercise1Container = WorkoutStateContainer.ExerciseState(
            exerciseId1,
            mutableListOf(set1, set2)
        )
        val exercise2Container = WorkoutStateContainer.ExerciseState(
            exerciseId2,
            mutableListOf(set3)
        )
        val sequence = listOf(
            WorkoutStateSequenceItem.Container(exercise1Container),
            WorkoutStateSequenceItem.RestBetweenExercises(restBetween),
            WorkoutStateSequenceItem.Container(exercise2Container)
        )

        var machine = WorkoutStateMachine.fromSequence(sequence, startIndex = 1) // At set2

        // Insert new states after set1 (index 0)
        val newSet1 = createSetState(exerciseId1, UUID.randomUUID(), 2u)
        val newSet2 = createSetState(exerciseId1, UUID.randomUUID(), 3u)
        machine = machine.insertStatesIntoExercise(exerciseId1, listOf(newSet1, newSet2), afterChildIndex = 0)

        // Verify insertion
        val exerciseContainer = machine.getCurrentExerciseContainer()
        assertNotNull(exerciseContainer)
        assertEquals(exerciseId1, exerciseContainer!!.exerciseId)
        assertEquals(listOf(set1, newSet1, newSet2, set2), exerciseContainer.childStates)

        // Verify allStates is updated
        assertEquals(listOf(set1, newSet1, newSet2, set2, restBetween, set3), machine.allStates)
    }

    @Test
    fun testGetCurrentExerciseContainer() {
        val set1 = createSetState(exerciseId1, setId1, 0u)
        val set2 = createSetState(exerciseId1, setId2, 1u)
        val restBetween = createRestState(UUID.randomUUID())
        val set3 = createSetState(exerciseId2, setId3, 0u)

        val exercise1Container = WorkoutStateContainer.ExerciseState(
            exerciseId1,
            mutableListOf(set1, set2)
        )
        val exercise2Container = WorkoutStateContainer.ExerciseState(
            exerciseId2,
            mutableListOf(set3)
        )
        val sequence = listOf(
            WorkoutStateSequenceItem.Container(exercise1Container),
            WorkoutStateSequenceItem.RestBetweenExercises(restBetween),
            WorkoutStateSequenceItem.Container(exercise2Container)
        )

        var machine = WorkoutStateMachine.fromSequence(sequence, startIndex = 1) // At set2
        var container = machine.getCurrentExerciseContainer()
        assertNotNull(container)
        assertEquals(exerciseId1, container!!.exerciseId)

        machine = WorkoutStateMachine.fromSequence(sequence, startIndex = 3) // At set3 (set1=0, set2=1, restBetween=2, set3=3)
        container = machine.getCurrentExerciseContainer()
        assertNotNull(container)
        assertEquals(exerciseId2, container!!.exerciseId)
    }

    @Test
    fun testGetStatesForExercise() {
        val set1 = createSetState(exerciseId1, setId1, 0u)
        val set2 = createSetState(exerciseId1, setId2, 1u)
        val restBetween = createRestState(UUID.randomUUID())
        val set3 = createSetState(exerciseId2, setId3, 0u)

        val exercise1Container = WorkoutStateContainer.ExerciseState(
            exerciseId1,
            mutableListOf(set1, set2)
        )
        val exercise2Container = WorkoutStateContainer.ExerciseState(
            exerciseId2,
            mutableListOf(set3)
        )
        val sequence = listOf(
            WorkoutStateSequenceItem.Container(exercise1Container),
            WorkoutStateSequenceItem.RestBetweenExercises(restBetween),
            WorkoutStateSequenceItem.Container(exercise2Container)
        )

        val machine = WorkoutStateMachine.fromSequence(sequence)
        val exercise1States = machine.getStatesForExercise(exerciseId1)
        assertEquals(listOf(set1, set2), exercise1States)

        val exercise2States = machine.getStatesForExercise(exerciseId2)
        assertEquals(listOf(set3), exercise2States)
    }
}

