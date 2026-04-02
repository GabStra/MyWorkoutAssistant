package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.composables.PageExercisesRestSemantics
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

        val restDurationVisible = device.wait(
            Until.hasObject(By.descContains(PageExercisesRestSemantics.restDurationRowDescription(""))),
            3_000
        )
        require(restDurationVisible) { "Rest duration row semantics were not visible on PageExercises" }

        val transitionVisible = device.wait(
            Until.hasObject(By.desc(PageExercisesRestSemantics.BetweenExercisesTransitionDescription)),
            3_000
        )
        require(transitionVisible) { "Between-exercises transition arrow was not visible on PageExercises" }

        val previousExerciseVisible = device.wait(
            Until.hasObject(By.desc(PageExercisesRestSemantics.previousExerciseDescription("Bench Press"))),
            3_000
        )
        require(previousExerciseVisible) { "Previous exercise semantics were not visible on inter-exercise rest page" }

        val nextExerciseVisible = device.wait(
            Until.hasObject(By.desc(PageExercisesRestSemantics.nextExerciseDescription("Barbell Row"))),
            3_000
        )
        require(nextExerciseVisible) { "Next exercise semantics were not visible on inter-exercise rest page" }
    }
}
