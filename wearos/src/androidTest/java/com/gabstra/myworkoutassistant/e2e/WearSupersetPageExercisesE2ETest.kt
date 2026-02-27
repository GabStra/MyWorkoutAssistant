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

        // Unified superset view shows both exercises' sets: A1 (60 kg), B1 (40 kg), REST, A2, B2.
        // Without unified view we'd only see one exercise's sets. Assert on weights 60 and 40
        // (fixture values for Superset A and B) - their presence proves both exercises are in the list.
        val weight60Found = workoutDriver.findWithScrollFallback(By.text("60")) != null
        require(weight60Found) {
            "Weight 60 (Superset A) not visible - PageExercises should show unified superset sets"
        }

        val weight40Found = workoutDriver.findWithScrollFallback(By.text("40")) != null
        require(weight40Found) {
            "Weight 40 (Superset B) not visible - PageExercises should show unified superset sets (A1, B1, ...)"
        }
    }
}
