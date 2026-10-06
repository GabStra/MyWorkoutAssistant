package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.composables.workout.pages.ExercisesPageRestSemantics
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.ExerciseToExerciseRestWorkoutStoreFixture
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearExerciseRestExercisesPageE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun exercisesPage_showsStandaloneRestPageBetweenExercises() {
        ExerciseToExerciseRestWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(ExerciseToExerciseRestWorkoutStoreFixture.getWorkoutName())

        workoutDriver.completeCurrentSet()
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)

        val restVisible = device.wait(Until.hasObject(By.textContains(":")), 5_000)
        require(restVisible) { "Rest screen did not appear after completing first exercise" }

        val onExercisesPage = workoutDriver.navigateToExercisesPage()
        require(onExercisesPage) { "Exercises page did not appear from inter-exercise rest" }

        val restDurationVisible = device.wait(
            Until.hasObject(By.descContains(ExercisesPageRestSemantics.restDurationRowDescription(""))),
            3_000
        )
        require(restDurationVisible) { "Rest duration row semantics were not visible on ExercisesPage" }

        val upNextVisible = device.wait(
            Until.hasObject(By.text("UP NEXT")),
            3_000
        )
        require(upNextVisible) { "UP NEXT label was not visible on the inter-exercise rest page" }

        val nextExerciseVisible = device.wait(
            Until.hasObject(By.desc(ExercisesPageRestSemantics.nextExerciseDescription("Barbell Row"))),
            3_000
        )
        require(nextExerciseVisible) { "Next exercise semantics were not visible on inter-exercise rest page" }
    }
}
