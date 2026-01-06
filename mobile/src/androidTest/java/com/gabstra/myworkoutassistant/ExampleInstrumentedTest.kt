package com.gabstra.myworkoutassistant

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.gabstra.myworkoutassistant.screens.WorkoutForm
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutSchedule
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Instrumented tests, which will execute on an Android device.
 */
@RunWith(AndroidJUnit4::class)
class ExampleInstrumentedTest {

    @get:Rule
    val composeRule = createAndroidComposeRule<MainActivity>()

    @Test
    fun useAppContext() {
        // Context of the app under test.
        val appContext = InstrumentationRegistry.getInstrumentation().targetContext
        assertEquals("com.gabstra.myworkoutassistant", appContext.packageName)
    }

    /**
     * Basic sanity check that the outlined text field for workout name is rendered,
     * which indirectly verifies that our shared high-contrast text field styling
     * composes without errors.
     */
    @Test
    fun outlinedTextField_rendersWithLabel() {
        composeRule.setContent {
            WorkoutForm(
                onWorkoutUpsert = { _: Workout, _: List<WorkoutSchedule> -> },
                onCancel = {},
                workout = null,
                isSaving = false,
                existingSchedules = emptyList()
            )
        }

        composeRule.onNodeWithText("Workout name").assertIsDisplayed()
    }
}