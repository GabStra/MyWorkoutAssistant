package com.gabstra.myworkoutassistant.shared.viewmodels

import android.content.Context
import androidx.compose.runtime.mutableStateOf
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.coroutines.TestDispatcherProvider
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [30])
@OptIn(ExperimentalCoroutinesApi::class)
class GetSetCounterForExerciseTest {

    private lateinit var database: AppDatabase
    private lateinit var viewModel: WorkoutViewModel
    private lateinit var context: Context
    private lateinit var stateMachineField: java.lang.reflect.Field
    private val testDispatcher = StandardTestDispatcher()

    private val exerciseId = UUID.randomUUID()
    private val setId1 = UUID.randomUUID()
    private val setId2 = UUID.randomUUID()
    private val calibrationSetId = UUID.randomUUID()

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

    private fun createCalibrationLoadState(): WorkoutState.CalibrationLoadSelection {
        return WorkoutState.CalibrationLoadSelection(
            exerciseId = exerciseId,
            calibrationSet = WeightSet(calibrationSetId, 8, 80.0),
            setIndex = 2u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(WeightSetData(8, 80.0, 800.0)),
            equipment = null,
            currentBodyWeight = 70.0
        )
    }

    private fun createCalibrationRIRState(): WorkoutState.CalibrationRIRSelection {
        return WorkoutState.CalibrationRIRSelection(
            exerciseId = exerciseId,
            calibrationSet = WeightSet(calibrationSetId, 8, 80.0),
            setIndex = 2u,
            currentSetDataState = mutableStateOf(WeightSetData(8, 80.0, 800.0)),
            equipment = null,
            currentBodyWeight = 70.0
        )
    }

    private fun createRestState(): WorkoutState.Rest {
        return WorkoutState.Rest(
            set = RestSet(UUID.randomUUID(), 90),
            order = 0u,
            currentSetDataState = mutableStateOf(RestSetData(90, 90)),
            exerciseId = null,
            nextState = null,
            startTime = null,
            isIntraSetRest = false
        )
    }

    @Before
    fun setup() {
        Dispatchers.setMain(testDispatcher)
        context = ApplicationProvider.getApplicationContext()
        database = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java)
            .allowMainThreadQueries().build()

        val tempDir = File(context.cacheDir, "test_workout_store")
        tempDir.mkdirs()
        val mockWorkoutStoreRepository = WorkoutStoreRepository(tempDir)

        viewModel = WorkoutViewModel(TestDispatcherProvider(testDispatcher))

        listOf(
            "setHistoryDao" to database.setHistoryDao(),
            "workoutHistoryDao" to database.workoutHistoryDao(),
            "workoutScheduleDao" to database.workoutScheduleDao(),
            "workoutRecordDao" to database.workoutRecordDao(),
            "exerciseInfoDao" to database.exerciseInfoDao(),
            "exerciseSessionProgressionDao" to database.exerciseSessionProgressionDao()
        ).forEach { (name, dao) ->
            val field = WorkoutViewModel::class.java.getDeclaredField(name)
            field.isAccessible = true
            field.set(viewModel, dao)
        }

        stateMachineField = WorkoutViewModel::class.java.getDeclaredField("stateMachine")
        stateMachineField.isAccessible = true

