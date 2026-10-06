package com.gabstra.myworkoutassistant.e2e

import android.os.SystemClock
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
class WearEquipmentChangeCrossDeviceProducerE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun changeEquipment_persistsUpdatedExerciseOnPhone() {
        EquipmentChangeWorkoutStoreFixture.setupWeightWorkoutStore(context)
        launchAppFromHome()
        startWorkout(EquipmentChangeWorkoutStoreFixture.getWeightWorkoutName())

        require(
            device.wait(
                Until.hasObject(By.text(EquipmentChangeWorkoutStoreFixture.WEIGHT_EXERCISE_NAME)),
                defaultTimeoutMs
            )
        ) { "Weight exercise did not appear" }
        require(
            WearWorkoutEquipmentChangeHelper.waitForPersistedExerciseEquipment(
                context = context,
                workoutName = EquipmentChangeWorkoutStoreFixture.getWeightWorkoutName(),
                exerciseName = EquipmentChangeWorkoutStoreFixture.WEIGHT_EXERCISE_NAME,
                expectedEquipmentName = EquipmentChangeWorkoutStoreFixture.MACHINE_NAME,
                timeoutMs = 5_000
            )
        ) { "Weight exercise was not using Test Machine before the equipment change" }
        require(
            WearWorkoutEquipmentChangeHelper.waitForLiveExerciseEquipment(
                exerciseName = EquipmentChangeWorkoutStoreFixture.WEIGHT_EXERCISE_NAME,
                expectedEquipmentName = EquipmentChangeWorkoutStoreFixture.MACHINE_NAME,
                timeoutMs = 5_000
            ) != null
        ) { "Live weight exercise diverged from the persisted Test Machine definition before the change" }

        require(navigateToChangeEquipmentPage()) {
            "Buttons page with Change equipment was not reachable"
        }
        val changeButton = workoutDriver.findWithScrollFallback(
            selector = By.text("Change equipment"),
            initialWaitMs = 1_000,
            directions = listOf(Direction.DOWN, Direction.UP)
        )
        require(changeButton != null) { "Change equipment action was not visible" }
        workoutDriver.clickObjectOrAncestor(changeButton)
        require(device.wait(Until.hasObject(By.text("Choose equipment")), 5_000)) {
            "Equipment picker did not appear"
        }

        workoutDriver.clickText(EquipmentChangeWorkoutStoreFixture.BARBELL_NAME, defaultTimeoutMs)
        require(device.wait(Until.hasObject(By.text("Update Equipment")), 5_000)) {
            "Equipment confirmation dialog did not appear"
        }
        workoutDriver.confirmLongPressDialog(5_000)
        require(device.wait(Until.gone(By.text("Update Equipment")), 5_000)) {
            "Equipment confirmation dialog did not dismiss"
        }

        require(
            WearWorkoutEquipmentChangeHelper.waitForPersistedExerciseEquipment(
                context = context,
                workoutName = EquipmentChangeWorkoutStoreFixture.getWeightWorkoutName(),
                exerciseName = EquipmentChangeWorkoutStoreFixture.WEIGHT_EXERCISE_NAME,
                expectedEquipmentName = EquipmentChangeWorkoutStoreFixture.BARBELL_NAME,
                timeoutMs = 10_000
            )
        ) { "Wear did not persist the equipment change before cross-device verification" }

        require(
            WearWorkoutEquipmentChangeHelper.waitForEquipmentChangeCompletion(
                exerciseName = EquipmentChangeWorkoutStoreFixture.WEIGHT_EXERCISE_NAME,
                expectedEquipmentName = EquipmentChangeWorkoutStoreFixture.BARBELL_NAME,
                timeoutMs = 30_000
            )
        ) { "Equipment change did not finish its runtime rebuild and cross-device sync" }
        SystemClock.sleep(WORKOUT_STORE_TRANSFER_WINDOW_MS)
    }

    private fun navigateToChangeEquipmentPage(): Boolean {
        if (device.hasObject(By.text("Change equipment"))) return true

        repeat(4) {
            workoutDriver.navigateToPagerPage(Direction.RIGHT)
            if (device.wait(Until.hasObject(By.text("Change equipment")), 1_500)) return true
        }
        repeat(4) {
            workoutDriver.navigateToPagerPage(Direction.LEFT)
            if (device.wait(Until.hasObject(By.text("Change equipment")), 1_500)) return true
        }
        return device.hasObject(By.text("Change equipment"))
    }

    private companion object {
        const val WORKOUT_STORE_TRANSFER_WINDOW_MS = 15_000L
    }

}
