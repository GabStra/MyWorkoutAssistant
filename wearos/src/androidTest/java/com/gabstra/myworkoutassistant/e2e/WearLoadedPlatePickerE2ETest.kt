package com.gabstra.myworkoutassistant.e2e

import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.unit.Density
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.UiDevice
import androidx.wear.compose.material3.AppScaffold
import com.gabstra.myworkoutassistant.composables.LoadedPlateConfigurationOption
import com.gabstra.myworkoutassistant.composables.LoadedPlateConfigurationPickerOverlay
import com.gabstra.myworkoutassistant.presentation.theme.MyWorkoutAssistantTheme
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearLoadedPlatePickerE2ETest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun loadedPlatePicker_fitsLabelsAndSelectsConfiguration() {
        val scale = mutableStateOf(1f)
        val selected = mutableStateOf<List<Double>?>(null)
        val dismissed = mutableStateOf(false)
        val options = listOf(
            LoadedPlateConfigurationOption(listOf(20.0, 10.0), "20 kg + 10 kg per side", true),
            LoadedPlateConfigurationOption(listOf(20.0, 5.0, 2.5, 2.5), "20 kg + 5 kg + 2.5 kg + 2.5 kg per side", false),
        )
        composeRule.setContent {
            val density = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(density.density, scale.value)) {
                MyWorkoutAssistantTheme {
                    AppScaffold(timeText = {}) {
                        key(scale.value) {
                            LoadedPlateConfigurationPickerOverlay(
                                show = true,
                                options = options,
                                onSelect = { selected.value = it },
                                onDismiss = { dismissed.value = true },
                            )
                        }
                    }
                }
            }
        }
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val device = UiDevice.getInstance(instrumentation)
        val captures = File(instrumentation.targetContext.getExternalFilesDir(null), "loaded-plate-picker").apply {
            mkdirs()
        }
        for (fontScale in listOf(1f, 1.3f)) {
            composeRule.runOnIdle {
                scale.value = fontScale
                selected.value = null
                dismissed.value = false
            }
            composeRule.onNodeWithText(options.first().label).assertIsNotEnabled()
            composeRule.onNodeWithText("(Current)").assertIsDisplayed()
            val label = composeRule.onNodeWithText(options[1].label, useUnmergedTree = true)
            label.performScrollTo().assertIsDisplayed()
            val layouts = mutableListOf<TextLayoutResult>()
            label.performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(layouts) }
            assertTrue("Label should expose its measured layout", layouts.isNotEmpty())
            assertFalse("The complete plate label must fit at font scale $fontScale", layouts.single().hasVisualOverflow)
            assertTrue(device.takeScreenshot(File(captures, "font_$fontScale.png")))
            composeRule.onNodeWithText(options[1].label).performClick()
            composeRule.runOnIdle { assertEquals(options[1].plates, selected.value) }
            composeRule.onNodeWithText("Cancel").performScrollTo().performClick()
            composeRule.runOnIdle { assertTrue(dismissed.value) }
        }
    }
}
