package com.gabstra.myworkoutassistant.e2e

import android.content.Context
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsOff
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextClearance
import androidx.compose.ui.test.performTextInput
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.UiDevice
import com.gabstra.myworkoutassistant.composables.EditPlanNameDialog
import com.gabstra.myworkoutassistant.ui.theme.MyWorkoutAssistantTheme
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PlanSettingsDialogLayoutTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun planSettingsFieldAndSuggestionDoNotOverlapAndSaveReturnsBothValues() {
        var savedName: String? = null
        var savedSuggestion: Boolean? = null
        composeRule.setContent {
            MyWorkoutAssistantTheme {
                EditPlanNameDialog(
                    show = true,
                    currentName = "Recurring plan",
                    suggestNextPrescription = true,
                    onDismiss = {},
                    onConfirm = { name, suggest ->
                        savedName = name
                        savedSuggestion = suggest
                    },
                )
            }
        }
        composeRule.waitForIdle()

        val nameField = composeRule.onNode(hasSetTextAction())
        val toggle = composeRule.onNodeWithTag("suggest_next_prescription_toggle")
        val suggestionLabel = composeRule.onNodeWithText(
            "Suggest the next recurring prescription",
            useUnmergedTree = true,
        )
        nameField.assertIsDisplayed()
        toggle.assertIsDisplayed()
        suggestionLabel.assertIsDisplayed()

        val fieldBounds = nameField.fetchSemanticsNode().boundsInRoot
        val labelBounds = suggestionLabel.fetchSemanticsNode().boundsInRoot
        val toggleBounds = toggle.fetchSemanticsNode().boundsInRoot
        assertTrue(
            "Suggestion label overlaps the plan-name field: field=$fieldBounds label=$labelBounds",
            labelBounds.top >= fieldBounds.bottom,
        )
        assertTrue(
            "Suggestion toggle overlaps the plan-name field: field=$fieldBounds toggle=$toggleBounds",
            toggleBounds.top >= fieldBounds.bottom,
        )

        val targetContext = ApplicationProvider.getApplicationContext<Context>()
        val screenshot = File(targetContext.cacheDir, "plan_settings_dialog_layout.png")
        assertTrue(
            "Could not capture plan settings dialog screenshot at ${screenshot.absolutePath}",
            UiDevice.getInstance(InstrumentationRegistry.getInstrumentation()).takeScreenshot(screenshot),
        )
        println("PLAN_SETTINGS_DIALOG_SCREENSHOT=${screenshot.absolutePath}")

        toggle.performClick()
        toggle.assertIsOff()
        nameField.performTextClearance()
        nameField.performTextInput("  Revised cycle  ")
        composeRule.onNodeWithText("Save").performClick()
        composeRule.waitForIdle()

        assertEquals("Revised cycle", savedName)
        assertEquals(false, savedSuggestion)
    }
}
