package com.gabstra.myworkoutassistant.e2e

import org.junit.Test

class WearSmokeE2ETest : WearBaseE2ETest() {

    @Test
    fun appLaunches_toWorkoutSelectionScreen() {
        val headerVisible = createWorkoutDriver().waitForText("My Workout Assistant", defaultTimeoutMs)
        require(headerVisible) { "Workout selection header not visible after app launch" }
    }
}

