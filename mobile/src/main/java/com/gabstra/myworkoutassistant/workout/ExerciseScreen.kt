package com.gabstra.myworkoutassistant.workout

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.HapticsViewModel
import com.gabstra.myworkoutassistant.composables.StandardDialog
import com.gabstra.myworkoutassistant.screens.ExerciseMovementPreviewPage
import com.gabstra.myworkoutassistant.composables.ScrollableTextColumn
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.equipments.isCompatibleWith
import com.gabstra.myworkoutassistant.shared.workout.calibration.CalibrationUiLabels
import com.gabstra.myworkoutassistant.shared.workout.display.SetDisplayCounterKind
import com.gabstra.myworkoutassistant.shared.workout.display.buildUnilateralSideLabel
import com.gabstra.myworkoutassistant.shared.workout.display.displayCounterKindForSetState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.UUID

enum class PageType {
    BUTTONS, INFO, PLATES, EXERCISE_DETAIL, MUSCLES, EXERCISES, NOTES, MOVEMENT, REST_TIMER
}

@OptIn(ExperimentalFoundationApi::class, ExperimentalLayoutApi::class)
@Composable
fun ExerciseScreen(
    viewModel: WorkoutViewModel,
    hapticsViewModel: HapticsViewModel,
    state: WorkoutState.Set,
    hearthRateChart: @Composable () -> Unit,
    onLeaveWorkout: () -> Unit = {},
    onExerciseDetailPageVisibilityChanged: (Boolean) -> Unit = {},
) {
    var allowHorizontalScrolling by remember { mutableStateOf(true) }
    val showNextDialog by viewModel.isCustomDialogOpen.collectAsState()

    val exercise = viewModel.exercisesById[state.exerciseId] ?: return
    val equipment = exercise.equipmentId?.let { viewModel.getEquipmentById(it) }
    val canChangeEquipment = remember(exercise, state.isCalibrationSet) {
        !state.isCalibrationSet &&
            (exercise.exerciseType == ExerciseType.WEIGHT ||
                exercise.exerciseType == ExerciseType.BODY_WEIGHT)
    }
    val equipmentOptions = remember(exercise.exerciseType, exercise.equipmentId, viewModel.workoutStore.equipments) {
        val availableEquipment = viewModel.workoutStore.equipments
            .filter { it.isCompatibleWith(exercise.exerciseType) }
            .sortedBy { it.name.lowercase() }
        if (exercise.exerciseType == ExerciseType.BODY_WEIGHT) {
            listOf(null) + availableEquipment
        } else {
            availableEquipment
        }
    }
    var showEquipmentPicker by remember(state.set.id) { mutableStateOf(false) }
    var pendingEquipmentId by remember(state.set.id) { mutableStateOf(exercise.equipmentId) }

    val accessoryEquipments = remember(exercise) {
        (exercise.requiredAccessoryEquipmentIds ?: emptyList()).mapNotNull { id ->
            viewModel.getAccessoryEquipmentById(id)
        }
    }

    val showPlatesPage = remember(exercise, equipment) {
        equipment != null
                && equipment.type == EquipmentType.BARBELL
                && equipment.name.contains("barbell", ignoreCase = true)
                && (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT)
    }

    val showMovementPage = remember(exercise.movementRef) { exercise.movementRef != null }
    val hasMuscleInfo = remember(exercise.muscleGroups, exercise.secondaryMuscleGroups) {
        !exercise.muscleGroups.isNullOrEmpty() || !exercise.secondaryMuscleGroups.isNullOrEmpty()
    }

    val pageTypes = remember(showPlatesPage, hasMuscleInfo) {
        mutableListOf<PageType>().apply {
            add(PageType.BUTTONS)
            add(PageType.INFO)
            if (showPlatesPage) add(PageType.PLATES)
            add(PageType.EXERCISE_DETAIL)
            if (hasMuscleInfo) add(PageType.MUSCLES)
            add(PageType.EXERCISES)
        }
    }

    val exercisesPageIndex = remember(pageTypes) {
        pageTypes.indexOf(PageType.EXERCISES)
    }

    val exerciseDetailPageIndex = remember(pageTypes) {
        pageTypes.indexOf(PageType.EXERCISE_DETAIL)
    }

    val platesPageIndex = remember(pageTypes) {
        pageTypes.indexOf(PageType.PLATES)
    }

    val pagerState = key(state.set.id, showPlatesPage) {
        rememberPagerState(
            initialPage = exerciseDetailPageIndex,
            pageCount = { pageTypes.size },
        )
    }

    LaunchedEffect(state.set.id) {
        if (pagerState.currentPage != exerciseDetailPageIndex) {
            pagerState.scrollToPage(exerciseDetailPageIndex)
        }
        allowHorizontalScrolling = true
        if (showNextDialog) {
            viewModel.closeCustomDialog()
        }
    }

    val scope = rememberCoroutineScope()
    var goBackJob by remember { mutableStateOf<Job?>(null) }

    fun restartGoBack() {
        goBackJob?.cancel()

        goBackJob = scope.launch {
            delay(10000)
            val isOnExerciseDetailPage = pagerState.currentPage == exerciseDetailPageIndex
            val isOnPlatesPage = pagerState.currentPage == platesPageIndex
            if (!isOnExerciseDetailPage && !isOnPlatesPage) {
                pagerState.scrollToPage(exerciseDetailPageIndex)
            }
        }
    }

    var marqueeEnabled by remember { mutableStateOf(false) }

    val exerciseOrSupersetIds = remember(viewModel.allWorkoutStates.size) {
        viewModel.setsByExerciseId.keys.toList()
            .map { if (viewModel.supersetIdByExerciseId.containsKey(it)) viewModel.supersetIdByExerciseId[it] else it }
            .distinct()
    }
    val exerciseOrSupersetId =
        remember(state.exerciseId) { if (viewModel.supersetIdByExerciseId.containsKey(state.exerciseId)) viewModel.supersetIdByExerciseId[state.exerciseId] else state.exerciseId }
    val currentExerciseOrSupersetIndex =
        remember(exerciseOrSupersetId) { exerciseOrSupersetIds.indexOf(exerciseOrSupersetId) }
    val isSuperset = remember(exerciseOrSupersetId) {
        viewModel.exercisesBySupersetId.containsKey(exerciseOrSupersetId)
    }

    var selectedExerciseId by remember { mutableStateOf<UUID?>(null) }

    val context = LocalContext.current

    LaunchedEffect(pagerState.currentPage) {
        onExerciseDetailPageVisibilityChanged(
            pagerState.currentPage == exerciseDetailPageIndex,
        )
        val isOnPlatesPage = pagerState.currentPage == platesPageIndex

        // Match Wear: edit mode only belongs to the exercise-detail page. If navigation
        // leaves it through the indicator or a programmatic page change, restore paging.
        if (pagerState.currentPage != exerciseDetailPageIndex) {
            allowHorizontalScrolling = true
        }

        if (isOnPlatesPage) {
            viewModel.setDimming(false)
        } else {
            viewModel.reEvaluateDimmingForCurrentState()
        }

        if (pagerState.currentPage != exercisesPageIndex) {
            selectedExerciseId = null
        }
    }

        val animatedExercise = exercise
        val targetRepRange = remember(animatedExercise, state.set, state.isWarmupSet) {
            buildTargetRepRange(animatedExercise, state)
        }
        val activeExerciseContext = buildActiveExerciseContextLabel(
            setCounter = viewModel.getSetCounterForExercise(state.exerciseId, state),
            setCounterKind = displayCounterKindForSetState(state),
            unilateralSideIndex = viewModel.getUnilateralSideIndex(state),
            intraSetTotal = state.intraSetTotal,
        )
        val exerciseTitleComposable: @Composable (onLongClick: () -> Unit) -> Unit =
            { providedOnLongClick ->
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(2.5.dp),
                ) {
                    ScrollableTextColumn(
                        text = animatedExercise.name,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 12.dp)
                            .combinedClickable(
                                onClick = {
                                    hapticsViewModel.doGentleVibration()
                                    marqueeEnabled = !marqueeEnabled
                                },
                                onLongClick = providedOnLongClick,
                            ),
                        maxLines = 2,
                        style = mobileWorkoutPageTitleStyle(),
                        textAlign = TextAlign.Center,
                    )
                    activeExerciseContext?.let { contextLabel ->
                        Text(
                            text = contextLabel,
                            modifier = Modifier.fillMaxWidth(),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            textAlign = TextAlign.Center,
                        )
                    }
                }
            }

        CustomHorizontalPager(
            modifier = Modifier.fillMaxSize()
                .pointerInput(Unit) {
                    awaitPointerEventScope {
                        var gestureInProgress = false
                        while (true) {
                            val event = awaitPointerEvent()
                            val hasPressedPointer = event.changes.any { it.pressed }
                            if (hasPressedPointer && !gestureInProgress) {
                                restartGoBack()
                            }
                            gestureInProgress = hasPressedPointer
                        }
                    }
                },
            pagerState = pagerState,
            userScrollEnabled = allowHorizontalScrolling,
            beyondViewportPageCount = 1,
            pageLabel = { index -> pageTypes[index].mobileLabel() },
        ) { pageIndex ->
            // Get the page type for the current index
            val pageType = pageTypes[pageIndex]
            when (pageType) {
                PageType.INFO -> ExerciseSessionInfoPage(
                    exerciseName = animatedExercise.name,
                    equipmentName = equipment?.name,
                    accessoryNames = accessoryEquipments.map { it.name },
                    notes = animatedExercise.notes,
                    targetRepRange = targetRepRange,
                    progressionLabel = state.progressionState?.name
                        ?.lowercase()
                        ?.replaceFirstChar { it.uppercase() },
                    plateauReason = viewModel.plateauReasonByExerciseId[state.exerciseId]
                )

                PageType.PLATES -> PagePlates(state, equipment)
                PageType.EXERCISE_DETAIL -> ExerciseDetail(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(horizontal = 12.dp),
                    updatedState = state,
                    viewModel = viewModel,
                    onEditModeDisabled = { allowHorizontalScrolling = true },
                    onEditModeEnabled = { allowHorizontalScrolling = false },
                    onTimerDisabled = { },
                    onTimerEnabled = { },
                    extraInfo = if (showMovementPage) {
                        { _ ->
                            ExerciseMovementPreviewPage(
                                exercise = animatedExercise,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .height(180.dp),
                            )
                        }
                    } else {
                        null
                    },
                    exerciseTitleComposable = exerciseTitleComposable,
                    targetRepRange = targetRepRange.takeUnless { state.isWarmupSet },
                    hapticsViewModel = hapticsViewModel,
                    heartRateChart = hearthRateChart,
                    customComponentWrapper = { content -> content() }
                )

                PageType.MUSCLES -> PageMuscles(exercise = animatedExercise)

                PageType.EXERCISES -> PageExercises(
                            workoutState = state,
                            viewModel = viewModel,
                            hapticsViewModel = hapticsViewModel,
                            currentExercise = animatedExercise,
                            onExerciseSelected = {
                                selectedExerciseId = it
                            })

                PageType.NOTES -> ExerciseSessionInfoPage(
                    exerciseName = "Notes",
                    equipmentName = null,
                    accessoryNames = emptyList(),
                    notes = animatedExercise.notes,
                    targetRepRange = null,
                    progressionLabel = null,
                    plateauReason = null
                )
                PageType.MOVEMENT -> Unit
                PageType.BUTTONS -> PageButtons(
                    updatedState = state,
                    viewModel = viewModel,
                    hapticsViewModel = hapticsViewModel,
                    canChangeEquipment = canChangeEquipment,
                    onChangeEquipmentClick = {
                        pendingEquipmentId = exercise.equipmentId
                        showEquipmentPicker = true
                    },
                    onLeaveWorkout = onLeaveWorkout
                )
                PageType.REST_TIMER -> Unit
            }
        }

        if (showEquipmentPicker) {
            StandardDialog(
                onDismissRequest = { showEquipmentPicker = false },
                title = "Change equipment",
                body = {
                    Column(modifier = Modifier.fillMaxWidth()) {
                        equipmentOptions.forEach { equipmentOption ->
                            val equipmentId = equipmentOption?.id
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clickable { pendingEquipmentId = equipmentId }
                                    .padding(vertical = 8.dp),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                RadioButton(
                                    selected = pendingEquipmentId == equipmentId,
                                    onClick = { pendingEquipmentId = equipmentId }
                                )
                                Text(
                                    text = equipmentOption?.name ?: "None",
                                    modifier = Modifier.padding(start = 8.dp),
                                    style = MaterialTheme.typography.bodyLarge
                                )
                            }
                        }
                    }
                },
                confirmText = "Change",
                onConfirm = {
                    showEquipmentPicker = false
                    scope.launch {
                        viewModel.updateExerciseEquipmentForCurrentWorkout(
                            exerciseId = exercise.id,
                            equipmentId = pendingEquipmentId
                        )
                    }
                },
                dismissText = "Cancel",
                onDismissButton = { showEquipmentPicker = false },
                confirmEnabled = pendingEquipmentId != exercise.equipmentId
            )
        }

        CustomDialogYesOnLongPress(
            show = showNextDialog,
            title = when {
                state.isCalibrationSet -> CalibrationUiLabels.CompleteCalibrationSet
                state.isAutoRegulationWorkSet -> "Complete Set"
                state.intraSetTotal != null && state.intraSetCounter < state.intraSetTotal!! -> "Switch side"
                else -> "Complete Set"
            },
            message = when {
                state.isCalibrationSet -> CalibrationUiLabels.RateRirAfterSet
                state.isAutoRegulationWorkSet -> "Complete this set to auto-adjust the next load."
                else -> "Do you want to proceed?"
            },
            handleYesClick = {

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
            handleOnAutomaticClose = {
                viewModel.closeCustomDialog()
            },
            holdTimeInMillis = 1000,
            onVisibilityChange = { isVisible ->
                if (isVisible) {
                    viewModel.setDimming(false)
                } else {
                    viewModel.reEvaluateDimmingForCurrentState()
                }
            }
        )

/*        Box(
            modifier = Modifier
                .fillMaxSize(),
            contentAlignment = Alignment.Center
        ) {
            ExerciseIndicator(
                viewModel,
                state,
                selectedExerciseId
            )

            hearthRateChart()
        }

        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(vertical = 20.dp, horizontal = 20.dp)
                .clip(CircleShape),
        ) {
        }*/
    DisposableEffect(Unit) {
        onDispose {
            goBackJob?.cancel()
            onExerciseDetailPageVisibilityChanged(true)
        }
    }
}

