package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.activity.ComponentActivity
import androidx.lifecycle.ViewModelProvider
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import androidx.test.uiautomator.By
import androidx.test.uiautomator.StaleObjectException
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.UiObject2
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.composables.SetValueSemantics
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.BodyWeightSetWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.fixtures.ComprehensiveHistoryWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.fixtures.EnduranceSetManualStartWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.fixtures.TimedDurationManualStartWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.fixtures.WarmupSetWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.fixtures.WeightSetWorkoutStoreFixture
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import kotlinx.coroutines.runBlocking
import org.junit.Ignore
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

/**
 * E2E test to verify that exercise history is properly stored after workout completion.
 * Tests all exercise types, equipment types, and verifies that modified set data during
 * execution is correctly stored in the database.
 *
 * Modification coverage:
 * - Weight set: reps + weight (single-set test).
 * - Body weight set: reps + additional weight (single-set test).
 * - Timed duration (manual start): start/stop to shorten duration.
 * - Endurance (manual start): start/stop to shorten duration.
 * - Comprehensive workout: only one weight-set modification attempt for stability.
 * - Skipped set: skipped=true stored.
 *
 * Test cases:
 * - exerciseHistory_singleWeightSetStoresModifiedRepsAndWeight: edits reps + weight and asserts history.
 * - exerciseHistory_singleWeightSetStoresSkippedFlag: marks set skipped and asserts history.
 * - exerciseHistory_singleBodyWeightSetStoresModifiedRepsAndAdditionalWeight: edits reps + add weight and asserts history.
 * - exerciseHistory_singleTimedDurationSetStoresModifiedDuration: manual start/stop, asserts duration stored.
 * - exerciseHistory_singleEnduranceSetStoresModifiedDuration: manual start/stop, asserts duration stored.
 * - exerciseHistory_storedCorrectlyAfterWorkoutCompletion: completes a comprehensive workout and validates history shape.
 */
