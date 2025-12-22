package com.gabstra.myworkoutassistant.e2e

import android.util.Log
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.composables.SetValueSemantics
import com.gabstra.myworkoutassistant.e2e.fixtures.ComprehensiveHistoryWorkoutStoreFixture
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import kotlinx.coroutines.runBlocking
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

/**
 * E2E test to verify that exercise history is properly stored after workout completion.
 * Tests all exercise types, equipment types, and verifies that modified set data during
 * execution is correctly stored in the database.
 */
@RunWith(AndroidJUnit4::class)
class ExerciseHistoryStorageE2ETest : BaseWearE2ETest() {

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
        val originalDuration: Int?,
        val actualDuration: Int?
    )

    private val modifications = mutableMapOf<UUID, ModifiedSetData>()

    private data class CurrentSetInfo(
        val set: com.gabstra.myworkoutassistant.shared.sets.Set,
        val exerciseId: UUID
    )

    /**
     * Determines the current set info by querying the database (WorkoutRecord).
     * This is more reliable than UI detection since it directly accesses the workout state.
     *
     * @return The current set info, or null if no workout record exists or workout is complete
     */
    private suspend fun getCurrentSetInfo(): CurrentSetInfo? {
        val db = AppDatabase.getDatabase(context)
        val workoutRecordDao = db.workoutRecordDao()
        
        // Get workout name and find workout
        val workoutName = ComprehensiveHistoryWorkoutStoreFixture.getWorkoutName()
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
        
        return CurrentSetInfo(
            set = exercise.sets[setIndex],
            exerciseId = exercise.id
        )
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

    /**
     * Completes all sets in the workout by navigating through them.
     * This is a simplified version - in practice, you'd need to handle each exercise type.
     */
    private fun completeAllSetsInWorkout() {
        // Navigate through exercises and complete sets
        // For WeightSet and BodyWeightSet: complete set with potential modifications
        // For TimedDurationSet: wait for timer
        // For EnduranceSet: start and stop manually

        var setsCompleted = 0
        val maxSets = 200 // Increased limit for comprehensive workouts
        var consecutiveNulls = 0 // Track consecutive nulls to detect completion

        while (setsCompleted < maxSets && consecutiveNulls < 3) {
            device.waitForIdle(500)

            // Check if workout is complete first
            val completed = device.wait(Until.hasObject(By.text("Completed")), 1_000)
            if (completed) {
                break
            }

            // Determine set type from database (more reliable than UI detection)
            val currentSetInfo = runBlocking { getCurrentSetInfo() }
            val currentSet = currentSetInfo?.set
            
            when (currentSet) {
                is TimedDurationSet, is EnduranceSet -> {
                    consecutiveNulls = 0 // Reset counter
                    completeTimedSet()
                    setsCompleted++
                    // Wait a bit after completing timed set
                    device.waitForIdle(1_000)
                }
                is WeightSet, is BodyWeightSet -> {
                    consecutiveNulls = 0 // Reset counter
                    tryModifySetData(currentSetInfo)
                    device.pressBack()
                    confirmLongPressDialog()
                    setsCompleted++
                    device.waitForIdle(500)
                }
                is RestSet -> {
                    consecutiveNulls = 0 // Reset counter
                    // Skip rest sets
                    device.waitForIdle(500)
                    skipRest()
                    device.waitForIdle(500)
                }
                null -> {
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
     * Legacy exploration for UI-based modifications (kept for reference).
     */
    /*
    private fun tryModifySetData() {
        Log.d("ExerciseHistoryStorageE2ETest", "tryModifySetData() called - starting modification attempt")
        try {
            // Wait for screen to be ready
            device.waitForIdle(500)
            
            // The reps and weight are in clickable Row containers in the center area
            // We'll try to find clickable elements or long-press in the area where they're displayed
            val width = device.displayWidth
            val height = device.displayHeight
            val centerX = width / 2
            val centerY = height / 2
            
            Log.d("ExerciseHistoryStorageE2ETest", "Screen dimensions: ${width}x${height}, center: ($centerX, $centerY)")
            
            // Approach 1: Try to find all clickable/long-clickable elements
            val clickableObjects = try {
                device.findObjects(By.clickable(true))
            } catch (e: Exception) {
                Log.w("ExerciseHistoryStorageE2ETest", "Failed to find clickable objects: ${e.message}")
                emptyList()
            }
            Log.d("ExerciseHistoryStorageE2ETest", "Found ${clickableObjects.size} clickable objects")
            
            // Log all clickable objects to see what we have
            clickableObjects.forEachIndexed { index, obj ->
                Log.d("ExerciseHistoryStorageE2ETest", "Clickable object $index: text='${obj.text}', desc='${obj.contentDescription}', bounds=${obj.bounds}, clickable=${obj.isClickable}, longClickable=${obj.isLongClickable}")
            }
            
            // Approach 2: Try to find elements by text that might be numeric
            // Even if they're in clickable containers, the text might still be accessible
            val allTextObjects = try {
                device.findObjects(By.clazz("android.widget.TextView"))
            } catch (e: Exception) {
                Log.w("ExerciseHistoryStorageE2ETest", "Failed to find TextView objects: ${e.message}")
                emptyList()
            }
            Log.d("ExerciseHistoryStorageE2ETest", "Found ${allTextObjects.size} TextView objects")
            
            // Look for numeric text in TextViews
            var foundNumericText = false
            for (obj in allTextObjects) {
                val text = obj.text
                if (text != null && text.isNotBlank() && text.matches(Regex("\\d+(\\.\\d+)?"))) {
                    Log.d("ExerciseHistoryStorageE2ETest", "Found numeric TextView: '$text' at bounds: ${obj.bounds}")
                    // Try to get the parent or find a clickable container near this text
                    try {
                        // Try to long-click the text element itself
                        Log.d("ExerciseHistoryStorageE2ETest", "Attempting to long-click numeric TextView: '$text'")
                        obj.longClick()
                        device.waitForIdle(1_000)
                        foundNumericText = true
                        Log.d("ExerciseHistoryStorageE2ETest", "Successfully long-clicked numeric TextView")
                        
                        // Try to find +/- buttons and click plus once
                        val plusButton = device.wait(Until.findObject(By.desc("Plus")), 1_000)
                            ?: device.wait(Until.findObject(By.desc("+")), 1_000)
                        if (plusButton != null) {
                            Log.d("ExerciseHistoryStorageE2ETest", "Found plus button, clicking it")
                            plusButton.click()
                            device.waitForIdle(1_000)
                        } else {
                            Log.d("ExerciseHistoryStorageE2ETest", "Plus button not found")
                        }

                        // Wait for edit mode to auto-exit (2 seconds)
                        device.waitForIdle(2_500)
                        Log.d("ExerciseHistoryStorageE2ETest", "Edit mode should have auto-exited")
                        break
                    } catch (e: Exception) {
                        Log.w("ExerciseHistoryStorageE2ETest", "Failed to interact with numeric TextView '$text': ${e.message}")
                    }
                }
            }
            
            // Approach 3: If we didn't find numeric text, try long-pressing clickable containers
            // The reps/weight containers are in the center area, slightly offset
            if (!foundNumericText && clickableObjects.isNotEmpty()) {
                Log.d("ExerciseHistoryStorageE2ETest", "Trying to long-press clickable containers")
                // Try the first few clickable objects that are in the center area
                for (obj in clickableObjects.take(5)) {
                    val bounds = obj.bounds
                    val objCenterX = bounds.centerX()
                    val objCenterY = bounds.centerY()
                    // Check if it's in the center area (where reps/weight are displayed)
                    if (objCenterX in (width * 0.2).toInt()..(width * 0.8).toInt() &&
                        objCenterY in (height * 0.3).toInt()..(height * 0.7).toInt()) {
                        try {
                            Log.d("ExerciseHistoryStorageE2ETest", "Long-clicking clickable container at ($objCenterX, $objCenterY), bounds: $bounds")
                            obj.longClick()
                            device.waitForIdle(1_000)
                            
                            // Check if edit mode appeared (look for plus button)
                            val plusButton = device.wait(Until.findObject(By.desc("Plus")), 1_000)
                                ?: device.wait(Until.findObject(By.desc("+")), 1_000)
                            if (plusButton != null) {
                                Log.d("ExerciseHistoryStorageE2ETest", "Found plus button after long-click, clicking it")
                                plusButton.click()
                                device.waitForIdle(1_000)
                                device.waitForIdle(2_500) // Wait for edit mode to auto-exit
                                break
                            } else {
                                Log.d("ExerciseHistoryStorageE2ETest", "No plus button found after long-click")
                            }
                        } catch (e: Exception) {
                            Log.w("ExerciseHistoryStorageE2ETest", "Failed to long-click container: ${e.message}")
                        }
                    }
                }
            }
            
            // Approach 4: Fallback - long-press in the center area where reps/weight are displayed
            if (!foundNumericText) {
                Log.d("ExerciseHistoryStorageE2ETest", "Using fallback: long-press in center area")
                // The reps/weight are typically in the center-left and center-right areas
                // Try center-left first (where REPS usually is)
                val repsX = (width * 0.35).toInt()
                val repsY = centerY
                Log.d("ExerciseHistoryStorageE2ETest", "Long-pressing at reps area: ($repsX, $repsY)")
                device.swipe(repsX, repsY, repsX, repsY, 50) // 50 steps = longer press
                device.waitForIdle(1_000)
                
                // Check if edit mode appeared
                val plusButton = device.wait(Until.findObject(By.desc("Plus")), 1_000)
                    ?: device.wait(Until.findObject(By.desc("+")), 1_000)
                if (plusButton != null) {
                    Log.d("ExerciseHistoryStorageE2ETest", "Found plus button after fallback long-press, clicking it")
                    plusButton.click()
                    device.waitForIdle(1_000)
                    device.waitForIdle(2_500) // Wait for edit mode to auto-exit
                } else {
                    Log.d("ExerciseHistoryStorageE2ETest", "No plus button found after fallback long-press")
                }
            }
        } catch (e: Exception) {
            Log.e("ExerciseHistoryStorageE2ETest", "Exception in tryModifySetData(): ${e.message}", e)
            // If modification fails, continue - not all sets may support modification in this way
            // This is expected for some set types or UI states
        }
        Log.d("ExerciseHistoryStorageE2ETest", "tryModifySetData() completed")
    }
    */

    /**
     * Attempts to modify reps and weight via accessibility-labeled rows and records expected changes.
     * Best-effort: skips if nodes aren't present.
     */
    private fun tryModifySetData(currentSetInfo: CurrentSetInfo?) {
        if (currentSetInfo == null) return
        if (currentSetInfo.set !is WeightSet && currentSetInfo.set !is BodyWeightSet) return

        device.waitForIdle(500)

        val repsTarget = device.wait(
            Until.findObject(By.descContains(SetValueSemantics.RepsValueDescription)),
            5_000
        )

        if (repsTarget != null) {
            val parsedReps = repsTarget.contentDescription
                ?.toString()
                ?.substringAfter(":", "")
                ?.trim()
                ?.toIntOrNull()

            val originalReps = parsedReps ?: when (val set = currentSetInfo.set) {
                is WeightSet -> set.reps
                is BodyWeightSet -> set.reps
                else -> null
            }

            if (parsedReps == null) {
                Log.w(
                    "ExerciseHistoryStorageE2ETest",
                    "Unable to parse reps value from content description; falling back to set data"
                )
            }

            if (originalReps == null) {
                Log.w("ExerciseHistoryStorageE2ETest", "Unable to determine reps value for modification")
            } else {
                runCatching {
                    repsTarget.longClick()
                    device.waitForIdle(500)

                    val addButton = device.wait(Until.findObject(By.desc("Add")), 1_000)
                    if (addButton == null) {
                        Log.w("ExerciseHistoryStorageE2ETest", "Add button not found after long-press")
                        return@runCatching
                    }

                    addButton.click()
                    device.waitForIdle(2_500)

                    val updatedReps = device.wait(
                        Until.findObject(By.descContains(SetValueSemantics.RepsValueDescription)),
                        1_000
                    )?.contentDescription
                        ?.toString()
                        ?.substringAfter(":", "")
                        ?.trim()
                        ?.toIntOrNull()

                    if (updatedReps == null || updatedReps == originalReps) {
                        Log.w("ExerciseHistoryStorageE2ETest", "Reps value did not change after modification")
                        return@runCatching
                    }

                    val modifiedReps = updatedReps
                    val set = currentSetInfo.set
                    val modification = when (set) {
                        is WeightSet -> ModifiedSetData(
                            setId = set.id,
                            exerciseId = currentSetInfo.exerciseId,
                            originalReps = originalReps,
                            modifiedReps = modifiedReps,
                            originalWeight = set.weight,
                            modifiedWeight = null,
                            originalAdditionalWeight = null,
                            modifiedAdditionalWeight = null,
                            originalDuration = null,
                            actualDuration = null
                        )
                        is BodyWeightSet -> ModifiedSetData(
                            setId = set.id,
                            exerciseId = currentSetInfo.exerciseId,
                            originalReps = originalReps,
                            modifiedReps = modifiedReps,
                            originalWeight = null,
                            modifiedWeight = null,
                            originalAdditionalWeight = set.additionalWeight,
                            modifiedAdditionalWeight = null,
                            originalDuration = null,
                            actualDuration = null
                        )
                        else -> null
                    }

                    if (modification != null) {
                        modifications[modification.setId] = modification
                    }
                }.onFailure { e ->
                    Log.w("ExerciseHistoryStorageE2ETest", "Failed to modify set data: ${e.message}")
                }
            }
        } else {
            Log.w("ExerciseHistoryStorageE2ETest", "Reps value not found for modification")
        }

        device.waitForIdle(1_000)

        val weightTarget = device.wait(
            Until.findObject(By.descContains(SetValueSemantics.WeightValueDescription)),
            1_000
        )

        if (weightTarget == null) {
            Log.w("ExerciseHistoryStorageE2ETest", "Weight value not found for modification")
            return
        }

        runCatching {
            val originalWeight = parseWeightFromDescription(weightTarget.contentDescription?.toString())
                ?: when (val set = currentSetInfo.set) {
                    is WeightSet -> set.weight
                    is BodyWeightSet -> set.additionalWeight
                    else -> null
                }

            if (originalWeight == null) {
                Log.w("ExerciseHistoryStorageE2ETest", "Unable to determine weight value for modification")
                return@runCatching
            }

            weightTarget.longClick()
            device.waitForIdle(500)

            val addButton = device.wait(Until.findObject(By.desc("Add")), 1_000)
            if (addButton == null) {
                Log.w("ExerciseHistoryStorageE2ETest", "Add button not found after weight long-press")
                return@runCatching
            }

            addButton.click()
            device.waitForIdle(2_500)

            val updatedWeight = device.wait(
                Until.findObject(By.descContains(SetValueSemantics.WeightValueDescription)),
                1_000
            )?.contentDescription
                ?.toString()
                ?.let { parseWeightFromDescription(it) }

            if (updatedWeight == null || updatedWeight == originalWeight) {
                Log.w("ExerciseHistoryStorageE2ETest", "Weight value did not change after modification")
                return@runCatching
            }

            val set = currentSetInfo.set
            val existing = modifications[set.id]
            val updatedModification = when (set) {
                is WeightSet -> {
                    val base = existing ?: ModifiedSetData(
                        setId = set.id,
                        exerciseId = currentSetInfo.exerciseId,
                        originalReps = null,
                        modifiedReps = null,
                        originalWeight = originalWeight,
                        modifiedWeight = null,
                        originalAdditionalWeight = null,
                        modifiedAdditionalWeight = null,
                        originalDuration = null,
                        actualDuration = null
                    )
                    base.copy(
                        originalWeight = originalWeight,
                        modifiedWeight = updatedWeight
                    )
                }
                is BodyWeightSet -> {
                    val base = existing ?: ModifiedSetData(
                        setId = set.id,
                        exerciseId = currentSetInfo.exerciseId,
                        originalReps = null,
                        modifiedReps = null,
                        originalWeight = null,
                        modifiedWeight = null,
                        originalAdditionalWeight = originalWeight,
                        modifiedAdditionalWeight = null,
                        originalDuration = null,
                        actualDuration = null
                    )
                    base.copy(
                        originalAdditionalWeight = originalWeight,
                        modifiedAdditionalWeight = updatedWeight
                    )
                }
                else -> null
            }

            if (updatedModification != null) {
                modifications[updatedModification.setId] = updatedModification
            }
        }.onFailure { e ->
            Log.w("ExerciseHistoryStorageE2ETest", "Failed to modify weight data: ${e.message}")
        }
    }

    private fun parseWeightFromDescription(description: String?): Double? {
        if (description == null) return null
        val text = description.substringAfter(":", "").trim()
        if (text.equals("BW", ignoreCase = true) || text == "-") return 0.0

        val totalMatch = Regex("Tot:?\\s*([0-9]+(?:\\.[0-9]+)?)", RegexOption.IGNORE_CASE).find(text)
        if (totalMatch != null) {
            return totalMatch.groupValues[1].toDoubleOrNull()
        }

        val doubledMatch = Regex("([0-9]+(?:\\.[0-9]+)?)\\s*x\\s*2", RegexOption.IGNORE_CASE).find(text)
        if (doubledMatch != null) {
            val base = doubledMatch.groupValues[1].toDoubleOrNull() ?: return null
            return base * 2.0
        }

        val numberMatch = Regex("([0-9]+(?:\\.[0-9]+)?)").find(text)
        return numberMatch?.groupValues?.get(1)?.toDoubleOrNull()
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
            // Manual start - find start button
            val startButton = device.wait(Until.findObject(By.text("Start")), 2_000)
            startButton?.click()
            device.waitForIdle(2_000)
            
            // Wait a bit
            device.waitForIdle(3_000)
            
            // Find stop button
            val stopButton = device.wait(Until.findObject(By.text("Stop")), 2_000)
            stopButton?.click()
        }

        // Complete the set
        device.pressBack()
        confirmLongPressDialog()
    }

    /**
     * Waits for workout completion screen.
     */
    private fun waitForWorkoutCompletion() {
        val completedVisible = device.wait(
            Until.hasObject(By.text("Completed")),
            30_000
        )
        require(completedVisible) { "Workout completion screen did not appear" }
    }

    /**
     * Completes a set by triggering the "Complete Set" dialog and confirming.
     */
    private fun confirmLongPressDialog() {
        device.waitForIdle(1_000)
        longPressByDesc("Done")
        device.waitForIdle(1_000)
    }

    /**
     * Skips the rest timer.
     */
    private fun skipRest() {
        device.pressBack()
        device.waitForIdle(200)
        device.pressBack()
        device.waitForIdle(500)

        val dialogAppeared = device.wait(
            Until.hasObject(By.text("Skip Rest")),
            3_000
        )
        if (dialogAppeared) {
            longPressByDesc("Done")
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
                        require(setData.actualReps == modifiedReps) {
                            "WeightSetData actualReps should match modified value: expected $modifiedReps, got ${setData.actualReps}"
                        }
                        require(setData.actualReps != modification.originalReps) {
                            "WeightSetData actualReps should not equal original value"
                        }
                    }
                    modification.modifiedWeight?.let { modifiedWeight ->
                        require(kotlin.math.abs(setData.actualWeight - modifiedWeight) < 0.1) {
                            "WeightSetData actualWeight should match modified value: expected $modifiedWeight, got ${setData.actualWeight}"
                        }
                        modification.originalWeight?.let { originalWeight ->
                            require(kotlin.math.abs(setData.actualWeight - originalWeight) > 0.1) {
                                "WeightSetData actualWeight should not equal original value"
                            }
                        }
                    }
                    // Verify volume calculation
                    val expectedVolume = setData.actualReps * setData.actualWeight
                    require(kotlin.math.abs(setData.volume - expectedVolume) < 0.1) {
                        "WeightSetData volume should be correctly calculated: expected $expectedVolume, got ${setData.volume}"
                    }
                }
                is BodyWeightSetData -> {
                    modification.modifiedReps?.let { modifiedReps ->
                        require(setData.actualReps == modifiedReps) {
                            "BodyWeightSetData actualReps should match modified value"
                        }
                    }
                    modification.modifiedAdditionalWeight?.let { modifiedAdditionalWeight ->
                        require(kotlin.math.abs(setData.additionalWeight - modifiedAdditionalWeight) < 0.1) {
                            "BodyWeightSetData additionalWeight should match modified value"
                        }
                    }
                    // Verify volume calculation
                    val expectedVolume = setData.actualReps * setData.getWeight()
                    require(kotlin.math.abs(setData.volume - expectedVolume) < 0.1) {
                        "BodyWeightSetData volume should be correctly calculated"
                    }
                }
                is TimedDurationSetData -> {
                    // For timed sets, verify actual duration matches modification
                    modification.actualDuration?.let { actualDuration ->
                        val actualDurationMs = (setData.endTimer - setData.startTimer) / 1000
                        require(kotlin.math.abs(actualDurationMs - actualDuration) < 2) {
                            "TimedDurationSetData duration should match actual execution time"
                        }
                    }
                }
                is EnduranceSetData -> {
                    // For endurance sets, verify actual duration matches modification
                    modification.actualDuration?.let { actualDuration ->
                        val actualDurationMs = (setData.endTimer - setData.startTimer) / 1000
                        require(kotlin.math.abs(actualDurationMs - actualDuration) < 2) {
                            "EnduranceSetData duration should match actual execution time"
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
                        require(timedData.endTimer >= timedData.startTimer) {
                            "TimedDurationSetData endTimer should be >= startTimer"
                        }
                    }
                    is com.gabstra.myworkoutassistant.shared.sets.EnduranceSet -> {
                        require(setHistory.setData is EnduranceSetData) {
                            "SetHistory setData should be EnduranceSetData for EnduranceSet"
                        }
                        val enduranceData = setHistory.setData as EnduranceSetData
                        require(enduranceData.endTimer >= enduranceData.startTimer) {
                            "EnduranceSetData endTimer should be >= startTimer"
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

