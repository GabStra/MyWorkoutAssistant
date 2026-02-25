package com.gabstra.myworkoutassistant.workout

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.HapticsViewModel
import com.gabstra.myworkoutassistant.composables.ExerciseMetadataStrip
import com.gabstra.myworkoutassistant.composables.ScrollableTextColumn
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.calibration.CalibrationUiLabels
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.UUID

enum class PageType {
    PLATES, EXERCISE_DETAIL, MUSCLES, EXERCISES, NOTES, BUTTONS
}

@OptIn(ExperimentalFoundationApi::class, ExperimentalLayoutApi::class)
@Composable
fun ExerciseScreen(
    viewModel: WorkoutViewModel,
    hapticsViewModel: HapticsViewModel,
    state: WorkoutState.Set,
    hearthRateChart: @Composable () -> Unit,
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

    val showNotesPage = remember(exercise) { exercise.notes.isNotEmpty() }
    val hasMuscleInfo = remember(exercise) { !exercise.muscleGroups.isNullOrEmpty() }

    val pageTypes = remember(showPlatesPage, showNotesPage, hasMuscleInfo) {
        mutableListOf<PageType>().apply {
            if (showPlatesPage) add(PageType.PLATES)
            add(PageType.EXERCISE_DETAIL)
            if (hasMuscleInfo) add(PageType.MUSCLES)
            add(PageType.EXERCISES)
            // if (showNotesPage) add(PageType.NOTES)
            add(PageType.BUTTONS)
        }
    }

    val exercisesPageIndex = remember(pageTypes) {
        pageTypes.indexOf(PageType.EXERCISES)
    }

    val exerciseDetailPageIndex = remember(pageTypes) {
        pageTypes.indexOf(PageType.EXERCISE_DETAIL)
    }

    val musclesPageIndex = remember(pageTypes) {
        pageTypes.indexOf(PageType.MUSCLES)
    }

    val platesPageIndex = remember(pageTypes) {
        pageTypes.indexOf(PageType.PLATES)
    }

    val pagerState = rememberPagerState(
        initialPage = exerciseDetailPageIndex,
        pageCount = {
            pageTypes.size
        }
    )

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

    val captionStyle = MaterialTheme.typography.bodySmall

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
        val isOnPlatesPage = pagerState.currentPage == platesPageIndex

        if (isOnPlatesPage) {
            viewModel.setDimming(false)
        } else {
            viewModel.reEvaluateDimmingForCurrentState()
        }

        if (pagerState.currentPage != exercisesPageIndex) {
            selectedExerciseId = null
        }
    }

    AnimatedContent(
        targetState = state.exerciseId to state.set.id,
        transitionSpec = {
            fadeIn(animationSpec = tween(500)) togetherWith fadeOut(animationSpec = tween(500))
        }, label = ""
    ) { targetState ->
        val animatedExerciseId = targetState.first
        val animatedExercise = remember(animatedExerciseId, exercise) {
            viewModel.exercisesById[animatedExerciseId] ?: exercise
        }

        val exerciseTitleComposable: @Composable (onLongClick: () -> Unit) -> Unit =
            { providedOnLongClick ->
                ScrollableTextColumn(
                    text = animatedExercise.name,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 25.dp)
                        .combinedClickable(
                            onClick = {
                                hapticsViewModel.doGentleVibration()
                                marqueeEnabled = !marqueeEnabled
                            },
                            onLongClick = {
                                providedOnLongClick.invoke()
                            }
                        ),
                    maxLines = 2,
                    style = MaterialTheme.typography.titleLarge,
                    textAlign = TextAlign.Center
                )
            }

        CustomHorizontalPager(
            modifier = Modifier.fillMaxSize()
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
            userScrollEnabled = (pagerState.currentPage == exerciseDetailPageIndex) && allowHorizontalScrolling,
        ) { pageIndex ->
            // Get the page type for the current index
            val pageType = pageTypes[pageIndex]
            when (pageType) {
                PageType.PLATES -> PagePlates(state, equipment)
                PageType.EXERCISE_DETAIL -> ExerciseDetail(
                    modifier = Modifier.fillMaxSize(),
                    updatedState = state,
                    viewModel = viewModel,
                    onEditModeDisabled = { allowHorizontalScrolling = true },
                    onEditModeEnabled = { allowHorizontalScrolling = false },
                    onTimerDisabled = { },
                    onTimerEnabled = { },
                    extraInfo = { _ ->
                        val isWarmupSet = remember(state.set) {
                            when(val set = state.set) {
                                is BodyWeightSet -> set.subCategory == SetSubCategory.WarmupSet
                                is WeightSet -> set.subCategory == SetSubCategory.WarmupSet
                                else -> false
                            }
                        }
                        
                        val isCalibrationSet = remember(state.isCalibrationSet) {
                            state.isCalibrationSet
                        }
                        val isAutoRegulationWorkSet = remember(state.isAutoRegulationWorkSet) {
                            state.isAutoRegulationWorkSet
                        }

                        val supersetExercises = remember(exerciseOrSupersetId, isSuperset) {
                            if (isSuperset) {
                                viewModel.exercisesBySupersetId[exerciseOrSupersetId]!!
                            } else null
                        }
                        val supersetIndex = remember(supersetExercises, animatedExercise) {
                            supersetExercises?.indexOf(animatedExercise)
                        }
                        
                        val sideIndicator = remember(state.intraSetTotal) {
                            if (state.intraSetTotal != null) {
                                "① ↔ ②"
                            } else null
                        }
                        
                        Column(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.spacedBy(5.dp)
                        ) {
                            // Metadata strip
                            ExerciseMetadataStrip(
                                exerciseLabel = if (isSuperset) {
                                    "Superset: ${currentExerciseOrSupersetIndex + 1}/${exerciseOrSupersetIds.size}"
                                } else {
                                    "Exercise: ${currentExerciseOrSupersetIndex + 1}/${exerciseOrSupersetIds.size}"
                                },
                                supersetExerciseLabel = if (isSuperset && supersetIndex != null) {
                                    "Exercise: ${supersetIndex + 1}/${supersetExercises!!.size}"
                                } else null,
                                setLabel = viewModel.getSetCounterForExercise(
                                    state.exerciseId,
                                    state
                                )?.let { (current, total) ->
                                    if (total > 1) "Set: $current/$total" else null
                                },
                                sideIndicator = sideIndicator,
                                currentSideIndex = state.intraSetCounter.takeIf { state.intraSetTotal != null },
                                isUnilateral = state.isUnilateral,
                                equipmentName = equipment?.name,
                                accessoryNames = accessoryEquipments.joinToString(", ") { it.name }.takeIf { accessoryEquipments.isNotEmpty() },
                                textColor = MaterialTheme.colorScheme.onBackground,
                                onTap = {
                                    hapticsViewModel.doGentleVibration()
                                }
                            )
                            
                            // Status badges row
                            if (isWarmupSet || isCalibrationSet || isAutoRegulationWorkSet) {
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.Center,
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    if (isWarmupSet) {
                                        Chip(backgroundColor = MaterialTheme.colorScheme.primary) {
                                            Text(
                                                text = "Warm-up",
                                                style = captionStyle,
                                                color = MaterialTheme.colorScheme.primary,
                                                textAlign = TextAlign.Center
                                            )
                                        }
                                    }
                                    if (isCalibrationSet) {
                                        Text(
                                            text = "This exercise is waiting to be calibrated.",
                                            style = captionStyle,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                            textAlign = TextAlign.Center
                                        )
                                    }
                                    if (isAutoRegulationWorkSet) {
                                        Chip(backgroundColor = MaterialTheme.colorScheme.tertiary) {
                                            Text(
                                                text = "Auto-regulation",
                                                style = captionStyle,
                                                color = MaterialTheme.colorScheme.onTertiary,
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

                PageType.MUSCLES -> PageMuscles(exercise = animatedExercise)

                PageType.EXERCISES -> PageExercises(
                            workoutState = state,
                            viewModel = viewModel,
                            hapticsViewModel = hapticsViewModel,
                            currentExercise = animatedExercise,
                            onExerciseSelected = {
                                selectedExerciseId = it
                            })

                PageType.NOTES -> {} // PageNotes(exercise.notes)
                PageType.BUTTONS -> PageButtons(state, viewModel, hapticsViewModel)
            }
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
                        viewModel.pushAndStoreWorkoutData(false, context) {
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
    }

    DisposableEffect(Unit) {
        onDispose {
            goBackJob?.cancel()
        }
    }
}
