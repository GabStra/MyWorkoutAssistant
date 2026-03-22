package com.gabstra.myworkoutassistant.shared.viewmodels

import androidx.compose.runtime.mutableStateOf
import com.gabstra.myworkoutassistant.shared.coroutines.TestDispatcherProvider
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.ExerciseChildItem
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateContainer
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateMachine
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateSequenceItem
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.time.LocalDateTime
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [30])
@OptIn(ExperimentalCoroutinesApi::class)
class GoToPreviousSetCalibrationNavigationTest {

    private val testDispatcher = StandardTestDispatcher()
    private lateinit var viewModel: WorkoutViewModel

    @Before
    fun setUp() {
        Dispatchers.setMain(testDispatcher)
        viewModel = WorkoutViewModel(TestDispatcherProvider(testDispatcher))
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun goToPreviousSet_fromRestAfterCalibration_returnsToCalibrationSet() = runTest(testDispatcher) {
        val exerciseId = UUID.randomUUID()
        val calibrationSetId = UUID.randomUUID()
        val workSetId = UUID.randomUUID()

        val machine = WorkoutStateMachine.fromSequence(
            sequence = listOf(
                WorkoutStateSequenceItem.Container(
                    WorkoutStateContainer.ExerciseState(
                        exerciseId = exerciseId,
                        childItems = mutableListOf(
                            ExerciseChildItem.LoadSelectionBlock(
                                mutableListOf(createCalibrationLoadSelection(exerciseId, calibrationSetId))
                            ),
                            ExerciseChildItem.CalibrationExecutionBlock(
                                mutableListOf(
                                    createCalibrationSetState(exerciseId, calibrationSetId),
                                    createRestState(exerciseId)
                                )
                            ),
                            ExerciseChildItem.Normal(createWorkSetState(exerciseId, workSetId))
                        )
                    )
                )
            ),
            timeProvider = { LocalDateTime.of(2026, 1, 1, 12, 0) },
            startIndex = 2
        )

        viewModel.stateMachine = machine
        viewModel.updateStateFlowsFromMachine()

        viewModel.goToPreviousSet()
        advanceUntilIdle()

        val currentState = viewModel.stateMachine!!.currentState as WorkoutState.Set
        assertTrue("Expected to land back on the calibration set", currentState.isCalibrationSet)
        assertEquals(calibrationSetId, currentState.set.id)
    }

    @Test
    fun goToPreviousSet_fromRestAfterCalibration_doesNotJumpToEarlierExercise() = runTest(testDispatcher) {
        val previousExerciseId = UUID.randomUUID()
        val previousSetId = UUID.randomUUID()
        val currentExerciseId = UUID.randomUUID()
        val calibrationSetId = UUID.randomUUID()
        val workSetId = UUID.randomUUID()

        val machine = WorkoutStateMachine.fromSequence(
            sequence = listOf(
                WorkoutStateSequenceItem.Container(
                    WorkoutStateContainer.ExerciseState(
                        exerciseId = previousExerciseId,
                        childItems = mutableListOf(
                            ExerciseChildItem.Normal(createWorkSetState(previousExerciseId, previousSetId))
                        )
                    )
                ),
                WorkoutStateSequenceItem.RestBetweenExercises(
                    createRestState(exerciseId = null)
                ),
                WorkoutStateSequenceItem.Container(
                    WorkoutStateContainer.ExerciseState(
                        exerciseId = currentExerciseId,
                        childItems = mutableListOf(
                            ExerciseChildItem.LoadSelectionBlock(
                                mutableListOf(createCalibrationLoadSelection(currentExerciseId, calibrationSetId))
                            ),
                            ExerciseChildItem.CalibrationExecutionBlock(
                                mutableListOf(
                                    createCalibrationSetState(currentExerciseId, calibrationSetId),
                                    createRestState(currentExerciseId)
                                )
                            ),
                            ExerciseChildItem.Normal(createWorkSetState(currentExerciseId, workSetId))
                        )
                    )
                )
            ),
            timeProvider = { LocalDateTime.of(2026, 1, 1, 12, 0) },
            startIndex = 4
        )

        viewModel.stateMachine = machine
        viewModel.updateStateFlowsFromMachine()

        viewModel.goToPreviousSet()
        advanceUntilIdle()

        val currentState = viewModel.stateMachine!!.currentState as WorkoutState.Set
        assertEquals(
            "Expected to return to the current exercise calibration set",
            calibrationSetId,
            currentState.set.id
        )
        assertEquals(currentExerciseId, currentState.exerciseId)
        assertTrue(currentState.isCalibrationSet)
    }

    @Test
    fun goToPreviousSet_fromStandardRest_keepsExistingBehavior() = runTest(testDispatcher) {
        val exerciseId = UUID.randomUUID()
        val firstSetId = UUID.randomUUID()
        val secondSetId = UUID.randomUUID()

        val machine = WorkoutStateMachine.fromSequence(
            sequence = listOf(
                WorkoutStateSequenceItem.Container(
                    WorkoutStateContainer.ExerciseState(
                        exerciseId = exerciseId,
                        childItems = mutableListOf(
                            ExerciseChildItem.Normal(createWorkSetState(exerciseId, firstSetId)),
                            ExerciseChildItem.Normal(createRestState(exerciseId)),
                            ExerciseChildItem.Normal(createWorkSetState(exerciseId, secondSetId))
                        )
                    )
                )
            ),
            timeProvider = { LocalDateTime.of(2026, 1, 1, 12, 0) },
            startIndex = 1
        )

        viewModel.stateMachine = machine
        viewModel.updateStateFlowsFromMachine()

        viewModel.goToPreviousSet()
        advanceUntilIdle()

        val currentState = viewModel.stateMachine!!.currentState as WorkoutState.Set
        assertEquals(firstSetId, currentState.set.id)
        assertTrue(!currentState.isCalibrationSet)
    }

    private fun createCalibrationLoadSelection(
        exerciseId: UUID,
        calibrationSetId: UUID
    ) = WorkoutState.CalibrationLoadSelection(
        exerciseId = exerciseId,
        calibrationSet = WeightSet(
            id = calibrationSetId,
            reps = 8,
            weight = 80.0,
            subCategory = SetSubCategory.CalibrationSet
        ),
        setIndex = 0u,
        previousSetData = null,
        currentSetDataState = mutableStateOf(WeightSetData(8, 80.0, 640.0)),
        equipmentId = null,
        currentBodyWeight = 75.0
    )

    private fun createCalibrationSetState(
        exerciseId: UUID,
        calibrationSetId: UUID
    ) = WorkoutState.Set(
        exerciseId = exerciseId,
        set = WeightSet(
            id = calibrationSetId,
            reps = 8,
            weight = 80.0,
            subCategory = SetSubCategory.CalibrationSet
        ),
        setIndex = 0u,
        previousSetData = null,
        currentSetDataState = mutableStateOf(WeightSetData(8, 80.0, 640.0)),
        hasNoHistory = true,
        startTime = null,
        skipped = false,
        lowerBoundMaxHRPercent = null,
        upperBoundMaxHRPercent = null,
        currentBodyWeight = 75.0,
        plateChangeResult = null,
        streak = 0,
        progressionState = null,
        isWarmupSet = false,
        equipmentId = null,
        isUnilateral = false,
        intraSetTotal = null,
        intraSetCounter = 0u,
        isCalibrationSet = true
    )

    private fun createWorkSetState(
        exerciseId: UUID,
        setId: UUID
    ) = WorkoutState.Set(
        exerciseId = exerciseId,
        set = WeightSet(
            id = setId,
            reps = 8,
            weight = 80.0
        ),
        setIndex = 1u,
        previousSetData = null,
        currentSetDataState = mutableStateOf(WeightSetData(8, 80.0, 640.0)),
        hasNoHistory = true,
        startTime = null,
        skipped = false,
        lowerBoundMaxHRPercent = null,
        upperBoundMaxHRPercent = null,
        currentBodyWeight = 75.0,
        plateChangeResult = null,
        streak = 0,
        progressionState = null,
        isWarmupSet = false,
        equipmentId = null,
        isUnilateral = false,
        intraSetTotal = null,
        intraSetCounter = 0u
    )

    private fun createRestState(exerciseId: UUID?) = WorkoutState.Rest(
        set = RestSet(UUID.randomUUID(), 60),
        order = 1u,
        currentSetDataState = mutableStateOf(RestSetData(60, 60)),
        exerciseId = exerciseId
    )
}
