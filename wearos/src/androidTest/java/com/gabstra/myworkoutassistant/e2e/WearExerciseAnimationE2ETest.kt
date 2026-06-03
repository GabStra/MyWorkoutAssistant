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
    fun animationPage_inNormalWorkoutFlow_staysResponsiveDuringRotationAndIncline() {
        startWorkout(SnatchAnimationWorkoutStoreFixture.getWorkoutName())

        workoutDriver.navigateToPagerPage(Direction.LEFT)

        require(
            device.wait(
                Until.hasObject(By.desc("Animation reset view")),
                defaultTimeoutMs
            )
        ) { "Animation page controls did not appear from the normal workout flow" }

        require(device.wait(Until.hasObject(By.desc("Animation viewer canvas")), 3_000)) {
            "Animation viewer canvas did not appear"
        }

        val zoomIn = requireNotNull(device.findObject(By.desc("Animation zoom in"))) {
            "Animation zoom in button not found"
        }
        val zoomOut = requireNotNull(device.findObject(By.desc("Animation zoom out"))) {
            "Animation zoom out button not found"
        }
        val reset = requireNotNull(device.findObject(By.desc("Animation reset view"))) {
            "Animation reset button not found"
        }

        zoomIn.click()
        device.waitForIdle(500)
        zoomOut.click()
        device.waitForIdle(500)

        repeat(3) {
            rotateAndInclineViewer()
            device.waitForIdle(1_000)
        }

        SystemClock.sleep(4_000)
        reset.click()
        device.waitForIdle(1_000)

        require(device.hasObject(By.desc("Animation reset view"))) {
            "Animation page stopped responding after repeated interaction"
        }
        require(device.hasObject(By.desc("Animation viewer canvas"))) {
            "Animation viewer disappeared after repeated interaction"
        }
    }

    private fun rotateAndInclineViewer() {
        val width = device.displayWidth
        val height = device.displayHeight
        val centerY = (height * 0.48f).toInt()
        val lowerY = (height * 0.62f).toInt()

        device.swipe(
            (width * 0.72f).toInt(),
            centerY,
            (width * 0.38f).toInt(),
            centerY,
            18
        )
        device.waitForIdle(600)

        device.swipe(
            (width * 0.60f).toInt(),
            lowerY,
            (width * 0.46f).toInt(),
            (height * 0.35f).toInt(),
            18
        )
    }
}
