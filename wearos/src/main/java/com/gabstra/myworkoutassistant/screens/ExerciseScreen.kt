package com.gabstra.myworkoutassistant.screens

import android.util.Log
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.pager.PagerState
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.wear.compose.foundation.lazy.ScalingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberScalingLazyListState
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text

import com.gabstra.myworkoutassistant.composable.BodyWeightSetScreen
import com.gabstra.myworkoutassistant.composable.ButtonWithText
import com.gabstra.myworkoutassistant.composable.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composable.CustomHorizontalPager
import com.gabstra.myworkoutassistant.composable.EnduranceSetScreen
import com.gabstra.myworkoutassistant.composable.ExerciseIndicator
import com.gabstra.myworkoutassistant.composable.ExerciseSetsViewer
import com.gabstra.myworkoutassistant.composable.TimedDurationSetScreen
import com.gabstra.myworkoutassistant.composable.WeightSetScreen
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.VibrateGentle
import com.gabstra.myworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.data.circleMask
import com.gabstra.myworkoutassistant.data.verticalColumnScrollbar
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.PlateCalculator
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.time.LocalDateTime


@Composable
fun ExerciseDetail(
    updatedState: WorkoutState.Set, // Assuming SetState is the type holding set
    viewModel: AppViewModel,
    onEditModeDisabled: () -> Unit,
    onEditModeEnabled: () -> Unit,
    onTimerDisabled: () -> Unit,
    onTimerEnabled: () -> Unit,
    extraInfo: (@Composable (WorkoutState.Set) -> Unit)? = null,
    exerciseTitleComposable: @Composable () -> Unit,
) {
    val context = LocalContext.current

    when (updatedState.set) {
        is WeightSet -> {
            LaunchedEffect(updatedState) {
                if (updatedState.startTime == null) {
                    updatedState.startTime = LocalDateTime.now()
                }
            }

            WeightSetScreen(
                viewModel = viewModel,
                modifier = Modifier.fillMaxSize(),
                state = updatedState,
                forceStopEditMode = false,
                onEditModeDisabled = onEditModeDisabled,
                onEditModeEnabled = onEditModeEnabled,
                extraInfo = extraInfo,
                exerciseTitleComposable = exerciseTitleComposable
            )
        }

        is BodyWeightSet -> {
            LaunchedEffect(updatedState) {
                if (updatedState.startTime == null) {
                    updatedState.startTime = LocalDateTime.now()
                }
            }

            BodyWeightSetScreen(
                viewModel = viewModel,
                modifier = Modifier.fillMaxSize(),
                state = updatedState,
                forceStopEditMode = false,
                onEditModeDisabled = onEditModeDisabled,
                onEditModeEnabled = onEditModeEnabled,
                extraInfo = extraInfo,
                exerciseTitleComposable = exerciseTitleComposable
            )
        }

        is TimedDurationSet -> {
            TimedDurationSetScreen(
                viewModel = viewModel,
                modifier = Modifier.fillMaxSize(),
                state = updatedState,
                onTimerEnd = {
                    viewModel.storeSetData()
                    viewModel.pushAndStoreWorkoutData(false, context) {
                        viewModel.upsertWorkoutRecord(updatedState.set.id)
                        viewModel.goToNextState()
                        viewModel.lightScreenUp()
                    }
                },
                onTimerDisabled = onTimerDisabled,
                onTimerEnabled = onTimerEnabled,
                extraInfo = extraInfo,
                exerciseTitleComposable = exerciseTitleComposable
            )
        }

        is EnduranceSet -> EnduranceSetScreen(
            viewModel = viewModel,
            modifier = Modifier.fillMaxSize(),
            state = updatedState,
            onTimerEnd = {
                viewModel.storeSetData()
                viewModel.pushAndStoreWorkoutData(false, context) {
                    viewModel.upsertWorkoutRecord(updatedState.set.id)
                    viewModel.goToNextState()
                    viewModel.lightScreenUp()
                }
            },
            onTimerDisabled = onTimerDisabled,
            onTimerEnabled = onTimerEnabled,
            extraInfo = extraInfo,
            exerciseTitleComposable = exerciseTitleComposable
        )

        is RestSet -> throw IllegalStateException("Rest set should not be here")
    }
}

