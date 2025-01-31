package com.gabstra.myworkoutassistant.screens

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
import com.gabstra.myworkoutassistant.composable.ExerciseInfo
import com.gabstra.myworkoutassistant.composable.ExerciseSetsViewer
import com.gabstra.myworkoutassistant.composable.TimedDurationSetScreen
import com.gabstra.myworkoutassistant.composable.WeightSetScreen
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.VibrateGentle
import com.gabstra.myworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.data.circleMask
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.PlateCalculator
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise


@Composable
fun ExerciseDetail(
    updatedState: WorkoutState.Set, // Assuming SetState is the type holding set
    viewModel: AppViewModel,
    onEditModeDisabled: () -> Unit,
    onEditModeEnabled: () -> Unit,
    onTimerDisabled: () -> Unit,
    onTimerEnabled: () -> Unit,
    extraInfo: (@Composable (WorkoutState.Set) -> Unit)? = null,
    exerciseTitleComposable:  @Composable () -> Unit,
) {
    val context = LocalContext.current

    when (updatedState.set) {
        is WeightSet -> WeightSetScreen(
            viewModel = viewModel,
            modifier = Modifier.fillMaxSize(),
            state = updatedState,
            forceStopEditMode = false,
            onEditModeDisabled = onEditModeDisabled,
            onEditModeEnabled = onEditModeEnabled,
            extraInfo = extraInfo,
            exerciseTitleComposable = exerciseTitleComposable
        )
        is BodyWeightSet -> BodyWeightSetScreen(
            viewModel = viewModel,
            modifier = Modifier.fillMaxSize(),
            state = updatedState,
            forceStopEditMode = false,
            onEditModeDisabled = onEditModeDisabled,
            onEditModeEnabled = onEditModeEnabled,
            extraInfo = extraInfo,
            exerciseTitleComposable = exerciseTitleComposable
        )
        is TimedDurationSet -> TimedDurationSetScreen(
            viewModel = viewModel,
            modifier = Modifier.fillMaxSize(),
            state = updatedState,
            onTimerEnd = {
                viewModel.storeSetData()
                viewModel.pushAndStoreWorkoutData(false,context){
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
        is EnduranceSet -> EnduranceSetScreen(
            viewModel = viewModel,
            modifier = Modifier.fillMaxSize(),
            state = updatedState,
            onTimerEnd = {
                viewModel.storeSetData()
                viewModel.pushAndStoreWorkoutData(false,context){
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
fun SimplifiedHorizontalPager(
    modifier: Modifier,
    pagerState: PagerState,
    allowHorizontalScrolling: Boolean,
    updatedState:  WorkoutState.Set,
    viewModel: AppViewModel,
    exerciseTitleComposable: @Composable () -> Unit,
    onScrollEnabledChange: (Boolean) -> Unit
) {
    val exercise = viewModel.exercisesById[updatedState.exerciseId]!!

    CustomHorizontalPager(
        modifier = modifier,
        pagerState = pagerState,
        userScrollEnabled = allowHorizontalScrolling,
    ) { page ->
        when (page) {
            0 -> PagePlates(updatedState,exercise,viewModel)
            1 -> PageExerciseDetail(
                updatedState = updatedState,
                viewModel = viewModel,
                onScrollEnabledChange = { onScrollEnabledChange(it) },
                exerciseTitleComposable = exerciseTitleComposable
            )
            2 -> PageNextSets(updatedState,viewModel)
            3 -> PageCompleteOrSkip(updatedState,viewModel)
            4 -> PageNewSets(updatedState,viewModel)
            5 -> PageNotes(exercise.notes)
        }
    }
}

@Composable
fun PageNextSets(
    updatedState:  WorkoutState.Set,
    viewModel: AppViewModel
){
    val exercise = viewModel.exercisesById[updatedState.exerciseId]!!

    Column(
        modifier = Modifier.fillMaxSize().padding(15.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            modifier = Modifier.fillMaxWidth(),
            text = "Exercise Sets",
            style = MaterialTheme.typography.body1,
            textAlign = TextAlign.Center
        )
        ExerciseSetsViewer(
            modifier = Modifier.fillMaxSize(),
            viewModel = viewModel,
            exercise = exercise,
            currentSet = updatedState.set
        )
    }
}

@Composable
fun PageCompleteOrSkip(
    updatedState:  WorkoutState.Set,
    viewModel: AppViewModel
) {
    val isHistoryEmpty by viewModel.isHistoryEmpty.collectAsState()

    val context = LocalContext.current

    var showCompleteDialog by remember { mutableStateOf(false) }
    var showGoBackDialog by remember { mutableStateOf(false) }
    val listState = rememberScalingLazyListState(initialCenterItemIndex = 0)

    LaunchedEffect(updatedState) {
        showCompleteDialog = false
        showGoBackDialog = false
    }

    ScalingLazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(10.dp),
        state = listState
    ) {
        item{
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
    }

    CustomDialogYesOnLongPress(
        show = showCompleteDialog,
        title = "Complete exercise",
        message = "Do you want to proceed?",
        handleYesClick = {
            VibrateGentle(context)

            viewModel.storeSetData()
            viewModel.pushAndStoreWorkoutData(false,context){
                viewModel.completeExercise()
                viewModel.lightScreenUp()
            }


            showCompleteDialog = false
        },
        handleNoClick = {
            showCompleteDialog = false
            VibrateGentle(context)
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showCompleteDialog = false
        },
        holdTimeInMillis = 1000
    )

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
    updatedState:  WorkoutState.Set,
    viewModel: AppViewModel,
    onScrollEnabledChange: (Boolean) -> Unit,
    exerciseTitleComposable:  @Composable () -> Unit,
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

    if(updatedState.set is RestSet || updatedState.currentSetData is RestSetData || updatedState.previousSetData is RestSetData){
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
            .padding(top = 10.dp)
    ) {
        Text(
            modifier = Modifier.fillMaxSize(),
            text = "Notes",
            style = MaterialTheme.typography.body1,
            textAlign = TextAlign.Center
        )

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp, 25.dp, 20.dp, 25.dp)
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
fun PagePlates(updatedState:  WorkoutState.Set, exercise: Exercise, viewModel: AppViewModel) {
    val equipment = remember(exercise) {
        if(exercise.equipmentId != null) viewModel.getEquipmentById(exercise.equipmentId!!) else null
    }

    val scrollState = rememberScrollState()
    Column(
        modifier = Modifier.fillMaxSize().padding(15.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            modifier = Modifier.fillMaxWidth(),
            text = "Plates Helper",
            style = MaterialTheme.typography.body1,
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
                Row(
                    modifier = Modifier
                        .fillMaxSize()
                        .verticalScroll(scrollState),
                    horizontalArrangement = Arrangement.Center
                ) {
                    if (updatedState.plateChangeResult.change.steps.isNotEmpty()) {
                        val style = MaterialTheme.typography.body1
                        Column(
                            modifier= Modifier.fillMaxWidth().padding(horizontal = 20.dp).padding(bottom = 20.dp),
                            verticalArrangement = Arrangement.spacedBy(5.dp),
                            horizontalAlignment = Alignment.CenterHorizontally
                        ) {
                            updatedState.plateChangeResult.change.steps.forEachIndexed { index, step ->
                                Row(modifier= Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(5.dp)){
                                    Text(
                                        text = "${index+1})",
                                        style = MaterialTheme.typography.body1,
                                        textAlign = TextAlign.Start
                                    )
                                    Row(modifier= Modifier.fillMaxWidth(),horizontalArrangement= Arrangement.Center, verticalAlignment = Alignment.Bottom) {
                                        val weightText = if (step.weight % 1 == 0.0) {
                                            "${step.weight.toInt()}"
                                        } else {
                                            "${step.weight}"
                                        }

                                        val actionText = if(step.action == PlateCalculator.Companion.Action.ADD) { "+" } else { "-" }

                                        Text(
                                            text = "$actionText $weightText",
                                            style = style,
                                            textAlign = TextAlign.End,
                                        )
                                        Spacer(modifier = Modifier.width(3.dp))
                                        Text(
                                            text = "kg",
                                            style = style.copy(fontSize = style.fontSize * 0.5f),
                                            modifier = Modifier.padding(bottom = 2.dp)
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
}

@Composable
fun PageNewSets(
    updatedState:  WorkoutState.Set,
    viewModel: AppViewModel
){
    val context = LocalContext.current

    val listState = rememberScalingLazyListState(initialCenterItemIndex = 0)

    val exercise = viewModel.exercisesById[updatedState.exerciseId]!!
    val exerciseSets = exercise.sets

    val setIndex =  exerciseSets.indexOfFirst { it === updatedState.set }
    val isLastSet = setIndex == exerciseSets.size - 1

    val isMovementSet = updatedState.set is WeightSet || updatedState.set is BodyWeightSet
    val nextWorkoutState by viewModel.nextWorkoutState.collectAsState()

    ScalingLazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(10.dp),
        state = listState
    ) {
        item{
            ButtonWithText(
                text = "Add Set",
                onClick = {
                    VibrateGentle(context)
                    viewModel.storeSetData()
                    viewModel.pushAndStoreWorkoutData(false,context){
                        viewModel.addNewSetStandard()
                    }
                },
                backgroundColor = MaterialTheme.colors.background
            )
        }
        if(nextWorkoutState !is WorkoutState.Rest){
            item{
                ButtonWithText(
                    text = "Add Rest",
                    onClick = {
                        VibrateGentle(context)
                        viewModel.storeSetData()
                        viewModel.pushAndStoreWorkoutData(false,context){
                            viewModel.addNewRest()
                        }
                    },
                    backgroundColor = MaterialTheme.colors.background
                )
            }
        }

        if(isMovementSet && isLastSet){
            item{
                ButtonWithText(
                    text = "Add Rest-Pause Set",
                    onClick = {
                        VibrateGentle(context)
                        viewModel.storeSetData()
                        viewModel.pushAndStoreWorkoutData(false,context){
                            viewModel.addNewRestPauseSet()
                        }
                    },
                    backgroundColor = MaterialTheme.colors.background
                )
            }
        }
    }
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

    val pagerState = rememberPagerState(
        initialPage = 0,
        pageCount = {
        6
    })

    LaunchedEffect(state.set.id) {
        pagerState.scrollToPage(1)
        allowHorizontalScrolling = true
        viewModel.closeCustomDialog()
    }

    LaunchedEffect(allowHorizontalScrolling) {
        if (!allowHorizontalScrolling && pagerState.currentPage != 0) {
            pagerState.scrollToPage(1)
        }
    }

    var marqueeEnabled by remember { mutableStateOf(false) }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(10.dp)
            .circleMask(),
        contentAlignment = Alignment.Center
    ) {
        AnimatedContent(
            targetState = state,
            transitionSpec = {
                fadeIn(animationSpec = tween(500)) togetherWith fadeOut(animationSpec = tween(500))
            }, label = ""
        ) { updatedState ->

            val exercise = viewModel.exercisesById[updatedState.exerciseId]!!
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(vertical = 10.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                val exerciseTitleComposable = @Composable{
                    Text(
                        modifier = Modifier
                            .width(100.dp)
                            .clickable { marqueeEnabled = !marqueeEnabled }
                            .then(if (marqueeEnabled) Modifier.basicMarquee(iterations = Int.MAX_VALUE) else Modifier),
                        text = exercise.name,
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.title3,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }

                SimplifiedHorizontalPager(
                    modifier = Modifier.fillMaxSize(),
                    pagerState = pagerState,
                    allowHorizontalScrolling = allowHorizontalScrolling,
                    updatedState = updatedState,
                    viewModel = viewModel,
                    onScrollEnabledChange = {
                        allowHorizontalScrolling = it
                    },
                    exerciseTitleComposable = exerciseTitleComposable,
                )
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
            viewModel.pushAndStoreWorkoutData(false,context){
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
