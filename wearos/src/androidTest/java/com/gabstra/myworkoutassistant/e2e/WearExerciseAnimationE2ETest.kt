package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.SnatchAnimationWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.MovementPreviewNavigationHelper
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearExerciseAnimationE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver
    private lateinit var movementPreviewHelper: MovementPreviewNavigationHelper

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
        movementPreviewHelper = MovementPreviewNavigationHelper(device, workoutDriver)
    }

    override fun prepareAppStateBeforeLaunch() {
        SnatchAnimationWorkoutStoreFixture.setupWorkoutStore(context)
    }

    @Test
    fun animationPage_inNormalWorkoutFlow_rendersMovementPreview() {
        startWorkout(SnatchAnimationWorkoutStoreFixture.getWorkoutName())

        movementPreviewHelper.requireMovementPreviewVisibleAndStable()
    }
}