private fun buildTargetRepRange(
    exercise: com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise,
    state: WorkoutState.Set,
): String? {
    if (state.isWarmupSet) {
        val warmupReps = when (val set = state.set) {
            is com.gabstra.myworkoutassistant.shared.sets.WeightSet -> set.reps
            is com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet -> set.reps
            else -> null
        }
        if (warmupReps != null && warmupReps > 0) return warmupReps.toString()
    }

    return if (
        (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT) &&
        exercise.minReps > 0 &&
        exercise.maxReps >= exercise.minReps
    ) {
        if (exercise.minReps == exercise.maxReps) exercise.minReps.toString()
        else "${exercise.minReps}-${exercise.maxReps}"
    } else null
}

private fun buildActiveExerciseContextLabel(
    setCounter: Pair<Int, Int>?,
    setCounterKind: SetDisplayCounterKind?,
    unilateralSideIndex: UInt?,
    intraSetTotal: UInt?,
): String? = listOfNotNull(
    setCounter?.let { (current, total) ->
        val label = when (setCounterKind) {
            SetDisplayCounterKind.Warmup -> "WARM-UP"
            SetDisplayCounterKind.Work -> "WORK SET"
            SetDisplayCounterKind.Calibration -> "CALIBRATION"
            null -> "SET"
        }
        "$label $current/$total"
    },
    buildUnilateralSideLabel(unilateralSideIndex, intraSetTotal)
        ?.removePrefix("-")
        ?.let { side -> "SIDE $side" },
).takeIf { it.isNotEmpty() }?.joinToString(" · ")

