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
import com.gabstra.myworkoutassistant.composables.ExerciseMetadataStrip
import com.gabstra.myworkoutassistant.composables.FadingText
import com.gabstra.myworkoutassistant.composables.PageButtons
import com.gabstra.myworkoutassistant.composables.PageCalibrationLoad
import com.gabstra.myworkoutassistant.composables.PageExercises
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

enum class CalibrationPageType {
    BUTTONS, EXERCISES, CALIBRATION_LOAD, CALIBRATION_RIR
}

@OptIn(ExperimentalFoundationApi::class, ExperimentalLayoutApi::class)
@Composable
fun CalibrationLoadScreen(
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    state: WorkoutState.CalibrationLoadSelection,
    navController: NavController,
    hearthRateChart: @Composable () -> Unit,
    onWeightSelected: (Double) -> Unit,
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
            add(CalibrationPageType.CALIBRATION_LOAD)
        }
    }

    val calibrationPageIndex = remember(pageTypes) {
        pageTypes.indexOf(CalibrationPageType.CALIBRATION_LOAD)
    }

    val pagerState = rememberPagerState(
        initialPage = calibrationPageIndex,
        pageCount = {
            pageTypes.size
        }
    )

    LaunchedEffect(state.calibrationSet.id) {
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
        FadingText(
            text = exercise.name,
            modifier = Modifier
                .fillMaxWidth()
                .height(20.dp)
                .padding(horizontal = 22.5.dp),
            style = MaterialTheme.typography.titleLarge.copy(
                fontWeight = FontWeight.SemiBold
            ),
            textAlign = TextAlign.Center
        )
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
                            // PageButtons already handles calibration states, but it needs WorkoutState.Set
                            // We'll create a mock Set state that represents the calibration set
                            val mockSetState = remember(state) {
                                WorkoutState.Set(
                                    exerciseId = state.exerciseId,
                                    set = state.calibrationSet,
                                    setIndex = state.setIndex,
                                    previousSetData = state.previousSetData,
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
                                    isUnilateral = state.isUnilateral,
                                    intraSetTotal = null,
                                    intraSetCounter = 0u,
                                    isCalibrationSet = true
                                )
                            }
                            PageButtons(
                                updatedState = mockSetState,
                                viewModel = viewModel,
                                hapticsViewModel = hapticsViewModel,
                                navController = navController
                            )
                        }
                    }

                    CalibrationPageType.EXERCISES -> {
                        key(pageType, pageIndex) {
                            // Create a temporary Set state from calibration state for PageExercises
                            val mockSetState = remember(state) {
                                WorkoutState.Set(
                                    exerciseId = state.exerciseId,
                                    set = state.calibrationSet,
                                    setIndex = state.setIndex,
                                    previousSetData = state.previousSetData,
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
                                    isUnilateral = state.isUnilateral,
                                    intraSetTotal = null,
                                    intraSetCounter = 0u,
                                    isCalibrationSet = true
                                )
                            }
                            PageExercises(
                                selectedExercise = selectedExercise,
                                currentStateSet = mockSetState,
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

                    CalibrationPageType.CALIBRATION_LOAD -> {
                        key(pageType, pageIndex) {
                            PageCalibrationLoad(
                                modifier = Modifier.fillMaxSize(),
                                viewModel = viewModel,
                                hapticsViewModel = hapticsViewModel,
                                state = state,
                                onWeightSelected = onWeightSelected,
                                exerciseTitleComposable = exerciseTitleComposable,
                                extraInfo = { _ ->
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
                                            exerciseLabel = "${currentExerciseOrSupersetIndex.value + 1}/${exerciseOrSupersetIds.size}",
                                            supersetExerciseIndex = if (isSuperset && supersetIndex != null) supersetIndex else null,
                                            supersetExerciseTotal = if (isSuperset && supersetExercises != null) supersetExercises!!.size else null,
                                            setLabel = viewModel.getSetCounterForExercise(
                                                exercise.id,
                                                state
                                            )?.let { (current, total) ->
                                                if (total > 1) "$current/$total" else null
                                            },
                                            sideIndicator = null,
                                            currentSideIndex = null,
                                            isUnilateral = false,
                                            equipmentName = equipment?.name,
                                            accessoryNames = accessoryEquipments.joinToString(", ") { it.name }.takeIf { accessoryEquipments.isNotEmpty() },
                                            textColor = MaterialTheme.colorScheme.onBackground,
                                            onTap = {
                                                hapticsViewModel.doGentleVibration()
                                            }
                                        )
                                    }
                                }
                            )
                        }
                    }

                    CalibrationPageType.CALIBRATION_RIR -> {
                        // This won't be used in CalibrationLoadSelection state
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
