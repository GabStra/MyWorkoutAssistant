package com.gabstra.myworkoutassistant.shared.viewmodels

import android.content.Context
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.mutableStateOf
import androidx.room.Room
import kotlinx.coroutines.flow.MutableStateFlow
import androidx.test.core.app.ApplicationProvider
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.coroutines.TestDispatcherProvider
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.ExerciseChildItem
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateMachine
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateSequenceItem
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateContainer
import com.gabstra.myworkoutassistant.shared.workout.ui.WorkoutSessionPhase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File
import java.util.UUID

/**
 * Unit tests for [WorkoutViewModel.resumeLastState], especially that when the current state
 * is Rest (after the Set matching WorkoutRecord), we stay on Rest and do not advance.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [30])
@OptIn(ExperimentalCoroutinesApi::class)
class ResumeLastStateRestTest {

    private lateinit var database: AppDatabase
    private lateinit var viewModel: WorkoutViewModel
    private lateinit var context: Context
    private lateinit var stateMachineField: java.lang.reflect.Field
    private lateinit var workoutStateField: java.lang.reflect.Field
    private lateinit var workoutRecordField: java.lang.reflect.Field
    private lateinit var sessionPhaseField: java.lang.reflect.Field
    private val testDispatcher = StandardTestDispatcher()

    private val exerciseId = UUID.randomUUID()
    private val workoutId = UUID.randomUUID()
    private val workoutHistoryId = UUID.randomUUID()
    private val setId = UUID.randomUUID()
    private val restSetId = UUID.randomUUID()

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
            equipmentId = null,
            isUnilateral = false,
            intraSetTotal = null,
            intraSetCounter = 0u,
            isCalibrationSet = false
        )
    }

    private fun createRestState(exerciseId: UUID, order: UInt): WorkoutState.Rest {
        return WorkoutState.Rest(
            set = RestSet(restSetId, 90),
            order = order,
            currentSetDataState = mutableStateOf(RestSetData(90, 90)),
            exerciseId = exerciseId,
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
            .allowMainThreadQueries()
            .build()

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
        workoutStateField = WorkoutViewModel::class.java.getDeclaredField("_workoutState")
        workoutStateField.isAccessible = true
        workoutRecordField = WorkoutViewModel::class.java.getDeclaredField("_workoutRecord\$delegate")
        workoutRecordField.isAccessible = true
        sessionPhaseField = WorkoutViewModel::class.java.getDeclaredField("_sessionPhase")
        sessionPhaseField.isAccessible = true

        viewModel.initWorkoutStoreRepository(mockWorkoutStoreRepository)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
        database.close()
    }

    @Test
    fun resumeLastState_whenCurrentStateIsRestAfterRecordSet_staysOnRest() = runTest {
        val setState = createSetState(exerciseId, setId, 0u)
        val restState = createRestState(exerciseId, 0u)
        val container = WorkoutStateContainer.ExerciseState(
            exerciseId,
            mutableListOf(
                ExerciseChildItem.Normal(setState),
                ExerciseChildItem.Normal(restState)
            ).toMutableList()
        )
        val sequence = listOf(WorkoutStateSequenceItem.Container(container))
        val machine = WorkoutStateMachine.fromSequence(sequence, startIndex = 1)
        stateMachineField.set(viewModel, machine)
        (workoutStateField.get(viewModel) as MutableStateFlow<WorkoutState>).value = restState

        val record = WorkoutRecord(
            id = UUID.randomUUID(),
            workoutId = workoutId,
            workoutHistoryId = workoutHistoryId,
            setIndex = 0u,
            exerciseId = exerciseId
        )
        (workoutRecordField.get(viewModel) as MutableState<WorkoutRecord?>).value = record
        (sessionPhaseField.get(viewModel) as MutableStateFlow<WorkoutSessionPhase>).value =
            WorkoutSessionPhase.RESUMING

        viewModel.resumeLastState()
        advanceUntilIdle()

        val machineAfter = stateMachineField.get(viewModel) as? WorkoutStateMachine
        assertNotNull(machineAfter)
        assertEquals(1, machineAfter!!.currentIndex)
        assertTrue(
            "Current state should still be Rest",
            machineAfter.currentState is WorkoutState.Rest
        )
        assertEquals(
            "A successful resume should leave the dedicated resume phase and reactivate the workout state machine.",
            WorkoutSessionPhase.ACTIVE,
            (sessionPhaseField.get(viewModel) as MutableStateFlow<WorkoutSessionPhase>).value
        )
    }

    @Test
    fun resumeLastState_whenSessionHydrationInFlight_isNoOp() = runTest {
        val hydrationTriggerField =
            WorkoutViewModel::class.java.getDeclaredField("activeSessionHydrationTrigger")
        hydrationTriggerField.isAccessible = true
        @Suppress("UNCHECKED_CAST")
        val hydrationTrigger =
            hydrationTriggerField.get(viewModel) as java.util.concurrent.atomic.AtomicReference<Any?>
        val triggerClass = Class.forName(
            "com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel\$SessionHydrationTrigger"
        )
        hydrationTrigger.set(requireNotNull(triggerClass.enumConstants).first())

        (sessionPhaseField.get(viewModel) as MutableStateFlow<WorkoutSessionPhase>).value =
            WorkoutSessionPhase.ACTIVE

        viewModel.resumeLastState()
        advanceUntilIdle()

        assertEquals(
            "resumeLastState must not regress session phase while hydration is still running.",
            WorkoutSessionPhase.ACTIVE,
            (sessionPhaseField.get(viewModel) as MutableStateFlow<WorkoutSessionPhase>).value
        )
    }

    @Test
    fun resumeLastState_whenResumingAbortsWithoutStateMachine_doesNotStayInResuming() = runTest {
        val record = WorkoutRecord(
            id = UUID.randomUUID(),
            workoutId = workoutId,
            workoutHistoryId = workoutHistoryId,
            setIndex = 0u,
            exerciseId = exerciseId
        )
        (workoutRecordField.get(viewModel) as MutableState<WorkoutRecord?>).value = record
        (sessionPhaseField.get(viewModel) as MutableStateFlow<WorkoutSessionPhase>).value =
            WorkoutSessionPhase.PREPARING

        viewModel.resumeLastState()

        assertEquals(
            "Resume should enter the dedicated RESUMING phase before asynchronous state reconstruction proceeds.",
            WorkoutSessionPhase.RESUMING,
            (sessionPhaseField.get(viewModel) as MutableStateFlow<WorkoutSessionPhase>).value
        )

        advanceUntilIdle()

        assertEquals(
            "An aborted resume should fall back to a non-loading phase instead of leaving the screen stuck on RESUMING.",
            WorkoutSessionPhase.PREPARING,
            (sessionPhaseField.get(viewModel) as MutableStateFlow<WorkoutSessionPhase>).value
        )
    }
}
