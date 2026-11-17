package com.gabstra.myworkoutassistant.e2e

import android.graphics.Bitmap
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.unit.Density
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.gabstra.myworkoutassistant.composables.FullScreenLoadingIndicator
import com.gabstra.myworkoutassistant.presentation.theme.MyWorkoutAssistantTheme
import com.gabstra.myworkoutassistant.screens.PreparingHeartRateContent
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PreparingScreenTypographyE2ETest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun waitingTextStaysInsideRoundScreenAndDoesNotShiftAsDotsAnimate() {
        val scale = mutableFloatStateOf(1f)
        val message = mutableStateOf("Connecting to WHOOP")
        composeRule.mainClock.autoAdvance = false
        composeRule.setContent {
            val density = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(density.density, scale.floatValue)) {
                MyWorkoutAssistantTheme { FullScreenLoadingIndicator(text = message.value) }
            }
        }

        for (fontScale in listOf(1f, 1.3f)) {
            for (label in listOf("Connecting to WHOOP", "Connecting to Polar",
                "Connecting to your sensor", "Checking your heart rate", "Getting your workout ready")) {
                composeRule.runOnIdle { scale.floatValue = fontScale; message.value = label }
                composeRule.mainClock.advanceTimeByFrame()
                var initialBounds: androidx.compose.ui.geometry.Rect? = null
                for (frame in 0..3) {
                    if (frame > 0) composeRule.mainClock.advanceTimeBy(500)
                    val text = composeRule.onNodeWithText("$label...", useUnmergedTree = true)
                    val layouts = mutableListOf<TextLayoutResult>()
                    text.performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(layouts) }
                    val layout = layouts.single()
                    assertFalse("'$label' clips at font scale $fontScale", layout.hasVisualOverflow)
                    val bounds = text.fetchSemanticsNode().boundsInRoot
                    if (initialBounds == null) initialBounds = bounds
                    else assertEquals("Dot animation moved '$label' at font scale $fontScale", initialBounds, bounds)
                    assertTextFitsRoundScreen(bounds, layout,
                        composeRule.onRoot().fetchSemanticsNode().boundsInRoot, fontScale)
                }
                if (label == "Connecting to WHOOP") saveScreenshot("preparing-waiting-$fontScale.png")
            }
        }
    }

    @Test
    fun failureFallbackWrapsAndKeepsSkipAndBackReachableAtLargeFontScale() {
        val scale = mutableFloatStateOf(1f)
        val canSkip = mutableStateOf(false)
        val loadingText = mutableStateOf("Connecting to WHOOP")
        val needsSensorSetup = mutableStateOf(false)
        val latchReset = mutableStateOf(0)
        var skipped = false
        var wentBack = false
        composeRule.setContent {
            val density = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(density.density, scale.floatValue)) {
                MyWorkoutAssistantTheme {
                    key(scale.floatValue, latchReset.value) {
                        PreparingHeartRateContent(
                            canSkip = canSkip.value,
                            loadingText = loadingText.value,
                            needsSensorSetup = needsSensorSetup.value,
                            onSkip = { skipped = true },
                            onBack = { wentBack = true },
                        )
                    }
                }
            }
        }

        for (fontScale in listOf(1f, 1.3f)) {
            for (setupRequired in listOf(false, true)) {
                composeRule.runOnIdle {
                    scale.floatValue = fontScale
                    latchReset.value++
                    needsSensorSetup.value = setupRequired
                    canSkip.value = false
                    loadingText.value = "Connecting to WHOOP"
                    skipped = false
                    wentBack = false
                }
                composeRule.mainClock.advanceTimeByFrame()
                composeRule.onNodeWithText("Connecting to WHOOP...", useUnmergedTree = true).assertExists()
                composeRule.runOnIdle { canSkip.value = true }
                composeRule.mainClock.advanceTimeByFrame()

                val helpText = if (setupRequired) {
                    "Set up your heart-rate sensor in the phone app, or skip for now."
                } else {
                    "No heart rate yet.\nCheck your sensor or skip for now."
                }
                val status = composeRule.onNodeWithText(helpText, useUnmergedTree = true)
                val layouts = mutableListOf<TextLayoutResult>()
                status.performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(layouts) }
                val layout = layouts.single()
                assertFalse("Failure text clips at font scale $fontScale", layout.hasVisualOverflow)
                assertFalse("Failure text is ellipsized at font scale $fontScale",
                    layout.isLineEllipsized(layout.lineCount - 1))
                assertTextFitsRoundScreen(status.fetchSemanticsNode().boundsInRoot, layout,
                    composeRule.onRoot().fetchSemanticsNode().boundsInRoot, fontScale)
                if (!setupRequired) saveScreenshot("preparing-failure-$fontScale.png")

                val initialStatusBounds = status.fetchSemanticsNode().boundsInRoot
                val initialSkipBounds = composeRule.onNodeWithText("Skip").fetchSemanticsNode().boundsInRoot
                composeRule.runOnIdle {
                    canSkip.value = false
                    loadingText.value = "Getting your workout ready"
                    needsSensorSetup.value = !setupRequired
                }
                composeRule.mainClock.advanceTimeByFrame()
                composeRule.onNodeWithText(helpText, useUnmergedTree = true).assertExists()
                assertEquals(initialStatusBounds,
                    composeRule.onNodeWithText(helpText, useUnmergedTree = true).fetchSemanticsNode().boundsInRoot)
                assertEquals(initialSkipBounds, composeRule.onNodeWithText("Skip").fetchSemanticsNode().boundsInRoot)
                composeRule.runOnIdle { canSkip.value = true }
                composeRule.mainClock.advanceTimeByFrame()
                assertEquals(initialStatusBounds,
                    composeRule.onNodeWithText(helpText, useUnmergedTree = true).fetchSemanticsNode().boundsInRoot)
                assertEquals(initialSkipBounds, composeRule.onNodeWithText("Skip").fetchSemanticsNode().boundsInRoot)

                composeRule.onNodeWithText("Skip").performScrollTo().performClick()
                composeRule.runOnIdle { assertTrue("Skip callback did not fire", skipped) }
                composeRule.onNodeWithText("Back").performScrollTo().performClick()
                composeRule.runOnIdle { assertTrue("Back callback did not fire", wentBack) }
            }
        }
    }

    private fun assertTextFitsRoundScreen(
        textBounds: androidx.compose.ui.geometry.Rect,
        layout: TextLayoutResult,
        screenBounds: androidx.compose.ui.geometry.Rect,
        fontScale: Float,
    ) {
        val centerX = (screenBounds.left + screenBounds.right) / 2f
        val centerY = (screenBounds.top + screenBounds.bottom) / 2f
        val radius = minOf(screenBounds.width, screenBounds.height) / 2f
        val scaleX = textBounds.width / layout.size.width
        val scaleY = textBounds.height / layout.size.height
        for (line in 0 until layout.lineCount) {
            val left = textBounds.left + layout.getLineLeft(line) * scaleX
            val right = textBounds.left + layout.getLineRight(line) * scaleX
            val top = textBounds.top + layout.getLineTop(line) * scaleY
            val bottom = textBounds.top + layout.getLineBottom(line) * scaleY
            for ((x, y) in listOf(left to top, left to bottom, right to top, right to bottom)) {
                assertTrue("Text line $line extends outside round screen at font scale $fontScale: line=($left,$top)-($right,$bottom), screen=$screenBounds",
                    (x - centerX) * (x - centerX) + (y - centerY) * (y - centerY) <= radius * radius)
            }
        }
    }

    private fun saveScreenshot(name: String) {
        val directory = InstrumentationRegistry.getInstrumentation().targetContext.getExternalFilesDir(null)
        val bitmap = composeRule.onRoot().captureToImage().asAndroidBitmap()
        File(directory, name).outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }
}
