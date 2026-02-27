package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import com.gabstra.myworkoutassistant.composables.rememberWearCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.navigation.NavController
import androidx.wear.compose.foundation.pager.rememberPagerState
import androidx.wear.compose.material3.MaterialTheme
import com.gabstra.myworkoutassistant.composables.CustomHorizontalPager
import com.gabstra.myworkoutassistant.composables.ExerciseIndicator
import com.gabstra.myworkoutassistant.composables.ExerciseNameText
import com.gabstra.myworkoutassistant.composables.PageButtons
import com.gabstra.myworkoutassistant.composables.PageCalibrationRIR
import com.gabstra.myworkoutassistant.composables.PageExercises
import com.gabstra.myworkoutassistant.composables.WorkoutPagerLayoutTokens
import com.gabstra.myworkoutassistant.composables.WorkoutPagerPageSafeAreaPadding
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private const val CALIBRATION_RIR_PAGER_AUTO_RETURN_DELAY_MS = 15000L

@OptIn(ExperimentalFoundationApi::class, ExperimentalLayoutApi::class)
@Composable
fun CalibrationRIRScreen(
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    state: WorkoutState.CalibrationRIRSelection,
    navController: NavController,
    onBeforeGoHome: (() -> Unit)? = null,
    hearthRateChart: @Composable (Modifier) -> Unit,
    onRIRConfirmed: (Double, Boolean) -> Unit,
) {
    var allowHorizontalScrolling by remember { mutableStateOf(true) }

    val exercise = remember(state.exerciseId) {
        viewModel.exercisesById[state.exerciseId]!!
    }

    var selectedExercise by remember(exercise.id) { mutableStateOf(exercise) }

    val pageTypes = remember {
        mutableListOf<CalibrationPageType>().apply {
            add(CalibrationPageType.BUTTONS)
            add(CalibrationPageType.CALIBRATION_RIR)
            add(CalibrationPageType.EXERCISES)
        }
    }

    val calibrationPageIndex = remember(pageTypes) {
        pageTypes.indexOf(CalibrationPageType.CALIBRATION_RIR)
    }

    val pagerState = rememberPagerState(
        initialPage = calibrationPageIndex,
        pageCount = {
            pageTypes.size
        }
    )
    LaunchedEffect(state.calibrationSet.id) {
        // Navigate to the calibration page only when needed.
        if (pagerState.currentPage != calibrationPageIndex) {
            pagerState.scrollToPage(calibrationPageIndex)
        }
        allowHorizontalScrolling = true
    }

    val scope = rememberWearCoroutineScope()
    var goBackJob by remember { mutableStateOf<Job?>(null) }

    fun restartGoBack() {
        goBackJob?.cancel()

        goBackJob = scope.launch {
            delay(CALIBRATION_RIR_PAGER_AUTO_RETURN_DELAY_MS)
            val isOnCalibrationPage = pagerState.currentPage == calibrationPageIndex
            if (!isOnCalibrationPage && !pagerState.isScrollInProgress) {
                pagerState.scrollToPage(calibrationPageIndex)
            }
        }
    }

    LaunchedEffect(pagerState.currentPage) {
        if (pagerState.currentPage == calibrationPageIndex) {
            goBackJob?.cancel()
        } else {
            restartGoBack()
        }
    }

    LaunchedEffect(pagerState.currentPage) {
        val isOnExercisesPage = pagerState.currentPage == pageTypes.indexOf(CalibrationPageType.EXERCISES)
        if (!isOnExercisesPage) {
            selectedExercise = exercise
        }
    }

    val exerciseTitleComposable: @Composable () -> Unit = {
        ExerciseNameText(
            text = exercise.name,
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = WorkoutPagerLayoutTokens.ExerciseTitleHorizontalPadding),
            style = MaterialTheme.typography.titleLarge.copy(
                fontWeight = FontWeight.SemiBold
            ),
            textAlign = TextAlign.Center
        )
    }

    Box(
        modifier = Modifier.fillMaxSize(),
    ) {
        CustomHorizontalPager(
            modifier = Modifier
                .fillMaxSize(),
            pagerState = pagerState,
            userScrollEnabled = allowHorizontalScrolling,
            pageOverlay = { pageIndex ->
                if (pageTypes[pageIndex] == CalibrationPageType.CALIBRATION_RIR) {
                    hearthRateChart(Modifier.fillMaxSize())
                    ExerciseIndicator(
                        viewModel = viewModel,
                        modifier = Modifier.fillMaxSize(),
                        selectedExerciseId = selectedExercise.id
                    )
                }
            }
        ) { pageIndex ->
            // Get the page type for the current index
            val pageType = pageTypes[pageIndex]

            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(WorkoutPagerPageSafeAreaPadding)
                    .clipToBounds()
            ) {
                when (pageType) {
                    CalibrationPageType.BUTTONS -> {
                        key(pageType, pageIndex) {
                            // Create a temporary Set state from calibration state for PageButtons
                            val mockSetState = remember(state) {
                                WorkoutState.Set(
                                    exerciseId = state.exerciseId,
                                    set = state.calibrationSet,
                                    setIndex = state.setIndex,
                                    previousSetData = null,
                                    currentSetDataState = state.currentSetDataState,
                                    hasNoHistory = true,
                                    startTime = null,
                                    skipped = false,
                                    lowerBoundMaxHRPercent = state.lowerBoundMaxHRPercent,
                                    upperBoundMaxHRPercent = state.upperBoundMaxHRPercent,
                                    currentBodyWeight = state.currentBodyWeight,
                                    plateChangeResult = null,
                                    streak = 0,
                                    progressionState = null,
                                    isWarmupSet = false,
                                    equipmentId = state.equipmentId,
                                    isUnilateral = false,
                                    intraSetTotal = null,
                                    intraSetCounter = 0u,
                                    isCalibrationSet = true
                                )
                            }
                            Box(modifier = Modifier.fillMaxSize()) {
                                PageButtons(
                                    updatedState = mockSetState,
                                    viewModel = viewModel,
                                    hapticsViewModel = hapticsViewModel,
                                    navController = navController,
                                    onBeforeGoHome = onBeforeGoHome
                                )
                            }
                        }
                    }

                    CalibrationPageType.EXERCISES -> {
                        key(pageType, pageIndex) {
                            Box(modifier = Modifier.fillMaxSize()) {
                                PageExercises(
                                    selectedExercise = selectedExercise,
                                    workoutState = state,
                                    viewModel = viewModel,
                                    hapticsViewModel = hapticsViewModel,
                                    currentExercise = exercise,
                                    onExerciseSelected = {
                                        selectedExercise = it
                                    }
                                )
                            }
                        }
                    }

                    CalibrationPageType.CALIBRATION_RIR -> {
                        key(pageType, pageIndex) {
                            Box(modifier = Modifier.fillMaxSize()) {
                                Box(
                                    modifier = Modifier
                                        .fillMaxSize()
                                        .padding(horizontal = WorkoutPagerLayoutTokens.OverlayContentHorizontalPadding)
                                ) {
                                    PageCalibrationRIR(
                                        modifier = Modifier.fillMaxSize(),
                                        viewModel = viewModel,
                                        hapticsViewModel = hapticsViewModel,
                                        state = state,
                                        onRIRConfirmed = onRIRConfirmed,
                                        exerciseTitleComposable = exerciseTitleComposable
                                    )
                                }
                            }
                        }
                    }

                    CalibrationPageType.CALIBRATION_LOAD -> {
                        // This won't be used in CalibrationRIRSelection state
                    }
                }
            }
        }
    }

    DisposableEffect(Unit) {
        onDispose {
            goBackJob?.cancel()
        }
    }
}
