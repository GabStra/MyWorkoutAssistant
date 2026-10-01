package com.gabstra.myworkoutassistant.e2e

import android.os.SystemClock
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.longClick
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.swipeUp
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.UiDevice
import androidx.wear.compose.material3.AppScaffold
import com.gabstra.myworkoutassistant.composables.HeartRateCircularChart
import com.gabstra.myworkoutassistant.composables.LocalTopOverlayController
import com.gabstra.myworkoutassistant.composables.TutorialOverlay
import com.gabstra.myworkoutassistant.composables.TutorialStep
import com.gabstra.myworkoutassistant.composables.WorkoutNameText
import com.gabstra.myworkoutassistant.composables.rememberTopOverlayController
import com.gabstra.myworkoutassistant.data.HapticsHelper
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.presentation.theme.MyWorkoutAssistantTheme
import com.gabstra.myworkoutassistant.repository.SensorDataRepository
import com.gabstra.myworkoutassistant.screens.AutoRegulationRIRScreen
import com.gabstra.myworkoutassistant.screens.CalibrationLoadScreen
import com.gabstra.myworkoutassistant.screens.CalibrationRIRScreen
import com.gabstra.myworkoutassistant.screens.ExercisePreviewScenario
import com.gabstra.myworkoutassistant.screens.ExercisePreviewSetType
import com.gabstra.myworkoutassistant.screens.WorkoutDetailScreen
import com.gabstra.myworkoutassistant.screens.buildExercisePreviewFixture
import com.gabstra.myworkoutassistant.screens.findFieldRecursively
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.viewmodels.HeartRateChangeViewModel
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.ui.IncompleteWorkoutStrings
import java.io.File
import java.util.UUID
import kotlinx.coroutines.flow.MutableStateFlow
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Exercises production UI at two representative viewport/text settings, without persistent data changes. */
@RunWith(AndroidJUnit4::class)
class WearUiConsistencyE2ETest {
    @get:Rule val composeRule = createComposeRule()

    private data class Case(val page: String, val widthDp: Int, val fontScale: Float)

