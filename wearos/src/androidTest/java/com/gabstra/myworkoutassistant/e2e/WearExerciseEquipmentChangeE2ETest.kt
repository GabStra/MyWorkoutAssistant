package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Direction
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.EquipmentChangeWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.WearWorkoutEquipmentChangeHelper
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearExerciseEquipmentChangeE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun bodyWeightExercise_canClearEquipmentToNone() {
        EquipmentChangeWorkoutStoreFixture.setupBodyWeightWorkoutStore(context)
        launchAppFromHome()
        startWorkout(EquipmentChangeWorkoutStoreFixture.getBodyWeightWorkoutName())

        val bodyWeightVisible = device.wait(
            Until.hasObject(By.text(EquipmentChangeWorkoutStoreFixture.BODY_WEIGHT_EXERCISE_NAME)),
            defaultTimeoutMs
        )
        require(bodyWeightVisible) { "Bodyweight exercise did not appear" }

        dismissTutorialIfPresent(TutorialContext.SET_SCREEN, 2_000)
        openButtonsPage()
        openEquipmentPicker()
        require(device.hasObject(By.text("None"))) {
            "Bodyweight exercise picker must offer a None option"
        }
        selectEquipmentAndConfirm("None")
        assertPersistedExerciseEquipment(
            workoutName = EquipmentChangeWorkoutStoreFixture.getBodyWeightWorkoutName(),
            exerciseName = EquipmentChangeWorkoutStoreFixture.BODY_WEIGHT_EXERCISE_NAME,
            expectedEquipmentName = null
        )
        assertLiveExerciseEquipment(
            exerciseName = EquipmentChangeWorkoutStoreFixture.BODY_WEIGHT_EXERCISE_NAME,
            expectedEquipmentName = null
        )
    }

    @Test
    fun weightExercise_canChangeEquipmentAndRefreshExerciseUi() {
        EquipmentChangeWorkoutStoreFixture.setupWeightWorkoutStore(context)
        launchAppFromHome()
        startWorkout(EquipmentChangeWorkoutStoreFixture.getWeightWorkoutName())

        require(
            device.wait(
                Until.hasObject(By.text(EquipmentChangeWorkoutStoreFixture.WEIGHT_EXERCISE_NAME)),
                defaultTimeoutMs
            )
        ) { "Weight exercise did not appear" }

        openButtonsPage()
        openEquipmentPicker()
        require(!device.hasObject(By.text("None"))) {
            "Weight exercise picker must not offer a None option"
        }
        selectEquipmentAndConfirm(EquipmentChangeWorkoutStoreFixture.BARBELL_NAME)
        assertPersistedExerciseEquipment(
            workoutName = EquipmentChangeWorkoutStoreFixture.getWeightWorkoutName(),
            exerciseName = EquipmentChangeWorkoutStoreFixture.WEIGHT_EXERCISE_NAME,
            expectedEquipmentName = EquipmentChangeWorkoutStoreFixture.BARBELL_NAME
        )
        assertLiveExerciseEquipment(
            exerciseName = EquipmentChangeWorkoutStoreFixture.WEIGHT_EXERCISE_NAME,
            expectedEquipmentName = EquipmentChangeWorkoutStoreFixture.BARBELL_NAME
        )
    }

    private fun openButtonsPage() {
        require(navigateToPageContainingText("Change Equipment", preferredDirection = Direction.RIGHT)) {
            "Buttons page with Change Equipment was not reachable"
        }
    }

    private fun openEquipmentPicker() {
        repeat(3) { attempt ->
            device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
            workoutDriver.clickText("Change Equipment", defaultTimeoutMs)
            if (device.wait(Until.hasObject(By.text("Select equipment")), 5_000)) {
                return
            }
            if (attempt < 2) {
                device.waitForIdle(E2ETestTimings.LONG_IDLE_MS)
            }
        }
        error("Equipment picker did not appear")
    }

    private fun selectEquipmentAndConfirm(optionLabel: String) {
        workoutDriver.clickText(optionLabel, defaultTimeoutMs)
        require(
            device.wait(Until.hasObject(By.text("Update Equipment")), 5_000)
        ) { "Equipment confirmation dialog did not appear" }
        workoutDriver.confirmLongPressDialog(5_000)
        require(device.wait(Until.gone(By.text("Update Equipment")), 5_000)) {
            "Equipment confirmation dialog did not dismiss"
        }
        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
    }

    private fun navigateToPageContainingText(
        text: String,
        preferredDirection: Direction,
        maxPasses: Int = 4
    ): Boolean {
        if (device.hasObject(By.text(text))) {
            return true
        }

        repeat(maxPasses) {
            swipePager(preferredDirection)
            if (device.wait(Until.hasObject(By.text(text)), 1_500)) {
                return true
            }
        }

        val fallbackDirection = if (preferredDirection == Direction.RIGHT) Direction.LEFT else Direction.RIGHT
        repeat(maxPasses) {
            swipePager(fallbackDirection)
            if (device.wait(Until.hasObject(By.text(text)), 1_500)) {
                return true
            }
        }

        return device.hasObject(By.text(text))
    }

    private fun swipePager(direction: Direction) {
        workoutDriver.navigateToPagerPage(direction)
        if (device.hasObject(By.text("Change Equipment")) || device.hasObject(By.text("Loading Guide"))) {
            return
        }

        val width = device.displayWidth
        val height = device.displayHeight
        val swipeY = height / 2
        if (direction == Direction.LEFT) {
            device.swipe(
                (width * 0.8).toInt().coerceAtMost(width - 1),
                swipeY,
                (width * 0.2).toInt().coerceAtLeast(0),
                swipeY,
                10
            )
        } else {
            device.swipe(
                (width * 0.2).toInt().coerceAtLeast(0),
                swipeY,
                (width * 0.8).toInt().coerceAtMost(width - 1),
                swipeY,
                10
            )
        }
        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
    }
    private fun assertPersistedExerciseEquipment(
        workoutName: String,
        exerciseName: String,
        expectedEquipmentName: String?
    ) {
        require(
            WearWorkoutEquipmentChangeHelper.waitForPersistedExerciseEquipment(
                context = context,
                workoutName = workoutName,
                exerciseName = exerciseName,
                expectedEquipmentName = expectedEquipmentName,
                timeoutMs = 10_000
            )
        ) {
            "Workout store did not persist $exerciseName with equipment=$expectedEquipmentName"
        }
    }

    private fun assertLiveExerciseEquipment(
        exerciseName: String,
        expectedEquipmentName: String?
    ) {
        require(
            WearWorkoutEquipmentChangeHelper.waitForLiveExerciseEquipment(
                exerciseName = exerciseName,
                expectedEquipmentName = expectedEquipmentName,
                timeoutMs = 10_000
            ) != null
        ) {
            "Live workout state did not update $exerciseName to equipment=$expectedEquipmentName"
        }
    }

}
