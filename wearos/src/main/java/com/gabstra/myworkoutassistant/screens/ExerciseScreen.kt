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
import androidx.compose.runtime.CompositionLocalProvider
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
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import androidx.wear.compose.foundation.pager.rememberPagerState
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import androidx.wear.tooling.preview.devices.WearDevices
import com.gabstra.myworkoutassistant.composables.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composables.CustomHorizontalPager
import com.gabstra.myworkoutassistant.composables.ExerciseDetail
import com.gabstra.myworkoutassistant.composables.ExerciseIndicator
import com.gabstra.myworkoutassistant.composables.ExerciseMetadataStrip
import com.gabstra.myworkoutassistant.composables.ExerciseNameText
import com.gabstra.myworkoutassistant.composables.HeartRateCircularChart
import com.gabstra.myworkoutassistant.composables.LocalTopOverlayController
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
import com.gabstra.myworkoutassistant.composables.rememberTopOverlayController
import com.gabstra.myworkoutassistant.composables.rememberWearCoroutineScope
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsHelper
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.presentation.theme.MyWorkoutAssistantTheme
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.equipments.AccessoryEquipment
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.equipments.Plate
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.viewmodels.HeartRateChangeViewModel
import com.gabstra.myworkoutassistant.shared.workout.state.ProgressionState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateMachine
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import java.lang.reflect.Field
import java.time.LocalDateTime
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
private val PREVIEW_FIXED_NOW: LocalDateTime = LocalDateTime.of(2026, 1, 1, 12, 0)

