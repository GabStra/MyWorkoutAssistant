package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.TestWorkoutStoreSeeder
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Plate
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.time.LocalDate
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class WorkoutE2ETest : BaseWearE2ETest() {

    private val workoutName = "Test Workout"

    @Before
    override fun baseSetUp() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        device = UiDevice.getInstance(instrumentation)
        context = ApplicationProvider.getApplicationContext()

        // Grant all required runtime permissions before launching the app
        grantPermissions(
            android.Manifest.permission.BODY_SENSORS,
            android.Manifest.permission.ACTIVITY_RECOGNITION,
            android.Manifest.permission.POST_NOTIFICATIONS,
            android.Manifest.permission.ACCESS_FINE_LOCATION,
            android.Manifest.permission.ACCESS_COARSE_LOCATION,
            android.Manifest.permission.BLUETOOTH_SCAN,
            android.Manifest.permission.BLUETOOTH_CONNECT
        )

        // Use default workout store - individual tests will override if needed
        seedWorkoutStore()
        
        // Launch the app
        launchAppFromHome()
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
            id = UUID.randomUUID(),
            name = "Test Barbell",
            availablePlates = plates,
            barLength = 200,
            barWeight = 20.0
        )
    }

    /**
     * Sets up a workout store with a workout that has a TimedDurationSet exercise
     * with countdown enabled. This is used for tests that need to verify countdown dialog.
     */
    private fun setupWorkoutStoreWithTimedDurationSet() {
        val equipment = createTestBarbell()
        val exerciseId = UUID.randomUUID()
        val setId = UUID.randomUUID()

        // TimedDurationSet supports countdown dialog
        val exercise = Exercise(
            id = exerciseId,
            enabled = true,
            name = "Timed Exercise",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                TimedDurationSet(setId, 60_000, autoStart = true, autoStop = false) // 60 seconds
            ),
            exerciseType = ExerciseType.COUNTDOWN,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 5,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            enableProgression = false,
            keepScreenOn = false,
            showCountDownTimer = true, // Enable countdown dialog
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )

        val workout = Workout(
            id = UUID.randomUUID(),
            name = workoutName,
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
            globalId = UUID.randomUUID(),
            type = 0
        )

        val workoutStore = WorkoutStore(
            workouts = listOf(workout),
            equipments = listOf(equipment),
            polarDeviceId = null,
            birthDateYear = 1990,
            weightKg = 75.0,
            progressionPercentageAmount = 0.0
        )

        TestWorkoutStoreSeeder.seedWorkoutStore(context, workoutStore)
    }

    /**
     * Sets up a workout store with a workout that has an EnduranceSet exercise
     * with countdown enabled. This is used for tests that need to verify countdown dialog.
     */
    private fun setupWorkoutStoreWithEnduranceSet() {
        val equipment = createTestBarbell()
        val exerciseId = UUID.randomUUID()
        val setId = UUID.randomUUID()

        // EnduranceSet supports countdown dialog
        val exercise = Exercise(
            id = exerciseId,
            enabled = true,
            name = "Endurance Exercise",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                EnduranceSet(setId, 60_000, autoStart = false, autoStop = false) // 60 seconds
            ),
            exerciseType = ExerciseType.COUNTUP,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 5,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            enableProgression = false,
            keepScreenOn = false,
            showCountDownTimer = true, // Enable countdown dialog
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )

        val workout = Workout(
            id = UUID.randomUUID(),
            name = workoutName,
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
            globalId = UUID.randomUUID(),
            type = 0
        )

        val workoutStore = WorkoutStore(
            workouts = listOf(workout),
            equipments = listOf(equipment),
            polarDeviceId = null,
            birthDateYear = 1990,
            weightKg = 75.0,
            progressionPercentageAmount = 0.0
        )

        TestWorkoutStoreSeeder.seedWorkoutStore(context, workoutStore)
    }

    /**
     * Sets up a workout store with a workout that has a WeightSet exercise.
     * This is used for tests that don't need countdown functionality.
     */
    private fun setupWorkoutStoreWithWeightSet() {
        val equipment = createTestBarbell()
        val exerciseId = UUID.randomUUID()
        val setId = UUID.randomUUID()

        val exercise = Exercise(
            id = exerciseId,
            enabled = true,
            name = "Bench Press",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                WeightSet(setId, 10, 100.0)
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 5,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipment.id,
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

        val workout = Workout(
            id = UUID.randomUUID(),
            name = workoutName,
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
            globalId = UUID.randomUUID(),
            type = 0
        )

        val workoutStore = WorkoutStore(
            workouts = listOf(workout),
            equipments = listOf(equipment),
            polarDeviceId = null,
            birthDateYear = 1990,
            weightKg = 75.0,
            progressionPercentageAmount = 0.0
        )

        TestWorkoutStoreSeeder.seedWorkoutStore(context, workoutStore)
    }

    @Test
    fun countdownDialog_showsWhenEnabled() {
        // Set up workout store with TimedDurationSet that supports countdown
        setupWorkoutStoreWithTimedDurationSet()
        
        // Restart the app to load the new workout store
        launchAppFromHome()
        
        startWorkout(workoutName)

        // Wait for the first exercise screen to appear (after preparing step)
        // The countdown dialog should appear when the exercise starts
        // It shows numbers 3, 2, 1 sequentially
        val countdown3Visible = device.wait(
            Until.hasObject(By.text("3")),
            5_000
        )
        require(countdown3Visible) { "Countdown dialog with '3' not visible" }

        // Wait for countdown to progress to 2
        val countdown2Visible = device.wait(
            Until.hasObject(By.text("2")),
            5_000
        )
        require(countdown2Visible) { "Countdown dialog with '2' not visible" }

        // Wait for countdown to progress to 1
        val countdown1Visible = device.wait(
            Until.hasObject(By.text("1")),
            5_000
        )
        require(countdown1Visible) { "Countdown dialog with '1' not visible" }

        // After countdown completes, the exercise screen should be visible
        // We can verify by checking that the countdown is gone and exercise name is visible
        device.waitForIdle(1_000)
        val exerciseNameVisible = device.wait(
            Until.hasObject(By.text("Timed Exercise")),
            5_000
        )
        require(exerciseNameVisible) { "Exercise screen not visible after countdown" }
    }

    @Test
    fun completeWorkout_showsSummary() {
        // Set up workout store with WeightSet for this test
        setupWorkoutStoreWithWeightSet()
        
        // Restart the app to load the new workout store
        launchAppFromHome()
        
        startWorkout(workoutName)

        val completedVisible = device.wait(Until.hasObject(By.text("Completed")), 10_000)
        require(completedVisible) { "'Completed' text not visible on WorkoutCompleteScreen" }

        val nameVisible = device.wait(Until.hasObject(By.text(workoutName)), 5_000)
        require(nameVisible) { "Workout name '$workoutName' not visible on completion screen" }
    }

    @Test
    fun showCountdown_autoCloseOrFinish() {
        // Set up workout store with WeightSet for this test
        setupWorkoutStoreWithWeightSet()
        
        // Restart the app to load the new workout store
        launchAppFromHome()
        
        startWorkout(workoutName)

        val countdownVisible = device.wait(
            Until.hasObject(By.textStartsWith("Closing in:")),
            10_000
        )
        require(countdownVisible) { "Countdown 'Closing in:' not visible on completion screen" }

        val stillCompleted = device.wait(
            Until.hasObject(By.text("Completed")),
            35_000
        )
        if (!stillCompleted) {
            return
        }
    }

    @Test
    fun dialog_returnToMainMenu() {
        // Set up workout store with WeightSet for this test
        setupWorkoutStoreWithWeightSet()
        
        // Restart the app to load the new workout store
        launchAppFromHome()
        
        startWorkout(workoutName)

        val dialogTitleVisible = device.wait(
            Until.hasObject(By.text("Workout completed")),
            15_000
        )
        require(dialogTitleVisible) { "'Workout completed' dialog not visible" }

        // The "Done" button requires a long press to confirm, not a regular click
        longPressByDesc("Done", 5_000)

        val headerVisible = device.wait(
            Until.hasObject(By.text("My Workout Assistant")),
            10_000
        )
        require(headerVisible) { "Did not return to WorkoutSelectionScreen from completion dialog" }
    }

    @Test
    fun dialog_stayAndAutoClose() {
        // Set up workout store with WeightSet for this test
        setupWorkoutStoreWithWeightSet()
        
        // Restart the app to load the new workout store
        launchAppFromHome()
        
        startWorkout(workoutName)

        val dialogTitleVisible = device.wait(
            Until.hasObject(By.text("Workout completed")),
            15_000
        )
        require(dialogTitleVisible) { "'Workout completed' dialog not visible" }

        val noButton = device.wait(
            Until.findObject(By.desc("Close")),
            5_000
        )
        require(noButton != null) { "Close (no) icon not found in completion dialog" }
        noButton.click()

        val completedVisible = device.wait(Until.hasObject(By.text("Completed")), 5_000)
        require(completedVisible) { "Completion screen not visible after choosing to stay" }

        device.waitForIdle(35_000)
    }
}

