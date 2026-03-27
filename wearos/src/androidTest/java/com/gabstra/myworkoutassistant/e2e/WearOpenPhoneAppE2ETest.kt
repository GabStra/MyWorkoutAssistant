package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Direction
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.helpers.TestWorkoutStoreSeeder
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.time.LocalDate

@RunWith(AndroidJUnit4::class)
class WearOpenPhoneAppE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    override fun prepareAppStateBeforeLaunch() {
        val setupRequiredStore = TestWorkoutStoreSeeder.createDefaultTestWorkoutStore().copy(
            birthDateYear = LocalDate.now().year
        )
        TestWorkoutStoreSeeder.seedWorkoutStore(context, setupRequiredStore)
    }

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun openPhoneApp_requestsPhoneLaunch() {
        val openPhoneButton = workoutDriver.findWithScrollFallback(
            selector = By.text("Open phone app"),
            initialWaitMs = E2ETestTimings.CROSS_DEVICE_SYNC_TIMEOUT_MS,
            directions = listOf(Direction.UP, Direction.DOWN)
        )

        requireNotNull(openPhoneButton) {
            "Timed out waiting for 'Open phone app'. Ensure the paired phone has the same app variant installed."
        }

        workoutDriver.clickObjectOrAncestor(openPhoneButton)
        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
    }
}
