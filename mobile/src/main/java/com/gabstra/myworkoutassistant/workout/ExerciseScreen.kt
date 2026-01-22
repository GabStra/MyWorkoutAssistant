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
import com.gabstra.myworkoutassistant.composables.FadingText
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
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

    val exerciseSetIds = remember(exercise) {
        viewModel.setsByExerciseId[exercise.id]!!.map { it.set.id }
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

    var marqueeEnabled by remember { mutableStateOf(false) }

    val captionStyle = MaterialTheme.typography.bodySmall

    val exerciseOrSupersetIds = remember {
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
        targetState = state,
        transitionSpec = {
            fadeIn(animationSpec = tween(500)) togetherWith fadeOut(animationSpec = tween(500))
        }, label = ""
    ) { updatedState ->
        val setIndex = remember(updatedState.set.id) { exerciseSetIds.indexOf(updatedState.set.id) }

        val exerciseTitleComposable: @Composable (onLongClick: () -> Unit) -> Unit =
            { providedOnLongClick ->
                FadingText(
                    text = exercise.name,
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
                    style = MaterialTheme.typography.titleLarge,
                    marqueeEnabled = marqueeEnabled,
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
            userScrollEnabled = allowHorizontalScrolling,
        ) { pageIndex ->
            // Get the page type for the current index
            val pageType = pageTypes[pageIndex]
            when (pageType) {
                PageType.PLATES -> PagePlates(updatedState, equipment)
                PageType.EXERCISE_DETAIL -> ExerciseDetail(
                    modifier = Modifier.fillMaxSize(),
                    updatedState = updatedState,
                    viewModel = viewModel,
                    onEditModeDisabled = { allowHorizontalScrolling = true },
                    onEditModeEnabled = { allowHorizontalScrolling = false },
                    onTimerDisabled = { },
                    onTimerEnabled = { },
                    extraInfo = { _ ->
                        val isWarmupSet = remember(updatedState.set) {
                            when(val set = updatedState.set) {
                                is BodyWeightSet -> set.subCategory == SetSubCategory.WarmupSet
                                is WeightSet -> set.subCategory == SetSubCategory.WarmupSet
                                else -> false
                            }
                        }
                        
                        val isCalibrationSet = remember(updatedState.isCalibrationSet) {
                            updatedState.isCalibrationSet
                        }
                        
                        val supersetExercises = remember(exerciseOrSupersetId, isSuperset) {
                            if (isSuperset) {
                                viewModel.exercisesBySupersetId[exerciseOrSupersetId]!!
                            } else null
                        }
                        val supersetIndex = remember(supersetExercises, exercise) {
                            supersetExercises?.indexOf(exercise)
                        }
                        
                        val sideIndicator = remember(updatedState.intraSetTotal) {
                            if (updatedState.intraSetTotal != null) {
                                "A ↔ B"
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
                                setLabel = if (exerciseSetIds.size > 1) {
                                    "Set: ${setIndex + 1}/${exerciseSetIds.size}"
                                } else null,
                                sideIndicator = sideIndicator,
                                currentSideIndex = updatedState.intraSetCounter.takeIf { updatedState.intraSetTotal != null },
                                isUnilateral = updatedState.isUnilateral,
                                equipmentName = equipment?.name,
                                accessoryNames = accessoryEquipments.joinToString(", ") { it.name }.takeIf { accessoryEquipments.isNotEmpty() },
                                textColor = MaterialTheme.colorScheme.onBackground,
                                onTap = {
                                    hapticsViewModel.doGentleVibration()
                                }
                            )
                            
                            // Status badges row
                            if (isWarmupSet || isCalibrationSet) {
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
                                        Chip(backgroundColor = Green) {
                                            Text(
                                                text = "Calibration",
                                                style = captionStyle,
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

                PageType.MUSCLES -> PageMuscles(exercise = exercise)

                PageType.EXERCISES ->PageExercises(
                            updatedState,
                            viewModel, hapticsViewModel,
                            exercise,
                            onExerciseSelected = {
                                selectedExerciseId = it
                            })

                PageType.NOTES -> {} // PageNotes(exercise.notes)
                PageType.BUTTONS -> PageButtons(updatedState, viewModel, hapticsViewModel)
            }
        }

        CustomDialogYesOnLongPress(
            show = showNextDialog,
            title = if (updatedState.intraSetTotal != null && updatedState.intraSetCounter < updatedState.intraSetTotal!!) "Switch side" else "Complete Set",
            message = "Do you want to proceed?",
            handleYesClick = {

                if (updatedState.intraSetTotal != null) {
                    updatedState.intraSetCounter++
                }

                hapticsViewModel.doGentleVibration()
                viewModel.storeSetData()
                viewModel.pushAndStoreWorkoutData(false, context) {
                    viewModel.goToNextState()
                    viewModel.lightScreenUp()
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
                updatedState,
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