        viewModel.initWorkoutStoreRepository(mockWorkoutStoreRepository)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
        database.close()
    }

    @Test
    fun returnsCorrectCounterForWorkoutStateSet() {
        val set1 = createSetState(exerciseId, setId1, 0u)
        val set2 = createSetState(exerciseId, setId2, 1u)
        val container = WorkoutStateContainer.ExerciseState(
            exerciseId,
            mutableListOf(set1, set2).map { ExerciseChildItem.Normal(it) }.toMutableList()
        )
        val machine = WorkoutStateMachine.fromSequence(
            listOf(WorkoutStateSequenceItem.Container(container)),
            startIndex = 0
        )
        stateMachineField.set(viewModel, machine)

        assertEquals(Pair(1, 2), viewModel.getSetCounterForExercise(exerciseId, set1))
        assertEquals(Pair(2, 2), viewModel.getSetCounterForExercise(exerciseId, set2))
    }

    @Test
    fun returnsCorrectCounterForCalibrationLoadSelection() {
        val set1 = createSetState(exerciseId, setId1, 0u)
        val set2 = createSetState(exerciseId, setId2, 1u)
        val calibrationLoad = createCalibrationLoadState()
        val set4 = createSetState(exerciseId, UUID.randomUUID(), 3u)
        val container = WorkoutStateContainer.ExerciseState(
            exerciseId,
            mutableListOf(set1, set2, calibrationLoad, set4).map { ExerciseChildItem.Normal(it) }.toMutableList()
        )
        val machine = WorkoutStateMachine.fromSequence(
            listOf(WorkoutStateSequenceItem.Container(container)),
            startIndex = 2
        )
        stateMachineField.set(viewModel, machine)

        val result = viewModel.getSetCounterForExercise(exerciseId, calibrationLoad)
        assertEquals(Pair(3, 4), result)
    }

    @Test
    fun returnsCorrectCounterForCalibrationRIRSelection() {
        val set1 = createSetState(exerciseId, setId1, 0u)
        val calibrationSet = createSetState(exerciseId, calibrationSetId, 2u)
        val calibrationRIR = createCalibrationRIRState()
        val container = WorkoutStateContainer.ExerciseState(
            exerciseId,
            mutableListOf(set1, calibrationSet, calibrationRIR).map { ExerciseChildItem.Normal(it) }.toMutableList()
        )
        val machine = WorkoutStateMachine.fromSequence(
            listOf(WorkoutStateSequenceItem.Container(container)),
            startIndex = 2
        )
        stateMachineField.set(viewModel, machine)

        val result = viewModel.getSetCounterForExercise(exerciseId, calibrationRIR)
        assertEquals(Pair(2, 2), result)
    }

    @Test
    fun returnsNullForRestState() {
        val set1 = createSetState(exerciseId, setId1, 0u)
        val rest = createRestState()
        val set2 = createSetState(exerciseId, setId2, 1u)
        val container = WorkoutStateContainer.ExerciseState(
            exerciseId,
            mutableListOf(set1, rest, set2).map { ExerciseChildItem.Normal(it) }.toMutableList()
        )
        val machine = WorkoutStateMachine.fromSequence(
            listOf(WorkoutStateSequenceItem.Container(container)),
            startIndex = 1
        )
        stateMachineField.set(viewModel, machine)

        assertNull(viewModel.getSetCounterForExercise(exerciseId, rest))
    }

    @Test
    fun unilateralTwoSetStatesCountAsOneLogicalSet() {
        val set1 = createSetState(exerciseId, setId1, 0u)
        val set2Left = createSetState(exerciseId, setId2, 1u)
        val rest = createRestState()
        val set2Right = createSetState(exerciseId, setId2, 1u)
        val container = WorkoutStateContainer.ExerciseState(
            exerciseId,
            mutableListOf(
                ExerciseChildItem.Normal(set1),
                ExerciseChildItem.UnilateralSetBlock(mutableListOf(set2Left, rest, set2Right))
            )
        )
        val machine = WorkoutStateMachine.fromSequence(
            listOf(WorkoutStateSequenceItem.Container(container)),
            startIndex = 1
        )
        stateMachineField.set(viewModel, machine)

        assertEquals(Pair(1, 2), viewModel.getSetCounterForExercise(exerciseId, set1))
        assertEquals(Pair(2, 2), viewModel.getSetCounterForExercise(exerciseId, set2Left))
        assertEquals(Pair(2, 2), viewModel.getSetCounterForExercise(exerciseId, set2Right))
    }

    @Test
    fun returnsNullWhenStateMachineIsNull() {
        stateMachineField.set(viewModel, null)
        val set1 = createSetState(exerciseId, setId1, 0u)
        assertNull(viewModel.getSetCounterForExercise(exerciseId, set1))
    }

    @Test
    fun getTotalSetCountForExerciseReturnsCorrectCount() {
        val set1 = createSetState(exerciseId, setId1, 0u)
        val calibrationLoad = createCalibrationLoadState()
        val set4 = createSetState(exerciseId, UUID.randomUUID(), 3u)
        val container = WorkoutStateContainer.ExerciseState(
            exerciseId,
            mutableListOf(set1, calibrationLoad, set4).map { ExerciseChildItem.Normal(it) }.toMutableList()
        )
        val machine = WorkoutStateMachine.fromSequence(
            listOf(WorkoutStateSequenceItem.Container(container)),
            startIndex = 0
        )
        stateMachineField.set(viewModel, machine)

        assertEquals(3, viewModel.getTotalSetCountForExercise(exerciseId))
    }

    @Test
    fun getTotalSetCountForExerciseReturnsZeroWhenStateMachineIsNull() {
        stateMachineField.set(viewModel, null)
        assertEquals(0, viewModel.getTotalSetCountForExercise(exerciseId))
    }
}