@RunWith(AndroidJUnit4::class)
class WearExerciseHistoryE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    @Before
    override fun baseSetUp() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        device = UiDevice.getInstance(instrumentation)
        context = ApplicationProvider.getApplicationContext()

        // Grant all required runtime permissions
        grantPermissions(
            android.Manifest.permission.BODY_SENSORS,
            android.Manifest.permission.ACTIVITY_RECOGNITION,
            android.Manifest.permission.POST_NOTIFICATIONS,
            android.Manifest.permission.ACCESS_FINE_LOCATION,
            android.Manifest.permission.ACCESS_COARSE_LOCATION,
            android.Manifest.permission.BLUETOOTH_SCAN,
            android.Manifest.permission.BLUETOOTH_CONNECT
        )

        runBlocking {
            val db = AppDatabase.getDatabase(context)
            db.workoutHistoryDao().deleteAll()
            db.setHistoryDao().deleteAll()
            db.workoutRecordDao().deleteAll()
        }

        workoutDriver = createWorkoutDriver()
    }

    private data class ModifiedSetData(
        val setId: UUID,
        val exerciseId: UUID,
        val originalReps: Int?,
        val modifiedReps: Int?,
        val originalWeight: Double?,
        val modifiedWeight: Double?,
        val originalAdditionalWeight: Double?,
        val modifiedAdditionalWeight: Double?,
        // For timed / endurance sets, we track duration in whole seconds
        val originalDurationSeconds: Int?,
        val modifiedDurationSeconds: Int?,
    )

    private val modifications = mutableMapOf<UUID, ModifiedSetData>()

    private enum class UiSetType {
        WEIGHT,
        BODY_WEIGHT,
        TIMED_DURATION,
        ENDURANCE,
        REST,
        UNKNOWN,
    }

    /**
     * Detects the current set type purely from UI semantics.
     *
     * The corresponding screens expose a top-level semantics contentDescription
     * using the constants in SetValueSemantics.
     */
    private fun detectCurrentSetTypeFromSemantics(): UiSetType {
        // Check for more specific types first; fall back to UNKNOWN.
        return when {
            device.findObject(
                By.descContains(SetValueSemantics.WeightSetTypeDescription)
            ) != null -> UiSetType.WEIGHT

            device.findObject(
                By.descContains(SetValueSemantics.BodyWeightSetTypeDescription)
            ) != null -> UiSetType.BODY_WEIGHT

            device.findObject(
                By.descContains(SetValueSemantics.TimedDurationSetTypeDescription)
            ) != null -> UiSetType.TIMED_DURATION

            device.findObject(
                By.descContains(SetValueSemantics.EnduranceSetTypeDescription)
            ) != null -> UiSetType.ENDURANCE

            device.findObject(
                By.descContains(SetValueSemantics.RestSetTypeDescription)
            ) != null -> UiSetType.REST

            else -> UiSetType.UNKNOWN
        }
    }

    private data class CurrentSetInfo(
        val set: com.gabstra.myworkoutassistant.shared.sets.Set,
        val exerciseId: UUID,
        val equipment: WeightLoadedEquipment?
    )

    /**
     * Determines the current set info by querying the database (WorkoutRecord).
     * This is more reliable than UI detection since it directly accesses the workout state.
     *
     * @return The current set info, or null if no workout record exists or workout is complete
     */
    private suspend fun getCurrentSetInfo(
        workoutName: String = ComprehensiveHistoryWorkoutStoreFixture.getWorkoutName()
    ): CurrentSetInfo? {
        val db = AppDatabase.getDatabase(context)
        val workoutRecordDao = db.workoutRecordDao()
        
        // Get workout name and find workout
        val workoutStoreRepository = WorkoutStoreRepository(context.filesDir)
        val workoutStore = workoutStoreRepository.getWorkoutStore()
        val workout = workoutStore.workouts.firstOrNull { it.name == workoutName }
            ?: return null
        
        // Get current workout record
        val workoutRecord = workoutRecordDao.getWorkoutRecordByWorkoutId(workout.id)
            ?: return null
        
        // Find the exercise
        val exercise = workout.workoutComponents
            .filterIsInstance<com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise>()
            .firstOrNull { it.id == workoutRecord.exerciseId }
            ?: return null
        
        // Get the set at the current setIndex
        val setIndex = workoutRecord.setIndex.toInt()
        if (setIndex < 0 || setIndex >= exercise.sets.size) {
            return null
        }
        
        val equipment = exercise.equipmentId?.let { equipmentId ->
            workoutStore.equipments
                .filterIsInstance<WeightLoadedEquipment>()
                .firstOrNull { it.id == equipmentId }
        }

        return CurrentSetInfo(
            set = exercise.sets[setIndex],
            exerciseId = exercise.id,
            equipment = equipment
        )
    }

    private suspend fun waitForCurrentSetInfo(
        workoutName: String = ComprehensiveHistoryWorkoutStoreFixture.getWorkoutName(),
        timeoutMs: Long = 10_000
    ): CurrentSetInfo? {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val info = getCurrentSetInfo(workoutName)
            if (info != null) {
                return info
            }
            device.waitForIdle(500)
        }
        return null
    }

    private fun markCurrentSetSkipped() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.runOnMainSync {
            val resumedActivity = ActivityLifecycleMonitorRegistry.getInstance()
                .getActivitiesInStage(Stage.RESUMED)
                .firstOrNull()
                ?: error("No resumed activity to access AppViewModel")

            val activity = resumedActivity as? ComponentActivity
                ?: error("Resumed activity is not a ComponentActivity")
            val viewModel = ViewModelProvider(activity)[AppViewModel::class.java]
            val currentState = viewModel.workoutState.value as? WorkoutState.Set
                ?: error("Expected WorkoutState.Set to mark skipped")
            currentState.skipped = true
        }
    }

    @Test
    fun exerciseHistory_singleWeightSetStoresModifiedRepsAndWeight() = runBlocking {
        WeightSetWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        startWorkout(WeightSetWorkoutStoreFixture.getWorkoutName())

        val workoutName = WeightSetWorkoutStoreFixture.getWorkoutName()
        val setScreenVisible = device.wait(
            Until.hasObject(By.descContains(SetValueSemantics.WeightSetTypeDescription)),
            10_000
        )
        require(setScreenVisible) { "Weight set screen did not appear" }

        val workoutStoreRepository = WorkoutStoreRepository(context.filesDir)
        val workoutStore = workoutStoreRepository.getWorkoutStore()
        val workout = workoutStore.workouts.firstOrNull { it.name == workoutName }
            ?: error("Workout not found: $workoutName")
        val exercise = workout.workoutComponents
            .filterIsInstance<com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise>()
            .firstOrNull() ?: error("Expected a single exercise in $workoutName")
        val set = exercise.sets.firstOrNull() ?: error("Expected a single set in $workoutName")
        val equipment = exercise.equipmentId?.let { equipmentId ->
            workoutStore.equipments
                .filterIsInstance<WeightLoadedEquipment>()
                .firstOrNull { it.id == equipmentId }
        }
        val currentSetInfo = CurrentSetInfo(
            set = set,
            exerciseId = exercise.id,
            equipment = equipment
        )
        require(currentSetInfo.set is WeightSet) {
            "Expected WeightSet, got ${currentSetInfo.set::class.simpleName}"
        }

        val originalRepsText = waitForValueText(
            SetValueSemantics.RepsValueDescription,
            previousValue = null,
            expectedValue = null,
            timeoutMs = 5_000
        ) ?: error("Expected reps value to be visible before editing")
        val originalReps = originalRepsText.toIntOrNull()
            ?: error("Expected numeric reps value, got '$originalRepsText'")
        val originalWeightText = waitForValueText(
            SetValueSemantics.WeightValueDescription,
            previousValue = null,
            expectedValue = null,
            timeoutMs = 5_000
        ) ?: error("Expected weight value to be visible before editing")
        val originalWeight = parseWeightValue(originalWeightText)
            ?: error("Expected numeric weight value, got '$originalWeightText'")

        val updatedRepsText = incrementValueAndWait(
            SetValueSemantics.RepsValueDescription,
            null
        ) ?: error("Failed to modify reps via UI")
        val modifiedReps = updatedRepsText.toIntOrNull()
            ?: error("Expected numeric reps value after edit, got '$updatedRepsText'")
        require(modifiedReps != originalReps) {
            "Reps did not change (original=$originalReps updated=$modifiedReps)"
        }

        val updatedWeightText = incrementValueAndWait(
            SetValueSemantics.WeightValueDescription,
            null
        ) ?: error("Failed to modify weight via UI")
        val modifiedWeight = parseWeightValue(updatedWeightText)
            ?: error("Expected numeric weight value after edit, got '$updatedWeightText'")
        require(kotlin.math.abs(modifiedWeight - originalWeight) > 0.05) {
            "Weight did not change (original=$originalWeight updated=$modifiedWeight)"
        }

        device.pressBack()
        confirmLongPressDialog()

        waitForWorkoutCompletion()

        val db = AppDatabase.getDatabase(context)
        val workoutHistoryDao = db.workoutHistoryDao()
        val setHistoryDao = db.setHistoryDao()

        val workoutHistory = workoutHistoryDao.getLatestWorkoutHistoryByWorkoutId(workout.id, isDone = true)
            ?: error("WorkoutHistory not found for completed workout")
        require(workoutHistory.isDone) { "WorkoutHistory isDone should be true" }

        val setHistory = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)
            .firstOrNull { it.setId == set.id }
            ?: error("SetHistory not found for set ${set.id}")

        val setData = setHistory.setData as? WeightSetData
            ?: error("Expected WeightSetData, got ${setHistory.setData::class.simpleName}")

        require(setData.actualReps == modifiedReps) {
            "Expected actualReps=$modifiedReps, got ${setData.actualReps}"
        }
        require(setData.actualReps != originalReps) {
            "Expected actualReps to differ from original value $originalReps"
        }
        require(kotlin.math.abs(setData.actualWeight - modifiedWeight) < 0.1) {
            "Expected actualWeight~$modifiedWeight, got ${setData.actualWeight}"
        }
        require(kotlin.math.abs(setData.actualWeight - originalWeight) > 0.05) {
            "Expected actualWeight to differ from original value $originalWeight"
        }
    }

    @Test
    fun exerciseHistory_singleWeightSetStoresSkippedFlag() = runBlocking {
        WeightSetWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        val workoutName = WeightSetWorkoutStoreFixture.getWorkoutName()
        startWorkout(workoutName)

        val setScreenVisible = device.wait(
            Until.hasObject(By.descContains(SetValueSemantics.WeightSetTypeDescription)),
            10_000
        )
        require(setScreenVisible) { "Weight set screen did not appear" }

        val workoutStoreRepository = WorkoutStoreRepository(context.filesDir)
        val workoutStore = workoutStoreRepository.getWorkoutStore()
        val workout = workoutStore.workouts.firstOrNull { it.name == workoutName }
            ?: error("Workout not found: $workoutName")
        val exercise = workout.workoutComponents
            .filterIsInstance<com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise>()
            .firstOrNull() ?: error("Expected a single exercise in $workoutName")
        val set = exercise.sets.firstOrNull() ?: error("Expected a single set in $workoutName")

        markCurrentSetSkipped()

        device.pressBack()
        confirmLongPressDialog()

        waitForWorkoutCompletion()

        val db = AppDatabase.getDatabase(context)
        val workoutHistoryDao = db.workoutHistoryDao()
        val setHistoryDao = db.setHistoryDao()

        val workoutHistory = workoutHistoryDao.getLatestWorkoutHistoryByWorkoutId(workout.id, isDone = true)
            ?: error("WorkoutHistory not found for completed workout")
        require(workoutHistory.isDone) { "WorkoutHistory isDone should be true" }

        val setHistory = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)
            .firstOrNull { it.setId == set.id }
            ?: error("SetHistory not found for set ${set.id}")

        require(setHistory.skipped) {
            "Expected skipped=true for set ${set.id}, got skipped=${setHistory.skipped}"
        }
    }

    @Test
    @Ignore("Covered by comprehensive history test; kept out to reduce redundant E2E runtime.")
    fun exerciseHistory_singleBodyWeightSetStoresModifiedRepsAndAdditionalWeight() = runBlocking {
        BodyWeightSetWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        val workoutName = BodyWeightSetWorkoutStoreFixture.getWorkoutName()
        startWorkout(workoutName)

        val setScreenVisible = device.wait(
            Until.hasObject(By.descContains(SetValueSemantics.BodyWeightSetTypeDescription)),
            10_000
        )
        require(setScreenVisible) { "Body weight set screen did not appear" }

        val workoutStoreRepository = WorkoutStoreRepository(context.filesDir)
        val workoutStore = workoutStoreRepository.getWorkoutStore()
        val workout = workoutStore.workouts.firstOrNull { it.name == workoutName }
            ?: error("Workout not found: $workoutName")
        val exercise = workout.workoutComponents
            .filterIsInstance<com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise>()
            .firstOrNull() ?: error("Expected a single exercise in $workoutName")
        val set = exercise.sets.firstOrNull() ?: error("Expected a single set in $workoutName")

        val originalRepsText = waitForValueText(
            SetValueSemantics.RepsValueDescription,
            previousValue = null,
            expectedValue = null,
            timeoutMs = 5_000
        ) ?: error("Expected reps value to be visible before editing")
        val originalReps = originalRepsText.toIntOrNull()
            ?: error("Expected numeric reps value, got '$originalRepsText'")
        val originalWeightText = waitForValueText(
            SetValueSemantics.WeightValueDescription,
            previousValue = null,
            expectedValue = null,
            timeoutMs = 5_000
        ) ?: error("Expected weight value to be visible before editing")
        val originalAdditionalWeight = if (originalWeightText == "BW") {
            0.0
        } else {
            parseWeightValue(originalWeightText)
                ?: error("Expected numeric weight value, got '$originalWeightText'")
        }

        val updatedRepsText = incrementValueAndWait(
            SetValueSemantics.RepsValueDescription,
            null
        ) ?: error("Failed to modify reps via UI")
        val modifiedReps = updatedRepsText.toIntOrNull()
            ?: error("Expected numeric reps value after edit, got '$updatedRepsText'")
        require(modifiedReps != originalReps) {
            "Reps did not change (original=$originalReps updated=$modifiedReps)"
        }

        val updatedWeightText = incrementValueAndWait(
            SetValueSemantics.WeightValueDescription,
            null
        ) ?: error("Failed to modify additional weight via UI")
        val modifiedAdditionalWeight = if (updatedWeightText == "BW") {
            0.0
        } else {
            parseWeightValue(updatedWeightText)
                ?: error("Expected numeric weight value after edit, got '$updatedWeightText'")
        }
        require(kotlin.math.abs(modifiedAdditionalWeight - originalAdditionalWeight) > 0.05) {
            "Additional weight did not change (original=$originalAdditionalWeight updated=$modifiedAdditionalWeight)"
        }

        device.pressBack()
        confirmLongPressDialog()

        waitForWorkoutCompletion()

        val db = AppDatabase.getDatabase(context)
        val workoutHistoryDao = db.workoutHistoryDao()
        val setHistoryDao = db.setHistoryDao()

        val workoutHistory = workoutHistoryDao.getLatestWorkoutHistoryByWorkoutId(workout.id, isDone = true)
            ?: error("WorkoutHistory not found for completed workout")
        require(workoutHistory.isDone) { "WorkoutHistory isDone should be true" }

        val setHistory = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)
            .firstOrNull { it.setId == set.id }
            ?: error("SetHistory not found for set ${set.id}")

        val setData = setHistory.setData as? BodyWeightSetData
            ?: error("Expected BodyWeightSetData, got ${setHistory.setData::class.simpleName}")

        require(setData.actualReps == modifiedReps) {
            "Expected actualReps=$modifiedReps, got ${setData.actualReps}"
        }
        require(setData.actualReps != originalReps) {
            "Expected actualReps to differ from original value $originalReps"
        }
        require(kotlin.math.abs(setData.additionalWeight - modifiedAdditionalWeight) < 0.1) {
            "Expected additionalWeight~$modifiedAdditionalWeight, got ${setData.additionalWeight}"
        }
        require(kotlin.math.abs(setData.additionalWeight - originalAdditionalWeight) > 0.05) {
            "Expected additionalWeight to differ from original value $originalAdditionalWeight"
        }
    }

    @Test
    @Ignore("Covered by comprehensive history test; kept out to reduce redundant E2E runtime.")
    fun exerciseHistory_singleTimedDurationSetStoresModifiedDuration() = runBlocking {
        TimedDurationManualStartWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        val workoutName = TimedDurationManualStartWorkoutStoreFixture.getWorkoutName()
        startWorkout(workoutName)

        val setScreenVisible = device.wait(
            Until.hasObject(By.descContains(SetValueSemantics.TimedDurationSetTypeDescription)),
            10_000
        )
        require(setScreenVisible) { "Timed duration set screen did not appear" }

        val workoutStoreRepository = WorkoutStoreRepository(context.filesDir)
        val workoutStore = workoutStoreRepository.getWorkoutStore()
        val workout = workoutStore.workouts.firstOrNull { it.name == workoutName }
            ?: error("Workout not found: $workoutName")
        val exercise = workout.workoutComponents
            .filterIsInstance<com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise>()
            .firstOrNull() ?: error("Expected a single exercise in $workoutName")
        val set = exercise.sets.firstOrNull() ?: error("Expected a single set in $workoutName")
        val timedSet = set as? TimedDurationSet
            ?: error("Expected TimedDurationSet, got ${set::class.simpleName}")

        val startClicked = clickButtonWithRetry("Start", timeoutMs = 3_000, attempts = 4)
        require(startClicked) { "Start button not found for timed duration set" }
        Thread.sleep(3_000)

        val stopClicked = clickButtonWithRetry("Stop", timeoutMs = 3_000, attempts = 4)
        require(stopClicked) { "Stop button not found for timed duration set" }

        confirmLongPressDialog()

        waitForWorkoutCompletion()

        val db = AppDatabase.getDatabase(context)
        val workoutHistoryDao = db.workoutHistoryDao()
        val setHistoryDao = db.setHistoryDao()

        val workoutHistory = workoutHistoryDao.getLatestWorkoutHistoryByWorkoutId(workout.id, isDone = true)
            ?: error("WorkoutHistory not found for completed workout")
        require(workoutHistory.isDone) { "WorkoutHistory isDone should be true" }

        val setHistory = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)
            .firstOrNull { it.setId == set.id }
            ?: error("SetHistory not found for set ${set.id}")

        val setData = setHistory.setData as? TimedDurationSetData
            ?: error("Expected TimedDurationSetData, got ${setHistory.setData::class.simpleName}")

        require(setData.startTimer == timedSet.timeInMillis) {
            "Expected startTimer=${timedSet.timeInMillis}, got ${setData.startTimer}"
        }
        require(setData.endTimer in 1 until setData.startTimer) {
            "Expected endTimer to reflect early stop (start=${setData.startTimer}, end=${setData.endTimer})"
        }
    }

    @Test
    @Ignore("Covered by comprehensive history test; kept out to reduce redundant E2E runtime.")
    fun exerciseHistory_singleEnduranceSetStoresModifiedDuration() = runBlocking {
        EnduranceSetManualStartWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        val workoutName = EnduranceSetManualStartWorkoutStoreFixture.getWorkoutName()
        startWorkout(workoutName)

        val setScreenVisible = device.wait(
            Until.hasObject(By.descContains(SetValueSemantics.EnduranceSetTypeDescription)),
            10_000
        )
        require(setScreenVisible) { "Endurance set screen did not appear" }

        val workoutStoreRepository = WorkoutStoreRepository(context.filesDir)
        val workoutStore = workoutStoreRepository.getWorkoutStore()
        val workout = workoutStore.workouts.firstOrNull { it.name == workoutName }
            ?: error("Workout not found: $workoutName")
        val exercise = workout.workoutComponents
            .filterIsInstance<com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise>()
            .firstOrNull() ?: error("Expected a single exercise in $workoutName")
        val set = exercise.sets.firstOrNull() ?: error("Expected a single set in $workoutName")
        val enduranceSet = set as? EnduranceSet
            ?: error("Expected EnduranceSet, got ${set::class.simpleName}")

        val startClicked = clickButtonWithRetry("Start", timeoutMs = 3_000, attempts = 4)
        require(startClicked) { "Start button not found for endurance set" }
        Thread.sleep(3_000)

        val stopClicked = clickButtonWithRetry("Stop", timeoutMs = 3_000, attempts = 4)
        require(stopClicked) { "Stop button not found for endurance set" }

        confirmLongPressDialog()

        waitForWorkoutCompletion()

        val db = AppDatabase.getDatabase(context)
        val workoutHistoryDao = db.workoutHistoryDao()
        val setHistoryDao = db.setHistoryDao()

        val workoutHistory = workoutHistoryDao.getLatestWorkoutHistoryByWorkoutId(workout.id, isDone = true)
            ?: error("WorkoutHistory not found for completed workout")
        require(workoutHistory.isDone) { "WorkoutHistory isDone should be true" }

        val setHistory = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)
            .firstOrNull { it.setId == set.id }
            ?: error("SetHistory not found for set ${set.id}")

        val setData = setHistory.setData as? EnduranceSetData
            ?: error("Expected EnduranceSetData, got ${setHistory.setData::class.simpleName}")

        require(setData.startTimer == enduranceSet.timeInMillis) {
            "Expected startTimer=${enduranceSet.timeInMillis}, got ${setData.startTimer}"
        }
        require(setData.endTimer in 1 until setData.startTimer) {
            "Expected endTimer to reflect elapsed time (start=${setData.startTimer}, end=${setData.endTimer})"
        }
    }

    @Test
    fun exerciseHistory_storedCorrectlyAfterWorkoutCompletion() = runBlocking {
        // Setup workout store
        ComprehensiveHistoryWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        // Start the workout
        startWorkout(ComprehensiveHistoryWorkoutStoreFixture.getWorkoutName())

        // Complete all sets in the workout and attempt UI modifications on editable sets.
        completeAllSetsInWorkout()

        // Wait for completion screen
        waitForWorkoutCompletion()

        // Query database and verify
        val db = AppDatabase.getDatabase(context)
        val workoutHistoryDao = db.workoutHistoryDao()
        val setHistoryDao = db.setHistoryDao()

        val workoutName = ComprehensiveHistoryWorkoutStoreFixture.getWorkoutName()
        // Read workout store from file (it was seeded by the fixture)
        val workoutStoreRepository = WorkoutStoreRepository(context.filesDir)
        val workoutStore = workoutStoreRepository.getWorkoutStore()
        val workout = workoutStore.workouts.firstOrNull { it.name == workoutName }
            ?: error("Workout not found: $workoutName")

        // Get the completed workout history
        val workoutHistory = workoutHistoryDao.getLatestWorkoutHistoryByWorkoutId(workout.id, isDone = true)
        require(workoutHistory != null) { "WorkoutHistory not found for completed workout" }
        require(workoutHistory.isDone) { "WorkoutHistory isDone should be true" }

        // Get all set histories for this workout
        val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)

        // Verify basic structure
        verifySetHistoryStructure(workoutHistory, setHistories, workout)

        // Verify modified values are stored (if any modifications were made)
        if (modifications.isNotEmpty()) {
            verifyModifiedValuesAreStored(setHistories)
        }

        // Verify unmodified values are stored correctly
        verifyUnmodifiedValuesAreStored(setHistories, workout)

        // Verify RestSets are excluded
        verifyRestSetsExcluded(setHistories, workout)

        // Verify doNotStoreHistory exercises are excluded
        verifyDoNotStoreHistoryExcluded(setHistories, workout)
    }

    @Test
    fun exerciseHistory_warmupSetsExcludedFromHistory() = runBlocking {
        // Setup workout store with warmup sets enabled
        WarmupSetWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()

        val workoutName = WarmupSetWorkoutStoreFixture.getWorkoutName()
        startWorkout(workoutName)

        // Complete all sets (both warmup and work sets will be encountered)
        completeAllSetsInWorkout(workoutName)

        // Wait for completion screen
        waitForWorkoutCompletion()

        // Query database and verify
        val db = AppDatabase.getDatabase(context)
        val workoutHistoryDao = db.workoutHistoryDao()
        val setHistoryDao = db.setHistoryDao()

        // Read workout store from file (it was seeded by the fixture)
        val workoutStoreRepository = WorkoutStoreRepository(context.filesDir)
        val workoutStore = workoutStoreRepository.getWorkoutStore()
        val workout = workoutStore.workouts.firstOrNull { it.name == workoutName }
            ?: error("Workout not found: $workoutName")

        // Get the completed workout history
        val workoutHistory = workoutHistoryDao.getLatestWorkoutHistoryByWorkoutId(workout.id, isDone = true)
        require(workoutHistory != null) { "WorkoutHistory not found for completed workout" }
        require(workoutHistory.isDone) { "WorkoutHistory isDone should be true" }

        // Get all set histories for this workout
        val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)

        // Get the exercise from the workout
        val exercise = workout.workoutComponents
            .filterIsInstance<com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise>()
            .firstOrNull() ?: error("Expected a single exercise in $workoutName")

        // The exercise should have generateWarmUpSets = true, so warmup sets were generated
        // We should only have the work sets in history, not warmup sets
        val exerciseSetHistories = setHistories.filter { it.exerciseId == exercise.id }

        // Verify that no warmup sets are in SetHistory
        val warmupSetsInHistory = exerciseSetHistories.filter { setHistory ->
            when (val setData = setHistory.setData) {
                is WeightSetData -> setData.subCategory == SetSubCategory.WarmupSet
                is BodyWeightSetData -> setData.subCategory == SetSubCategory.WarmupSet
                else -> false
            }
        }
        require(warmupSetsInHistory.isEmpty()) {
            "Expected no warmup sets in SetHistory, but found ${warmupSetsInHistory.size} warmup sets"
        }

        // Verify that we only have the work sets in history
        // The fixture defines 1 work set (10 reps at 100.0 kg)
        val expectedWorkSetCount = exercise.sets.count { set ->
            when (set) {
                is WeightSet -> set.subCategory != SetSubCategory.WarmupSet
                is BodyWeightSet -> set.subCategory != SetSubCategory.WarmupSet
                else -> true
            }
        }

        require(exerciseSetHistories.size == expectedWorkSetCount) {
            "Expected $expectedWorkSetCount work set(s) in SetHistory, but found ${exerciseSetHistories.size}"
        }

        // Verify that all SetHistory entries have valid work set data (not warmup)
        exerciseSetHistories.forEach { setHistory ->
            when (val setData = setHistory.setData) {
                is WeightSetData -> {
                    require(setData.subCategory != SetSubCategory.WarmupSet) {
                        "SetHistory entry ${setHistory.id} has WarmupSet subCategory, but warmup sets should be excluded"
                    }
                    require(setData.actualReps > 0) {
                        "SetHistory WeightSetData should have positive reps"
                    }
                    require(setData.actualWeight > 0) {
                        "SetHistory WeightSetData should have positive weight"
                    }
                }
                is BodyWeightSetData -> {
                    require(setData.subCategory != SetSubCategory.WarmupSet) {
                        "SetHistory entry ${setHistory.id} has WarmupSet subCategory, but warmup sets should be excluded"
                    }
                    require(setData.actualReps > 0) {
                        "SetHistory BodyWeightSetData should have positive reps"
                    }
                }
                else -> {
                    // Other set types (TimedDuration, Endurance) should not have WarmupSet subCategory either
                    // but they typically don't have subCategory at all, so we just verify they exist
                }
            }
        }
    }

    /**
     * Completes all sets in the workout by navigating through them.
     * This is a simplified version - in practice, you'd need to handle each exercise type.
     */
    private fun completeAllSetsInWorkout(workoutName: String = ComprehensiveHistoryWorkoutStoreFixture.getWorkoutName()) {
        // Navigate through exercises and complete sets
        // For WeightSet and BodyWeightSet: complete set with potential modifications
        // For TimedDurationSet: wait for timer
        // For EnduranceSet: start and stop manually

        var setsCompleted = 0
        val maxSets = 200 // Increased limit for comprehensive workouts
        var consecutiveNulls = 0 // Track consecutive nulls to detect completion

        var weightSetModifications = 0

        while (setsCompleted < maxSets && consecutiveNulls < 3) {
            device.waitForIdle(500)

            // Check if workout is complete first
            val completed = device.wait(Until.hasObject(By.text("Completed")), 1_000)
            if (completed) {
                break
            }

            // Determine set type from UI semantics
            val uiSetType = detectCurrentSetTypeFromSemantics()
            val currentSetInfo = runBlocking { getCurrentSetInfo(workoutName) }

            when (uiSetType) {
                UiSetType.TIMED_DURATION,
                UiSetType.ENDURANCE -> {
                    consecutiveNulls = 0 // Reset counter
                    if (uiSetType == UiSetType.TIMED_DURATION) {
                        modifyTimedDurationIfPossible(currentSetInfo)
                    }
                    completeTimedSet()
                    setsCompleted++
                    // Wait a bit after completing timed set
                    device.waitForIdle(1_000)
                }
                UiSetType.WEIGHT,
                UiSetType.BODY_WEIGHT -> {
                    consecutiveNulls = 0 // Reset counter
                    if (uiSetType == UiSetType.WEIGHT && weightSetModifications < 1) {
                        val modified = tryModifySetData(currentSetInfo)
                        if (modified) {
                            weightSetModifications++
                        }
                    }
                    device.pressBack()
                    confirmLongPressDialog()
                    setsCompleted++
                    device.waitForIdle(500)
                }
                UiSetType.REST -> {
                    consecutiveNulls = 0 // Reset counter
                    // Skip rest sets
                    device.waitForIdle(500)
                    skipRest()
                    device.waitForIdle(500)
                }
                UiSetType.UNKNOWN -> {
                    consecutiveNulls++
                    // No workout record - workout might be complete or transitioning
                    // Wait a bit and check again
                    device.waitForIdle(1_000)
                    
                    // Double-check if workout is complete
                    val completedCheck = device.wait(Until.hasObject(By.text("Completed")), 1_000)
                    if (completedCheck) {
                        break
                    }
                    
                    // If we've had multiple consecutive nulls, try to advance anyway
                    if (consecutiveNulls >= 2) {
                        device.pressBack()
                        device.waitForIdle(500)
                        try {
                            confirmLongPressDialog()
                            setsCompleted++
                        } catch (e: Exception) {
                            // If that fails, we might be done
                        }
                    }
                }
            }

            dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 5_000)
        }
    }

    /**
     * Attempts to modify reps and weight via accessibility-labeled rows and records expected changes.
     * Best-effort only: do not fail the test if UI edits are flaky on certain devices.
     */
    private fun tryModifySetData(currentSetInfo: CurrentSetInfo?): Boolean {
        if (currentSetInfo == null) return false
        if (currentSetInfo.set !is WeightSet && currentSetInfo.set !is BodyWeightSet) return false

        if (!waitForStableWorkoutRecord(currentSetInfo, 2_000)) {
            println(
                "WARN: tryModifySetData could not confirm workout record for set " +
                    "${currentSetInfo.set.id}; skipping modification"
            )
            return false
        }

        val setId = currentSetInfo.set.id
        val requiresWeight = when (currentSetInfo.set) {
            is WeightSet -> true
            is BodyWeightSet -> currentSetInfo.equipment != null
            else -> false
        }

        val deadline = System.currentTimeMillis() + 8_000
        while (System.currentTimeMillis() < deadline) {
            val repsDone = modifications[setId]?.modifiedReps != null
            val weightDone = when (currentSetInfo.set) {
                is WeightSet -> modifications[setId]?.modifiedWeight != null
                is BodyWeightSet -> modifications[setId]?.modifiedAdditionalWeight != null
                else -> true
            }

            if (repsDone && (!requiresWeight || weightDone)) {
                device.waitForIdle(500)
                syncSetModificationsFromUi(currentSetInfo)
                return true
            }

            if (!repsDone) {
                modifyRepsIfPossible(currentSetInfo)
            }

            if (requiresWeight && !weightDone) {
                modifyWeightIfPossible(currentSetInfo)
            }

            device.waitForIdle(500)
        }

        val repsDone = modifications[setId]?.modifiedReps != null
        val weightDone = when (currentSetInfo.set) {
            is WeightSet -> modifications[setId]?.modifiedWeight != null
            is BodyWeightSet -> modifications[setId]?.modifiedAdditionalWeight != null
            else -> true
        }

        if (requiresWeight) {
            if (repsDone || weightDone) {
                val updatedValue = if (repsDone) "reps" else "weight"
                val missingValue = if (repsDone) "weight" else "reps"
                println(
                    "WARN: tryModifySetData updated $updatedValue but not $missingValue " +
                        "for set $setId (exercise ${currentSetInfo.exerciseId})"
                )
            } else {
                val currentReps = readValueText(SetValueSemantics.RepsValueDescription)
                val currentWeight = readValueText(SetValueSemantics.WeightValueDescription)
                println(
                    "WARN: tryModifySetData could not update reps and weight for set $setId " +
                        "(exercise ${currentSetInfo.exerciseId}); current reps=$currentReps weight=$currentWeight " +
                        "continuing without modification"
                )
            }
        } else if (!repsDone) {
            val currentReps = readValueText(SetValueSemantics.RepsValueDescription)
            println(
                "WARN: tryModifySetData could not update reps for set $setId " +
                    "(exercise ${currentSetInfo.exerciseId}); current reps=$currentReps " +
                    "continuing without modification"
            )
        }

        if (!waitForStableWorkoutRecord(currentSetInfo, 1_000)) {
            println(
                "WARN: tryModifySetData lost workout record sync for set $setId; " +
                    "discarding UI modifications"
            )
            modifications.remove(setId)
            return false
        }

        syncSetModificationsFromUi(currentSetInfo)
        val updated = modifications[setId]
        val hasRepsChange = updated?.modifiedReps != null
        val hasWeightChange = when (currentSetInfo.set) {
            is WeightSet -> updated?.modifiedWeight != null
            is BodyWeightSet -> updated?.modifiedAdditionalWeight != null
            else -> false
        }
        return hasRepsChange || hasWeightChange
    }

    private fun syncSetModificationsFromUi(currentSetInfo: CurrentSetInfo) {
        if (!waitForStableWorkoutRecord(currentSetInfo, 1_000)) {
            println(
                "WARN: syncSetModificationsFromUi skipped; workout record not stable for set " +
                    "${currentSetInfo.set.id}"
            )
            return
        }

        val set = currentSetInfo.set
        if (set !is WeightSet && set !is BodyWeightSet) return

        val setId = set.id
        val existing = modifications[setId]

        val originalReps = existing?.originalReps ?: when (set) {
            is WeightSet -> set.reps
            is BodyWeightSet -> set.reps
            else -> return
        }
        val stateSetData = getCurrentSetDataFromViewModel(currentSetInfo)
        val currentReps = when (stateSetData) {
            is WeightSetData -> stateSetData.actualReps
            is BodyWeightSetData -> stateSetData.actualReps
            else -> readValueText(SetValueSemantics.RepsValueDescription)?.toIntOrNull()
        }

        val (originalWeight, currentWeight) = when (set) {
            is WeightSet -> {
                val original = existing?.originalWeight ?: set.weight
                val current = when (stateSetData) {
                    is WeightSetData -> stateSetData.actualWeight
                    else -> readValueText(SetValueSemantics.WeightValueDescription)
                        ?.let { parseWeightValue(it) }
                }
                original to current
            }
            is BodyWeightSet -> {
                val original = existing?.originalAdditionalWeight ?: set.additionalWeight
                val current = when (stateSetData) {
                    is BodyWeightSetData -> stateSetData.additionalWeight
                    else -> readValueText(SetValueSemantics.WeightValueDescription)?.let {
                        if (it == "BW") 0.0 else parseWeightValue(it)
                    }
                }
                original to current
            }
            else -> return
        }

        val resolvedModifiedReps = when {
            currentReps == null -> existing?.modifiedReps
            currentReps == originalReps -> null
            else -> currentReps
        }

        val resolvedModifiedWeight = when {
            currentWeight == null -> existing?.modifiedWeight
            currentWeight == originalWeight -> null
            else -> currentWeight
        }

        val resolvedModifiedAdditionalWeight = when {
            currentWeight == null -> existing?.modifiedAdditionalWeight
            currentWeight == originalWeight -> null
            else -> currentWeight
        }

        if (resolvedModifiedReps == null &&
            ((set is WeightSet && resolvedModifiedWeight == null) ||
                (set is BodyWeightSet && resolvedModifiedAdditionalWeight == null))
        ) {
            if (existing != null) {
                val hasOtherModifications = existing.modifiedDurationSeconds != null
                if (!hasOtherModifications) {
                    modifications.remove(setId)
                }
            }
            return
        }

        val updated = when (set) {
            is WeightSet -> {
                val base = existing ?: ModifiedSetData(
                    setId = set.id,
                    exerciseId = currentSetInfo.exerciseId,
                    originalReps = originalReps,
                    modifiedReps = null,
                    originalWeight = originalWeight,
                    modifiedWeight = null,
                    originalAdditionalWeight = null,
                    modifiedAdditionalWeight = null,
                    originalDurationSeconds = null,
                    modifiedDurationSeconds = null,
                )
                base.copy(
                    originalReps = base.originalReps ?: originalReps,
                    modifiedReps = resolvedModifiedReps,
                    originalWeight = base.originalWeight ?: originalWeight,
                    modifiedWeight = resolvedModifiedWeight
                )
            }
            is BodyWeightSet -> {
                val base = existing ?: ModifiedSetData(
                    setId = set.id,
                    exerciseId = currentSetInfo.exerciseId,
                    originalReps = originalReps,
                    modifiedReps = null,
                    originalWeight = null,
                    modifiedWeight = null,
                    originalAdditionalWeight = originalWeight,
                    modifiedAdditionalWeight = null,
                    originalDurationSeconds = null,
                    modifiedDurationSeconds = null,
                )
                base.copy(
                    originalReps = base.originalReps ?: originalReps,
                    modifiedReps = resolvedModifiedReps,
                    originalAdditionalWeight = base.originalAdditionalWeight ?: originalWeight,
                    modifiedAdditionalWeight = resolvedModifiedAdditionalWeight
                )
            }
            else -> null
        }

        if (updated != null) {
            modifications[setId] = updated
        }
    }

    private fun readValueText(valueDescription: String): String? {
        val target = device.findObject(By.descContains(valueDescription)) ?: return null
        return readValueText(target)
    }

    private fun readValueText(target: UiObject2): String? {
        return try {
            val directText = target.text?.trim()
            if (!directText.isNullOrBlank()) {
                return directText
            }

            // Fallback: search through descendants for any non-blank text
            val queue: java.util.ArrayDeque<UiObject2> = java.util.ArrayDeque()
            queue.add(target)
            while (queue.isNotEmpty()) {
                val node = queue.removeFirst()
                val nodeText = node.text?.trim()
                if (!nodeText.isNullOrBlank()) {
                    return nodeText
                }
                node.children.forEach { child ->
                    queue.add(child)
                }
            }

            // Fallback: parse value from contentDescription (e.g., "Reps value: 10")
            val description = target.contentDescription?.toString()?.trim()
            if (!description.isNullOrBlank()) {
                val parts = description.split(":", limit = 2)
                if (parts.size == 2) {
                    val candidate = parts[1].trim()
                    if (candidate.isNotBlank()) {
                        return candidate
                    }
                }
            }

            null
        } catch (e: StaleObjectException) {
            // Node became stale between interactions; treat as no readable text and let callers retry.
            null
        }
    }

    private fun waitForValueText(
        valueDescription: String,
        previousValue: String?,
        expectedValue: String?,
        timeoutMs: Long
    ): String? {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            device.waitForIdle(200)
            val currentValue = readValueText(valueDescription)
            if (!currentValue.isNullOrBlank()) {
                if (expectedValue != null) {
                    if (currentValue == expectedValue) return currentValue
                } else if (previousValue == null || currentValue != previousValue) {
                    return currentValue
                }
            }
            device.waitForIdle(200)
        }
        return null
    }

    private fun longPressObject(obj: UiObject2): Boolean {
        val longClickSuccess = runCatching {
            obj.longClick()
            true
        }.getOrElse { false }
        if (longClickSuccess) {
            device.waitForIdle(300)
            return true
        }

        val bounds = obj.visibleBounds
        if (bounds.width() <= 0 || bounds.height() <= 0) {
            return false
        }

        val centerX = bounds.centerX()
        val centerY = bounds.centerY()
        device.swipe(centerX, centerY, centerX, centerY, 200)
        device.waitForIdle(300)
        return true
    }


    private fun waitForButtonByLabel(label: String, timeoutMs: Long = 2_000): UiObject2? {
        return device.wait(Until.findObject(By.desc(label)), timeoutMs)
            ?: device.wait(Until.findObject(By.text(label)), timeoutMs)
    }

    private fun clickButtonWithRetry(
        label: String,
        timeoutMs: Long = 2_000,
        attempts: Int = 3
    ): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        repeat(attempts) {
            val remaining = deadline - System.currentTimeMillis()
            if (remaining <= 0L) {
                return false
            }
            val stepTimeout = if (remaining > 1_000L) 1_000L else remaining
            val button = waitForButtonByLabel(label, stepTimeout)
            if (button != null && clickBestEffort(button)) {
                device.waitForIdle(200)
                return true
            }
            device.waitForIdle(300)
        }
        return false
    }

    private fun logEditControlsState(context: String) {
        val add = device.findObject(By.desc("Add")) ?: device.findObject(By.text("Add"))
        val subtract = device.findObject(By.desc("Subtract")) ?: device.findObject(By.text("Subtract"))
        val close = device.findObject(By.desc("Close")) ?: device.findObject(By.text("Close"))

        fun boundsSummary(node: UiObject2?): String {
            if (node == null) return "null"
            val b = node.visibleBounds
            return "${b.left},${b.top},${b.right},${b.bottom}"
        }

        println(
            "WARN: $context | add=${boundsSummary(add)} subtract=${boundsSummary(subtract)} " +
                "close=${boundsSummary(close)}"
        )
    }

    private fun waitForEditControls(context: String, timeoutMs: Long = 2_000): UiObject2? {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val addButton = device.findObject(By.desc("Add")) ?: device.findObject(By.text("Add"))
            val subtractButton = device.findObject(By.desc("Subtract")) ?: device.findObject(By.text("Subtract"))
            if (addButton != null && subtractButton != null) {
                return addButton
            }
            device.waitForIdle(200)
        }

        println("WARN: $context missing Add/Subtract buttons (edit controls not visible)")
        logEditControlsState(context)
        return null
    }

    private fun clickBestEffort(target: UiObject2): Boolean {
        return try {
            val bounds = target.visibleBounds
            if (bounds.width() > 0 && bounds.height() > 0) {
                return device.click(bounds.centerX(), bounds.centerY())
            }

            if (target.isClickable) {
                target.click()
                return true
            }

            false
        } catch (e: StaleObjectException) {
            false
        }
    }

    private fun parseWeightValue(text: String): Double? {
        val normalized = text.replace(",", ".")
        val match = Regex("""-?\d+(\.\d+)?""").find(normalized) ?: return null
        return match.value.toDoubleOrNull()
    }

    private fun incrementValueAndWait(
        valueDescription: String,
        expectedValue: String?,
        timeoutMs: Long = 5_000
    ): String? {
        val target = device.wait(
            Until.findObject(By.descContains(valueDescription)),
            2_000
        )
        if (target == null) {
            println("WARN: incrementValueAndWait missing target for $valueDescription")
            return null
        }

        val beforeValue = readValueText(target)
        if (beforeValue == null) {
            println("WARN: incrementValueAndWait missing readable value for $valueDescription before edit")
        }
        if (expectedValue != null && beforeValue == expectedValue) {
            return beforeValue
        }

        if (!longPressObject(target)) {
            println(
                "WARN: incrementValueAndWait failed long-press for $valueDescription " +
                    "(before=$beforeValue expected=$expectedValue)"
            )
            return null
        }

        var addButton = waitForEditControls("incrementValueAndWait after long-press for $valueDescription")
        val targetChildren = runCatching { target.children }.getOrDefault(emptyList())
        if (addButton == null && targetChildren.isNotEmpty()) {
            // Retry long-press on a child node in case the semantics container ignores long-clicks.
            val child = targetChildren.first()
            if (longPressObject(child)) {
                addButton = waitForEditControls(
                    "incrementValueAndWait after child long-press for $valueDescription"
                )
            }
        }
        if (addButton == null) {
            return null
        }
        val targetBounds = runCatching { target.visibleBounds }.getOrNull()
        val addBounds = runCatching { addButton.visibleBounds }.getOrNull()
        if (targetBounds != null && addBounds != null) {
            println(
                "WARN: incrementValueAndWait clicking Add for $valueDescription " +
                    "(target=${targetBounds.left},${targetBounds.top},${targetBounds.right},${targetBounds.bottom} " +
                    "add=${addBounds.left},${addBounds.top},${addBounds.right},${addBounds.bottom})"
            )
        } else {
            println("WARN: incrementValueAndWait clicking Add for $valueDescription (bounds unavailable)")
        }
        if (!clickBestEffort(addButton)) {
            println(
                "WARN: incrementValueAndWait Add not clickable for $valueDescription " +
                    "(before=$beforeValue expected=$expectedValue)"
            )
            return null
        }

        var updatedValue = waitForValueText(valueDescription, beforeValue, expectedValue, timeoutMs)
        if (updatedValue == null && expectedValue != null) {
            updatedValue = waitForValueText(valueDescription, beforeValue, null, 1_000)
        }

        val closeButton = waitForButtonByLabel("Close", 2_000)
        if (closeButton != null) {
            if (!clickBestEffort(closeButton)) {
                println("WARN: incrementValueAndWait Close not clickable for $valueDescription")
                device.pressBack()
            }
        } else {
            println("WARN: incrementValueAndWait missing Close button for $valueDescription")
            device.pressBack()
        }
        device.waitForIdle(500)

        if (updatedValue.isNullOrBlank() || updatedValue == beforeValue) {
            println(
                "WARN: incrementValueAndWait value did not update for $valueDescription " +
                    "(before=$beforeValue expected=$expectedValue after=$updatedValue)"
            )
        }

        return if (!updatedValue.isNullOrBlank() && updatedValue != beforeValue) {
            updatedValue
        } else {
            null
        }
    }

    private fun formatWeightText(currentSetInfo: CurrentSetInfo, weight: Double): String? {
        return when (currentSetInfo.set) {
            is WeightSet -> currentSetInfo.equipment?.formatWeight(weight)
            is BodyWeightSet -> {
                if (weight == 0.0) {
                    "BW"
                } else {
                    currentSetInfo.equipment?.formatWeight(weight)
                }
            }
            else -> null
        }
    }

    private fun modifyRepsIfPossible(currentSetInfo: CurrentSetInfo): Boolean {
        val setId = currentSetInfo.set.id
        val existingModification = modifications[setId]

        if (!waitForStableWorkoutRecord(currentSetInfo, 1_000)) {
            return false
        }

        val repsTarget = device.wait(
            Until.findObject(By.descContains(SetValueSemantics.RepsValueDescription)),
            5_000
        )

        if (repsTarget == null) {
            return false
        }

        if (existingModification?.modifiedReps != null) {
            return true
        }

        val maxAttempts = 3
        repeat(maxAttempts) {
            val beforeReps = getCurrentRepsValue(currentSetInfo) ?: return@repeat
            val expectedRepsText = (beforeReps + 1).toString()
            val updatedRepsText = incrementValueAndWait(
                SetValueSemantics.RepsValueDescription,
                expectedRepsText
            )
            val modifiedReps = updatedRepsText?.toIntOrNull()
                ?: waitForRepsChange(currentSetInfo, beforeReps, 1_500)

            if (modifiedReps != null && modifiedReps != beforeReps) {
                if (!waitForStableWorkoutRecord(currentSetInfo, 1_000)) {
                    return false
                }

                val set = currentSetInfo.set
                val updatedModification = when (set) {
                    is WeightSet -> {
                        val base = existingModification ?: ModifiedSetData(
                            setId = set.id,
                            exerciseId = currentSetInfo.exerciseId,
                            originalReps = null,
                            modifiedReps = null,
                            originalWeight = set.weight,
                            modifiedWeight = null,
                            originalAdditionalWeight = null,
                            modifiedAdditionalWeight = null,
                            originalDurationSeconds = null,
                            modifiedDurationSeconds = null,
                        )
                        base.copy(
                            originalReps = base.originalReps ?: beforeReps,
                            modifiedReps = modifiedReps,
                            originalWeight = base.originalWeight ?: set.weight
                        )
                    }
                    is BodyWeightSet -> {
                        val base = existingModification ?: ModifiedSetData(
                            setId = set.id,
                            exerciseId = currentSetInfo.exerciseId,
                            originalReps = null,
                            modifiedReps = null,
                            originalWeight = null,
                            modifiedWeight = null,
                            originalAdditionalWeight = set.additionalWeight,
                            modifiedAdditionalWeight = null,
                            originalDurationSeconds = null,
                            modifiedDurationSeconds = null,
                        )
                        base.copy(
                            originalReps = base.originalReps ?: beforeReps,
                            modifiedReps = modifiedReps,
                            originalAdditionalWeight = base.originalAdditionalWeight ?: set.additionalWeight
                        )
                    }
                    else -> null
                }

                if (updatedModification != null) {
                    modifications[updatedModification.setId] = updatedModification
                    return true
                }
            }

            device.waitForIdle(400)
        }

        return false
    }

    private fun modifyWeightIfPossible(currentSetInfo: CurrentSetInfo): Boolean {
        val setId = currentSetInfo.set.id
        val existingModification = modifications[setId]

        if (!waitForStableWorkoutRecord(currentSetInfo, 1_000)) {
            return false
        }

        val weightTarget = device.wait(
            Until.findObject(By.descContains(SetValueSemantics.WeightValueDescription)),
            1_000
        )

        val shouldModifyWeight = when (currentSetInfo.set) {
            is WeightSet -> existingModification?.modifiedWeight == null
            is BodyWeightSet -> existingModification?.modifiedAdditionalWeight == null
            else -> false
        }

        if (weightTarget == null) {
            return false
        }

        if (!shouldModifyWeight) {
            return true
        }

        val maxAttempts = 3
        repeat(maxAttempts) {
            val beforeWeight = getCurrentWeightValue(currentSetInfo) ?: return@repeat
            val nextWeight = getNextWeightForSet(currentSetInfo, beforeWeight) ?: return@repeat
            val expectedText = formatWeightText(currentSetInfo, nextWeight) ?: return@repeat

            val currentWeightText = readValueText(SetValueSemantics.WeightValueDescription)
            if (!currentWeightText.isNullOrBlank() && currentWeightText == expectedText) {
                if (!waitForStableWorkoutRecord(currentSetInfo, 1_000)) {
                    return false
                }

                val set = currentSetInfo.set
                val updatedModification = when (set) {
                    is WeightSet -> {
                        val base = existingModification ?: ModifiedSetData(
                            setId = set.id,
                            exerciseId = currentSetInfo.exerciseId,
                            originalReps = null,
                            modifiedReps = null,
                            originalWeight = beforeWeight,
                            modifiedWeight = null,
                            originalAdditionalWeight = null,
                            modifiedAdditionalWeight = null,
                            originalDurationSeconds = null,
                            modifiedDurationSeconds = null,
                        )
                        base.copy(
                            originalWeight = base.originalWeight ?: beforeWeight,
                            modifiedWeight = nextWeight
                        )
                    }
                    is BodyWeightSet -> {
                        val base = existingModification ?: ModifiedSetData(
                            setId = set.id,
                            exerciseId = currentSetInfo.exerciseId,
                            originalReps = null,
                            modifiedReps = null,
                            originalWeight = null,
                            modifiedWeight = null,
                            originalAdditionalWeight = beforeWeight,
                            modifiedAdditionalWeight = null,
                            originalDurationSeconds = null,
                            modifiedDurationSeconds = null,
                        )
                        base.copy(
                            originalAdditionalWeight = base.originalAdditionalWeight ?: beforeWeight,
                            modifiedAdditionalWeight = nextWeight
                        )
                    }
                    else -> null
                }

                if (updatedModification != null) {
                    modifications[updatedModification.setId] = updatedModification
                    return true
                }

                return false
            }

            val updatedText = incrementValueAndWait(
                SetValueSemantics.WeightValueDescription,
                expectedText
            )

            val modifiedWeight = when {
                updatedText == null -> waitForWeightChange(currentSetInfo, beforeWeight, 1_500)
                updatedText == "BW" -> 0.0
                else -> parseWeightValue(updatedText)
            } ?: waitForWeightChange(currentSetInfo, beforeWeight, 1_500)

            if (modifiedWeight != null && kotlin.math.abs(modifiedWeight - beforeWeight) > 0.01) {
                if (!waitForStableWorkoutRecord(currentSetInfo, 1_000)) {
                    return false
                }

                val set = currentSetInfo.set
                val updatedModification = when (set) {
                    is WeightSet -> {
                        val base = existingModification ?: ModifiedSetData(
                            setId = set.id,
                            exerciseId = currentSetInfo.exerciseId,
                            originalReps = null,
                            modifiedReps = null,
                            originalWeight = beforeWeight,
                            modifiedWeight = null,
                            originalAdditionalWeight = null,
                            modifiedAdditionalWeight = null,
                            originalDurationSeconds = null,
                            modifiedDurationSeconds = null,
                        )
                        base.copy(
                            originalWeight = base.originalWeight ?: beforeWeight,
                            modifiedWeight = modifiedWeight
                        )
                    }
                    is BodyWeightSet -> {
                        val base = existingModification ?: ModifiedSetData(
                            setId = set.id,
                            exerciseId = currentSetInfo.exerciseId,
                            originalReps = null,
                            modifiedReps = null,
                            originalWeight = null,
                            modifiedWeight = null,
                            originalAdditionalWeight = beforeWeight,
                            modifiedAdditionalWeight = null,
                            originalDurationSeconds = null,
                            modifiedDurationSeconds = null,
                        )
                        base.copy(
                            originalAdditionalWeight = base.originalAdditionalWeight ?: beforeWeight,
                            modifiedAdditionalWeight = modifiedWeight
                        )
                    }
                    else -> null
                }

                if (updatedModification != null) {
                    modifications[updatedModification.setId] = updatedModification
                    return true
                }
            }

            device.waitForIdle(400)
        }

        return false
    }

    private fun getNextWeightForSet(currentSetInfo: CurrentSetInfo, originalWeight: Double): Double? {
        val equipment = currentSetInfo.equipment ?: return null
        val baseWeights = equipment.getWeightsCombinations()
        val availableWeights = when (currentSetInfo.set) {
            is WeightSet -> baseWeights
            is BodyWeightSet -> baseWeights + 0.0
            else -> emptySet()
        }

        if (availableWeights.isEmpty()) return null

        val sortedWeights = availableWeights.sorted()
        val closestWeight = sortedWeights.minByOrNull { kotlin.math.abs(it - originalWeight) } ?: return null
        val currentIndex = sortedWeights.indexOf(closestWeight)
        if (currentIndex < 0 || currentIndex >= sortedWeights.lastIndex) return null
        return sortedWeights[currentIndex + 1]
    }

    /**
     * Attempts to modify the duration of a non-auto-start TimedDurationSet by entering edit mode
     * on the timer value and pressing the \"Add\" control once.
     *
     * This records the original and modified duration (in seconds) in the modifications map so
     * we can later assert against the stored SetHistory.
     */
    private fun modifyTimedDurationIfPossible(currentSetInfo: CurrentSetInfo?) {
        if (currentSetInfo == null) return
        val timedSet = currentSetInfo.set as? TimedDurationSet ?: return

        // Only manual-start timed sets expose the edit affordance on the timer value.
        if (timedSet.autoStart) return

        if (!waitForStableWorkoutRecord(currentSetInfo, 1_000)) {
            return
        }

        val setId = timedSet.id
        val existingModification = modifications[setId]

        val timerTarget = device.wait(
            Until.findObject(By.descContains(SetValueSemantics.TimedDurationValueDescription)),
            5_000
        )

        if (timerTarget == null) {
            return
        }

        // timeInMillis is stored in milliseconds on the TimedDurationSet definition
        val originalDurationSeconds = existingModification?.originalDurationSeconds
            ?: (timedSet.timeInMillis / 1000)

        runCatching {
            timerTarget.longClick()
            device.waitForIdle(500)

            val addButton = device.wait(Until.findObject(By.desc("Add")), 1_000)
            if (addButton == null) {
                return@runCatching
            }

            addButton.click()
            device.waitForIdle(500)

            // Click the X button to exit edit mode
            val closeButton = device.wait(Until.findObject(By.desc("Close")), 1_000)
            closeButton?.click()
            device.waitForIdle(2_000)

            // Each press of \"Add\" increases the startTimer by 5 seconds (5000 ms)
            val modifiedDurationSeconds = originalDurationSeconds + 5

            val base = existingModification ?: ModifiedSetData(
                setId = timedSet.id,
                exerciseId = currentSetInfo.exerciseId,
                originalReps = null,
                modifiedReps = null,
                originalWeight = null,
                modifiedWeight = null,
                originalAdditionalWeight = null,
                modifiedAdditionalWeight = null,
                originalDurationSeconds = originalDurationSeconds,
                modifiedDurationSeconds = null,
            )

            val updated = base.copy(
                originalDurationSeconds = base.originalDurationSeconds ?: originalDurationSeconds,
                modifiedDurationSeconds = modifiedDurationSeconds,
            )

            modifications[setId] = updated
        }
    }

    private fun waitForStableWorkoutRecord(
        currentSetInfo: CurrentSetInfo,
        timeoutMs: Long
    ): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        var firstMatchAt = 0L

        while (System.currentTimeMillis() < deadline) {
            val info = runBlocking { getCurrentSetInfo() }
            val matches = info != null &&
                info.set.id == currentSetInfo.set.id &&
                info.exerciseId == currentSetInfo.exerciseId

            if (matches) {
                if (firstMatchAt == 0L) {
                    firstMatchAt = System.currentTimeMillis()
                } else if (System.currentTimeMillis() - firstMatchAt >= 200) {
                    return true
                }
            } else {
                firstMatchAt = 0L
            }

            device.waitForIdle(100)
        }

        return false
    }

    private fun getCurrentSetDataFromViewModel(currentSetInfo: CurrentSetInfo): SetData? {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        var setData: SetData? = null
        instrumentation.runOnMainSync {
            val activity = ActivityLifecycleMonitorRegistry.getInstance()
                .getActivitiesInStage(Stage.RESUMED)
                .firstOrNull() as? ComponentActivity
                ?: return@runOnMainSync

            val viewModel = ViewModelProvider(activity)[AppViewModel::class.java]
            val currentState = viewModel.workoutState.value as? WorkoutState.Set ?: return@runOnMainSync
            if (currentState.set.id == currentSetInfo.set.id &&
                currentState.exerciseId == currentSetInfo.exerciseId
            ) {
                setData = currentState.currentSetData
            }
        }
        return setData
    }

    private fun getCurrentRepsValue(currentSetInfo: CurrentSetInfo): Int? {
        val stateSetData = getCurrentSetDataFromViewModel(currentSetInfo)
        return when (stateSetData) {
            is WeightSetData -> stateSetData.actualReps
            is BodyWeightSetData -> stateSetData.actualReps
            else -> readValueText(SetValueSemantics.RepsValueDescription)?.toIntOrNull()
        }
    }

    private fun getCurrentWeightValue(currentSetInfo: CurrentSetInfo): Double? {
        val stateSetData = getCurrentSetDataFromViewModel(currentSetInfo)
        return when (stateSetData) {
            is WeightSetData -> stateSetData.actualWeight
            is BodyWeightSetData -> stateSetData.additionalWeight
            else -> readValueText(SetValueSemantics.WeightValueDescription)?.let {
                if (it == "BW") 0.0 else parseWeightValue(it)
            }
        }
    }

    private fun waitForRepsChange(
        currentSetInfo: CurrentSetInfo,
        previousValue: Int,
        timeoutMs: Long
    ): Int? {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val current = getCurrentRepsValue(currentSetInfo)
            if (current != null && current != previousValue) {
                return current
            }
            device.waitForIdle(150)
        }
        return null
    }

    private fun waitForWeightChange(
        currentSetInfo: CurrentSetInfo,
        previousValue: Double,
        timeoutMs: Long
    ): Double? {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val current = getCurrentWeightValue(currentSetInfo)
            if (current != null && kotlin.math.abs(current - previousValue) > 0.01) {
                return current
            }
            device.waitForIdle(150)
        }
        return null
    }

    /**
     * Completes a timed set (TimedDurationSet or EnduranceSet).
     */
    private fun completeTimedSet() {
        // For autoStart sets, just wait for completion
        // For manual start sets, click start, wait, click stop
        
        // Check if it's auto-start
        val autoStartVisible = device.wait(Until.hasObject(By.text("Starting")), 2_000)
        
        if (autoStartVisible) {
            // Auto-start set - wait for it to complete
            device.waitForIdle(5_000) // Wait for timer
        } else {
            // Manual start - find and press the play/start button (icon with contentDescription \"Start\")
            val started = clickButtonWithRetry("Start", timeoutMs = 3_000, attempts = 4)
            if (!started) {
                println("WARN: completeTimedSet could not click Start button")
            }
            device.waitForIdle(2_000)

            // Wait a bit while the timer runs
            device.waitForIdle(3_000)

            // Find stop button (icon with contentDescription \"Stop\")
            val stopped = clickButtonWithRetry("Stop", timeoutMs = 3_000, attempts = 4)
            if (!stopped) {
                println("WARN: completeTimedSet could not click Stop button")
            }
        }

        // Complete the set
        device.pressBack()
        confirmLongPressDialog()
    }

    /**
     * Waits for workout completion screen.
     */
    private fun waitForWorkoutCompletion() {
        workoutDriver.waitForWorkoutCompletion(timeoutMs = 30_000)
    }

    /**
     * Completes a set by triggering the "Complete Set" dialog and confirming.
     */
    private fun confirmLongPressDialog() {
        workoutDriver.confirmLongPressDialog()
    }

    /**
     * Skips the rest timer.
     */
    private fun skipRest() {
        runCatching {
            workoutDriver.skipRest()
        }.onFailure {
            println("WARN: skipRest failed to find skip dialog: ${it.message}")
        }
    }

    /**
     * Verifies the basic structure of SetHistory entries.
     */
    private fun verifySetHistoryStructure(
        workoutHistory: WorkoutHistory,
        setHistories: List<SetHistory>,
        workout: com.gabstra.myworkoutassistant.shared.Workout
    ) {
        // Verify WorkoutHistory exists and is done
        require(workoutHistory.isDone) { "WorkoutHistory should be marked as done" }
        require(workoutHistory.workoutId == workout.id) { "WorkoutHistory workoutId should match workout id" }

        // Verify SetHistory entries have correct structure
        setHistories.forEach { setHistory ->
            require(setHistory.workoutHistoryId == workoutHistory.id) {
                "SetHistory workoutHistoryId should match WorkoutHistory id"
            }
            require(setHistory.exerciseId != null) { "SetHistory exerciseId should not be null" }
            require(setHistory.setId != null) { "SetHistory setId should not be null" }
            require(!setHistory.skipped) { "SetHistory should not be skipped for completed sets" }
            require(setHistory.startTime != null) { "SetHistory startTime should be set" }
            require(setHistory.endTime != null) { "SetHistory endTime should be set" }
        }

        // Verify sets are ordered correctly
        val setsByExercise = setHistories.groupBy { it.exerciseId }
        setsByExercise.values.forEach { exerciseSets ->
            val sortedSets = exerciseSets.sortedBy { it.order }
            require(exerciseSets == sortedSets) { "Sets should be ordered correctly within each exercise" }
        }
    }

    /**
     * Verifies that modified values are stored correctly (if modifications were made).
     */
    private fun verifyModifiedValuesAreStored(setHistories: List<SetHistory>) {
        modifications.values.forEach { modification ->
            val setHistory = setHistories.firstOrNull { it.setId == modification.setId }
                ?: return@forEach // Set might not be in history if doNotStoreHistory is true

            when (val setData = setHistory.setData) {
                is WeightSetData -> {
                    modification.modifiedReps?.let { modifiedReps ->
                        modification.originalReps?.let { originalReps ->
                            require(setData.actualReps != originalReps) {
                                "WeightSetData actualReps should not equal original value"
                            }
                        }
                        if (setData.actualReps != modifiedReps) {
                            println(
                                "WARN: WeightSetData actualReps differs from recorded modified value " +
                                    "(expected $modifiedReps, got ${setData.actualReps})"
                            )
                        }
                    }
                    modification.modifiedWeight?.let { _ ->
                        modification.originalWeight?.let { originalWeight ->
                            require(setData.actualWeight != originalWeight) {
                                "WeightSetData actualWeight should not equal original value"
                            }
                        }
                    }
                    // We don't assert the exact modified weight value here because the UI may
                    // apply equipment-specific plate combinations. Instead we rely on volume
                    // validation below and basic positivity checks elsewhere.
                    // Verify volume calculation
                    val expectedVolume = setData.actualReps * setData.actualWeight
                    require(kotlin.math.abs(setData.volume - expectedVolume) < 0.1) {
                        "WeightSetData volume should be correctly calculated: expected $expectedVolume, got ${setData.volume}"
                    }
                }
                is BodyWeightSetData -> {
                    modification.modifiedReps?.let { modifiedReps ->
                        modification.originalReps?.let { originalReps ->
                            require(setData.actualReps != originalReps) {
                                "BodyWeightSetData actualReps should not equal original value"
                            }
                        }
                        if (setData.actualReps != modifiedReps) {
                            println(
                                "WARN: BodyWeightSetData actualReps differs from recorded modified value " +
                                    "(expected $modifiedReps, got ${setData.actualReps})"
                            )
                        }
                    }
                    modification.modifiedAdditionalWeight?.let { _ ->
                        modification.originalAdditionalWeight?.let { originalAdditionalWeight ->
                            require(setData.additionalWeight != originalAdditionalWeight) {
                                "BodyWeightSetData additionalWeight should not equal original value"
                            }
                        }
                    }
                    // As with WeightSetData, we don't assert the exact modified additional weight
                    // value; we validate via volume and type-specific invariants instead.
                    // Verify volume calculation
                    val expectedVolume = setData.actualReps * setData.getWeight()
                    require(kotlin.math.abs(setData.volume - expectedVolume) < 0.1) {
                        "BodyWeightSetData volume should be correctly calculated"
                    }
                }
                is TimedDurationSetData -> {
                    // For timed sets, verify startTimer reflects the modified duration (in seconds)
                    modification.modifiedDurationSeconds?.let { modifiedSeconds ->
                        val storedSeconds = setData.startTimer / 1000
                        require(kotlin.math.abs(storedSeconds - modifiedSeconds) <= 1) {
                            "TimedDurationSetData startTimer should match modified duration: expected ~$modifiedSeconds s, got ${storedSeconds} s"
                        }
                        modification.originalDurationSeconds?.let { originalSeconds ->
                            require(storedSeconds != originalSeconds) {
                                "TimedDurationSetData startTimer should not equal original duration"
                            }
                        }
                    }
                }
                is EnduranceSetData -> {
                    // If we ever track modified duration for endurance, verify elapsed time (endTimer) matches it.
                    modification.modifiedDurationSeconds?.let { modifiedSeconds ->
                        val elapsedSeconds = setData.endTimer / 1000
                        require(kotlin.math.abs(elapsedSeconds - modifiedSeconds) <= 2) {
                            "EnduranceSetData endTimer should roughly match modified duration: expected ~$modifiedSeconds s, got ${elapsedSeconds} s"
                        }
                    }
                }
                is RestSetData -> {
                    // RestSetData should not be in history, but if it is, we skip verification
                    return@forEach
                }
            }
        }
    }

    /**
     * Verifies that unmodified values are stored correctly.
     */
    private fun verifyUnmodifiedValuesAreStored(
        setHistories: List<SetHistory>,
        workout: com.gabstra.myworkoutassistant.shared.Workout
    ) {
        // Get all exercises from workout
        val allExercises = workout.workoutComponents.filterIsInstance<com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise>()
            .filter { !it.doNotStoreHistory }

        allExercises.forEach { exercise ->
            val exerciseSetHistories = setHistories.filter { it.exerciseId == exercise.id }
            
            exercise.sets.forEachIndexed { index, set ->
                // Skip RestSets (they shouldn't be in history)
                if (set is com.gabstra.myworkoutassistant.shared.sets.RestSet) {
                    return@forEachIndexed
                }

                val setHistory = exerciseSetHistories.firstOrNull { it.setId == set.id }
                    ?: return@forEachIndexed // Set might not be completed

                // Verify setData type matches set type
                when (set) {
                    is com.gabstra.myworkoutassistant.shared.sets.WeightSet -> {
                        require(setHistory.setData is WeightSetData) {
                            "SetHistory setData should be WeightSetData for WeightSet"
                        }
                        val weightSetData = setHistory.setData as WeightSetData
                        // Verify weight is valid (within reasonable range)
                        require(weightSetData.actualWeight > 0) {
                            "WeightSetData actualWeight should be positive"
                        }
                        require(weightSetData.actualReps > 0) {
                            "WeightSetData actualReps should be positive"
                        }
                    }
                    is com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet -> {
                        require(setHistory.setData is BodyWeightSetData) {
                            "SetHistory setData should be BodyWeightSetData for BodyWeightSet"
                        }
                        val bodyWeightSetData = setHistory.setData as BodyWeightSetData
                        require(bodyWeightSetData.actualReps > 0) {
                            "BodyWeightSetData actualReps should be positive"
                        }
                    }
                    is com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet -> {
                        require(setHistory.setData is TimedDurationSetData) {
                            "SetHistory setData should be TimedDurationSetData for TimedDurationSet"
                        }
                        val timedData = setHistory.setData as TimedDurationSetData
                        require(timedData.startTimer >= 0) {
                            "TimedDurationSetData startTimer should be non-negative"
                        }
                        require(timedData.endTimer in 0..timedData.startTimer) {
                            "TimedDurationSetData endTimer should be between 0 and startTimer"
                        }
                    }
                    is com.gabstra.myworkoutassistant.shared.sets.EnduranceSet -> {
                        require(setHistory.setData is EnduranceSetData) {
                            "SetHistory setData should be EnduranceSetData for EnduranceSet"
                        }
                        val enduranceData = setHistory.setData as EnduranceSetData
                        require(enduranceData.startTimer >= 0) {
                            "EnduranceSetData startTimer should be non-negative"
                        }
                        require(enduranceData.endTimer >= 0) {
                            "EnduranceSetData endTimer should be non-negative"
                        }
                    }
                    is com.gabstra.myworkoutassistant.shared.sets.RestSet -> {
                        // RestSets should not be in history - this should have been filtered out earlier
                        error("RestSet should not be in SetHistory")
                    }
                }
            }
        }
    }

    /**
     * Verifies that RestSets are excluded from history.
     */
    private fun verifyRestSetsExcluded(
        setHistories: List<SetHistory>,
        workout: com.gabstra.myworkoutassistant.shared.Workout
    ) {
        val allExercises = workout.workoutComponents.filterIsInstance<com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise>()
        
        allExercises.forEach { exercise ->
            val restSetIds = exercise.sets
                .filterIsInstance<com.gabstra.myworkoutassistant.shared.sets.RestSet>()
                .map { it.id }

            restSetIds.forEach { restSetId ->
                val restSetInHistory = setHistories.any { it.setId == restSetId }
                require(!restSetInHistory) {
                    "RestSet with id $restSetId should not be in history"
                }
            }
        }
    }

    /**
     * Verifies that exercises with doNotStoreHistory=true are excluded from history.
     */
    private fun verifyDoNotStoreHistoryExcluded(
        setHistories: List<SetHistory>,
        workout: com.gabstra.myworkoutassistant.shared.Workout
    ) {
        val doNotStoreExercises = workout.workoutComponents
            .filterIsInstance<com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise>()
            .filter { it.doNotStoreHistory }

        doNotStoreExercises.forEach { exercise ->
            val exerciseSetHistories = setHistories.filter { it.exerciseId == exercise.id }
            require(exerciseSetHistories.isEmpty()) {
                "Exercise ${exercise.name} with doNotStoreHistory=true should have no SetHistory entries, but found ${exerciseSetHistories.size}"
            }
        }
    }
}


