package com.gabstra.myworkoutassistant.screens

// MOVEMENT_ANIMATION disabled for now
// import com.gabstra.myworkoutassistant.composables.PageMovementAnimation
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
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
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import androidx.wear.compose.foundation.pager.rememberPagerState
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.composables.CircularEndsPillShape
import com.gabstra.myworkoutassistant.composables.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composables.CustomHorizontalPager
import com.gabstra.myworkoutassistant.composables.ExerciseDetail
import com.gabstra.myworkoutassistant.composables.ExerciseIndicator
import com.gabstra.myworkoutassistant.composables.ExerciseMetadataStrip
import com.gabstra.myworkoutassistant.composables.FadingText
import com.gabstra.myworkoutassistant.composables.PageButtons
import com.gabstra.myworkoutassistant.composables.PageExercises
import com.gabstra.myworkoutassistant.composables.PageMuscles
import com.gabstra.myworkoutassistant.composables.PageNotes
import com.gabstra.myworkoutassistant.composables.PagePlates
import com.gabstra.myworkoutassistant.composables.PageProgressionComparison
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

enum class PageType {
    PLATES, EXERCISE_DETAIL, MOVEMENT_ANIMATION, MUSCLES, EXERCISES, NOTES, BUTTONS, PROGRESSION_COMPARISON
}

