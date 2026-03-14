package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.SupersetWorkoutStoreFixture
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * E2E tests validating that PageExercises shows unified superset sets
 * (A1, B1, REST, A2, B2, ...) instead of per-exercise sets when viewing a superset.
 */
@RunWith(AndroidJUnit4::class)
class WearSupersetPageExercisesE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun supersetPageExercises_showsUnifiedSets() {
        SupersetWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(SupersetWorkoutStoreFixture.getWorkoutName())

        // Complete first set (A1) to reach rest screen - PageExercises is reachable from Rest
        workoutDriver.completeCurrentSet()
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)

        val restVisible = device.wait(Until.hasObject(By.textContains(":")), 5_000)
        require(restVisible) { "Rest screen did not appear after completing first set" }

        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)

        val onExercisesPage = workoutDriver.navigateToExercisesPage()
        require(onExercisesPage) {
            "Exercises page not visible after swiping - 'Exercise sets viewer' or 'SET' header not found"
        }

        // Unified superset view shows both exercises' set identifiers: A1, B1, REST, A2, B2.
        // These identifiers are published as semantics by ExerciseSetsViewer and are more stable
        // than asserting raw weight text rendering.
        val supersetA1Found = workoutDriver.findWithScrollFallback(By.desc("A1")) != null
        require(supersetA1Found) {
            "Set identifier A1 not visible - PageExercises should show unified superset sets"
        }

        val supersetB1Found = workoutDriver.findWithScrollFallback(By.desc("B1")) != null
        require(supersetB1Found) {
            "Set identifier B1 not visible - PageExercises should show unified superset sets (A1, B1, ...)"
        }
    }
}
