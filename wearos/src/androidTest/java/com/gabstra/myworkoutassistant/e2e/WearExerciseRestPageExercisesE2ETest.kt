package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.ExerciseToExerciseRestWorkoutStoreFixture
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearExerciseRestPageExercisesE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun pageExercises_showsStandaloneRestPageBetweenExercises() {
        ExerciseToExerciseRestWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(ExerciseToExerciseRestWorkoutStoreFixture.getWorkoutName())

        workoutDriver.completeCurrentSet()
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)

        val restVisible = device.wait(Until.hasObject(By.textContains(":")), 5_000)
        require(restVisible) { "Rest screen did not appear after completing first exercise" }

        val onExercisesPage = workoutDriver.navigateToExercisesPage()
        require(onExercisesPage) { "Exercises page did not appear from inter-exercise rest" }

        val restSummaryVisible = device.wait(Until.hasObject(By.textContains("REST")), 3_000)
        require(restSummaryVisible) { "Standalone REST summary was not visible on PageExercises" }

        val fromVisible = device.wait(Until.hasObject(By.text("FROM")), 3_000)
        require(fromVisible) { "Standalone inter-exercise rest page did not show FROM context" }

        val toVisible = device.wait(Until.hasObject(By.text("TO")), 3_000)
        require(toVisible) { "Standalone inter-exercise rest page did not show TO context" }

        val previousExerciseVisible = device.wait(Until.hasObject(By.text("Bench Press")), 3_000)
        require(previousExerciseVisible) { "Previous exercise name was not visible on inter-exercise rest page" }

        val nextExerciseVisible = device.wait(Until.hasObject(By.text("Barbell Row")), 3_000)
        require(nextExerciseVisible) { "Next exercise name was not visible on inter-exercise rest page" }
    }
}