@Composable
fun PageNextSets(
    updatedState: WorkoutState.Set,
    viewModel: AppViewModel
) {
    val exercise = viewModel.exercisesById[updatedState.exerciseId]!!

    Column(
        modifier = Modifier.fillMaxSize(),
        verticalArrangement = Arrangement.spacedBy(5.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            modifier = Modifier.fillMaxWidth(),
            text = "Sets",
            style = MaterialTheme.typography.title3,
            textAlign = TextAlign.Center
        )
        ExerciseSetsViewer(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 5.dp),
            viewModel = viewModel,
            exercise = exercise,
            currentSet = updatedState.set
        )
    }
}

@Composable
fun PageButtons(
    updatedState: WorkoutState.Set,
    viewModel: AppViewModel
) {
    val isHistoryEmpty by viewModel.isHistoryEmpty.collectAsState()

    val context = LocalContext.current

    var showGoBackDialog by remember { mutableStateOf(false) }
    val listState = rememberScalingLazyListState(initialCenterItemIndex = 0)

    val exercise = viewModel.exercisesById[updatedState.exerciseId]!!
    val exerciseSets = exercise.sets

    val setIndex = exerciseSets.indexOfFirst { it === updatedState.set }
    val isLastSet = setIndex == exerciseSets.size - 1

    val isMovementSet = updatedState.set is WeightSet || updatedState.set is BodyWeightSet
    val nextWorkoutState by viewModel.nextWorkoutState.collectAsState()

    LaunchedEffect(updatedState) {
        showGoBackDialog = false
    }

    ScalingLazyColumn(
        modifier = Modifier
            .fillMaxSize(),
        state = listState
    ) {
        item {
            ButtonWithText(
                text = "Back",
                onClick = {
                    VibrateGentle(context)
                    showGoBackDialog = true
                },
                enabled = !isHistoryEmpty,
                backgroundColor = MaterialTheme.colors.background
            )
        }
        item {
            ButtonWithText(
                text = "Add Set",
                onClick = {
                    VibrateGentle(context)
                    viewModel.storeSetData()
                    viewModel.pushAndStoreWorkoutData(false, context) {
                        viewModel.addNewSetStandard()
                    }
                },
                backgroundColor = MaterialTheme.colors.background
            )
        }
        if (nextWorkoutState !is WorkoutState.Rest) {
            item {
                ButtonWithText(
                    text = "Add Rest",
                    onClick = {
                        VibrateGentle(context)
                        viewModel.storeSetData()
                        viewModel.pushAndStoreWorkoutData(false, context) {
                            viewModel.addNewRest()
                        }
                    },
                    backgroundColor = MaterialTheme.colors.background
                )
            }
        }

        if (isMovementSet && isLastSet) {
            item {
                ButtonWithText(
                    text = "Add Rest-Pause Set",
                    onClick = {
                        VibrateGentle(context)
                        viewModel.storeSetData()
                        viewModel.pushAndStoreWorkoutData(false, context) {
                            viewModel.addNewRestPauseSet()
                        }
                    },
                    backgroundColor = MaterialTheme.colors.background
                )
            }
        }
    }

    CustomDialogYesOnLongPress(
        show = showGoBackDialog,
        title = "Go to previous set",
        message = "Do you want to proceed?",
        handleYesClick = {
            VibrateGentle(context)
            viewModel.goToPreviousSet()
            viewModel.lightScreenUp()
            showGoBackDialog = false
        },
        handleNoClick = {
            showGoBackDialog = false
            VibrateGentle(context)
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showGoBackDialog = false
        },
        holdTimeInMillis = 1000
    )
}

@Composable
fun PageExerciseDetail(
    updatedState: WorkoutState.Set,
    viewModel: AppViewModel,
    onScrollEnabledChange: (Boolean) -> Unit,
    exerciseTitleComposable: @Composable () -> Unit,
) {
    /*val extraInfoComposable: @Composable (WorkoutState.Set) -> Unit = {state ->
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.Center
        ){
            when (val set = state.set) {
                is WeightSet -> WeightSetDataViewerMinimal(state.previousSetData as WeightSetData,MaterialTheme.typography.caption3)
                is BodyWeightSet -> BodyWeightSetDataViewerMinimal(state.previousSetData as BodyWeightSetData,MaterialTheme.typography.caption2)
                is TimedDurationSet -> TimedDurationSetDataViewerMinimal(state.previousSetData as TimedDurationSetData,MaterialTheme.typography.caption2,historyMode = true)
                is EnduranceSet -> EnduranceSetDataViewerMinimal(state.previousSetData as EnduranceSetData,MaterialTheme.typography.caption2,historyMode = true)
                is RestSet -> throw IllegalStateException("Rest set should not be here")
            }
        }
    }*/

    if (updatedState.set is RestSet || updatedState.currentSetData is RestSetData || updatedState.previousSetData is RestSetData) {
        throw IllegalStateException("Rest set should not be here")
    }

    ExerciseDetail(
        updatedState = updatedState,
        viewModel = viewModel,
        onEditModeDisabled = { onScrollEnabledChange(true) },
        onEditModeEnabled = { onScrollEnabledChange(false) },
        onTimerDisabled = { onScrollEnabledChange(true) },
        onTimerEnabled = { onScrollEnabledChange(false) },
        extraInfo = null,
        exerciseTitleComposable = exerciseTitleComposable
    )
}