    @Test
    fun productionUi_preservesLabelsControlsAndSafeAreas() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val device = UiDevice.getInstance(instrumentation)
        device.wakeUp()
        val pages = listOf("heart", "name", "rir", "auto_rir", "load_min", "load_max", "detail", "tutorial")
        val current = mutableStateOf(Case(pages.first(), 240, 1f))
        val workoutName = "Upper Body Strength and Conditioning Session A"
        val captures = File(context.getExternalFilesDir(null), "wear-ui-consistency").apply { mkdirs() }
        var expectedLoadLabel = ""
        composeRule.mainClock.autoAdvance = false
        composeRule.setContent {
            val case = current.value
            CompositionLocalProvider(LocalDensity provides Density(device.displayWidth.toFloat() / case.widthDp, case.fontScale)) {
                MyWorkoutAssistantTheme {
                    AppScaffold(timeText = {}) {
                        key(case) {
                            val fixture = remember {
                                buildExercisePreviewFixture(ExercisePreviewScenario("consistency", ExercisePreviewSetType.WEIGHT)).also { fixture ->
                                    if (case.page == "detail") {
                                        val viewModel = fixture.viewModel
                                        val workout = viewModel.selectedWorkout.value.copy(name = workoutName)
                                        field<MutableState<UUID?>>(viewModel, "_selectedWorkoutId").value = workout.id
                                        field<MutableStateFlow<List<Workout>>>(viewModel, "_workouts").value = listOf(workout)
                                        field<MutableStateFlow<Boolean>>(viewModel, "_hasWorkoutRecord").value = true
                                    }
                                }
                            }
                            val viewModel = fixture.viewModel
                            val state = fixture.state
                            val haptics = remember { HapticsViewModel(context, HapticsHelper(context)) }
                            val navigation = remember { NavController(context) }
                            val hrChanges = remember { HeartRateChangeViewModel() }
                            val overlay = rememberTopOverlayController()
                            DisposableEffect(fixture) {
                                onDispose { viewModel.workoutTimerService.unregisterAll() }
                            }
                            val heartRate: @androidx.compose.runtime.Composable (Modifier) -> Unit = { modifier ->
                                HeartRateCircularChart(
                                    modifier = modifier, appViewModel = viewModel, hapticsViewModel = haptics,
                                    heartRateChangeViewModel = hrChanges, hr = 140, age = 30,
                                    measuredMaxHeartRate = null, restingHeartRate = null,
                                    lowerBoundMaxHRPercent = null, upperBoundMaxHRPercent = null,
                                )
                            }
                            CompositionLocalProvider(LocalTopOverlayController provides overlay) {
                                when (case.page) {
                                    "heart" -> heartRate(Modifier.fillMaxSize())
                                    "name" -> Box(Modifier.fillMaxSize().padding(horizontal = 25.dp, vertical = 40.dp)) {
                                        WorkoutNameText(workoutName)
                                    }
                                    "rir" -> CalibrationRIRScreen(
                                        viewModel, haptics,
                                        WorkoutState.CalibrationRIRSelection(state.exerciseId, state.set, state.setIndex,
                                            state.currentSetDataState, state.equipmentId, currentBodyWeight = state.currentBodyWeight),
                                        navigation, hearthRateChart = heartRate, onRIRConfirmed = { _, _ -> },
                                    )
                                    "auto_rir" -> AutoRegulationRIRScreen(
                                        viewModel, haptics,
                                        WorkoutState.AutoRegulationRIRSelection(state.exerciseId, state.set, state.setIndex,
                                            state.currentSetDataState, state.equipmentId, currentBodyWeight = state.currentBodyWeight),
                                        navigation, hearthRateChart = heartRate,
                                    )
                                    "load_min", "load_max" -> {
                                        val equipment = remember { viewModel.getEquipmentById(state.equipmentId!!)!! }
                                        val weights = remember { viewModel.getWeightByEquipment(equipment).sorted() }
                                        val weight = if (case.page == "load_min") weights.first() else weights.last()
                                        expectedLoadLabel = equipment.formatWeight(weight)
                                        val loadData = remember {
                                            mutableStateOf<SetData>((state.currentSetData as WeightSetData).copy(actualWeight = weight))
                                        }
                                        CalibrationLoadScreen(
                                            viewModel, haptics,
                                            WorkoutState.CalibrationLoadSelection(state.exerciseId, state.set, state.setIndex,
                                                null, loadData, state.equipmentId, currentBodyWeight = state.currentBodyWeight),
                                            navigation, hearthRateChart = heartRate, onWeightSelected = {},
                                        )
                                    }
                                    "detail" -> {
                                        val sensors = remember { SensorDataViewModel(SensorDataRepository(context)) }
                                        WorkoutDetailScreen(navigation, viewModel, haptics, sensors)
                                    }
                                    "tutorial" -> TutorialOverlay(
                                        visible = true,
                                        steps = listOf(
                                            TutorialStep("Adjust your set", "Long press a value to edit weight, repetitions, or timer duration."),
                                            TutorialStep("Browse workout pages", "Swipe horizontally to review exercise information, muscle groups, and upcoming sets."),
                                            TutorialStep("Confirm your selection", "Use the watch back button to open the confirmation dialog."),
                                        ),
                                        onDismiss = {},
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
        fun settle() {
            composeRule.mainClock.advanceTimeBy(1000)
            SystemClock.sleep(450)
            composeRule.mainClock.advanceTimeBy(500)
            composeRule.waitForIdle()
        }
        fun assertFits(text: String, allowTitleEllipsis: Boolean = false) {
            val layouts = mutableListOf<TextLayoutResult>()
            composeRule.onNodeWithText(text, useUnmergedTree = true)
                .performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(layouts) }
            assertTrue("Missing text measurement: $text", layouts.isNotEmpty())
            val layout = layouts.single()
            if (allowTitleEllipsis) {
                assertTrue("Title must use at most two lines", layout.lineCount <= 2)
                assertTrue("Title overflow must use ellipsis", !layout.hasVisualOverflow || layout.isLineEllipsized(layout.lineCount - 1))
            } else {
                assertFalse("Text overflows: $text in ${current.value}", layout.hasVisualOverflow)
                assertFalse("Text is truncated: $text in ${current.value}",
                    (0 until layout.lineCount).any { layout.isLineEllipsized(it) })
            }
        }
        for ((width, fontScale) in listOf(240 to 1f, 240 to 1.3f)) {
            for (page in pages) {
                instrumentation.runOnMainSync { current.value = Case(page, width, fontScale) }
                settle()
                when (page) {
                    "heart" -> { assertFits("140 bpm"); assertFits("Z2") }
                    "name" -> assertFits(workoutName, allowTitleEllipsis = true)
                    "rir", "auto_rir" -> {
                        assertFits("0 = Form Breaks")
                        val hintBounds = composeRule.onNodeWithText("0 = Form Breaks").fetchSemanticsNode().boundsInRoot
                        assertTrue("RIR hint must clear the heart-rate area",
                            hintBounds.bottom <= device.displayHeight - 32.5f * device.displayWidth / width + 1f)
                        val bounds = composeRule.onAllNodesWithText("Preview Exercise", substring = true)
                            .fetchSemanticsNodes().first {
                                val bounds = it.boundsInRoot
                                kotlin.math.abs(bounds.left - 52.5f * device.displayWidth / width) < 1f
                            }.boundsInRoot
                        assertTrue("Exercise title must clear header", bounds.top >= 32.5f * device.displayWidth / width - 1f)
                    }
                    "load_min", "load_max" -> {
                        assertTrue(device.takeScreenshot(File(captures, "${page}_initial_${width}_font_$fontScale.png")))
                        composeRule.onNodeWithText(expectedLoadLabel).performTouchInput { longClick() }
                        settle()
                        assertFits(expectedLoadLabel)
                        assertFits("WEIGHT (KG)")
                        val backBounds = composeRule.onNodeWithContentDescription("Back").fetchSemanticsNode().boundsInRoot
                        assertTrue("Edit controls must clear the heart-rate area",
                            backBounds.bottom <= device.displayHeight - 32.5f * device.displayWidth / width + 1f)
                        val minus = composeRule.onNodeWithContentDescription("Subtract")
                        for (control in listOf("Subtract", "Add", "Back", "Reset")) {
                            val bounds = composeRule.onNodeWithContentDescription(control).fetchSemanticsNode().boundsInRoot
                            val density = device.displayWidth.toFloat() / width
                            val paintedDiameter = if (control == "Subtract" || control == "Add") 50f else 40f
                            val touchTargetInset = (bounds.width - paintedDiameter * density) / 2f
                            assertTrue("$control must clear the side indicators",
                                bounds.left + touchTargetInset >= 50f * density &&
                                    bounds.right - touchTargetInset <= device.displayWidth - 50f * density)
                        }
                        val plus = composeRule.onNodeWithContentDescription("Add")
                        if (page == "load_min") { minus.assertIsNotEnabled(); plus.assertIsEnabled() }
                        else { minus.assertIsEnabled(); plus.assertIsNotEnabled() }
                    }
                    "detail" -> {
                        composeRule.onNodeWithText("Resume").assertExists()
                        assertTrue(device.takeScreenshot(File(captures, "detail_actions_${width}_font_$fontScale.png")))
                        composeRule.mainClock.autoAdvance = true
                        composeRule.onNodeWithText("Start new").performScrollTo().performClick()
                        settle()
                        composeRule.onNodeWithText(IncompleteWorkoutStrings.START_NEW_WORKOUT_TITLE).assertIsDisplayed()
                        composeRule.mainClock.autoAdvance = false
                    }
                    "tutorial" -> {
                        composeRule.mainClock.autoAdvance = true
                        composeRule.onNodeWithText("Got it").performScrollTo()
                        composeRule.onRoot().performTouchInput { swipeUp() }
                        composeRule.waitForIdle()
                        val button = composeRule.onNodeWithText("Got it").assertIsDisplayed()
                        val bounds = button.fetchSemanticsNode().boundsInRoot
                        assertTrue("Tutorial button needs bottom clearance", bounds.bottom <= device.displayHeight - 20f * device.displayWidth / width + 1f)
                        composeRule.mainClock.autoAdvance = false
                    }
                }
                assertTrue(device.takeScreenshot(File(captures, "${page}_${width}_font_$fontScale.png")))
            }
        }
    }

    @Suppress("UNCHECKED_CAST")
    private fun <T> field(target: Any, name: String): T =
        findFieldRecursively(target.javaClass, name)!!.apply { isAccessible = true }.get(target) as T
}
