package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import androidx.wear.compose.foundation.pager.rememberPagerState
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.composables.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composables.CustomHorizontalPager
import com.gabstra.myworkoutassistant.composables.ExerciseDetail
import com.gabstra.myworkoutassistant.composables.ExerciseIndicator
import com.gabstra.myworkoutassistant.composables.ExerciseMetadataStrip
import com.gabstra.myworkoutassistant.composables.ExerciseNameText
import com.gabstra.myworkoutassistant.composables.PageButtons
import com.gabstra.myworkoutassistant.composables.PageExercises
import com.gabstra.myworkoutassistant.composables.PageMuscles
import com.gabstra.myworkoutassistant.composables.PageNotes
import com.gabstra.myworkoutassistant.composables.PagePlates
import com.gabstra.myworkoutassistant.composables.PageProgressionComparison
import com.gabstra.myworkoutassistant.composables.PageTitledLines
import com.gabstra.myworkoutassistant.composables.TitledLinesSection
import com.gabstra.myworkoutassistant.composables.WorkoutPagerLayoutTokens
import com.gabstra.myworkoutassistant.composables.WorkoutPagerPageSafeAreaPadding
import com.gabstra.myworkoutassistant.composables.rememberWearCoroutineScope
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.UUID

private enum class ExerciseHorizontalPage {
    BUTTONS,
    PLATES,
    EXERCISE_DETAIL,
    TITLED_LINES,
    MUSCLES,
    PROGRESSION_COMPARISON,
    NOTES,
    EXERCISES
}

private const val EXERCISE_PAGER_AUTO_RETURN_DELAY_MS = 15000L

