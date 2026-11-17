package com.gabstra.myworkoutassistant.e2e

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.test.platform.app.InstrumentationRegistry
import android.graphics.Bitmap
import java.io.File
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.TextUnit
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.wear.compose.material3.MaterialTheme
import com.gabstra.myworkoutassistant.composables.WearTonalButton
import com.gabstra.myworkoutassistant.composables.WorkoutNameText
import com.gabstra.myworkoutassistant.composables.workout.pages.NotesPage
import com.gabstra.myworkoutassistant.presentation.theme.MyWorkoutAssistantTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearTypographyE2ETest {
    @get:Rule val composeRule = createComposeRule()

    @Test
    fun longWorkoutAndButtonLabelsRemainReadableAtLargeFontScale() {
        val fontScale = mutableFloatStateOf(1f)
        val title = "Upper Body Strength and Conditioning Session A"
        val plateLabel = "20 kg + 10 kg + 5 kg per side"
        var expectedTitleSize = TextUnit.Unspecified

        composeRule.setContent {
            val density = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(density.density, fontScale.floatValue)) {
                MyWorkoutAssistantTheme {
                    expectedTitleSize = MaterialTheme.typography.titleLarge.fontSize
                    Column(Modifier.width(180.dp)) {
                        WorkoutNameText(title)
                        WearTonalButton(
                            modifier = Modifier.fillMaxWidth(),
                            text = plateLabel,
                            supportingText = "Current",
                            onClick = {},
                        )
                    }
                }
            }
        }

        for (scale in listOf(1f, 1.3f)) {
            composeRule.runOnIdle { fontScale.floatValue = scale }
            for (text in listOf(plateLabel, "Current")) {
                val layouts = mutableListOf<TextLayoutResult>()
                composeRule.onNodeWithText(text, useUnmergedTree = true)
                    .performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(layouts) }
                assertTrue("Missing measured layout for '$text' at scale $scale", layouts.isNotEmpty())
                assertFalse("'$text' overflows at scale $scale", layouts.single().hasVisualOverflow)
            }

            val titleLayout = mutableListOf<TextLayoutResult>()
            composeRule.onNodeWithText(title, useUnmergedTree = true)
                .performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(titleLayout) }
            assertTrue("Workout title should fit within two lines at scale $scale", titleLayout.single().lineCount <= 2)
            assertTrue("Workout title should not clip without ellipsis at scale $scale",
                !titleLayout.single().hasVisualOverflow || titleLayout.single().isLineEllipsized(titleLayout.single().lineCount - 1))
            assertEquals("Workout title should retain its title typography role", expectedTitleSize,
                titleLayout.single().layoutInput.style.fontSize)
            assertTrue("Long button label should wrap at scale $scale", run {
                val layouts = mutableListOf<TextLayoutResult>()
                composeRule.onNodeWithText(plateLabel, useUnmergedTree = true)
                    .performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(layouts) }
                layouts.single().lineCount > 1
            })
            val screenshot = composeRule.onRoot().captureToImage().asAndroidBitmap()
            val directory = InstrumentationRegistry.getInstrumentation().targetContext.getExternalFilesDir(null)
            File(directory, "wear-typography-$scale.png").outputStream().use {
                screenshot.compress(Bitmap.CompressFormat.PNG, 100, it)
            }
        }
    }

    @Test
    fun pageHeadersRetainTitleSizeAndSeparateNotesContent() {
        val fontScale = mutableFloatStateOf(1f)
        val notes = "Keep a controlled tempo."
        var expectedTitleSize = TextUnit.Unspecified
        composeRule.setContent {
            val density = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(density.density, fontScale.floatValue)) {
                MyWorkoutAssistantTheme {
                    expectedTitleSize = MaterialTheme.typography.titleLarge.fontSize
                    NotesPage(notes)
                }
            }
        }
        for (scale in listOf(1f, 1.3f)) {
            composeRule.runOnIdle { fontScale.floatValue = scale }
            val header = composeRule.onNodeWithText("Notes")
            val layouts = mutableListOf<TextLayoutResult>()
            header.performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(layouts) }
            assertEquals(expectedTitleSize, layouts.single().layoutInput.style.fontSize)
            assertFalse("Page header clips at font scale $scale", layouts.single().hasVisualOverflow)
            val bodyBounds = composeRule.onNodeWithText(notes).fetchSemanticsNode().boundsInRoot
            assertTrue("Notes overlap their page header at font scale $scale",
                bodyBounds.top > header.fetchSemanticsNode().boundsInRoot.bottom)
            val directory = InstrumentationRegistry.getInstrumentation().targetContext.getExternalFilesDir(null)
            File(directory, "wear-page-header-$scale.png").outputStream().use {
                composeRule.onRoot().captureToImage().asAndroidBitmap().compress(Bitmap.CompressFormat.PNG, 100, it)
            }
        }
    }
}
