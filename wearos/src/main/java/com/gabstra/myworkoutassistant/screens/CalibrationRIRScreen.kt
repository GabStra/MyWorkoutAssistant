package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import com.gabstra.myworkoutassistant.composables.rememberWearCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import androidx.wear.compose.foundation.pager.rememberPagerState
import androidx.wear.compose.material3.MaterialTheme
import com.gabstra.myworkoutassistant.composables.CircularEndsPillShape
import com.gabstra.myworkoutassistant.composables.CustomHorizontalPager
import com.gabstra.myworkoutassistant.composables.ExerciseIndicator
import com.gabstra.myworkoutassistant.composables.ExerciseNameText
import com.gabstra.myworkoutassistant.composables.ExerciseMetadataStrip
import com.gabstra.myworkoutassistant.composables.PageButtons
import com.gabstra.myworkoutassistant.composables.PageCalibrationRIR
import com.gabstra.myworkoutassistant.composables.PageExercises
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@OptIn(ExperimentalFoundationApi::class, ExperimentalLayoutApi::class)
@Composable
fun CalibrationRIRScreen(
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    state: WorkoutState.CalibrationRIRSelection,
    navController: NavController,
    onBeforeGoHome: (() -> Unit)? = null,
    hearthRateChart: @Composable () -> Unit,
    onRIRConfirmed: (Double, Boolean) -> Unit,
) {
    var allowHorizontalScrolling by remember { mutableStateOf(true) }

    val exercise = remember(state.exerciseId) {
        viewModel.exercisesById[state.exerciseId]!!
    }

    val equipment = remember(exercise) {
        exercise.equipmentId?.let { viewModel.getEquipmentById(it) }
    }

    val accessoryEquipments = remember(exercise) {
        (exercise.requiredAccessoryEquipmentIds ?: emptyList()).mapNotNull { id ->
            viewModel.getAccessoryEquipmentById(id)
        }
    }

    val exerciseOrSupersetIds = remember(viewModel.allWorkoutStates.size) {
        viewModel.setsByExerciseId.keys.toList()
            .mapNotNull { if (viewModel.supersetIdByExerciseId.containsKey(it)) viewModel.supersetIdByExerciseId[it] else it }
            .distinct()
    }
    val exerciseOrSupersetId =
        remember(state.exerciseId) { if (viewModel.supersetIdByExerciseId.containsKey(state.exerciseId)) viewModel.supersetIdByExerciseId[state.exerciseId] else state.exerciseId }
    val currentExerciseOrSupersetIndex = remember(exerciseOrSupersetId, exerciseOrSupersetIds) {
        derivedStateOf { exerciseOrSupersetIds.indexOf(exerciseOrSupersetId) }
    }
    val isSuperset = remember(exerciseOrSupersetId) {
        viewModel.exercisesBySupersetId.containsKey(exerciseOrSupersetId)
    }

    var selectedExercise by remember(exercise.id) { mutableStateOf(exercise) }

    val pageTypes = remember {
        mutableListOf<CalibrationPageType>().apply {
            add(CalibrationPageType.BUTTONS)
            add(CalibrationPageType.EXERCISES)
            add(CalibrationPageType.CALIBRATION_RIR)
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

    LaunchedEffect(state.currentSetData) {
        // Navigate to the calibration page
        pagerState.scrollToPage(calibrationPageIndex)
        allowHorizontalScrolling = true
    }

    val scope = rememberWearCoroutineScope()
    var goBackJob by remember { mutableStateOf<Job?>(null) }

    fun restartGoBack() {
        goBackJob?.cancel()

        goBackJob = scope.launch {
            delay(10000)
            val isOnCalibrationPage = pagerState.currentPage == calibrationPageIndex
            if (!isOnCalibrationPage) {
                pagerState.scrollToPage(calibrationPageIndex)
            }
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
                .padding(horizontal = 22.5.dp),
            style = MaterialTheme.typography.titleLarge.copy(
                fontWeight = FontWeight.SemiBold
            ),
            textAlign = TextAlign.Center
        )
    }

    val extraInfo: @Composable (WorkoutState.CalibrationRIRSelection) -> Unit = { rirState ->
        val supersetExercises = remember(exerciseOrSupersetId, isSuperset) {
            if (isSuperset) {
                viewModel.exercisesBySupersetId[exerciseOrSupersetId]!!
            } else null
        }
        val supersetIndex = remember(supersetExercises, exercise) {
            supersetExercises?.indexOf(exercise)
        }

        Column(
            modifier = Modifier.fillMaxWidth(),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(5.dp)
        ) {
            // Metadata strip
            ExerciseMetadataStrip(
                supersetExerciseIndex = if (isSuperset && supersetIndex != null) supersetIndex else null,
                supersetExerciseTotal = if (isSuperset && supersetExercises != null) supersetExercises!!.size else null,
                setLabel = viewModel.getSetCounterForExercise(
                    exercise.id,
                    rirState
                )?.let { (current, total) ->
                    if (total > 1) "$current/$total" else null
                },
                sideIndicator = null,
                currentSideIndex = null,
                isUnilateral = false,
                textColor = MaterialTheme.colorScheme.onBackground,
                onTap = {
                    hapticsViewModel.doGentleVibration()
                }
            )
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 22.5.dp, vertical = 30.dp)
            .clip(CircularEndsPillShape(straightWidth = 50.dp)),
    ) {
        CustomHorizontalPager(
            modifier = Modifier
                .fillMaxSize()
                .pointerInput(Unit) {
                    awaitPointerEventScope {
                        while (true) {
                            val event = awaitPointerEvent()
                            if (event.changes.any { it.pressed }) {
                                restartGoBack()
                            }
                        }
                    }
                },
            pagerState = pagerState,
            userScrollEnabled = allowHorizontalScrolling,
        ) { pageIndex ->
            // Get the page type for the current index
            val pageType = pageTypes[pageIndex]

            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(horizontal = 15.dp)
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
                                    equipment = state.equipment,
                                    isUnilateral = false,
                                    intraSetTotal = null,
                                    intraSetCounter = 0u,
                                    isCalibrationSet = true
                                )
                            }
                            PageButtons(
                                updatedState = mockSetState,
                                viewModel = viewModel,
                                hapticsViewModel = hapticsViewModel,
                                navController = navController,
                                onBeforeGoHome = onBeforeGoHome
                            )
                        }
                    }

                    CalibrationPageType.EXERCISES -> {
                        key(pageType, pageIndex) {
                            PageExercises(
                                selectedExercise = selectedExercise,
                                workoutState = state,
                                viewModel = viewModel,
                                hapticsViewModel = hapticsViewModel,
                                currentExercise = exercise,
                                exerciseOrSupersetIds = exerciseOrSupersetIds,
                                onExerciseSelected = {
                                    selectedExercise = it
                                }
                            )
                        }
                    }

                    CalibrationPageType.CALIBRATION_RIR -> {
                        key(pageType, pageIndex) {
                            PageCalibrationRIR(
                                modifier = Modifier.fillMaxSize(),
                                viewModel = viewModel,
                                hapticsViewModel = hapticsViewModel,
                                state = state,
                                onRIRConfirmed = onRIRConfirmed,
                                exerciseTitleComposable = exerciseTitleComposable,
                                extraInfo = extraInfo
                            )
                        }
                    }

                    CalibrationPageType.CALIBRATION_LOAD -> {
                        // This won't be used in CalibrationRIRSelection state
                    }
                }
            }
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize(),
        contentAlignment = Alignment.Center
    ) {
        ExerciseIndicator(
            viewModel,
            selectedExerciseId = selectedExercise.id
        )

        Box {
            hearthRateChart()
        }
    }

    DisposableEffect(Unit) {
        onDispose {
            goBackJob?.cancel()
        }
    }
}