@OptIn(ExperimentalFoundationApi::class, ExperimentalLayoutApi::class)
@Composable
fun ExerciseScreen(
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    state: WorkoutState.Set,
    hearthRateChart: @Composable (Modifier) -> Unit,
    navController: NavController,
    onBeforeGoHome: (() -> Unit)? = null,
) {
    var isEditModeEnabled by remember { mutableStateOf(false) }
    val showNextDialog by viewModel.isCustomDialogOpen.collectAsState()
    val isPaused by viewModel.isPaused

    val exercise = remember(state.exerciseId) { viewModel.exercisesById[state.exerciseId]!! }
    val equipment = remember(exercise) { exercise.equipmentId?.let { viewModel.getEquipmentById(it) } }
    val accessoryEquipments = remember(exercise) {
        (exercise.requiredAccessoryEquipmentIds ?: emptyList()).mapNotNull { id ->
            viewModel.getAccessoryEquipmentById(id)
        }
    }

    val showPlatesPage = remember(exercise, equipment) {
        equipment != null &&
            equipment.type == EquipmentType.BARBELL &&
            equipment.name.contains("barbell", ignoreCase = true) &&
            (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT)
    }
    val showNotesPage = remember(exercise) { exercise.notes.isNotEmpty() }
    val hasMuscleInfo = remember(exercise) { !exercise.muscleGroups.isNullOrEmpty() }
    val showTitledLinesPage = remember(exercise, equipment, accessoryEquipments) {
        exercise.notes.isNotEmpty() || equipment != null || accessoryEquipments.isNotEmpty()
    }
    val showProgressionComparisonPage = remember(exercise) {
        !exercise.requiresLoadCalibration &&
            viewModel.exerciseProgressionByExerciseId.containsKey(exercise.id) &&
            viewModel.lastSessionWorkout != null &&
            ((viewModel.lastSessionWorkout!!.workoutComponents.filterIsInstance<Exercise>() +
                viewModel.lastSessionWorkout!!.workoutComponents
                    .filterIsInstance<com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset>()
                    .flatMap { it.exercises }).any { it.id == exercise.id })
    }

    val pageTypes = remember(
        showPlatesPage,
        showTitledLinesPage,
        hasMuscleInfo,
        showProgressionComparisonPage,
        showNotesPage
    ) {
        mutableListOf<ExerciseHorizontalPage>().apply {
            add(ExerciseHorizontalPage.BUTTONS)
            if (showPlatesPage) add(ExerciseHorizontalPage.PLATES)
            add(ExerciseHorizontalPage.EXERCISE_DETAIL)
            if (showTitledLinesPage) add(ExerciseHorizontalPage.TITLED_LINES)
            //if (hasMuscleInfo) add(ExerciseHorizontalPage.MUSCLES)
            //if (showProgressionComparisonPage) add(ExerciseHorizontalPage.PROGRESSION_COMPARISON)
            //if (showNotesPage) add(ExerciseHorizontalPage.NOTES)
            add(ExerciseHorizontalPage.EXERCISES)
        }
    }

    val exerciseDetailPageIndex = remember(pageTypes) {
        pageTypes.indexOf(ExerciseHorizontalPage.EXERCISE_DETAIL)
    }
    val exercisesPageIndex = remember(pageTypes) {
        pageTypes.indexOf(ExerciseHorizontalPage.EXERCISES)
    }
    val platesPageIndex = remember(pageTypes) {
        pageTypes.indexOf(ExerciseHorizontalPage.PLATES)
    }
    val progressionPageIndex = remember(pageTypes) {
        pageTypes.indexOf(ExerciseHorizontalPage.PROGRESSION_COMPARISON)
    }

    val horizontalPagerState = rememberPagerState(
        initialPage = exerciseDetailPageIndex,
        pageCount = { pageTypes.size }
    )

    LaunchedEffect(state.set.id) {
        if (horizontalPagerState.currentPage != exerciseDetailPageIndex) {
            horizontalPagerState.scrollToPage(exerciseDetailPageIndex)
        }
        isEditModeEnabled = false
        if (showNextDialog) {
            viewModel.closeCustomDialog()
        }
    }

    val scope = rememberWearCoroutineScope()
    var goBackJob by remember { mutableStateOf<Job?>(null) }
    var shouldResumeTimerAfterDialog by remember(state.set.id) { mutableStateOf(false) }

    fun restartGoBack() {
        goBackJob?.cancel()
        goBackJob = scope.launch {
            delay(EXERCISE_PAGER_AUTO_RETURN_DELAY_MS)
            val isOnExerciseDetailPage = horizontalPagerState.currentPage == exerciseDetailPageIndex
            if (!isOnExerciseDetailPage && !horizontalPagerState.isScrollInProgress) {
                horizontalPagerState.scrollToPage(exerciseDetailPageIndex)
            }
        }
    }

    val exerciseOrSupersetIds = remember(viewModel.allWorkoutStates.size) {
        viewModel.setsByExerciseId.keys.toList()
            .mapNotNull {
                if (viewModel.supersetIdByExerciseId.containsKey(it)) {
                    viewModel.supersetIdByExerciseId[it]
                } else {
                    it
                }
            }
            .distinct()
    }
    val exerciseOrSupersetId = remember(state.exerciseId) {
        viewModel.supersetIdByExerciseId[state.exerciseId] ?: state.exerciseId
    }
    val isSuperset = remember(exerciseOrSupersetId) {
        viewModel.exercisesBySupersetId.containsKey(exerciseOrSupersetId)
    }
    var selectedExercise by remember(exercise.id) { mutableStateOf(exercise) }
    val context = LocalContext.current

    LaunchedEffect(horizontalPagerState.currentPage) {
        if (horizontalPagerState.currentPage == exerciseDetailPageIndex) {
            goBackJob?.cancel()
        } else {
            restartGoBack()
        }
    }

    LaunchedEffect(horizontalPagerState.currentPage) {
        val isOnPlatesPage = platesPageIndex >= 0 && horizontalPagerState.currentPage == platesPageIndex
        if (isOnPlatesPage) viewModel.setDimming(false) else viewModel.reEvaluateDimmingForCurrentState()

        if (horizontalPagerState.currentPage != exercisesPageIndex) {
            selectedExercise = exercise
        }

        if (horizontalPagerState.currentPage != exerciseDetailPageIndex) {
            isEditModeEnabled = false
        }
    }

    key(state.exerciseId to state.set.id) {
        val exerciseTitleComposable: @Composable (onLongClick: () -> Unit) -> Unit =
            { providedOnLongClick ->
                ExerciseNameText(
                    text = exercise.name,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = WorkoutPagerLayoutTokens.ExerciseTitleHorizontalPadding)
                        .combinedClickable(
                            onClick = {  },
                            onLongClick = { providedOnLongClick.invoke() }
                        ),
                    style = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.SemiBold),
                    textAlign = TextAlign.Center
                )
            }

        Box(modifier = Modifier.fillMaxSize()) {
            CustomHorizontalPager(
                modifier = Modifier.fillMaxSize(),
                pagerState = horizontalPagerState,
                userScrollEnabled = !isEditModeEnabled,
                animatePages = false,
                beyondViewportPageCount = 0,
                pageOverlay = { pageIndex ->
                    if (pageTypes[pageIndex] == ExerciseHorizontalPage.EXERCISE_DETAIL) {
                        hearthRateChart(Modifier.fillMaxSize())
                        ExerciseIndicator(
                            viewModel = viewModel,
                            modifier = Modifier.fillMaxSize(),
                            selectedExerciseId = selectedExercise.id
                        )
                    }
                }
            ) { pageIndex ->
                val pageModifier = Modifier
                    .fillMaxSize()
                    .padding(WorkoutPagerPageSafeAreaPadding)
                    .clipToBounds()
                when (pageTypes[pageIndex]) {
                    ExerciseHorizontalPage.BUTTONS -> {
                        Box(modifier = pageModifier) {
                            PageButtons(state, viewModel, hapticsViewModel, navController, onBeforeGoHome)
                        }
                    }

                    ExerciseHorizontalPage.PLATES -> {
                        if (equipment != null) {
                            Box(modifier = pageModifier) {
                                PagePlates(state, equipment, hapticsViewModel, viewModel)
                            }
                        }
                    }

                    ExerciseHorizontalPage.EXERCISE_DETAIL -> {
                        Box(modifier = pageModifier) {
                            ExerciseDetailContent(
                                state = state,
                                viewModel = viewModel,
                                hapticsViewModel = hapticsViewModel,
                                exercise = exercise,
                                exerciseOrSupersetId = exerciseOrSupersetId,
                                isSuperset = isSuperset,
                                exerciseTitleComposable = exerciseTitleComposable,
                                onEditModeEnabled = { isEditModeEnabled = true },
                                onEditModeDisabled = { isEditModeEnabled = false }
                            )
                        }
                    }

                    ExerciseHorizontalPage.TITLED_LINES -> {
                        val titledLinesSections = remember(exercise, equipment, accessoryEquipments) {
                            val sections = mutableListOf<TitledLinesSection>()
                            if (exercise.notes.isNotEmpty()) {
                                sections.add(TitledLinesSection("Notes", listOf(exercise.notes)))
                            }
                            equipment?.let { sections.add(TitledLinesSection("Equipment", listOf(it.name))) }
                            if (accessoryEquipments.isNotEmpty()) {
                                sections.add(
                                    TitledLinesSection(
                                        "Accessories",
                                        accessoryEquipments.map { it.name }
                                    )
                                )
                            }
                            sections
                        }
                        Box(modifier = pageModifier) {
                            PageTitledLines(sections = titledLinesSections)
                        }
                    }

                    ExerciseHorizontalPage.MUSCLES -> {
                        Box(modifier = pageModifier) {
                            PageMuscles(exercise = exercise)
                        }
                    }

                    ExerciseHorizontalPage.PROGRESSION_COMPARISON -> {
                        val isProgressionPageVisible = showProgressionComparisonPage &&
                            horizontalPagerState.currentPage == progressionPageIndex &&
                            !horizontalPagerState.isScrollInProgress
                        Box(modifier = pageModifier) {
                            PageProgressionComparison(
                                viewModel = viewModel,
                                hapticsViewModel = hapticsViewModel,
                                exercise = exercise,
                                state = state,
                                isPageVisible = isProgressionPageVisible
                            )
                        }
                    }

                    ExerciseHorizontalPage.NOTES -> {
                        Box(modifier = pageModifier) {
                            PageNotes(exercise.notes)
                        }
                    }

                    ExerciseHorizontalPage.EXERCISES -> {
                        Box(modifier = pageModifier) {
                            PageExercises(
                                selectedExercise = selectedExercise,
                                workoutState = state,
                                viewModel = viewModel,
                                hapticsViewModel = hapticsViewModel,
                                currentExercise = exercise,
                                exerciseOrSupersetIds = exerciseOrSupersetIds,
                                onExerciseSelected = { selectedExercise = it }
                            )
                        }
                    }
                }
            }
        }

        CustomDialogYesOnLongPress(
            show = showNextDialog,
            title = when {
                state.isCalibrationSet -> "Complete Calibration Set"
                state.isAutoRegulationWorkSet -> "Complete Set"
                state.intraSetTotal != null && state.intraSetCounter < state.intraSetTotal!! -> "Switch side"
                else -> "Complete Set"
            },
            message = when {
                state.isCalibrationSet -> "Rate your RIR after completing this set."
                state.isAutoRegulationWorkSet -> "Rate your RIR (or we'll auto-apply)."
                else -> "Do you want to proceed?"
            },
            handleYesClick = {
                shouldResumeTimerAfterDialog = false
                if (state.intraSetTotal != null) {
                    state.intraSetCounter++
                }

                hapticsViewModel.doGentleVibration()
                viewModel.storeSetData()

                when {
                    state.isAutoRegulationWorkSet -> {
                        viewModel.completeAutoRegulationSet()
                        viewModel.lightScreenUp()
                    }
                    state.isCalibrationSet -> {
                        viewModel.completeCalibrationSet()
                        viewModel.lightScreenUp()
                    }
                    else -> {
                        val isDone = viewModel.isNextStateCompleted()
                        viewModel.pushAndStoreWorkoutData(isDone, context) {
                            viewModel.goToNextState()
                            viewModel.lightScreenUp()
                        }
                    }
                }

                viewModel.closeCustomDialog()
            },
            handleNoClick = {
                viewModel.closeCustomDialog()
                hapticsViewModel.doGentleVibration()
            },
            closeTimerInMillis = 5000,
            handleOnAutomaticClose = { viewModel.closeCustomDialog() },
            onVisibilityChange = { isVisible ->
                if (isVisible) {
                    if (state.set is TimedDurationSet || state.set is EnduranceSet) {
                        if (viewModel.workoutTimerService.isTimerRegistered(state.set.id)) {
                            viewModel.workoutTimerService.pauseTimer(state.set.id)
                            shouldResumeTimerAfterDialog = true
                        } else {
                            shouldResumeTimerAfterDialog = false
                        }
                    }
                    viewModel.setDimming(false)
                } else {
                    if (
                        shouldResumeTimerAfterDialog &&
                        !isPaused &&
                        (state.set is TimedDurationSet || state.set is EnduranceSet) &&
                        viewModel.workoutTimerService.isTimerRegistered(state.set.id)
                    ) {
                        viewModel.workoutTimerService.resumeTimer(state.set.id)
                    }
                    shouldResumeTimerAfterDialog = false
                    viewModel.reEvaluateDimmingForCurrentState()
                }
            }
        )
    }

    DisposableEffect(Unit) {
        onDispose { goBackJob?.cancel() }
    }
}