@OptIn(ExperimentalFoundationApi::class, ExperimentalLayoutApi::class)
@Composable
fun ExerciseScreen(
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    state: WorkoutState.Set,
    hearthRateChart: @Composable (Modifier) -> Unit,
    navController: NavController,
    onBeforeGoHome: (() -> Unit)? = null,
    initialPageOverride: Int? = null,
) {
    val isPreviewInspection = LocalInspectionMode.current
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
        initialPage = initialPageOverride?.coerceIn(0, (pageTypes.lastIndex).coerceAtLeast(0)) ?: exerciseDetailPageIndex,
        pageCount = { pageTypes.size }
    )

    LaunchedEffect(state.set.id) {
        val shouldForceDetailPage = !isPreviewInspection || initialPageOverride == null
        if (shouldForceDetailPage && horizontalPagerState.currentPage != exerciseDetailPageIndex) {
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
                        .padding(horizontal = 27.5.dp)
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

internal enum class ExercisePreviewSetType {
    WEIGHT,
    BODY_WEIGHT,
    TIMED_DURATION,
    ENDURANCE
}

internal data class ExercisePreviewScenario(
    val name: String,
    val setType: ExercisePreviewSetType,
    val isWarmupSet: Boolean = false,
    val isCalibrationSet: Boolean = false,
    val isAutoRegulationWorkSet: Boolean = false,
    val isUnilateral: Boolean = false,
    val intraSetCounter: UInt = 0u,
    val showConfirmationDialog: Boolean = false,
    val includeBarbellPage: Boolean = false,
    val includeTitledLinesPage: Boolean = false,
    val openPageIndex: Int? = null,
    val timedIsRunning: Boolean = false,
    val enduranceOverLimit: Boolean = false,
)

internal data class ExercisePreviewFixture(
    val viewModel: AppViewModel,
    val state: WorkoutState.Set,
)

internal fun buildExercisePreviewFixture(scenario: ExercisePreviewScenario): ExercisePreviewFixture {
    val viewModel = AppViewModel()
    val now = PREVIEW_FIXED_NOW
    val mainExerciseId = UUID.fromString("10000000-0000-0000-0000-000000000001")
    val altExerciseId = UUID.fromString("10000000-0000-0000-0000-000000000002")
    val barbellId = UUID.fromString("10000000-0000-0000-0000-000000000101")
    val accessoryId = UUID.fromString("10000000-0000-0000-0000-000000000201")

    val mainSet = when (scenario.setType) {
        ExercisePreviewSetType.WEIGHT -> WeightSet(
            id = UUID.fromString("20000000-0000-0000-0000-000000000001"),
            reps = 8,
            weight = 80.0,
            subCategory = if (scenario.isWarmupSet) SetSubCategory.WarmupSet else SetSubCategory.WorkSet
        )
        ExercisePreviewSetType.BODY_WEIGHT -> BodyWeightSet(
            id = UUID.fromString("20000000-0000-0000-0000-000000000002"),
            reps = 12,
            additionalWeight = 20.0,
            subCategory = if (scenario.isWarmupSet) SetSubCategory.WarmupSet else SetSubCategory.WorkSet
        )
        ExercisePreviewSetType.TIMED_DURATION -> TimedDurationSet(
            id = UUID.fromString("20000000-0000-0000-0000-000000000003"),
            timeInMillis = 60_000,
            autoStart = false,
            autoStop = true
        )
        ExercisePreviewSetType.ENDURANCE -> EnduranceSet(
            id = UUID.fromString("20000000-0000-0000-0000-000000000004"),
            timeInMillis = 45_000,
            autoStart = false,
            autoStop = !scenario.enduranceOverLimit
        )
    }

    val mainExercise = Exercise(
        id = mainExerciseId,
        enabled = true,
        name = "Preview Exercise LONG EXTREMELY LONG ",
        doNotStoreHistory = false,
        notes = if (scenario.includeTitledLinesPage) "Keep elbows tucked and brace core." else "",
        sets = listOf(mainSet),
        exerciseType = when (scenario.setType) {
            ExercisePreviewSetType.WEIGHT, ExercisePreviewSetType.TIMED_DURATION, ExercisePreviewSetType.ENDURANCE -> ExerciseType.WEIGHT
            ExercisePreviewSetType.BODY_WEIGHT -> ExerciseType.BODY_WEIGHT
        },
        minLoadPercent = 0.0,
        maxLoadPercent = 0.0,
        minReps = 6,
        maxReps = 12,
        lowerBoundMaxHRPercent = null,
        upperBoundMaxHRPercent = null,
        equipmentId = if (
            scenario.includeBarbellPage ||
            scenario.setType == ExercisePreviewSetType.BODY_WEIGHT ||
            scenario.setType == ExercisePreviewSetType.WEIGHT
        ) {
            barbellId
        } else {
            null
        },
        bodyWeightPercentage = if (scenario.setType == ExercisePreviewSetType.BODY_WEIGHT) 1.0 else null,
        keepScreenOn = false,
        showCountDownTimer = false,
        requiredAccessoryEquipmentIds = if (scenario.includeTitledLinesPage) listOf(accessoryId) else emptyList(),
        requiresLoadCalibration = false
    )
    val altExercise = Exercise(
        id = altExerciseId,
        enabled = true,
        name = "Next Exercise",
        doNotStoreHistory = false,
        notes = "",
        sets = listOf(WeightSet(UUID.fromString("20000000-0000-0000-0000-000000000009"), reps = 10, weight = 50.0)),
        exerciseType = ExerciseType.WEIGHT,
        minLoadPercent = 0.0,
        maxLoadPercent = 0.0,
        minReps = 8,
        maxReps = 12,
        lowerBoundMaxHRPercent = null,
        upperBoundMaxHRPercent = null,
        equipmentId = null,
        bodyWeightPercentage = null
    )

    val state = WorkoutState.Set(
        exerciseId = mainExerciseId,
        set = mainSet,
        setIndex = 0u,
        previousSetData = when (scenario.setType) {
            ExercisePreviewSetType.WEIGHT -> WeightSetData(8, 75.0, 600.0)
            ExercisePreviewSetType.BODY_WEIGHT -> BodyWeightSetData(10, 15.0, 75.0, 900.0)
            ExercisePreviewSetType.TIMED_DURATION -> TimedDurationSetData(60_000, 60_000, autoStart = false, autoStop = true)
            ExercisePreviewSetType.ENDURANCE -> EnduranceSetData(45_000, 10_000, autoStart = false, autoStop = !scenario.enduranceOverLimit)
        },
        currentSetDataState = mutableStateOf(
            when (scenario.setType) {
                ExercisePreviewSetType.WEIGHT -> WeightSetData(
                    actualReps = 8,
                    actualWeight = 80.0,
                    volume = 640.0,
                    subCategory = if (scenario.isWarmupSet) SetSubCategory.WarmupSet else SetSubCategory.WorkSet
                )
                ExercisePreviewSetType.BODY_WEIGHT -> BodyWeightSetData(
                    actualReps = 12,
                    additionalWeight = 20.0,
                    relativeBodyWeightInKg = 75.0,
                    volume = 1_140.0,
                    subCategory = if (scenario.isWarmupSet) SetSubCategory.WarmupSet else SetSubCategory.WorkSet
                )
                ExercisePreviewSetType.TIMED_DURATION -> {
                    if (scenario.timedIsRunning) {
                        TimedDurationSetData(60_000, 25_000, autoStart = false, autoStop = true)
                    } else {
                        TimedDurationSetData(60_000, 60_000, autoStart = false, autoStop = true)
                    }
                }
                ExercisePreviewSetType.ENDURANCE -> {
                    if (scenario.enduranceOverLimit) {
                        EnduranceSetData(45_000, 45_000, autoStart = false, autoStop = false)
                    } else {
                        EnduranceSetData(45_000, 12_000, autoStart = false, autoStop = true)
                    }
                }
            }
        ),
        hasNoHistory = false,
        startTime = when {
            scenario.timedIsRunning -> now.minusSeconds(20)
            scenario.enduranceOverLimit -> now.minusSeconds(55)
            else -> null
        },
        skipped = false,
        currentBodyWeight = 75.0,
        streak = 1,
        progressionState = ProgressionState.PROGRESS,
        isWarmupSet = scenario.isWarmupSet,
        equipmentId = mainExercise.equipmentId,
        isUnilateral = scenario.isUnilateral,
        intraSetTotal = if (scenario.isUnilateral) 2u else null,
        intraSetCounter = if (scenario.isUnilateral) scenario.intraSetCounter else 0u,
        isCalibrationSet = scenario.isCalibrationSet,
        isAutoRegulationWorkSet = scenario.isAutoRegulationWorkSet
    )
    val altState = WorkoutState.Set(
        exerciseId = altExerciseId,
        set = altExercise.sets.first(),
        setIndex = 0u,
        previousSetData = WeightSetData(10, 50.0, 500.0),
        currentSetDataState = mutableStateOf(WeightSetData(10, 50.0, 500.0)),
        hasNoHistory = false,
        startTime = null,
        skipped = false,
        currentBodyWeight = 75.0,
        streak = 0,
        progressionState = null,
        isWarmupSet = false,
        equipmentId = null
    )

    val workoutStates = listOf(state, altState)
    val stateMachine = WorkoutStateMachine.fromStates(workoutStates, { now }, startIndex = 0)

    viewModel.exercisesById = mapOf(
        mainExercise.id to mainExercise,
        altExercise.id to altExercise
    )
    viewModel.supersetIdByExerciseId = emptyMap()
    viewModel.exercisesBySupersetId = emptyMap()

    val equipments = mutableListOf<com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment>()
    if (mainExercise.equipmentId == barbellId) {
        equipments += Barbell(
            id = barbellId,
            name = "Olympic Barbell",
            availablePlates = listOf(Plate(20.0, 40.0), Plate(10.0, 30.0), Plate(5.0, 20.0), Plate(2.5, 15.0)),
            sleeveLength = 200,
            barWeight = 20.0
        )
    }

    viewModel.workoutStore = viewModel.workoutStore.copy(
        equipments = equipments,
        accessoryEquipments = if (scenario.includeTitledLinesPage) {
            listOf(AccessoryEquipment(accessoryId, "Lifting Straps"))
        } else {
            emptyList()
        }
    )

    setFieldValue(viewModel, "stateMachine", stateMachine)
    setCurrentWorkoutState(viewModel, state)

    // Keep previews deterministic and avoid background timer side effects.
    if (scenario.setType == ExercisePreviewSetType.TIMED_DURATION || scenario.setType == ExercisePreviewSetType.ENDURANCE) {
        viewModel.pauseWorkout()
    }

    if (scenario.showConfirmationDialog) {
        viewModel.openCustomDialog()
    }

    return ExercisePreviewFixture(viewModel = viewModel, state = state)
}

internal fun setCurrentWorkoutState(viewModel: AppViewModel, state: WorkoutState) {
    val field = findFieldRecursively(viewModel::class.java, "_workoutState") ?: return
    field.isAccessible = true
    val flow = field.get(viewModel) as? MutableStateFlow<WorkoutState> ?: return
    flow.value = state
}

internal fun setFieldValue(target: Any, fieldName: String, value: Any?) {
    val field = findFieldRecursively(target::class.java, fieldName) ?: return
    field.isAccessible = true
    field.set(target, value)
}

internal fun findFieldRecursively(clazz: Class<*>, fieldName: String): Field? {
    var current: Class<*>? = clazz
    while (current != null) {
        current.declaredFields.firstOrNull { it.name == fieldName }?.let { return it }
        current = current.superclass
    }
    return null
}

@Composable
internal fun ExerciseScreenPreviewScenario(scenario: ExercisePreviewScenario) {
    val fixture = remember(scenario) { buildExercisePreviewFixture(scenario) }
    val context = LocalContext.current
    val navController = remember(context) { NavController(context) }
    val hapticsViewModel = remember(context) { HapticsViewModel(context, HapticsHelper(context)) }
    val heartRateChangeViewModel = remember { HeartRateChangeViewModel() }
    val topOverlayController = rememberTopOverlayController()

    DisposableEffect(Unit) {
        onDispose {
            fixture.viewModel.workoutTimerService.unregisterAll()
        }
    }

    MyWorkoutAssistantTheme {
        CompositionLocalProvider(LocalTopOverlayController provides topOverlayController) {
            ExerciseScreen(
                viewModel = fixture.viewModel,
                hapticsViewModel = hapticsViewModel,
                state = fixture.state,
                hearthRateChart = { modifier ->
                    HeartRateCircularChart(
                        modifier = modifier,
                        appViewModel = fixture.viewModel,
                        hapticsViewModel = hapticsViewModel,
                        heartRateChangeViewModel = heartRateChangeViewModel,
                        hr = 140,
                        age = 30,
                        measuredMaxHeartRate = null,
                        restingHeartRate = null,
                        lowerBoundMaxHRPercent = null,
                        upperBoundMaxHRPercent = null
                    )
                },
                navController = navController,
                initialPageOverride = scenario.openPageIndex
            )
        }
    }
}

@Preview(
    name = "Weight Work Set",
    group = "ExerciseScreen/States",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
private fun ExerciseScreenPreviewWeightWorkSet() {
    ExerciseScreenPreviewScenario(
        ExercisePreviewScenario(
            name = "weight_work",
            setType = ExercisePreviewSetType.WEIGHT
        )
    )
}

@Preview(
    name = "Weight Warm-up Set",
    group = "ExerciseScreen/States",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
private fun ExerciseScreenPreviewWeightWarmup() {
    ExerciseScreenPreviewScenario(
        ExercisePreviewScenario(
            name = "weight_warmup",
            setType = ExercisePreviewSetType.WEIGHT,
            isWarmupSet = true
        )
    )
}

@Preview(
    name = "Calibration Confirmation Dialog",
    group = "ExerciseScreen/Dialog",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
private fun ExerciseScreenPreviewCalibrationDialog() {
    ExerciseScreenPreviewScenario(
        ExercisePreviewScenario(
            name = "calibration_dialog",
            setType = ExercisePreviewSetType.WEIGHT,
            isCalibrationSet = true,
            showConfirmationDialog = true
        )
    )
}

@Preview(
    name = "Auto-Regulation Confirmation Dialog",
    group = "ExerciseScreen/Dialog",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
private fun ExerciseScreenPreviewAutoRegulationDialog() {
    ExerciseScreenPreviewScenario(
        ExercisePreviewScenario(
            name = "auto_reg_dialog",
            setType = ExercisePreviewSetType.WEIGHT,
            isAutoRegulationWorkSet = true,
            showConfirmationDialog = true
        )
    )
}

@Preview(
    name = "Unilateral Switch Side Dialog",
    group = "ExerciseScreen/Dialog",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
private fun ExerciseScreenPreviewUnilateralDialog() {
    ExerciseScreenPreviewScenario(
        ExercisePreviewScenario(
            name = "unilateral_dialog",
            setType = ExercisePreviewSetType.WEIGHT,
            isUnilateral = true,
            intraSetCounter = 0u,
            showConfirmationDialog = true
        )
    )
}

@Preview(
    name = "Body Weight Set",
    group = "ExerciseScreen/States",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
private fun ExerciseScreenPreviewBodyWeight() {
    ExerciseScreenPreviewScenario(
        ExercisePreviewScenario(
            name = "body_weight",
            setType = ExercisePreviewSetType.BODY_WEIGHT
        )
    )
}

@Preview(
    name = "Timed Set Not Started",
    group = "ExerciseScreen/Timers",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
private fun ExerciseScreenPreviewTimedNotStarted() {
    ExerciseScreenPreviewScenario(
        ExercisePreviewScenario(
            name = "timed_not_started",
            setType = ExercisePreviewSetType.TIMED_DURATION
        )
    )
}

@Preview(
    name = "Timed Set Running",
    group = "ExerciseScreen/Timers",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
private fun ExerciseScreenPreviewTimedRunning() {
    ExerciseScreenPreviewScenario(
        ExercisePreviewScenario(
            name = "timed_running",
            setType = ExercisePreviewSetType.TIMED_DURATION,
            timedIsRunning = true
        )
    )
}

@Preview(
    name = "Endurance Set Over Limit",
    group = "ExerciseScreen/Timers",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
private fun ExerciseScreenPreviewEnduranceOverLimit() {
    ExerciseScreenPreviewScenario(
        ExercisePreviewScenario(
            name = "endurance_over_limit",
            setType = ExercisePreviewSetType.ENDURANCE,
            enduranceOverLimit = true
        )
    )
}

@Preview(
    name = "Buttons Page",
    group = "ExerciseScreen/Pages",
    device = WearDevices.SMALL_ROUND,
    showBackground = true
)
@Composable
private fun ExerciseScreenPreviewButtonsPage() {
    ExerciseScreenPreviewScenario(
        ExercisePreviewScenario(
            name = "buttons_page",
            setType = ExercisePreviewSetType.WEIGHT,
            openPageIndex = 0
        )
    )
}

@Preview(
    name = "Plates Page",
    group = "ExerciseScreen/Pages",
    device = WearDevices.SMALL_ROUND,
    showBackground = true
)
@Composable
private fun ExerciseScreenPreviewPlatesPage() {
    ExerciseScreenPreviewScenario(
        ExercisePreviewScenario(
            name = "plates_page",
            setType = ExercisePreviewSetType.WEIGHT,
            includeBarbellPage = true,
            openPageIndex = 1
        )
    )
}

@Preview(
    name = "Titled Lines Page",
    group = "ExerciseScreen/Pages",
    device = WearDevices.SMALL_ROUND,
    showBackground = true
)
@Composable
private fun ExerciseScreenPreviewTitledLinesPage() {
    ExerciseScreenPreviewScenario(
        ExercisePreviewScenario(
            name = "titled_lines_page",
            setType = ExercisePreviewSetType.WEIGHT,
            includeBarbellPage = true,
            includeTitledLinesPage = true,
            openPageIndex = 3
        )
    )
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
