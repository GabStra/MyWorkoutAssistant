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

        val restTitleVisible = device.wait(Until.hasObject(By.text("REST")), 3_000)
        require(restTitleVisible) { "Standalone REST title was not visible on PageExercises" }

        val upNextVisible = device.wait(Until.hasObject(By.text("UP NEXT")), 3_000)
        require(upNextVisible) { "Standalone inter-exercise rest page did not show UP NEXT context" }

        val nextExerciseVisible = device.wait(Until.hasObject(By.text("Barbell Row")), 3_000)
        require(nextExerciseVisible) { "Next exercise name was not visible on inter-exercise rest page" }
    }
}
