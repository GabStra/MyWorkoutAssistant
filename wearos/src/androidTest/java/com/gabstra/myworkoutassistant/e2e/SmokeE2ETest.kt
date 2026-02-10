package com.gabstra.myworkoutassistant.e2e

import org.junit.Test

class SmokeE2ETest : BaseWearE2ETest() {

    @Test
    fun appLaunches_toWorkoutSelectionScreen() {
        val headerVisible = createWorkoutDriver().waitForText("My Workout Assistant", defaultTimeoutMs)
        require(headerVisible) { "Workout selection header not visible after app launch" }
    }
}