@OptIn(ExperimentalFoundationApi::class, ExperimentalLayoutApi::class)
@Composable
fun ExerciseScreen(
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    state: WorkoutState.Set,
    hearthRateChart: @Composable () -> Unit,
    navController: NavController,
) {
    var allowHorizontalScrolling by remember { mutableStateOf(true) }
    val showNextDialog by viewModel.isCustomDialogOpen.collectAsState()

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

    val showPlatesPage = remember(exercise, equipment) {
        equipment != null
                && equipment.type == EquipmentType.BARBELL
                && equipment.name.contains("barbell", ignoreCase = true)
                && (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT)
    }

    val showNotesPage = remember(exercise) {
        exercise.notes.isNotEmpty()
    }

    val hasMuscleInfo = remember(exercise) { !exercise.muscleGroups.isNullOrEmpty() }

    val showProgressionComparisonPage = remember(exercise) {
        !exercise.requiresLoadCalibration &&
                viewModel.exerciseProgressionByExerciseId.containsKey(exercise.id) &&
                viewModel.lastSessionWorkout != null &&
                ((viewModel.lastSessionWorkout!!.workoutComponents.filterIsInstance<Exercise>() +
                        viewModel.lastSessionWorkout!!.workoutComponents.filterIsInstance<com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset>()
                            .flatMap { it.exercises }).any { it.id == exercise.id })
    }

    val pageTypes = remember(showPlatesPage, showNotesPage, showProgressionComparisonPage, hasMuscleInfo) {
        mutableListOf<PageType>().apply {
            add(PageType.BUTTONS)  // First item - index 0
            add(PageType.EXERCISE_DETAIL)
            // MOVEMENT_ANIMATION disabled for now
            // add(PageType.MOVEMENT_ANIMATION)
            if (showPlatesPage) add(PageType.PLATES)
            if (showProgressionComparisonPage) add(PageType.PROGRESSION_COMPARISON)
            if (hasMuscleInfo) add(PageType.MUSCLES)
            if (showNotesPage) add(PageType.NOTES)
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

    val progressionComparisonPageIndex = remember(pageTypes) {
        pageTypes.indexOf(PageType.PROGRESSION_COMPARISON)
    }

    // MOVEMENT_ANIMATION disabled for now
    // val movementAnimationPageIndex = remember(pageTypes) {
    //     pageTypes.indexOf(PageType.MOVEMENT_ANIMATION)
    // }

    val pagerState = rememberPagerState(
        initialPage = exerciseDetailPageIndex,
        pageCount = {
            pageTypes.size
        }
    )

    androidx.compose.runtime.LaunchedEffect(state.set.id) {
        // Navigate to the exercise detail page
        pagerState.scrollToPage(exerciseDetailPageIndex)
        allowHorizontalScrolling = true
        viewModel.closeCustomDialog()
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

    val exerciseOrSupersetIds = remember {
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

    val context = LocalContext.current

    LaunchedEffect(pagerState.currentPage) {
        val isOnPlatesPage = pagerState.currentPage == platesPageIndex

        if (isOnPlatesPage) {
            viewModel.setDimming(false)
        } else {
            viewModel.reEvaluateDimmingForCurrentState()
        }

        val isOnExercisesPage = pagerState.currentPage == exercisesPageIndex
        if (!isOnExercisesPage) {
            selectedExercise = exercise
        }
    }

    AnimatedContent(
        targetState = state.set.id,
        transitionSpec = {
            fadeIn(animationSpec = tween(250)) togetherWith fadeOut(animationSpec = tween(250))
        }, label = ""
    ) { _ ->
        val exerciseTitleComposable: @Composable (onLongClick: () -> Unit) -> Unit =
            { providedOnLongClick ->
                FadingText(
                    text = exercise.name,
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(20.dp)
                        .padding(horizontal = 22.5.dp)
                        .combinedClickable(
                            onClick = {
                                hapticsViewModel.doGentleVibration()
                            },
                            onLongClick = {
                                providedOnLongClick.invoke()
                            }
                        ),
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
                        PageType.PLATES -> {
                            PagePlates(state, equipment, hapticsViewModel, viewModel)
                        }

                        PageType.EXERCISE_DETAIL -> {
                            key(pageType, pageIndex) {
                                ExerciseDetail(
                                    updatedState = state,
                                    viewModel = viewModel,
                                    onEditModeDisabled = { allowHorizontalScrolling = true },
                                    onEditModeEnabled = { allowHorizontalScrolling = false },
                                    onTimerDisabled = { },
                                    onTimerEnabled = { },
                                    extraInfo = { _ ->
                                        val isWarmupSet = remember(state.set) {
                                            when (val set = state.set) {
                                                is BodyWeightSet -> set.subCategory == SetSubCategory.WarmupSet
                                                is WeightSet -> set.subCategory == SetSubCategory.WarmupSet
                                                else -> false
                                            }
                                        }
                                        
                                        val isCalibrationSet = remember(state.isCalibrationSet) {
                                            state.isCalibrationSet
                                        }
                                        
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
                                                    state.exerciseId,
                                                    state
                                                )?.let { (current, total) ->
                                                    if (total > 1) "$current/$total" else null
                                                },
                                                sideIndicator = if (state.intraSetTotal != null) "① ↔ ②" else null,
                                                currentSideIndex = state.intraSetCounter.takeIf { state.intraSetTotal != null },
                                                isUnilateral = state.isUnilateral,
                                                equipmentName = equipment?.name,
                                                accessoryNames = accessoryEquipments.joinToString(", ") { it.name }.takeIf { accessoryEquipments.isNotEmpty() },
                                                textColor = MaterialTheme.colorScheme.onBackground,
                                                onTap = {
                                                    hapticsViewModel.doGentleVibration()
                                                }
                                            )
                                            
                                            // Status badges row (Warm-up/Calibration)
                                            if (isWarmupSet || isCalibrationSet) {
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
                                                }
                                            }
                                        }
                                    },
                                    exerciseTitleComposable = exerciseTitleComposable,
                                    hapticsViewModel = hapticsViewModel,
                                    customComponentWrapper = { content ->
                                        content()
                                    }
                                )
                            }
                        }

                        // MOVEMENT_ANIMATION disabled for now
                        PageType.MOVEMENT_ANIMATION -> {
                            // PageMovementAnimation disabled
                        }

                        PageType.MUSCLES -> {
                            PageMuscles(exercise = exercise)
                        }

                        PageType.EXERCISES -> {
                            key(pageType, pageIndex) {
                                PageExercises(
                                    selectedExercise,
                                    state,
                                    viewModel, hapticsViewModel,
                                    exercise,
                                    exerciseOrSupersetIds = exerciseOrSupersetIds,
                                    onExerciseSelected = {
                                        selectedExercise = it
                                    })
                            }
                        }

                        PageType.PROGRESSION_COMPARISON -> {
                            PageProgressionComparison(
                                viewModel = viewModel,
                                hapticsViewModel = hapticsViewModel,
                                exercise = exercise,
                                state = state,
                                isPageVisible = pagerState.currentPage == progressionComparisonPageIndex
                            )
                        }

                        PageType.NOTES -> {
                            PageNotes(exercise.notes)
                        }

                        PageType.BUTTONS -> {
                            PageButtons(state, viewModel, hapticsViewModel, navController)
                        }
                    }
                }
            }
        }


        CustomDialogYesOnLongPress(
            show = showNextDialog,
            title = when {
                state.isCalibrationSet -> "Complete Calibration Set"
                state.intraSetTotal != null && state.intraSetCounter < state.intraSetTotal!! -> "Switch side"
                else -> "Complete Set"
            },
            message = if (state.isCalibrationSet) "Rate your RIR after completing this set." else "Do you want to proceed?",
            handleYesClick = {
                // Handle intra-set counter if applicable
                if (state.intraSetTotal != null) {
                    state.intraSetCounter++
                }

                hapticsViewModel.doGentleVibration()
                viewModel.storeSetData()
                
                // Check if this is a calibration set execution
                val isCalibrationSetExecution = state.isCalibrationSet
                
                if (isCalibrationSetExecution) {
                    // Move to RIR rating step instead of going to next state
                    viewModel.completeCalibrationSet()
                    viewModel.lightScreenUp()
                } else {
                    val isDone = viewModel.isNextStateCompleted()
                    viewModel.pushAndStoreWorkoutData(isDone, context) {
                        viewModel.goToNextState()
                        viewModel.lightScreenUp()
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
            onVisibilityChange = { isVisible ->
                if (isVisible) {
                    viewModel.setDimming(false)
                } else {
                    viewModel.reEvaluateDimmingForCurrentState()
                }
            }
        )

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

    }

    DisposableEffect(Unit) {
        onDispose {
            goBackJob?.cancel()
        }
    }
}
