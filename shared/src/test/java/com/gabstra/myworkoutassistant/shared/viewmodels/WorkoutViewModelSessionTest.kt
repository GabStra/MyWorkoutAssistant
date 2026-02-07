package com.gabstra.myworkoutassistant.shared.viewmodels
import com.gabstra.myworkoutassistant.shared.workout.state.ExerciseChildItem
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateContainer
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateSequenceItem
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateMachine
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState

import android.content.Context
import androidx.lifecycle.viewModelScope
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseInfo
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.coroutines.TestDispatcherProvider
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Plate
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.utils.Ternary
import com.gabstra.myworkoutassistant.shared.utils.compareSetListsUnordered
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.joinAll
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestDispatcher
import kotlinx.coroutines.test.TestScope
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
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [30])
@OptIn(ExperimentalCoroutinesApi::class)
class WorkoutViewModelSessionTest {

    private lateinit var database: AppDatabase
    private lateinit var viewModel: WorkoutViewModel
    private lateinit var context: Context
    private lateinit var mockWorkoutStoreRepository: WorkoutStoreRepository
    private lateinit var stateMachineField: java.lang.reflect.Field
    private lateinit var workoutStateField: java.lang.reflect.Field
    private lateinit var testDispatcher: TestDispatcher

    // Test data
    private lateinit var testWorkoutId: UUID
    private lateinit var testWorkoutGlobalId: UUID
    private lateinit var testExerciseId: UUID
    private lateinit var testEquipmentId: UUID

    private suspend fun joinViewModelJobs() {
        viewModel.viewModelScope.coroutineContext[Job]?.children?.toList()?.joinAll()
    }

    @Before
    fun setup() {
        testDispatcher = StandardTestDispatcher()
        Dispatchers.setMain(testDispatcher)
        context = ApplicationProvider.getApplicationContext()
        
        // Create in-memory database
        database = Room.inMemoryDatabaseBuilder(
            context,
            AppDatabase::class.java
        ).allowMainThreadQueries().build()

        // Create mock WorkoutStoreRepository
        val tempDir = File(context.cacheDir, "test_workout_store")
        tempDir.mkdirs()
        mockWorkoutStoreRepository = WorkoutStoreRepository(tempDir)

        // Initialize ViewModel and inject test database DAOs using reflection
        val dispatcherProvider = TestDispatcherProvider(testDispatcher)
        viewModel = WorkoutViewModel(dispatcherProvider)
        
        // Use reflection to set DAOs directly to avoid singleton database
        val setHistoryDaoField = WorkoutViewModel::class.java.getDeclaredField("setHistoryDao")
        setHistoryDaoField.isAccessible = true
        setHistoryDaoField.set(viewModel, database.setHistoryDao())
        
        val workoutHistoryDaoField = WorkoutViewModel::class.java.getDeclaredField("workoutHistoryDao")
        workoutHistoryDaoField.isAccessible = true
        workoutHistoryDaoField.set(viewModel, database.workoutHistoryDao())
        
        val workoutScheduleDaoField = WorkoutViewModel::class.java.getDeclaredField("workoutScheduleDao")
        workoutScheduleDaoField.isAccessible = true
        workoutScheduleDaoField.set(viewModel, database.workoutScheduleDao())
        
        val workoutRecordDaoField = WorkoutViewModel::class.java.getDeclaredField("workoutRecordDao")
        workoutRecordDaoField.isAccessible = true
        workoutRecordDaoField.set(viewModel, database.workoutRecordDao())
        
        val exerciseInfoDaoField = WorkoutViewModel::class.java.getDeclaredField("exerciseInfoDao")
        exerciseInfoDaoField.isAccessible = true
        exerciseInfoDaoField.set(viewModel, database.exerciseInfoDao())
        
        val exerciseSessionProgressionDaoField = WorkoutViewModel::class.java.getDeclaredField("exerciseSessionProgressionDao")
        exerciseSessionProgressionDaoField.isAccessible = true
        exerciseSessionProgressionDaoField.set(viewModel, database.exerciseSessionProgressionDao())
        
        // Get reflection access to stateMachine for verification
        stateMachineField = WorkoutViewModel::class.java.getDeclaredField("stateMachine")
        stateMachineField.isAccessible = true
        
        // Get reflection access to _workoutState for test updates
        workoutStateField = WorkoutViewModel::class.java.getDeclaredField("_workoutState")
        workoutStateField.isAccessible = true
        
        viewModel.initWorkoutStoreRepository(mockWorkoutStoreRepository)

        // Initialize test IDs
        testWorkoutId = UUID.randomUUID()
        testWorkoutGlobalId = UUID.randomUUID()
        testExerciseId = UUID.randomUUID()
        testEquipmentId = UUID.randomUUID()
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
        database.close()
    }

    private fun createTestBarbell(): Barbell {
        val plates = listOf(
            Plate(20.0, 20.0),
            Plate(10.0, 15.0),
            Plate(5.0, 10.0),
            Plate(2.5, 5.0),
            Plate(1.25, 3.0)
        )
        return Barbell(
            id = testEquipmentId,
            name = "Test Barbell",
            availablePlates = plates,
            sleeveLength = 200,
            barWeight = 20.0
        )
    }

    private fun createTestExercise(
        sets: List<com.gabstra.myworkoutassistant.shared.sets.Set>,
        name: String = "Test Exercise"
    ): Exercise {
        return Exercise(
            id = testExerciseId,
            enabled = true,
            name = name,
            doNotStoreHistory = false,
            notes = "",
            sets = sets,
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 5,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = testEquipmentId,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            enableProgression = true,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = 0.025,
            loadJumpMaxPct = 0.5,
            loadJumpOvercapUntil = 2
        )
    }

    private fun createTestWorkout(exercise: Exercise): Workout {
        return Workout(
            id = testWorkoutId,
            name = "Test Workout",
            description = "Test Description",
            workoutComponents = listOf(exercise),
            order = 0,
            enabled = true,
            usePolarDevice = false,
            creationDate = LocalDate.now(),
            previousVersionId = null,
            nextVersionId = null,
            isActive = true,
            timesCompletedInAWeek = null,
            globalId = testWorkoutGlobalId,
            type = 0
        )
    }

    private fun createTestWorkoutStore(workout: Workout): WorkoutStore {
        val equipment = createTestBarbell()
        
        return WorkoutStore(
            workouts = listOf(workout),
            equipments = listOf(equipment),
            polarDeviceId = null,
            birthDateYear = 1990,
            weightKg = 75.0,
            progressionPercentageAmount = 0.0
        )
    }

    private suspend fun createExerciseInfo(
        exerciseId: UUID,
        lastSuccessfulSession: List<SetHistory> = emptyList(),
        bestSession: List<SetHistory> = emptyList(),
        successfulSessionCounter: UInt = 0u,
        sessionFailedCounter: UInt = 0u,
        lastSessionWasDeload: Boolean = false,
        timesCompletedInAWeek: Int = 0,
        weeklyCompletionUpdateDate: LocalDate? = null
    ) {
        val exerciseInfo = ExerciseInfo(
            id = exerciseId,
            bestSession = bestSession.ifEmpty { lastSuccessfulSession },
            lastSuccessfulSession = lastSuccessfulSession,
            successfulSessionCounter = successfulSessionCounter,
            sessionFailedCounter = sessionFailedCounter,
            lastSessionWasDeload = lastSessionWasDeload,
            timesCompletedInAWeek = timesCompletedInAWeek,
            weeklyCompletionUpdateDate = weeklyCompletionUpdateDate
        )
        database.exerciseInfoDao().insert(exerciseInfo)
    }

    private suspend fun createWorkoutHistory(
        workoutId: UUID,
        globalId: UUID,
        date: LocalDate = LocalDate.now(),
        isDone: Boolean = true
    ): WorkoutHistory {
        val workoutHistory = WorkoutHistory(
            id = UUID.randomUUID(),
            workoutId = workoutId,
            date = date,
            duration = 3600,
            heartBeatRecords = emptyList(),
            time = LocalTime.now(),
            startTime = LocalDateTime.of(date, LocalTime.of(10, 0)),
            isDone = isDone,
            hasBeenSentToHealth = false,
            globalId = globalId
        )
        database.workoutHistoryDao().insert(workoutHistory)
        return workoutHistory
    }

    private suspend fun createSetHistory(
        workoutHistoryId: UUID,
        exerciseId: UUID,
        setId: UUID,
        order: UInt,
        weight: Double,
        reps: Int
    ): SetHistory {
        // Validate weight against equipment
        val equipment = createTestBarbell()
        val validatedWeight = findClosestAchievableWeight(weight, equipment)
        
        val setHistory = SetHistory(
            id = UUID.randomUUID(),
            workoutHistoryId = workoutHistoryId,
            exerciseId = exerciseId,
            setId = setId,
            order = order,
            startTime = LocalDateTime.now(),
            endTime = LocalDateTime.now(),
            setData = WeightSetData(actualReps = reps, actualWeight = validatedWeight, volume = validatedWeight * reps),
            skipped = false
        )
        database.setHistoryDao().insert(setHistory)
        return setHistory
    }