@Composable
fun PageNotes(notes: String) {
    val scrollState = rememberScrollState()
    Box(
        modifier = Modifier
            .fillMaxSize()
    ) {
        Text(
            modifier = Modifier.fillMaxSize(),
            text = "Notes",
            style = MaterialTheme.typography.title3,
            textAlign = TextAlign.Center
        )

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 25.dp)
                .verticalScroll(scrollState)
        ) {
            Text(
                text = notes.ifEmpty { "NOT AVAILABLE" },
                modifier = Modifier.fillMaxWidth(),
                style = MaterialTheme.typography.body1,
                textAlign = TextAlign.Center
            )
        }
    }
}

@Composable
fun PagePlates(updatedState: WorkoutState.Set, exercise: Exercise, viewModel: AppViewModel) {
    val equipment = remember(exercise) {
        if (exercise.equipmentId != null) viewModel.getEquipmentById(exercise.equipmentId!!) else null
    }

    val scrollState = rememberScrollState()
    Column(
        modifier = Modifier.fillMaxSize(),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            modifier = Modifier.fillMaxWidth(),
            text = "Plates",
            style = MaterialTheme.typography.title3,
            textAlign = TextAlign.Center
        )
        Spacer(modifier = Modifier.height(10.dp))

        if (equipment == null || equipment !is Barbell || updatedState.plateChangeResult == null) {
            Text(
                text = "NOT AVAILABLE",
                style = MaterialTheme.typography.body1,
                textAlign = TextAlign.Center
            )
        } else {
            if (updatedState.plateChangeResult.change.steps.isEmpty()) {
                Text(
                    text = "No changes needed",
                    modifier = Modifier.fillMaxWidth(),
                    style = MaterialTheme.typography.body1,
                    textAlign = TextAlign.Center
                )
            } else {
                val typography = MaterialTheme.typography
                val headerStyle =
                    remember { typography.body1.copy(fontSize = typography.body1.fontSize * 0.625f) }

                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(horizontal = 10.dp),
                    verticalArrangement = Arrangement.spacedBy(5.dp),
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            modifier = Modifier.weight(1f),
                            text = "#",
                            style = headerStyle,
                            textAlign = TextAlign.Center
                        )
                        Text(
                            modifier = Modifier.weight(1f),
                            text = "PLATES",
                            style = headerStyle,
                            textAlign = TextAlign.Center
                        )
                    }

                    if (updatedState.plateChangeResult.change.steps.isNotEmpty()) {
                        val style = MaterialTheme.typography.body1

                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .verticalColumnScrollbar(
                                    scrollState = scrollState,
                                    scrollBarColor = Color.White,
                                    scrollBarTrackColor = Color.DarkGray
                                )
                                .verticalScroll(scrollState),
                            verticalArrangement = Arrangement.spacedBy(5.dp),
                            horizontalAlignment = Alignment.CenterHorizontally
                        ) {
                            updatedState.plateChangeResult.change.steps.forEachIndexed { index, step ->
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    Text(
                                        modifier = Modifier.weight(1f),
                                        text = "${index + 1}",
                                        style = MaterialTheme.typography.body1,
                                        textAlign = TextAlign.Center
                                    )
                                    val weightText = if (step.weight % 1 == 0.0) {
                                        "${step.weight.toInt()}"
                                    } else {
                                        "${step.weight}"
                                    }

                                    val actionText =
                                        if (step.action == PlateCalculator.Companion.Action.ADD) {
                                            "+"
                                        } else {
                                            "-"
                                        }

                                    Text(
                                        modifier = Modifier.weight(1f),
                                        text = "$actionText $weightText",
                                        style = style,
                                        textAlign = TextAlign.Center,
                                    )
                                }
                            }
                        }

                    }
                }
            }
        }
    }
}