private fun PageType.mobileLabel(): String = when (this) {
    PageType.BUTTONS -> "Workout controls"
    PageType.INFO -> "Exercise info"
    PageType.PLATES -> "Barbell guide"
    PageType.EXERCISE_DETAIL -> "Current set"
    PageType.MUSCLES -> "Muscle groups"
    PageType.EXERCISES -> "Workout steps"
    PageType.NOTES -> "Exercise notes"
    PageType.MOVEMENT -> "Exercise movement"
    PageType.REST_TIMER -> "Rest timer"
}

@Composable
private fun ExerciseSessionInfoPage(
    exerciseName: String,
    equipmentName: String?,
    accessoryNames: List<String>,
    notes: String,
    targetRepRange: String?,
    progressionLabel: String?,
    plateauReason: String?
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp, vertical = 16.dp),
        verticalArrangement = Arrangement.spacedBy(22.dp)
    ) {
        ExerciseInfoSection("Exercise", listOf(exerciseName))
        targetRepRange?.let { ExerciseInfoSection("Target reps", listOf(it)) }
        progressionLabel?.let { ExerciseInfoSection("Progression", listOf(it)) }
        plateauReason?.let { ExerciseInfoSection("Plateau", listOf(it)) }
        equipmentName?.let { ExerciseInfoSection("Equipment", listOf(it)) }
        if (accessoryNames.isNotEmpty()) ExerciseInfoSection("Accessories", accessoryNames)
        if (notes.isNotBlank()) ExerciseInfoSection("Notes", listOf(notes))
    }
}

@Composable
private fun ExerciseInfoSection(title: String, lines: List<String>) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = title.uppercase(),
            modifier = Modifier.fillMaxWidth(),
            style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Medium),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )
        lines.forEachIndexed { index, line ->
            Text(
                text = line,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = if (index == 0) 7.dp else 10.dp),
                style = MaterialTheme.typography.displaySmall.copy(fontWeight = FontWeight.SemiBold),
                color = MaterialTheme.colorScheme.onBackground,
                textAlign = TextAlign.Center,
            )
        }
    }
}