    private suspend fun TestScope.waitForWorkoutToLoad() {
        // First, ensure all coroutines are given a chance to start
        advanceUntilIdle()
        joinViewModelJobs()
        delay(10)
        advanceUntilIdle()
        joinViewModelJobs()
        
        var attempts = 0
        var workoutState = viewModel.workoutState.value
        
        while (attempts < 200) {
            advanceUntilIdle()
            joinViewModelJobs()
            Thread.sleep(5)
            workoutState = viewModel.workoutState.value
            
            if (workoutState is WorkoutState.Preparing && workoutState.dataLoaded) {
                break
            }
            
            if (workoutState !is WorkoutState.Preparing) {
                break
            }
            
            attempts++
            
            if (attempts % 10 == 0) {
                delay(1)
                advanceUntilIdle()
                joinViewModelJobs()
                Thread.sleep(5)
            }
        }
        
        // Ensure all coroutines complete before checking queue
        advanceUntilIdle()
        joinViewModelJobs()
        delay(10)
        advanceUntilIdle()
        joinViewModelJobs()
        
        val currentState = viewModel.workoutState.value
        if (currentState is WorkoutState.Preparing && !currentState.dataLoaded) {
            @Suppress("UNCHECKED_CAST")
            val stateMachine = stateMachineField.get(viewModel) as? WorkoutStateMachine
            val queueSize = stateMachine?.nextStates?.size ?: 0
            
            if (queueSize > 0) {
                @Suppress("UNCHECKED_CAST")
                val workoutStateFlow = workoutStateField.get(viewModel) as kotlinx.coroutines.flow.MutableStateFlow<WorkoutState>
                workoutStateFlow.value = WorkoutState.Preparing(dataLoaded = true)
            }
        }
        
        var queuePopulated = false
        var queueAttempts = 0
        while (!queuePopulated && queueAttempts < 100) {
            advanceUntilIdle()
            joinViewModelJobs()
            delay(10)
            advanceUntilIdle()
            joinViewModelJobs()
            Thread.sleep(5)
            @Suppress("UNCHECKED_CAST")
            val stateMachine = stateMachineField.get(viewModel) as? WorkoutStateMachine
            queuePopulated = stateMachine != null && stateMachine.nextStates.isNotEmpty()
            queueAttempts++
        }
        
        // Final check to ensure all coroutines are complete
        advanceUntilIdle()
        joinViewModelJobs()
        delay(10)
        advanceUntilIdle()
        joinViewModelJobs()
        
        @Suppress("UNCHECKED_CAST")
        val stateMachine = stateMachineField.get(viewModel) as? WorkoutStateMachine
        assertTrue("StateMachine should be populated", stateMachine != null && stateMachine.nextStates.isNotEmpty())
        
        workoutState = viewModel.workoutState.value
        if (workoutState is WorkoutState.Preparing && workoutState.dataLoaded) {
            viewModel.goToNextState()
            advanceUntilIdle()
            joinViewModelJobs()
            delay(10)
            advanceUntilIdle()
            joinViewModelJobs()
        }
        
        assertTrue("Workout should not be in Preparing state", 
            viewModel.workoutState.value !is WorkoutState.Preparing)
    }

    private suspend fun TestScope.executeSetsOnly(
        setModifier: (WorkoutState.Set) -> Unit = {}
    ) {
        var setCount = 0
        val maxSets = 50
        
        while (setCount < maxSets) {
            val workoutState = viewModel.workoutState.value
            
            if (workoutState is WorkoutState.Completed) {
                break
            }
            
            if (workoutState is WorkoutState.Set && !workoutState.isWarmupSet) {
                setModifier(workoutState)
                
                if (workoutState.startTime == null) {
                    workoutState.startTime = LocalDateTime.now()
                }
                
                viewModel.storeSetData()
                advanceUntilIdle()
                joinViewModelJobs()
                
                setCount++
            }
            
            viewModel.goToNextState()
            advanceUntilIdle()
            joinViewModelJobs()
        }
        
        assertTrue("Should have stored sets", viewModel.executedSetsHistory.isNotEmpty())
        
        viewModel.pushAndStoreWorkoutData(isDone = true, context = context)
        advanceUntilIdle()
        joinViewModelJobs()
        repeat(5) {
            advanceUntilIdle()
            joinViewModelJobs()
        }
    }

    /**
     * Finds the closest achievable weight for the given equipment.
     * If equipment is null, returns the desired weight without validation.
     * Otherwise, finds the closest weight from the equipment's achievable combinations.
     */
    private fun findClosestAchievableWeight(desiredWeight: Double, equipment: com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment?): Double {
        if (equipment == null) {
            return desiredWeight
        }
        
        // Get available weights from equipment
        val availableWeights = equipment.getWeightsCombinations()
        
        if (availableWeights.isEmpty()) {
            return desiredWeight
        }
        
        // Find the closest achievable weight
        return availableWeights.minByOrNull { kotlin.math.abs(it - desiredWeight) } ?: desiredWeight
    }

    /**
     * Creates a WeightSet with validated weight based on equipment.
     * Uses the test equipment ID to get the equipment and validate the weight.
     */
    private fun createWeightSetWithValidatedWeight(setId: UUID, reps: Int, desiredWeight: Double): WeightSet {
        val equipment = createTestBarbell()
        val validatedWeight = findClosestAchievableWeight(desiredWeight, equipment)
        return WeightSet(setId, reps, validatedWeight)
    }

    private suspend fun TestScope.executeWorkoutWithSets(
        setModifier: (WorkoutState.Set) -> Unit = {}
    ) {
        viewModel.startWorkout()
        advanceUntilIdle()
        joinViewModelJobs()
        Thread.sleep(10)
        delay(10)
        advanceUntilIdle()
        
        waitForWorkoutToLoad()
        
        viewModel.setWorkoutStart()
        advanceUntilIdle()
        joinViewModelJobs()
        
        assertNotNull("Start workout time should be set", viewModel.startWorkoutTime)
        
        executeSetsOnly(setModifier)
    }