@OptIn(ExperimentalFoundationApi::class, ExperimentalLayoutApi::class)
@Composable
private fun ExerciseDetailContent(
    state: WorkoutState.Set,
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    exercise: Exercise,
    exerciseOrSupersetId: UUID,
    isSuperset: Boolean,
    exerciseTitleComposable: @Composable (onLongClick: () -> Unit) -> Unit,
    onEditModeEnabled: () -> Unit,
    onEditModeDisabled: () -> Unit,
) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = WorkoutPagerLayoutTokens.OverlayContentHorizontalPadding)
    ) {
        ExerciseDetail(
            updatedState = state,
            viewModel = viewModel,
            onEditModeDisabled = onEditModeDisabled,
            onEditModeEnabled = onEditModeEnabled,
            onTimerDisabled = { },
            onTimerEnabled = { },
            extraInfo = {
                val isWarmupSet = remember(state.set) {
                    when (val set = state.set) {
                        is BodyWeightSet -> set.subCategory == SetSubCategory.WarmupSet
                        is WeightSet -> set.subCategory == SetSubCategory.WarmupSet
                        else -> false
                    }
                }
                val isCalibrationSet = remember(state.isCalibrationSet) { state.isCalibrationSet }
                val isAutoRegulationWorkSet = remember(state.isAutoRegulationWorkSet) { state.isAutoRegulationWorkSet }
                val supersetExercises = remember(exerciseOrSupersetId, isSuperset) {
                    if (isSuperset) viewModel.exercisesBySupersetId[exerciseOrSupersetId].orEmpty() else null
                }
                val supersetIndex = remember(supersetExercises, exercise) {
                    supersetExercises?.indexOf(exercise)
                }
                val repRange = remember(exercise) {
                    when {
                        (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT) &&
                                exercise.minReps > 0 && exercise.maxReps >= exercise.minReps ->
                            "${exercise.minReps}–${exercise.maxReps}"
                        else -> null
                    }
                }

                Column(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(5.dp)
                ) {
                    ExerciseMetadataStrip(
                        supersetExerciseIndex = if (isSuperset && supersetIndex != null) supersetIndex else null,
                        supersetExerciseTotal = if (isSuperset && supersetExercises != null) supersetExercises.size else null,
                        setLabel = viewModel.getSetCounterForExercise(state.exerciseId, state)
                            ?.let { (current, total) -> if (total > 1) "$current/$total" else null },
                        repRange = repRange,
                        sideIndicator = if (state.intraSetTotal != null) "① ↔ ②" else null,
                        currentSideIndex = state.intraSetCounter.takeIf { state.intraSetTotal != null },
                        isUnilateral = state.isUnilateral
                    )

                    if (isWarmupSet || isCalibrationSet || isAutoRegulationWorkSet) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.Center,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            if (isWarmupSet) {
                                Box(
                                    modifier = Modifier
                                        .background(
                                            MaterialTheme.colorScheme.background,
                                            RoundedCornerShape(25)
                                        )
                                        .border(
                                            BorderStroke(1.dp, MaterialTheme.colorScheme.primary),
                                            RoundedCornerShape(25)
                                        )
                                        .padding(5.dp),
                                    contentAlignment = Alignment.Center
                                ) {
                                    Text(
                                        text = "Warm-up",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.primary,
                                        textAlign = TextAlign.Center
                                    )
                                }
                            }
                            if (isCalibrationSet) {
                                Box(
                                    modifier = Modifier
                                        .background(
                                            MaterialTheme.colorScheme.background,
                                            RoundedCornerShape(25)
                                        )
                                        .border(
                                            BorderStroke(1.dp, Green),
                                            RoundedCornerShape(25)
                                        )
                                        .padding(5.dp),
                                    contentAlignment = Alignment.Center
                                ) {
                                    Text(
                                        text = "Calibration",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = Green,
                                        textAlign = TextAlign.Center
                                    )
                                }
                            }
                            if (isAutoRegulationWorkSet) {
                                Box(
                                    modifier = Modifier
                                        .background(
                                            MaterialTheme.colorScheme.background,
                                            RoundedCornerShape(25)
                                        )
                                        .border(
                                            BorderStroke(1.dp, MaterialTheme.colorScheme.tertiary),
                                            RoundedCornerShape(25)
                                        )
                                        .padding(5.dp),
                                    contentAlignment = Alignment.Center
                                ) {
                                    Text(
                                        text = "Auto-regulation",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.tertiary,
                                        textAlign = TextAlign.Center
                                    )
                                }
                            }
                        }
                    }
                }
            },
            exerciseTitleComposable = exerciseTitleComposable,
            hapticsViewModel = hapticsViewModel,
            customComponentWrapper = { content -> content() }
        )
    }
}
