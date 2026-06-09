package com.gabstra.myworkoutassistant.e2e

import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Direction
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.SnatchAnimationWorkoutStoreFixture
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearExerciseAnimationE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    override fun prepareAppStateBeforeLaunch() {
        SnatchAnimationWorkoutStoreFixture.setupWorkoutStore(context)
    }

    @Test
    fun animationPage_inNormalWorkoutFlow_rendersMovementPreview() {
        startWorkout(SnatchAnimationWorkoutStoreFixture.getWorkoutName())

        workoutDriver.navigateToPagerPage(Direction.LEFT)

        require(
            device.wait(
                Until.hasObject(By.desc("Exercise movement preview")),
                defaultTimeoutMs
            )
        ) { "Exercise movement preview did not appear from the normal workout flow" }

        SystemClock.sleep(4_000)

        require(device.hasObject(By.desc("Exercise movement preview"))) {
            "Exercise movement preview disappeared while rendering"
        }
    }
}