enum class PageType {
    PLATES, EXERCISE_DETAIL, NEXT_SETS, NOTES, BUTTONS
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun ExerciseScreen(
    viewModel: AppViewModel,
    state: WorkoutState.Set,
    hearthRateChart: @Composable () -> Unit,
) {
    var allowHorizontalScrolling by remember { mutableStateOf(true) }
    val showNextDialog by viewModel.isCustomDialogOpen.collectAsState()

    val exercise = viewModel.exercisesById[state.exerciseId]!!
    val equipment = remember(exercise) {
        if (exercise.equipmentId != null) viewModel.getEquipmentById(exercise.equipmentId!!) else null
    }

    Log.d("ExerciseScreen", "Equipment: $equipment")

    // Determine which pages to show based on equipment type and notes
    val showPlatesPage = equipment != null
            && equipment.type == EquipmentType.BARBELL
            && (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT)

    val showNotesPage = exercise.notes.isNotEmpty()

    val pageTypes = remember(showPlatesPage, showNotesPage) {
        mutableListOf<PageType>().apply {
            if (showPlatesPage) add(PageType.PLATES)
            add(PageType.EXERCISE_DETAIL)
            add(PageType.NEXT_SETS)
            if (showNotesPage) add(PageType.NOTES)
            add(PageType.BUTTONS)
        }
    }

    // Find index of exercise detail page to scroll to on changes
    val exerciseDetailPageIndex = remember(pageTypes) {
        pageTypes.indexOf(PageType.EXERCISE_DETAIL).coerceAtLeast(0)
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

    LaunchedEffect(allowHorizontalScrolling, pageTypes) {
        if (!allowHorizontalScrolling && pageTypes.getOrNull(pagerState.currentPage) == PageType.PLATES) {
            pagerState.scrollToPage(exerciseDetailPageIndex)
        }
    }

    var marqueeEnabled by remember { mutableStateOf(false) }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(5.dp)
            .circleMask(),
        contentAlignment = Alignment.Center
    ) {
        AnimatedContent(
            targetState = state,
            transitionSpec = {
                fadeIn(animationSpec = tween(500)) togetherWith fadeOut(animationSpec = tween(500))
            }, label = ""
        ) { updatedState ->

            val currentExercise = viewModel.exercisesById[updatedState.exerciseId]!!
            val exerciseTitleComposable = @Composable {
                Text(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 30.dp)
                        .clickable { marqueeEnabled = !marqueeEnabled }
                        .then(if (marqueeEnabled) Modifier.basicMarquee(iterations = Int.MAX_VALUE) else Modifier),
                    text = currentExercise.name,
                    textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.title3,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }

            CustomHorizontalPager(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(20.dp),
                pagerState = pagerState,
                userScrollEnabled = allowHorizontalScrolling,
            ) { pageIndex ->
                // Get the page type for the current index
                val pageType = pageTypes[pageIndex]

                when (pageType) {
                    PageType.PLATES -> PagePlates(updatedState, currentExercise, viewModel)
                    PageType.EXERCISE_DETAIL -> PageExerciseDetail(
                        updatedState = updatedState,
                        viewModel = viewModel,
                        onScrollEnabledChange = {
                            allowHorizontalScrolling = it
                        },
                        exerciseTitleComposable = exerciseTitleComposable
                    )
                    PageType.NEXT_SETS -> PageNextSets(updatedState, viewModel)
                    PageType.NOTES -> PageNotes(currentExercise.notes)
                    PageType.BUTTONS -> PageButtons(updatedState, viewModel)
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
            modifier = Modifier.fillMaxSize(),
            viewModel,
            state
        )

        hearthRateChart()
    }

    val context = LocalContext.current

    CustomDialogYesOnLongPress(
        show = showNextDialog,
        title = "Complete set",
        message = "Do you want to proceed?",
        handleYesClick = {
            VibrateGentle(context)
            viewModel.storeSetData()
            viewModel.pushAndStoreWorkoutData(false, context) {
                viewModel.upsertWorkoutRecord(state.set.id)
                viewModel.goToNextState()
                viewModel.lightScreenUp()
            }

            viewModel.closeCustomDialog()
        },
        handleNoClick = {
            viewModel.closeCustomDialog()
            VibrateGentle(context)
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            viewModel.closeCustomDialog()
        },
        holdTimeInMillis = 1000
    )
}