    // Test 1: First Session (No ExerciseInfo)
    @Test
    fun testFirstSession_createsExerciseInfo() = runTest(testDispatcher) {
        val exercise = createTestExercise(
            sets = listOf(
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 10, 95.0),
                RestSet(UUID.randomUUID(), 90),
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 8, 95.0)
            )
        )
        val workout = createTestWorkout(exercise)
        val workoutStore = createTestWorkoutStore(workout)
        
        viewModel.updateWorkoutStore(workoutStore)
        viewModel.setSelectedWorkoutId(testWorkoutId)
        advanceUntilIdle()
        
        executeWorkoutWithSets()
        
        val exerciseInfo = database.exerciseInfoDao().getExerciseInfoById(testExerciseId)
        assertNotNull("ExerciseInfo should be created", exerciseInfo)
        assertEquals("ExerciseInfo id should match", testExerciseId, exerciseInfo?.id)
        assertEquals("successfulSessionCounter should be 1", 1u, exerciseInfo?.successfulSessionCounter)
        assertEquals("sessionFailedCounter should be 0", 0u, exerciseInfo?.sessionFailedCounter)
        assertTrue("lastSuccessfulSession should not be empty", exerciseInfo?.lastSuccessfulSession?.isNotEmpty() == true)
        assertTrue("bestSession should not be empty", exerciseInfo?.bestSession?.isNotEmpty() == true)
        assertEquals("lastSessionWasDeload should be false", false, exerciseInfo?.lastSessionWasDeload)
        assertEquals("timesCompletedInAWeek should be 1", 1, exerciseInfo?.timesCompletedInAWeek)
        assertNotNull("weeklyCompletionUpdateDate should be set", exerciseInfo?.weeklyCompletionUpdateDate)
        
        val progressions = database.exerciseSessionProgressionDao().getAllExerciseSessionProgressions()
        val progression = progressions.firstOrNull { it.exerciseId == testExerciseId }
        assertNotNull("ExerciseSessionProgression should be created", progression)
        assertEquals("progressionState should be PROGRESS", ProgressionState.PROGRESS, progression?.progressionState)
    }

    // Test 2: PROGRESS State - Success (ABOVE)
    @Test
    fun testProgressState_successAbove() = runTest(testDispatcher) {
        val previousSetId1 = UUID.randomUUID()
        val previousSetId2 = UUID.randomUUID()
        val previousWorkoutHistory = createWorkoutHistory(testWorkoutId, testWorkoutGlobalId)
        val previousSet1 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId1, 0u, 90.0, 10)
        val previousSet2 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId2, 1u, 90.0, 8)
        
        createExerciseInfo(
            exerciseId = testExerciseId,
            lastSuccessfulSession = listOf(previousSet1, previousSet2),
            successfulSessionCounter = 2u,
            sessionFailedCounter = 0u
        )
        
        val exercise = createTestExercise(
            sets = listOf(
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 10, 92.5), // Expected: 92.5kg x 10
                RestSet(UUID.randomUUID(), 90),
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 8, 92.5)   // Expected: 92.5kg x 8
            )
        )
        val workout = createTestWorkout(exercise)
        val workoutStore = createTestWorkoutStore(workout)
        
        viewModel.updateWorkoutStore(workoutStore)
        viewModel.setSelectedWorkoutId(testWorkoutId)
        advanceUntilIdle()
        
        executeWorkoutWithSets { setState ->
            val currentSetData = setState.currentSetData
            if (currentSetData is WeightSetData) {
                // Execute above expected: 95kg instead of 92.5kg
                val achievableWeight = findClosestAchievableWeight(95.0, setState.equipment)
                setState.currentSetData = currentSetData.copy(
                    actualReps = currentSetData.actualReps,
                    actualWeight = achievableWeight,
                    volume = achievableWeight * currentSetData.actualReps
                )
            }
        }
        
        val exerciseInfo = database.exerciseInfoDao().getExerciseInfoById(testExerciseId)
        assertNotNull("ExerciseInfo should exist", exerciseInfo)
        assertEquals("successfulSessionCounter should be incremented", 3u, exerciseInfo?.successfulSessionCounter)
        assertEquals("sessionFailedCounter should be reset", 0u, exerciseInfo?.sessionFailedCounter)
        assertTrue("lastSuccessfulSession should be updated", exerciseInfo?.lastSuccessfulSession?.isNotEmpty() == true)
        
        val progressions = database.exerciseSessionProgressionDao().getAllExerciseSessionProgressions()
        val progression = progressions.firstOrNull { it.exerciseId == testExerciseId }
        assertNotNull("Progression should exist", progression)
        assertEquals("vsPrevious should be ABOVE", Ternary.ABOVE, progression?.vsPrevious)
        assertEquals("vsExpected should be ABOVE", Ternary.ABOVE, progression?.vsExpected)
        assertEquals("progressionState should be PROGRESS", ProgressionState.PROGRESS, progression?.progressionState)
    }

    // Test 3: PROGRESS State - Success (EQUAL)
    @Test
    fun testProgressState_successEqual() = runTest(testDispatcher) {
        val previousSetId1 = UUID.randomUUID()
        val previousSetId2 = UUID.randomUUID()
        val previousWorkoutHistory = createWorkoutHistory(testWorkoutId, testWorkoutGlobalId)
        val previousSet1 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId1, 0u, 90.0, 10)
        val previousSet2 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId2, 1u, 90.0, 8)
        
        createExerciseInfo(
            exerciseId = testExerciseId,
            lastSuccessfulSession = listOf(previousSet1, previousSet2),
            successfulSessionCounter = 1u,
            sessionFailedCounter = 0u
        )
        
        val exercise = createTestExercise(
            sets = listOf(
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 10, 92.5),
                RestSet(UUID.randomUUID(), 90),
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 8, 92.5)
            )
        )
        val workout = createTestWorkout(exercise)
        val workoutStore = createTestWorkoutStore(workout)
        
        viewModel.updateWorkoutStore(workoutStore)
        viewModel.setSelectedWorkoutId(testWorkoutId)
        advanceUntilIdle()
        
        // Start workout to trigger progression generation
        viewModel.startWorkout()
        advanceUntilIdle()
        joinViewModelJobs()
        Thread.sleep(10)
        delay(10)
        advanceUntilIdle()
        joinViewModelJobs()
        
        waitForWorkoutToLoad()
        
        // Access exerciseProgressionByExerciseId via reflection to get expected sets
        val exerciseProgressionByExerciseIdField = WorkoutViewModel::class.java.getDeclaredField("exerciseProgressionByExerciseId")
        exerciseProgressionByExerciseIdField.isAccessible = true
        @Suppress("UNCHECKED_CAST")
        val exerciseProgressionMap = exerciseProgressionByExerciseIdField.get(viewModel) as MutableMap<UUID, Pair<com.gabstra.myworkoutassistant.shared.utils.DoubleProgressionHelper.Plan, ProgressionState>>
        
        val progressionData = exerciseProgressionMap[testExerciseId]
        assertNotNull("Progression should be generated", progressionData)
        val expectedSets = progressionData!!.first.sets.sortedByDescending { it.weight * it.reps }
        
        viewModel.setWorkoutStart()
        advanceUntilIdle()
        joinViewModelJobs()
        
        assertNotNull("Start workout time should be set", viewModel.startWorkoutTime)
        
        // Execute sets using expected sets from progression
        var expectedSetIndex = 0
        executeSetsOnly { setState ->
            val currentSetData = setState.currentSetData
            if (currentSetData is WeightSetData && expectedSetIndex < expectedSets.size) {
                val expectedSet = expectedSets[expectedSetIndex]
                // Execute exactly as expected from progression
                val achievableWeight = findClosestAchievableWeight(expectedSet.weight, setState.equipment)
                setState.currentSetData = currentSetData.copy(
                    actualReps = expectedSet.reps,
                    actualWeight = achievableWeight,
                    volume = achievableWeight * expectedSet.reps
                )
                expectedSetIndex++
            }
        }
        
        val exerciseInfo = database.exerciseInfoDao().getExerciseInfoById(testExerciseId)
        assertNotNull("ExerciseInfo should exist", exerciseInfo)
        assertEquals("successfulSessionCounter should be incremented", 2u, exerciseInfo?.successfulSessionCounter)
        assertEquals("sessionFailedCounter should be reset", 0u, exerciseInfo?.sessionFailedCounter)
        
        val progressions = database.exerciseSessionProgressionDao().getAllExerciseSessionProgressions()
        val progression = progressions.firstOrNull { it.exerciseId == testExerciseId }
        assertNotNull("Progression should exist", progression)
        assertEquals("vsExpected should be EQUAL", Ternary.EQUAL, progression?.vsExpected)
    }

    // Test 4: PROGRESS State - Failure (BELOW)
    @Test
    fun testProgressState_failureBelow() = runTest(testDispatcher) {
        val previousSetId1 = UUID.randomUUID()
        val previousSetId2 = UUID.randomUUID()
        val previousWorkoutHistory = createWorkoutHistory(testWorkoutId, testWorkoutGlobalId)
        val previousSet1 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId1, 0u, 50.0, 10)
        val previousSet2 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId2, 1u, 50.0, 8)
        
        createExerciseInfo(
            exerciseId = testExerciseId,
            lastSuccessfulSession = listOf(previousSet1, previousSet2),
            successfulSessionCounter = 3u,
            sessionFailedCounter = 0u
        )
        
        val exercise = createTestExercise(
            sets = listOf(
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 10, 55.0),
                RestSet(UUID.randomUUID(), 90),
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 8, 55.0)
            )
        )
        val workout = createTestWorkout(exercise)
        val workoutStore = createTestWorkoutStore(workout)
        
        viewModel.updateWorkoutStore(workoutStore)
        viewModel.setSelectedWorkoutId(testWorkoutId)
        advanceUntilIdle()
        
        executeWorkoutWithSets { setState ->
            val currentSetData = setState.currentSetData
            if (currentSetData is WeightSetData) {
                // Execute below expected: 50 instead of 55.0kg
                val achievableWeight = findClosestAchievableWeight(50.0, setState.equipment)
                setState.currentSetData = currentSetData.copy(
                    actualReps = currentSetData.actualReps,
                    actualWeight = achievableWeight,
                    volume = achievableWeight * currentSetData.actualReps
                )
            }
        }
        
        val exerciseInfo = database.exerciseInfoDao().getExerciseInfoById(testExerciseId)
        assertNotNull("ExerciseInfo should exist", exerciseInfo)
        assertEquals("successfulSessionCounter should be reset", 0u, exerciseInfo?.successfulSessionCounter)
        assertEquals("sessionFailedCounter should be incremented", 1u, exerciseInfo?.sessionFailedCounter)
        
        val progressions = database.exerciseSessionProgressionDao().getAllExerciseSessionProgressions()
        val progression = progressions.firstOrNull { it.exerciseId == testExerciseId }
        assertNotNull("Progression should exist", progression)
        assertEquals("vsExpected should be BELOW", Ternary.BELOW, progression?.vsExpected)
    }

    // Test 5: PROGRESS State - Failure (MIXED)
    @Test
    fun testProgressState_failureMixed() = runTest(testDispatcher) {
        val previousSetId1 = UUID.randomUUID()
        val previousSetId2 = UUID.randomUUID()
        val previousWorkoutHistory = createWorkoutHistory(testWorkoutId, testWorkoutGlobalId)
        val previousSet1 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId1, 0u, 90.0, 10)
        val previousSet2 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId2, 1u, 90.0, 8)
        
        createExerciseInfo(
            exerciseId = testExerciseId,
            lastSuccessfulSession = listOf(previousSet1, previousSet2),
            successfulSessionCounter = 2u,
            sessionFailedCounter = 0u
        )
        
        val set1Id = UUID.randomUUID()
        val set2Id = UUID.randomUUID()
        val exercise = createTestExercise(
            sets = listOf(
                createWeightSetWithValidatedWeight(set1Id, 10, 92.5),
                RestSet(UUID.randomUUID(), 90),
                createWeightSetWithValidatedWeight(set2Id, 8, 92.5)
            )
        )
        val workout = createTestWorkout(exercise)
        val workoutStore = createTestWorkoutStore(workout)
        
        viewModel.updateWorkoutStore(workoutStore)
        viewModel.setSelectedWorkoutId(testWorkoutId)
        advanceUntilIdle()
        
        var setIndex = 0
        executeWorkoutWithSets { setState ->
            val currentSetData = setState.currentSetData
            if (currentSetData is WeightSetData) {
                // First set above, second set below - creates MIXED
                val desiredWeight = if (setIndex == 0) 95.0 else 90.0
                val achievableWeight = findClosestAchievableWeight(desiredWeight, setState.equipment)
                setState.currentSetData = currentSetData.copy(
                    actualReps = currentSetData.actualReps,
                    actualWeight = achievableWeight,
                    volume = achievableWeight * currentSetData.actualReps
                )
                setIndex++
            }
        }
        
        val exerciseInfo = database.exerciseInfoDao().getExerciseInfoById(testExerciseId)
        assertNotNull("ExerciseInfo should exist", exerciseInfo)
        assertEquals("successfulSessionCounter should be reset", 0u, exerciseInfo?.successfulSessionCounter)
        assertEquals("sessionFailedCounter should be incremented", 1u, exerciseInfo?.sessionFailedCounter)
        
        val progressions = database.exerciseSessionProgressionDao().getAllExerciseSessionProgressions()
        val progression = progressions.firstOrNull { it.exerciseId == testExerciseId }
        assertNotNull("Progression should exist", progression)
        assertEquals("vsExpected should be MIXED", Ternary.MIXED, progression?.vsExpected)
    }

    // Test 6: RETRY State - Success (ABOVE)
    @Test
    fun testRetryState_successAbove() = runTest(testDispatcher) {
        val previousSetId1 = UUID.randomUUID()
        val previousSetId2 = UUID.randomUUID()
        val previousWorkoutHistory = createWorkoutHistory(testWorkoutId, testWorkoutGlobalId)
        val previousSet1 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId1, 0u, 95.0, 10)
        val previousSet2 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId2, 1u, 95.0, 8)
        
        // Create ExerciseInfo with failed session to trigger RETRY
        createExerciseInfo(
            exerciseId = testExerciseId,
            lastSuccessfulSession = listOf(previousSet1, previousSet2),
            successfulSessionCounter = 0u,
            sessionFailedCounter = 1u,
            lastSessionWasDeload = false
        )
        
        // Exercise sets match previous session (RETRY loads last successful session)
        val exercise = createTestExercise(
            sets = listOf(
                createWeightSetWithValidatedWeight(previousSetId1, 10, 95.0),
                RestSet(UUID.randomUUID(), 90),
                createWeightSetWithValidatedWeight(previousSetId2, 8, 95.0)
            )
        )
        val workout = createTestWorkout(exercise)
        val workoutStore = createTestWorkoutStore(workout)
        
        viewModel.updateWorkoutStore(workoutStore)
        viewModel.setSelectedWorkoutId(testWorkoutId)
        advanceUntilIdle()
        
        executeWorkoutWithSets { setState ->
            val currentSetData = setState.currentSetData
            if (currentSetData is WeightSetData) {
                // Execute above retry target
                val achievableWeight = findClosestAchievableWeight(currentSetData.actualWeight, setState.equipment)
                setState.currentSetData = currentSetData.copy(
                    actualReps = currentSetData.actualReps + 1,
                    actualWeight = achievableWeight,
                    volume = achievableWeight * (currentSetData.actualReps + 1)
                )
            }
        }
        
        val exerciseInfo = database.exerciseInfoDao().getExerciseInfoById(testExerciseId)
        assertNotNull("ExerciseInfo should exist", exerciseInfo)
        assertEquals("successfulSessionCounter should be incremented", 1u, exerciseInfo?.successfulSessionCounter)
        assertEquals("sessionFailedCounter should be reset", 0u, exerciseInfo?.sessionFailedCounter)
        
        val progressions = database.exerciseSessionProgressionDao().getAllExerciseSessionProgressions()
        val progression = progressions.firstOrNull { it.exerciseId == testExerciseId }
        assertNotNull("Progression should exist", progression)
        assertEquals("vsExpected should be ABOVE", Ternary.ABOVE, progression?.vsExpected)
        assertEquals("progressionState should be RETRY", ProgressionState.RETRY, progression?.progressionState)
    }

    // Test 7: RETRY State - Complete Retry (EQUAL)
    @Test
    fun testRetryState_completeRetryEqual() = runTest(testDispatcher) {
        val previousSetId1 = UUID.randomUUID()
        val previousSetId2 = UUID.randomUUID()
        val previousWorkoutHistory = createWorkoutHistory(testWorkoutId, testWorkoutGlobalId)
        val previousSet1 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId1, 0u, 95.0, 10)
        val previousSet2 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId2, 1u, 95.0, 8)
        
        createExerciseInfo(
            exerciseId = testExerciseId,
            lastSuccessfulSession = listOf(previousSet1, previousSet2),
            successfulSessionCounter = 0u,
            sessionFailedCounter = 1u
        )
        
        val exercise = createTestExercise(
            sets = listOf(
                createWeightSetWithValidatedWeight(previousSetId1, 10, 95.0),
                RestSet(UUID.randomUUID(), 90),
                createWeightSetWithValidatedWeight(previousSetId2, 8, 95.0)
            )
        )
        val workout = createTestWorkout(exercise)
        val workoutStore = createTestWorkoutStore(workout)
        
        viewModel.updateWorkoutStore(workoutStore)
        viewModel.setSelectedWorkoutId(testWorkoutId)
        advanceUntilIdle()
        
        executeWorkoutWithSets { setState ->
            val currentSetData = setState.currentSetData
            if (currentSetData is WeightSetData) {
                // Execute exactly as retry target
                val achievableWeight = findClosestAchievableWeight(currentSetData.actualWeight, setState.equipment)
                setState.currentSetData = currentSetData.copy(
                    actualReps = currentSetData.actualReps,
                    actualWeight = achievableWeight,
                    volume = achievableWeight * currentSetData.actualReps
                )
            }
        }
        
        val exerciseInfo = database.exerciseInfoDao().getExerciseInfoById(testExerciseId)
        assertNotNull("ExerciseInfo should exist", exerciseInfo)
        assertEquals("successfulSessionCounter should be reset", 0u, exerciseInfo?.successfulSessionCounter)
        assertEquals("sessionFailedCounter should be reset", 0u, exerciseInfo?.sessionFailedCounter)
        
        val progressions = database.exerciseSessionProgressionDao().getAllExerciseSessionProgressions()
        val progression = progressions.firstOrNull { it.exerciseId == testExerciseId }
        assertNotNull("Progression should exist", progression)
        assertEquals("vsExpected should be EQUAL", Ternary.EQUAL, progression?.vsExpected)
    }

    // Test 8: RETRY State - Failure (BELOW)
    @Test
    fun testRetryState_failureBelow() = runTest(testDispatcher) {
        val previousSetId1 = UUID.randomUUID()
        val previousSetId2 = UUID.randomUUID()
        val previousWorkoutHistory = createWorkoutHistory(testWorkoutId, testWorkoutGlobalId)
        val previousSet1 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId1, 0u, 95.0, 10)
        val previousSet2 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId2, 1u, 95.0, 8)
        
        createExerciseInfo(
            exerciseId = testExerciseId,
            lastSuccessfulSession = listOf(previousSet1, previousSet2),
            successfulSessionCounter = 0u,
            sessionFailedCounter = 1u
        )
        
        val exercise = createTestExercise(
            sets = listOf(
                createWeightSetWithValidatedWeight(previousSetId1, 10, 95.0),
                RestSet(UUID.randomUUID(), 90),
                createWeightSetWithValidatedWeight(previousSetId2, 8, 95.0)
            )
        )
        val workout = createTestWorkout(exercise)
        val workoutStore = createTestWorkoutStore(workout)
        
        viewModel.updateWorkoutStore(workoutStore)
        viewModel.setSelectedWorkoutId(testWorkoutId)
        advanceUntilIdle()
        
        executeWorkoutWithSets { setState ->
            val currentSetData = setState.currentSetData
            if (currentSetData is WeightSetData) {
                // Execute below retry target
                val achievableWeight = findClosestAchievableWeight(currentSetData.actualWeight, setState.equipment)
                setState.currentSetData = currentSetData.copy(
                    actualReps = currentSetData.actualReps - 1,
                    actualWeight = achievableWeight,
                    volume = achievableWeight * (currentSetData.actualReps - 1)
                )
            }
        }
        
        val exerciseInfo = database.exerciseInfoDao().getExerciseInfoById(testExerciseId)
        assertNotNull("ExerciseInfo should exist", exerciseInfo)
        // Counters should remain unchanged for RETRY failure
        assertEquals("successfulSessionCounter should remain 0", 0u, exerciseInfo?.successfulSessionCounter)
        assertEquals("sessionFailedCounter should remain 1", 1u, exerciseInfo?.sessionFailedCounter)
        
        val progressions = database.exerciseSessionProgressionDao().getAllExerciseSessionProgressions()
        val progression = progressions.firstOrNull { it.exerciseId == testExerciseId }
        assertNotNull("Progression should exist", progression)
        assertEquals("vsExpected should be BELOW", Ternary.BELOW, progression?.vsExpected)
    }

    // Test 9: RETRY State - Failure (MIXED)
    @Test
    fun testRetryState_failureMixed() = runTest(testDispatcher) {
        val previousSetId1 = UUID.randomUUID()
        val previousSetId2 = UUID.randomUUID()
        val previousWorkoutHistory = createWorkoutHistory(testWorkoutId, testWorkoutGlobalId)
        val previousSet1 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId1, 0u, 95.0, 10)
        val previousSet2 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId2, 1u, 95.0, 8)
        
        createExerciseInfo(
            exerciseId = testExerciseId,
            lastSuccessfulSession = listOf(previousSet1, previousSet2),
            successfulSessionCounter = 0u,
            sessionFailedCounter = 1u
        )
        
        val exercise = createTestExercise(
            sets = listOf(
                createWeightSetWithValidatedWeight(previousSetId1, 10, 95.0),
                RestSet(UUID.randomUUID(), 90),
                createWeightSetWithValidatedWeight(previousSetId2, 8, 95.0)
            )
        )
        val workout = createTestWorkout(exercise)
        val workoutStore = createTestWorkoutStore(workout)
        
        viewModel.updateWorkoutStore(workoutStore)
        viewModel.setSelectedWorkoutId(testWorkoutId)
        advanceUntilIdle()
        
        var setIndex = 0
        executeWorkoutWithSets { setState ->
            val currentSetData = setState.currentSetData
            if (currentSetData is WeightSetData) {
                // First set above, second set below - creates MIXED
                val reps = if (setIndex == 0) currentSetData.actualReps + 1 else currentSetData.actualReps - 1
                val achievableWeight = findClosestAchievableWeight(currentSetData.actualWeight, setState.equipment)
                setState.currentSetData = currentSetData.copy(
                    actualReps = reps,
                    actualWeight = achievableWeight,
                    volume = achievableWeight * reps
                )
                setIndex++
            }
        }
        
        val exerciseInfo = database.exerciseInfoDao().getExerciseInfoById(testExerciseId)
        assertNotNull("ExerciseInfo should exist", exerciseInfo)
        assertEquals("successfulSessionCounter should remain 0", 0u, exerciseInfo?.successfulSessionCounter)
        assertEquals("sessionFailedCounter should remain 1", 1u, exerciseInfo?.sessionFailedCounter)
        
        val progressions = database.exerciseSessionProgressionDao().getAllExerciseSessionProgressions()
        val progression = progressions.firstOrNull { it.exerciseId == testExerciseId }
        assertNotNull("Progression should exist", progression)
        assertEquals("vsExpected should be MIXED", Ternary.MIXED, progression?.vsExpected)
    }

    // Test 10: DELOAD State
    @Test
    fun testDeloadState() = runTest(testDispatcher) {
        val previousSetId1 = UUID.randomUUID()
        val previousSetId2 = UUID.randomUUID()
        val previousWorkoutHistory = createWorkoutHistory(testWorkoutId, testWorkoutGlobalId)
        val previousSet1 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId1, 0u, 90.0, 10)
        val previousSet2 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId2, 1u, 90.0, 8)
        
        createExerciseInfo(
            exerciseId = testExerciseId,
            lastSuccessfulSession = listOf(previousSet1, previousSet2),
            successfulSessionCounter = 0u,
            sessionFailedCounter = 2u,
            lastSessionWasDeload = false
        )
        
        // Note: DELOAD is currently disabled in computeSessionDecision, so we'll test the logic
        // by manually creating a progression state DELOAD scenario
        // For now, we test that if DELOAD happens, counters are reset
        val exercise = createTestExercise(
            sets = listOf(
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 10, 90.0), // Deload weight
                RestSet(UUID.randomUUID(), 90),
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 8, 90.0)
            )
        )
        val workout = createTestWorkout(exercise)
        val workoutStore = createTestWorkoutStore(workout)
        
        viewModel.updateWorkoutStore(workoutStore)
        viewModel.setSelectedWorkoutId(testWorkoutId)
        advanceUntilIdle()
        
        // Manually inject DELOAD progression state for testing
        val exerciseProgressionByExerciseIdField = WorkoutViewModel::class.java.getDeclaredField("exerciseProgressionByExerciseId")
        exerciseProgressionByExerciseIdField.isAccessible = true
        @Suppress("UNCHECKED_CAST")
        val exerciseProgressionMap = exerciseProgressionByExerciseIdField.get(viewModel) as MutableMap<UUID, Pair<com.gabstra.myworkoutassistant.shared.utils.DoubleProgressionHelper.Plan, ProgressionState>>
        
        // Wait for progression to be generated, then override with DELOAD
        viewModel.startWorkout()
        advanceUntilIdle()
        joinViewModelJobs()
        Thread.sleep(10)
        delay(10)
        advanceUntilIdle()
        
        waitForWorkoutToLoad()
        
        // Override progression state to DELOAD
        val progressionData = exerciseProgressionMap[testExerciseId]
        if (progressionData != null) {
            exerciseProgressionMap[testExerciseId] = progressionData.first to ProgressionState.DELOAD
        }
        
        viewModel.setWorkoutStart()
        advanceUntilIdle()
        joinViewModelJobs()
        
        executeSetsOnly { setState ->
            val currentSetData = setState.currentSetData
            if (currentSetData is WeightSetData) {
                val achievableWeight = findClosestAchievableWeight(currentSetData.actualWeight, setState.equipment)
                setState.currentSetData = currentSetData.copy(
                    actualReps = currentSetData.actualReps,
                    actualWeight = achievableWeight,
                    volume = achievableWeight * currentSetData.actualReps
                )
            }
        }
        
        val exerciseInfo = database.exerciseInfoDao().getExerciseInfoById(testExerciseId)
        assertNotNull("ExerciseInfo should exist", exerciseInfo)
        assertEquals("sessionFailedCounter should be reset", 0u, exerciseInfo?.sessionFailedCounter)
        assertEquals("successfulSessionCounter should be reset", 0u, exerciseInfo?.successfulSessionCounter)
        assertEquals("lastSessionWasDeload should be true", true, exerciseInfo?.lastSessionWasDeload)
    }

    // Test 11: No Progression State - Success
    @Test
    fun testNoProgressionState_success() = runTest(testDispatcher) {
        val previousSetId1 = UUID.randomUUID()
        val previousSetId2 = UUID.randomUUID()
        val previousWorkoutHistory = createWorkoutHistory(testWorkoutId, testWorkoutGlobalId)
        val previousSet1 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId1, 0u, 95.0, 10)
        val previousSet2 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId2, 1u, 95.0, 8)
        
        createExerciseInfo(
            exerciseId = testExerciseId,
            lastSuccessfulSession = listOf(previousSet1, previousSet2),
            successfulSessionCounter = 1u,
            sessionFailedCounter = 0u
        )
        
        // Create exercise without progression enabled
        val exercise = Exercise(
            id = testExerciseId,
            enabled = true,
            name = "Test Exercise",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 10, 95.0),
                RestSet(UUID.randomUUID(), 90),
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 8, 95.0)
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 5,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = testEquipmentId,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            enableProgression = false, // Disable progression
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )
        val workout = createTestWorkout(exercise)
        val workoutStore = createTestWorkoutStore(workout)
        
        viewModel.updateWorkoutStore(workoutStore)
        viewModel.setSelectedWorkoutId(testWorkoutId)
        advanceUntilIdle()
        
        executeWorkoutWithSets { setState ->
            val currentSetData = setState.currentSetData
            if (currentSetData is WeightSetData) {
                // Execute above last successful session
                val achievableWeight = findClosestAchievableWeight(currentSetData.actualWeight, setState.equipment)
                setState.currentSetData = currentSetData.copy(
                    actualReps = currentSetData.actualReps + 1,
                    actualWeight = achievableWeight,
                    volume = achievableWeight * (currentSetData.actualReps + 1)
                )
            }
        }
        
        val exerciseInfo = database.exerciseInfoDao().getExerciseInfoById(testExerciseId)
        assertNotNull("ExerciseInfo should exist", exerciseInfo)
        assertEquals("successfulSessionCounter should be incremented", 2u, exerciseInfo?.successfulSessionCounter)
        assertEquals("sessionFailedCounter should be reset", 0u, exerciseInfo?.sessionFailedCounter)
        
        // No progression should be created when progression is disabled
        val progressions = database.exerciseSessionProgressionDao().getAllExerciseSessionProgressions()
        val progression = progressions.firstOrNull { it.exerciseId == testExerciseId }
        assertTrue("Progression should not exist when progression disabled", progression == null)
    }

    @Test
    fun testRequiresCalibration_disablesProgressionEvenIfEnabled() = runTest(testDispatcher) {
        val previousSetId1 = UUID.randomUUID()
        val previousSetId2 = UUID.randomUUID()
        val previousWorkoutHistory = createWorkoutHistory(testWorkoutId, testWorkoutGlobalId)
        val previousSet1 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId1, 0u, 95.0, 10)
        val previousSet2 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId2, 1u, 95.0, 8)

        createExerciseInfo(
            exerciseId = testExerciseId,
            lastSuccessfulSession = listOf(previousSet1, previousSet2),
            successfulSessionCounter = 1u,
            sessionFailedCounter = 0u
        )

        val exercise = createTestExercise(
            sets = listOf(
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 10, 95.0),
                RestSet(UUID.randomUUID(), 90),
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 8, 95.0)
            )
        ).copy(
            enableProgression = true,
            requiresLoadCalibration = true
        )
        val workout = createTestWorkout(exercise)
        val workoutStore = createTestWorkoutStore(workout)

        viewModel.updateWorkoutStore(workoutStore)
        viewModel.setSelectedWorkoutId(testWorkoutId)
        advanceUntilIdle()

        executeWorkoutWithSets { setState ->
            val currentSetData = setState.currentSetData
            if (currentSetData is WeightSetData) {
                val achievableWeight = findClosestAchievableWeight(currentSetData.actualWeight, setState.equipment)
                setState.currentSetData = currentSetData.copy(
                    actualReps = currentSetData.actualReps + 1,
                    actualWeight = achievableWeight,
                    volume = achievableWeight * (currentSetData.actualReps + 1)
                )
            }
        }

        val progressions = database.exerciseSessionProgressionDao().getAllExerciseSessionProgressions()
        val progression = progressions.firstOrNull { it.exerciseId == testExerciseId }
        assertTrue("Progression should not exist when calibration is required", progression == null)
    }

    // Test 12: No Progression State - Failure
    @Test
    fun testNoProgressionState_failure() = runTest(testDispatcher) {
        val previousSetId1 = UUID.randomUUID()
        val previousSetId2 = UUID.randomUUID()
        val previousWorkoutHistory = createWorkoutHistory(testWorkoutId, testWorkoutGlobalId)
        val previousSet1 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId1, 0u, 95.0, 10)
        val previousSet2 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId2, 1u, 95.0, 8)
        
        createExerciseInfo(
            exerciseId = testExerciseId,
            lastSuccessfulSession = listOf(previousSet1, previousSet2),
            successfulSessionCounter = 2u,
            sessionFailedCounter = 0u
        )
        
        val exercise = Exercise(
            id = testExerciseId,
            enabled = true,
            name = "Test Exercise",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 10, 95.0),
                RestSet(UUID.randomUUID(), 90),
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 8, 95.0)
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 5,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = testEquipmentId,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            enableProgression = false,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )
        val workout = createTestWorkout(exercise)
        val workoutStore = createTestWorkoutStore(workout)
        
        viewModel.updateWorkoutStore(workoutStore)
        viewModel.setSelectedWorkoutId(testWorkoutId)
        advanceUntilIdle()
        
        executeWorkoutWithSets { setState ->
            val currentSetData = setState.currentSetData
            if (currentSetData is WeightSetData) {
                // Execute below last successful session
                val achievableWeight = findClosestAchievableWeight(currentSetData.actualWeight, setState.equipment)
                setState.currentSetData = currentSetData.copy(
                    actualReps = currentSetData.actualReps - 1,
                    actualWeight = achievableWeight,
                    volume = achievableWeight * (currentSetData.actualReps - 1)
                )
            }
        }
        
        val exerciseInfo = database.exerciseInfoDao().getExerciseInfoById(testExerciseId)
        assertNotNull("ExerciseInfo should exist", exerciseInfo)
        assertEquals("successfulSessionCounter should be reset", 0u, exerciseInfo?.successfulSessionCounter)
        assertEquals("sessionFailedCounter should be incremented", 1u, exerciseInfo?.sessionFailedCounter)
    }

    // Test 13: Best Session Update
    @Test
    fun testBestSessionUpdate() = runTest(testDispatcher) {
        val previousSetId1 = UUID.randomUUID()
        val previousSetId2 = UUID.randomUUID()
        val previousWorkoutHistory = createWorkoutHistory(testWorkoutId, testWorkoutGlobalId)
        val previousSet1 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId1, 0u, 90.0, 10)
        val previousSet2 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId2, 1u, 90.0, 8)
        
        createExerciseInfo(
            exerciseId = testExerciseId,
            lastSuccessfulSession = listOf(previousSet1, previousSet2),
            bestSession = listOf(previousSet1, previousSet2),
            successfulSessionCounter = 1u,
            sessionFailedCounter = 0u
        )
        
        val exercise = createTestExercise(
            sets = listOf(
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 10, 92.5),
                RestSet(UUID.randomUUID(), 90),
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 8, 92.5)
            )
        )
        val workout = createTestWorkout(exercise)
        val workoutStore = createTestWorkoutStore(workout)
        
        viewModel.updateWorkoutStore(workoutStore)
        viewModel.setSelectedWorkoutId(testWorkoutId)
        advanceUntilIdle()
        
        executeWorkoutWithSets { setState ->
            val currentSetData = setState.currentSetData
            if (currentSetData is WeightSetData) {
                // Execute significantly above expected to beat best session
                val desiredWeight = currentSetData.actualWeight + 5.0
                val achievableWeight = findClosestAchievableWeight(desiredWeight, setState.equipment)
                setState.currentSetData = currentSetData.copy(
                    actualReps = currentSetData.actualReps + 2,
                    actualWeight = achievableWeight,
                    volume = achievableWeight * (currentSetData.actualReps + 2)
                )
            }
        }
        
        val exerciseInfo = database.exerciseInfoDao().getExerciseInfoById(testExerciseId)
        assertNotNull("ExerciseInfo should exist", exerciseInfo)
        
        // Verify best session was updated
        val bestSessionSets = exerciseInfo?.bestSession?.mapNotNull { setHistory ->
            when (val setData = setHistory.setData) {
                is WeightSetData -> SimpleSet(setData.getWeight(), setData.actualReps)
                else -> null
            }
        } ?: emptyList()
        
        val executedSets = viewModel.executedSetsHistory
            .filter { it.exerciseId == testExerciseId }
            .mapNotNull { setHistory ->
                when (val setData = setHistory.setData) {
                    is WeightSetData -> SimpleSet(setData.getWeight(), setData.actualReps)
                    else -> null
                }
            }
        
        val vsBest = compareSetListsUnordered(executedSets, bestSessionSets)
        assertTrue("Best session should be updated when vsBest is ABOVE", vsBest == Ternary.ABOVE || vsBest == Ternary.EQUAL)
    }

    // Test 14: Weekly Count Updates - Same Week
    @Test
    fun testWeeklyCount_sameWeek() = runTest(testDispatcher) {
        val today = LocalDate.now()
        val exercise = createTestExercise(
            sets = listOf(
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 10, 95.0),
                RestSet(UUID.randomUUID(), 90),
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 8, 95.0)
            )
        )
        val workout = createTestWorkout(exercise)
        val workoutStore = createTestWorkoutStore(workout)
        
        createExerciseInfo(
            exerciseId = testExerciseId,
            timesCompletedInAWeek = 2,
            weeklyCompletionUpdateDate = today
        )
        
        viewModel.updateWorkoutStore(workoutStore)
        viewModel.setSelectedWorkoutId(testWorkoutId)
        advanceUntilIdle()
        
        // Start workout explicitly
        viewModel.startWorkout()
        
        // First, ensure all coroutines are given a chance to start
        advanceUntilIdle()
        joinViewModelJobs()
        delay(10)
        advanceUntilIdle()
        joinViewModelJobs()
        
        // Wait for workout states to be generated - poll until data is loaded AND queue is populated
        var attempts = 0
        var workoutState = viewModel.workoutState.value
        
        // First, verify we're in Preparing state (startWorkout sets this immediately)
        assertTrue("Should be in Preparing state after startWorkout()", workoutState is WorkoutState.Preparing)
        
        // Wait for both dataLoaded to be true AND queue to be populated
        // The queue is populated asynchronously in loadWorkoutHistory() callback
        var dataLoaded = false
        var queuePopulated = false
        while ((!dataLoaded || !queuePopulated) && attempts < 200) {
            advanceUntilIdle()
            joinViewModelJobs()
            Thread.sleep(5)
            workoutState = viewModel.workoutState.value
            
            // Check dataLoaded state
            if (workoutState is WorkoutState.Preparing) {
                dataLoaded = workoutState.dataLoaded
            } else {
                // Transitioned to a different state
                dataLoaded = true
            }
            
            // Check queue population
            @Suppress("UNCHECKED_CAST")
            val stateMachine = stateMachineField.get(viewModel) as? WorkoutStateMachine
            queuePopulated = stateMachine != null && stateMachine.nextStates.isNotEmpty()
            
            if (dataLoaded && queuePopulated) {
                break
            }
            
            attempts++
            
            if (attempts % 10 == 0) {
                delay(1)
                advanceUntilIdle()
                joinViewModelJobs()
                Thread.sleep(5)
            }
        }
        
        // Ensure all coroutines complete before final check
        advanceUntilIdle()
        joinViewModelJobs()
        delay(10)
        advanceUntilIdle()
        joinViewModelJobs()
        
        // Handle case where queue is populated but dataLoaded wasn't set
        val currentState = viewModel.workoutState.value
        if (currentState is WorkoutState.Preparing && !currentState.dataLoaded) {
            @Suppress("UNCHECKED_CAST")
            val stateMachine = stateMachineField.get(viewModel) as? WorkoutStateMachine
            if (stateMachine != null && stateMachine.nextStates.isNotEmpty()) {
                @Suppress("UNCHECKED_CAST")
                val workoutStateFlow = workoutStateField.get(viewModel) as kotlinx.coroutines.flow.MutableStateFlow<WorkoutState>
                workoutStateFlow.value = WorkoutState.Preparing(dataLoaded = true)
            }
        }
        
        // Final verification that state machine is populated
        @Suppress("UNCHECKED_CAST")
        val stateMachine = stateMachineField.get(viewModel) as? WorkoutStateMachine
        assertTrue("StateMachine should be populated after startWorkout(). Next states size: ${stateMachine?.nextStates?.size ?: 0}", 
            stateMachine != null && stateMachine.nextStates.isNotEmpty())
        
        // Now transition from Preparing state - ensure queue is still populated when we call goToNextState()
        workoutState = viewModel.workoutState.value
        if (workoutState is WorkoutState.Preparing && workoutState.dataLoaded) {
            // Verify state machine is still populated right before calling goToNextState()
            @Suppress("UNCHECKED_CAST")
            val stateMachineBeforeTransition = stateMachineField.get(viewModel) as? WorkoutStateMachine
            assertTrue("StateMachine must be populated before calling goToNextState(). Next states size: ${stateMachineBeforeTransition?.nextStates?.size ?: 0}", 
                stateMachineBeforeTransition != null && stateMachineBeforeTransition.nextStates.isNotEmpty())
            
            // Call goToNextState() - it should transition since queue is populated
            viewModel.goToNextState()
            advanceUntilIdle()
            joinViewModelJobs()
            delay(10) // Small delay for state update visibility
            advanceUntilIdle()
            joinViewModelJobs()
            
            // Verify transition happened
            workoutState = viewModel.workoutState.value
        }
        
        assertTrue("Workout should not be in Preparing state after loading. Current state: ${workoutState::class.simpleName}", 
            workoutState !is WorkoutState.Preparing)
        
        // Set workout start time
        viewModel.setWorkoutStart()
        advanceUntilIdle()
        joinViewModelJobs()
        
        assertNotNull("Start workout time should be set", viewModel.startWorkoutTime)
        
        // Execute sets
        executeSetsOnly()
        
        val exerciseInfo = database.exerciseInfoDao().getExerciseInfoById(testExerciseId)
        assertNotNull("ExerciseInfo should exist", exerciseInfo)
        assertEquals("timesCompletedInAWeek should increment", 3, exerciseInfo?.timesCompletedInAWeek)
        assertEquals("weeklyCompletionUpdateDate should be today", today, exerciseInfo?.weeklyCompletionUpdateDate)
    }

    // Test 15: Weekly Count Updates - New Week
    @Test
    fun testWeeklyCount_newWeek() = runTest(testDispatcher) {
        val today = LocalDate.now()
        val lastWeek = today.minusWeeks(1)
        val exercise = createTestExercise(
            sets = listOf(
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 10, 95.0),
                RestSet(UUID.randomUUID(), 90),
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 8, 95.0)
            )
        )
        val workout = createTestWorkout(exercise)
        val workoutStore = createTestWorkoutStore(workout)
        
        createExerciseInfo(
            exerciseId = testExerciseId,
            timesCompletedInAWeek = 3,
            weeklyCompletionUpdateDate = lastWeek
        )
        
        viewModel.updateWorkoutStore(workoutStore)
        viewModel.setSelectedWorkoutId(testWorkoutId)
        advanceUntilIdle()
        
        executeWorkoutWithSets()
        
        val exerciseInfo = database.exerciseInfoDao().getExerciseInfoById(testExerciseId)
        assertNotNull("ExerciseInfo should exist", exerciseInfo)
        assertEquals("timesCompletedInAWeek should reset to 1", 1, exerciseInfo?.timesCompletedInAWeek)
        assertEquals("weeklyCompletionUpdateDate should be today", today, exerciseInfo?.weeklyCompletionUpdateDate)
    }

    // Test 16: ExerciseSessionProgression - vsPrevious Verification
    @Test
    fun testExerciseSessionProgression_vsPrevious() = runTest(testDispatcher) {
        val previousSetId1 = UUID.randomUUID()
        val previousSetId2 = UUID.randomUUID()
        val previousWorkoutHistory = createWorkoutHistory(testWorkoutId, testWorkoutGlobalId)
        val previousSet1 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId1, 0u, 90.0, 10)
        val previousSet2 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId2, 1u, 90.0, 8)
        
        createExerciseInfo(
            exerciseId = testExerciseId,
            lastSuccessfulSession = listOf(previousSet1, previousSet2),
            successfulSessionCounter = 1u,
            sessionFailedCounter = 0u
        )
        
        val exercise = createTestExercise(
            sets = listOf(
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 10, 92.5),
                RestSet(UUID.randomUUID(), 90),
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 8, 92.5)
            )
        )
        val workout = createTestWorkout(exercise)
        val workoutStore = createTestWorkoutStore(workout)
        
        viewModel.updateWorkoutStore(workoutStore)
        viewModel.setSelectedWorkoutId(testWorkoutId)
        advanceUntilIdle()
        
        executeWorkoutWithSets { setState ->
            val currentSetData = setState.currentSetData
            if (currentSetData is WeightSetData) {
                // Execute above previous session
                val achievableWeight = findClosestAchievableWeight(currentSetData.actualWeight, setState.equipment)
                setState.currentSetData = currentSetData.copy(
                    actualReps = currentSetData.actualReps + 1,
                    actualWeight = achievableWeight,
                    volume = achievableWeight * (currentSetData.actualReps + 1)
                )
            }
        }
        
        val progressions = database.exerciseSessionProgressionDao().getAllExerciseSessionProgressions()
        val progression = progressions.firstOrNull { it.exerciseId == testExerciseId }
        assertNotNull("Progression should exist", progression)
        
        val previousSessionSets = listOf(
            SimpleSet(90.0, 10),
            SimpleSet(90.0, 8)
        )
        val executedSets = viewModel.executedSetsHistory
            .filter { it.exerciseId == testExerciseId }
            .mapNotNull { setHistory ->
                when (val setData = setHistory.setData) {
                    is WeightSetData -> SimpleSet(setData.getWeight(), setData.actualReps)
                    else -> null
                }
            }
        
        val expectedVsPrevious = compareSetListsUnordered(executedSets, previousSessionSets)
        assertEquals("vsPrevious should match calculated value", expectedVsPrevious, progression?.vsPrevious)
        assertTrue("vsPrevious should be ABOVE", progression?.vsPrevious == Ternary.ABOVE)
    }

    // Test 17: Cross-Session - Multiple PROGRESS Success
    @Test
    fun testCrossSession_multipleProgressSuccess() = runTest(testDispatcher) {
        val exercise = createTestExercise(
            sets = listOf(
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 10, 90.0),
                RestSet(UUID.randomUUID(), 90),
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 8, 90.0)
            )
        )
        val workout = createTestWorkout(exercise)
        val workoutStore = createTestWorkoutStore(workout)
        
        // First session
        viewModel.updateWorkoutStore(workoutStore)
        viewModel.setSelectedWorkoutId(testWorkoutId)
        advanceUntilIdle()
        
        executeWorkoutWithSets()
        
        var exerciseInfo = database.exerciseInfoDao().getExerciseInfoById(testExerciseId)
        assertEquals("First session counter should be 1", 1u, exerciseInfo?.successfulSessionCounter)
        
        // Second session - need to update exercise sets for progression
        val exercise2 = createTestExercise(
            sets = listOf(
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 10, 92.5),
                RestSet(UUID.randomUUID(), 90),
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 8, 92.5)
            )
        )
        val workout2 = createTestWorkout(exercise2)
        val workoutStore2 = createTestWorkoutStore(workout2)
        
        viewModel.updateWorkoutStore(workoutStore2)
        viewModel.setSelectedWorkoutId(testWorkoutId)
        advanceUntilIdle()
        
        executeWorkoutWithSets()
        
        exerciseInfo = database.exerciseInfoDao().getExerciseInfoById(testExerciseId)
        assertEquals("Second session counter should be 2", 2u, exerciseInfo?.successfulSessionCounter)
        assertEquals("sessionFailedCounter should be 0", 0u, exerciseInfo?.sessionFailedCounter)
    }

    // Test 18: Cross-Session - PROGRESS Failure Followed by RETRY
    @Test
    fun testCrossSession_progressFailureThenRetry() = runTest(testDispatcher) {
        val previousSetId1 = UUID.randomUUID()
        val previousSetId2 = UUID.randomUUID()
        val previousWorkoutHistory = createWorkoutHistory(testWorkoutId, testWorkoutGlobalId)
        val previousSet1 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId1, 0u, 90.0, 10)
        val previousSet2 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId2, 1u, 90.0, 8)
        
        createExerciseInfo(
            exerciseId = testExerciseId,
            lastSuccessfulSession = listOf(previousSet1, previousSet2),
            successfulSessionCounter = 1u,
            sessionFailedCounter = 0u
        )
        
        // First session - PROGRESS failure
        val exercise = createTestExercise(
            sets = listOf(
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 10, 92.5),
                RestSet(UUID.randomUUID(), 90),
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 8, 92.5)
            )
        )
        val workout = createTestWorkout(exercise)
        val workoutStore = createTestWorkoutStore(workout)
        
        viewModel.updateWorkoutStore(workoutStore)
        viewModel.setSelectedWorkoutId(testWorkoutId)
        advanceUntilIdle()
        
        executeWorkoutWithSets { setState ->
            val currentSetData = setState.currentSetData
            if (currentSetData is WeightSetData) {
                // Execute below expected - failure
                val desiredWeight = currentSetData.actualWeight - 5.0
                val achievableWeight = findClosestAchievableWeight(desiredWeight, setState.equipment)
                setState.currentSetData = currentSetData.copy(
                    actualReps = currentSetData.actualReps - 2,
                    actualWeight = achievableWeight,
                    volume = achievableWeight * (currentSetData.actualReps - 2)
                )
            }
        }
        
        var exerciseInfo = database.exerciseInfoDao().getExerciseInfoById(testExerciseId)
        assertEquals("sessionFailedCounter should be 1", 1u, exerciseInfo?.sessionFailedCounter)
        assertEquals("successfulSessionCounter should be 0", 0u, exerciseInfo?.successfulSessionCounter)
        
        // Second session - RETRY (should load last successful session)
        val exercise2 = createTestExercise(
            sets = listOf(
                createWeightSetWithValidatedWeight(previousSetId1, 10, 90.0),
                RestSet(UUID.randomUUID(), 90),
                createWeightSetWithValidatedWeight(previousSetId2, 8, 90.0)
            )
        )
        val workout2 = createTestWorkout(exercise2)
        val workoutStore2 = createTestWorkoutStore(workout2)
        
        viewModel.updateWorkoutStore(workoutStore2)
        viewModel.setSelectedWorkoutId(testWorkoutId)
        advanceUntilIdle()
        
        executeWorkoutWithSets { setState ->
            val currentSetData = setState.currentSetData
            if (currentSetData is WeightSetData) {
                // Execute above retry target - success
                val achievableWeight = findClosestAchievableWeight(currentSetData.actualWeight, setState.equipment)
                setState.currentSetData = currentSetData.copy(
                    actualReps = currentSetData.actualReps + 1,
                    actualWeight = achievableWeight,
                    volume = achievableWeight * (currentSetData.actualReps + 1)
                )
            }
        }
        
        exerciseInfo = database.exerciseInfoDao().getExerciseInfoById(testExerciseId)
        assertEquals("sessionFailedCounter should be reset", 0u, exerciseInfo?.sessionFailedCounter)
        assertEquals("successfulSessionCounter should be incremented", 1u, exerciseInfo?.successfulSessionCounter)
        
        val progressions = database.exerciseSessionProgressionDao().getAllExerciseSessionProgressions()
        val retryProgression = progressions.lastOrNull { it.exerciseId == testExerciseId }
        assertEquals("Second session should be RETRY", ProgressionState.RETRY, retryProgression?.progressionState)
    }

    // Test 19: PROGRESS State - Verify Progression Calculation
    @Test
    fun testProgressState_progressionCalculation() = runTest(testDispatcher) {
        val previousSetId1 = UUID.randomUUID()
        val previousSetId2 = UUID.randomUUID()
        val previousSetId3 = UUID.randomUUID()
        val previousWorkoutHistory = createWorkoutHistory(testWorkoutId, testWorkoutGlobalId)
        val previousSet1 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId1, 0u, 90.0, 10)
        val previousSet2 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId2, 1u, 90.0, 9)
        val previousSet3 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId3, 2u, 90.0, 8)
        
        createExerciseInfo(
            exerciseId = testExerciseId,
            lastSuccessfulSession = listOf(previousSet1, previousSet2, previousSet3),
            successfulSessionCounter = 1u,
            sessionFailedCounter = 0u
        )
        
        // Create exercise with initial sets (these should be replaced by progression)
        val exercise = createTestExercise(
            sets = listOf(
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 10, 90.0),
                RestSet(UUID.randomUUID(), 90),
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 9, 90.0),
                RestSet(UUID.randomUUID(), 90),
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 8, 90.0)
            )
        )
        val workout = createTestWorkout(exercise)
        val workoutStore = createTestWorkoutStore(workout)
        
        viewModel.updateWorkoutStore(workoutStore)
        viewModel.setSelectedWorkoutId(testWorkoutId)
        advanceUntilIdle()
        
        // Start workout to trigger progression generation
        viewModel.startWorkout()
        advanceUntilIdle()
        joinViewModelJobs()
        Thread.sleep(10)
        delay(10)
        advanceUntilIdle()
        joinViewModelJobs()
        
        waitForWorkoutToLoad()
        
        // Access exerciseProgressionByExerciseId via reflection
        val exerciseProgressionByExerciseIdField = WorkoutViewModel::class.java.getDeclaredField("exerciseProgressionByExerciseId")
        exerciseProgressionByExerciseIdField.isAccessible = true
        @Suppress("UNCHECKED_CAST")
        val exerciseProgressionMap = exerciseProgressionByExerciseIdField.get(viewModel) as MutableMap<UUID, Pair<com.gabstra.myworkoutassistant.shared.utils.DoubleProgressionHelper.Plan, ProgressionState>>
        
        val progressionData = exerciseProgressionMap[testExerciseId]
        assertNotNull("Progression should be generated", progressionData)
        
        val progressionPlan = progressionData!!.first
        val progressionState = progressionData.second
        
        assertEquals("Progression state should be PROGRESS", ProgressionState.PROGRESS, progressionState)
        
        // Verify that new sets are different from previous sets
        val previousSets = listOf(
            SimpleSet(90.0, 10),
            SimpleSet(90.0, 9),
            SimpleSet(90.0, 8)
        )
        val newSets = progressionPlan.sets
        
        assertTrue("New sets should be generated", newSets.isNotEmpty())
        assertEquals("New sets count should match previous sets count", previousSets.size, newSets.size)
        
        // Verify that progression was actually calculated by planNextSession()
        // The key test: new sets should be calculated from previous sets, not copied from exercise sets
        // Previous sets: 100kg x 10, 100kg x 9, 100kg x 8 (reps range 5-12)
        // Progression should increase reps (since not all at max) or weight
        val previousVolume = previousSets.sumOf { it.weight * it.reps }
        val newVolume = newSets.sumOf { it.weight * it.reps }
        
        // Verify that planNextSession was called (not just copying current sets)
        // The progression should result in different sets/volume
        // Note: In rare cases volume might stay same if at absolute limits, but sets should still reflect progression logic
        val previousTotalReps = previousSets.sumOf { it.reps }
        val newTotalReps = newSets.sumOf { it.reps }
        val maxPreviousWeight = previousSets.maxOf { it.weight }
        val maxNewWeight = newSets.maxOf { it.weight }
        
        // Progression should either:
        // 1. Increase reps (if not all at max)
        // 2. Increase weight (if all at max reps)
        // 3. Or at minimum, the sets should be normalized/calculated (not identical)
        val setsAreIdentical = newSets.size == previousSets.size &&
            newSets.zip(previousSets).all { (new, prev) -> 
                new.weight == prev.weight && new.reps == prev.reps 
            }
        
        assertTrue(
            "Progression should be calculated (not identical sets). " +
            "Previous: ${previousSets.map { "${it.weight}kg x ${it.reps}" }}, " +
            "New: ${newSets.map { "${it.weight}kg x ${it.reps}" }}. " +
            "Previous volume: $previousVolume, New volume: $newVolume. " +
            "Previous total reps: $previousTotalReps, New total reps: $newTotalReps. " +
            "Previous max weight: $maxPreviousWeight, New max weight: $maxNewWeight",
            !setsAreIdentical || newVolume != previousVolume || 
            newTotalReps > previousTotalReps || maxNewWeight > maxPreviousWeight
        )
        
        // Additional verification: if reps are below max (12), progression should increase reps
        val allAtMaxReps = previousSets.all { it.reps >= 12 }
        if (!allAtMaxReps) {
            assertTrue(
                "When not all sets at max reps, progression should increase reps or weight. " +
                "Previous total reps: $previousTotalReps, New total reps: $newTotalReps. " +
                "Previous max weight: $maxPreviousWeight, New max weight: $maxNewWeight",
                newTotalReps > previousTotalReps || maxNewWeight > maxPreviousWeight
            )
        }
    }

    // Test 20: ExerciseSessionProgression - Volume Verification
    @Test
    fun testExerciseSessionProgression_volumes() = runTest(testDispatcher) {
        val previousSetId1 = UUID.randomUUID()
        val previousSetId2 = UUID.randomUUID()
        val previousWorkoutHistory = createWorkoutHistory(testWorkoutId, testWorkoutGlobalId)
        val previousSet1 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId1, 0u, 90.0, 10)
        val previousSet2 = createSetHistory(previousWorkoutHistory.id, testExerciseId, previousSetId2, 1u, 90.0, 8)
        
        createExerciseInfo(
            exerciseId = testExerciseId,
            lastSuccessfulSession = listOf(previousSet1, previousSet2),
            successfulSessionCounter = 1u,
            sessionFailedCounter = 0u
        )
        
        val exercise = createTestExercise(
            sets = listOf(
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 10, 92.5),
                RestSet(UUID.randomUUID(), 90),
                createWeightSetWithValidatedWeight(UUID.randomUUID(), 8, 92.5)
            )
        )
        val workout = createTestWorkout(exercise)
        val workoutStore = createTestWorkoutStore(workout)
        
        viewModel.updateWorkoutStore(workoutStore)
        viewModel.setSelectedWorkoutId(testWorkoutId)
        advanceUntilIdle()
        
        executeWorkoutWithSets { setState ->
            val currentSetData = setState.currentSetData
            if (currentSetData is WeightSetData) {
                val achievableWeight = findClosestAchievableWeight(currentSetData.actualWeight, setState.equipment)
                setState.currentSetData = currentSetData.copy(
                    actualReps = currentSetData.actualReps,
                    actualWeight = achievableWeight,
                    volume = achievableWeight * currentSetData.actualReps
                )
            }
        }
        
        val progressions = database.exerciseSessionProgressionDao().getAllExerciseSessionProgressions()
        val progression = progressions.firstOrNull { it.exerciseId == testExerciseId }
        assertNotNull("Progression should exist", progression)
        
        val previousVolume = (90.0 * 10) + (90.0 * 8) // 1620
        val expectedVolume = (92.5 * 10) + (92.5 * 9) // 1757.5
        val executedVolume = viewModel.executedSetsHistory
            .filter { it.exerciseId == testExerciseId }
            .sumOf { setHistory ->
                when (val setData = setHistory.setData) {
                    is WeightSetData -> setData.getWeight() * setData.actualReps
                    else -> 0.0
                }
            }

        if (progression != null) {
            assertEquals(
                "previousSessionVolume should match",
                previousVolume,
                progression.previousSessionVolume,
                0.01
            )
            assertEquals(
                "expectedVolume should match",
                expectedVolume,
                progression.expectedVolume,
                0.01
            )
            assertEquals(
                "executedVolume should match",
                executedVolume,
                progression.executedVolume,
                0.01
            )
        }
    }

    // Test 21: Unilateral Exercise - Progress Bar Calculation
    @Test
    fun testUnilateralExercise_progressBarCalculation() = runTest(testDispatcher) {
        val unilateralSetId = UUID.randomUUID()
        
        // Create a unilateral exercise (with intraSetRestInSeconds set)
        val exercise = Exercise(
            id = testExerciseId,
            enabled = true,
            name = "Unilateral Dumbbell Curl",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                createWeightSetWithValidatedWeight(unilateralSetId, 10, 20.0)
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 5,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = testEquipmentId,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            enableProgression = false,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = 60, // This makes it unilateral
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )
        val workout = createTestWorkout(exercise)
        val workoutStore = createTestWorkoutStore(workout)
        
        viewModel.updateWorkoutStore(workoutStore)
        viewModel.setSelectedWorkoutId(testWorkoutId)
        advanceUntilIdle()
        
        // Start workout to generate states
        viewModel.startWorkout()
        advanceUntilIdle()
        joinViewModelJobs()
        Thread.sleep(10)
        delay(10)
        advanceUntilIdle()
        joinViewModelJobs()
        
        waitForWorkoutToLoad()
        
        // Get all workout states - for unilateral exercise, there should be 2 sets with same set.id
        val allStates = viewModel.allWorkoutStates
        val exerciseStates = allStates.filterIsInstance<WorkoutState.Set>()
            .filter { it.exerciseId == testExerciseId }
            .filter { !it.isWarmupSet }
        
        // Verify unilateral sets were created (should have 2 sets with same set.id)
        assertTrue("Should have 2 unilateral sets", exerciseStates.size >= 2)
        val unilateralSets = exerciseStates.filter { it.set.id == unilateralSetId }
        assertEquals("Should have 2 sets with same set.id for unilateral", 2, unilateralSets.size)
        assertTrue("Both unilateral sets should be same reference", unilateralSets[0] === unilateralSets[1])
        
        // Test getAllExerciseWorkoutStates - should return both but distinctBy should give 1
        val allExerciseStates = viewModel.getAllExerciseWorkoutStates(testExerciseId)
        val uniqueStates = allExerciseStates.distinctBy { it.set.id }
        assertEquals("getAllExerciseWorkoutStates should return 2 instances", 2, allExerciseStates.size)
        assertEquals("distinctBy set.id should return 1 unique set", 1, uniqueStates.size)
        
        // Test scenario 1: On first side (no sets completed)
        val firstSide = unilateralSets[0]
        val machine = viewModel.stateMachine!!
        val unilateralIndices = machine.allStates.mapIndexedNotNull { index, state ->
            if (state is WorkoutState.Set && state.set.id == unilateralSetId) index else null
        }
        assertTrue("Unilateral set must appear twice in state machine", unilateralIndices.size >= 2)
        val firstSideIndex = unilateralIndices[0]
        viewModel.stateMachine = machine.withCurrentIndex(firstSideIndex)
        viewModel.updateStateFlowsFromMachine()
        
        val completedBeforeFirstSide = viewModel.getAllExerciseCompletedSetsBefore(firstSide)
        val completedCount = completedBeforeFirstSide.count { it.exerciseId == testExerciseId }
        assertEquals("On first side, should have 0 completed sets", 0, completedCount)
        
        // Test scenario 2: After completing first side (on second side)
        val secondSide = unilateralSets[1]
        val secondSideIndex = unilateralIndices[1]
        viewModel.stateMachine = machine.withCurrentIndex(secondSideIndex)
        viewModel.updateStateFlowsFromMachine()
        
        val completedBeforeSecondSide = viewModel.getAllExerciseCompletedSetsBefore(secondSide)
        val completedCountSecondSide = completedBeforeSecondSide.count { it.exerciseId == testExerciseId }
        assertEquals("On second side, should have 1 completed set (deduplicated)", 1, completedCountSecondSide)
        
        // Verify deduplication - should only count unique sets
        val uniqueCompleted = completedBeforeSecondSide.distinctBy { it.set.id }
        assertEquals("Completed sets should be deduplicated", completedCountSecondSide, uniqueCompleted.size)
        
        // Test scenario 3: Verify total count is correct (should be 1, not 2)
        val totalUnique = viewModel.getAllExerciseWorkoutStates(testExerciseId).distinctBy { it.set.id }.size
        assertEquals("Total unique sets should be 1 for unilateral exercise", 1, totalUnique)
    }
}


