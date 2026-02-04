package com.gabstra.myworkoutassistant.shared.viewmodels

import android.content.Context
import androidx.compose.runtime.mutableStateOf
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.coroutines.TestDispatcherProvider
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Plate
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File
import java.time.LocalDateTime
import java.util.UUID
import kotlin.math.abs

/**
 * Tests that after calibration RIR is applied, work set states get non-null plateChangeResult
 * (via [WorkoutViewModel.recalculatePlatesForExerciseFromIndex]).
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [30])
@OptIn(ExperimentalCoroutinesApi::class)
class ApplyCalibrationRIRPlateRecalculationTest {

    private lateinit var database: AppDatabase
    private lateinit var viewModel: WorkoutViewModel
    private lateinit var context: Context
    private lateinit var stateMachineField: java.lang.reflect.Field
    private val testDispatcher = StandardTestDispatcher()

    private val exerciseId = UUID.randomUUID()
    private val workSet1Id = UUID.randomUUID()
    private val workSet2Id = UUID.randomUUID()
    private val barbellId = UUID.randomUUID()
    private val barbell: Barbell = Barbell(
        id = barbellId,
        name = "Test Barbell",
        availablePlates = listOf(
            Plate(20.0, 20.0),
            Plate(10.0, 15.0),
            Plate(5.0, 10.0),
            Plate(2.5, 5.0),
            Plate(1.25, 3.0)
        ),
        sleeveLength = 200,
        barWeight = 20.0
    )

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
    fun recalculatePlatesForExerciseFromIndex_populatesPlateChangeResultForAllWorkSets() = runTest(testDispatcher) {
        val totalWeight = 60.0 // 20kg bar + 40kg plates = 20kg per side
        val workSet1 = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(workSet1Id, 8, totalWeight),
            setIndex = 1u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(WeightSetData(8, totalWeight, totalWeight * 8)),
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
            equipment = barbell,
            isUnilateral = false,
            intraSetTotal = null,
            intraSetCounter = 0u
        )
        val workSet2 = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(workSet2Id, 8, totalWeight),
            setIndex = 3u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(WeightSetData(8, totalWeight, totalWeight * 8)),
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
            equipment = barbell,
            isUnilateral = false,
            intraSetTotal = null,
            intraSetCounter = 0u
        )
        val rest1 = WorkoutState.Rest(
            set = RestSet(UUID.randomUUID(), 90),
            order = 0u,
            currentSetDataState = mutableStateOf(RestSetData(90, 90)),
            exerciseId = exerciseId,
            nextState = workSet1,
            startTime = null,
            isIntraSetRest = false
        )
        val rest2 = WorkoutState.Rest(
            set = RestSet(UUID.randomUUID(), 90),
            order = 2u,
            currentSetDataState = mutableStateOf(RestSetData(90, 90)),
            exerciseId = exerciseId,
            nextState = workSet2,
            startTime = null,
            isIntraSetRest = false
        )

        val container = WorkoutStateContainer.ExerciseState(
            exerciseId,
            mutableListOf(rest1, workSet1, rest2, workSet2)
        )
        val sequence = listOf(WorkoutStateSequenceItem.Container(container))
        val machine = WorkoutStateMachine.fromSequence(sequence, { LocalDateTime.now() }, 0)
        stateMachineField.set(viewModel, machine)

        viewModel.recalculatePlatesForExerciseFromIndex(
            exerciseId = exerciseId,
            firstWorkSetStateIndex = 1,
            weights = listOf(totalWeight, totalWeight),
            equipment = barbell
        )
        advanceUntilIdle()

        val updatedMachine = stateMachineField.get(viewModel) as? WorkoutStateMachine
        assertNotNull(updatedMachine)
        val allStates = updatedMachine!!.allStates
        val workSetStates = allStates.filterIsInstance<WorkoutState.Set>()
            .filter { it.exerciseId == exerciseId }

        assertTrue("Expected 2 work set states", workSetStates.size == 2)
        workSetStates.forEach { setState ->
            assertNotNull(
                "Work set ${setState.set.id} should have plateChangeResult after recalculation",
                setState.plateChangeResult
            )
            val result = setState.plateChangeResult!!
            val sideWeight = result.currentPlates.sum()
            val totalFromPlates = barbell.barWeight + (sideWeight * 2)
            assertTrue(
                "Plate total $totalFromPlates should be close to $totalWeight (delta ${abs(totalFromPlates - totalWeight)})",
                abs(totalFromPlates - totalWeight) < 0.01
            )
        }
    }
}
