package com.gabstra.myworkoutassistant.screens

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.ExperimentalAnimationApi
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row

import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.pager.PagerState
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Check
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.drawscope.clipPath
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.foundation.ExperimentalWearFoundationApi
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.PositionIndicator
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.composable.BodyWeightSetDataViewer

import com.gabstra.myworkoutassistant.composable.BodyWeightSetScreen
import com.gabstra.myworkoutassistant.composable.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composable.CustomHorizontalPager
import com.gabstra.myworkoutassistant.composable.EnduranceSetDataViewerMinimal
import com.gabstra.myworkoutassistant.composable.EnduranceSetScreen
import com.gabstra.myworkoutassistant.composable.ExerciseIndicator
import com.gabstra.myworkoutassistant.composable.TimedDurationSetDataViewerMinimal
import com.gabstra.myworkoutassistant.composable.TimedDurationSetScreen
import com.gabstra.myworkoutassistant.composable.WeightSetDataViewer
import com.gabstra.myworkoutassistant.composable.WeightSetScreen
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.VibrateOnce
import com.gabstra.myworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import kotlinx.coroutines.delay


fun Modifier.circleMask() = this.drawWithContent {
    // Create a circular path for the mask
    val path = androidx.compose.ui.graphics.Path().apply {
        val radius = size.width  * 0.45f
        val center = Offset(size.width / 2, size.height / 2)
        addOval(androidx.compose.ui.geometry.Rect(center.x - radius, center.y - radius, center.x + radius, center.y + radius))
    }

    // Clip the path and draw the content
    clipPath(path) {
        this@drawWithContent.drawContent()
    }
}


@Composable
fun ExerciseDetail(
    updatedState: WorkoutState.Set, // Assuming SetState is the type holding set
    viewModel: AppViewModel,
    onEditModeDisabled: () -> Unit,
    onEditModeEnabled: () -> Unit,
    onTimerDisabled: () -> Unit,
    onTimerEnabled: () -> Unit
) {
    val context = LocalContext.current

    when (updatedState.set) {
        is WeightSet -> WeightSetScreen(
            viewModel = viewModel,
            modifier = Modifier.fillMaxSize(),
            state = updatedState,
            forceStopEditMode = false,
            onEditModeDisabled = onEditModeDisabled,
            onEditModeEnabled = onEditModeEnabled
        )
        is BodyWeightSet -> BodyWeightSetScreen(
            viewModel = viewModel,
            modifier = Modifier.fillMaxSize(),
            state = updatedState,
            forceStopEditMode = false,
            onEditModeDisabled = onEditModeDisabled,
            onEditModeEnabled = onEditModeEnabled
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
                }
            },
            onTimerDisabled = onTimerDisabled,
            onTimerEnabled = onTimerEnabled
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
                }
            },
            onTimerDisabled = onTimerDisabled,
            onTimerEnabled = onTimerEnabled
        )
    }
}

@Composable
fun SimplifiedHorizontalPager(
    modifier: Modifier,
    pagerState: PagerState,
    allowHorizontalScrolling: Boolean,
    updatedState:  WorkoutState.Set,
    viewModel: AppViewModel,
    completeOrSkipExerciseComposable: @Composable () -> Unit,
    notAvailableTextComposable: @Composable () -> Unit,
    onScrollEnabledChange: (Boolean) -> Unit
) {
    CustomHorizontalPager(
        modifier = modifier,
        pagerState = pagerState,
        userScrollEnabled = allowHorizontalScrolling
    ) { page ->
        when (page) {
            0 -> PageCompleteOrSkip(completeOrSkipExerciseComposable)
            1 -> PageExerciseDetail(
                updatedState = updatedState,
                viewModel = viewModel,
                onScrollEnabledChange = { onScrollEnabledChange(it) }
            )
            2 -> PageNotes(updatedState.parentExercise.notes)
            3 -> PagePreviousSet(updatedState, notAvailableTextComposable)
        }
    }
}

@Composable
fun PageCompleteOrSkip(completeOrSkipExerciseComposable: @Composable () -> Unit) {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        completeOrSkipExerciseComposable()
    }
}

@Composable
fun PageExerciseDetail(
    updatedState:  WorkoutState.Set,
    viewModel: AppViewModel,
    onScrollEnabledChange: (Boolean) -> Unit
) {
    ExerciseDetail(
        updatedState = updatedState,
        viewModel = viewModel,
        onEditModeDisabled = { onScrollEnabledChange(true) },
        onEditModeEnabled = { onScrollEnabledChange(false) },
        onTimerDisabled = { onScrollEnabledChange(true) },
        onTimerEnabled = { onScrollEnabledChange(false) }
    )
}

@Composable
fun PageNotes(notes: String) {
    val scrollState = rememberScrollState()
    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(0.dp, 10.dp, 0.dp, 0.dp)
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
                textAlign = TextAlign.Start
            )
        }
    }
}

@Composable
fun PagePreviousSet(
    updatedState:  WorkoutState.Set,
    notAvailableTextComposable: @Composable () -> Unit
) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(0.dp, 10.dp, 0.dp, 0.dp)
    ) {
        Text(
            modifier = Modifier.fillMaxSize(),
            text = "Previous Set",
            style = MaterialTheme.typography.body1,
            textAlign = TextAlign.Center
        )
        Column(
            modifier = Modifier.padding(40.dp, 25.dp, 40.dp, 0.dp),
            verticalArrangement = Arrangement.Top,
            horizontalAlignment = Alignment.End
        ) {
            if (updatedState.hasNoHistory) {
                notAvailableTextComposable()
            } else {
                when (val set = updatedState.set) {
                    is WeightSet -> WeightSetDataViewer(set as WeightSetData)
                    is BodyWeightSet -> BodyWeightSetDataViewer(set as BodyWeightSetData)
                    is TimedDurationSet -> TimedDurationSetDataViewerMinimal(set as TimedDurationSetData)
                    is EnduranceSet -> EnduranceSetDataViewerMinimal(set as EnduranceSetData)
                }
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class, ExperimentalComposeUiApi::class,
    ExperimentalAnimationApi::class, ExperimentalWearFoundationApi::class
)
@Composable
fun ExerciseScreen(
    viewModel: AppViewModel,
    state: WorkoutState.Set,
    hearthRateChart: @Composable () -> Unit
) {
    val context = LocalContext.current

    var showConfirmDialog by remember { mutableStateOf(false) }
    var showGoBackDialog by remember { mutableStateOf(false) }
    var showSkipDialog by remember { mutableStateOf(false) }

    var allowHorizontalScrolling by remember { mutableStateOf(true) }

    val isHistoryEmpty by viewModel.isHistoryEmpty.collectAsState()

    val pagerState = rememberPagerState(
        initialPage = 1,
        pageCount = {
        4
    })

    LaunchedEffect(state) {
        pagerState.animateScrollToPage(1)
        showConfirmDialog = false
        showGoBackDialog = false
        showSkipDialog = false
        allowHorizontalScrolling = false
        delay(2000)
        allowHorizontalScrolling = true
    }

    LaunchedEffect(allowHorizontalScrolling) {
        if (!allowHorizontalScrolling) {
            pagerState.animateScrollToPage(1)
        }
    }

    val completeOrSkipExerciseComposable = @Composable {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center
        ) {
            Button(
                modifier = Modifier
                    .size(30.dp)
                    .clip(CircleShape),
                onClick ={
                    VibrateOnce(context)
                    showGoBackDialog = true
                },
                enabled = !isHistoryEmpty
            ) {
                Icon(imageVector = Icons.Default.ArrowBack, contentDescription = "Back")
            }
            Spacer(modifier = Modifier.width(20.dp))
            Button(
                modifier = Modifier
                    .size(30.dp)
                    .clip(CircleShape),
                onClick ={
                    VibrateOnce(context)
                    showConfirmDialog = true
                },
            ) {
                Icon(imageVector = Icons.Default.Check, contentDescription = "Done")
            }
        }
    }

    val notAvailableTextComposable = @Composable {
        Text(
            modifier = Modifier.fillMaxSize(),
            text = "NOT AVAILABLE",
            style = MaterialTheme.typography.body1,
            textAlign = TextAlign.Center
        )
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(10.dp)
            .circleMask(),
        contentAlignment = Alignment.Center
    ) {
        Column(
            verticalArrangement = Arrangement.Top,
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier
                .fillMaxSize()
                .padding(0.dp, 20.dp, 0.dp, 10.dp)
        ) {
            AnimatedContent(
                targetState = state,
                transitionSpec = {
                    fadeIn(animationSpec = tween(500)) togetherWith fadeOut(animationSpec = tween(500))
                }, label = ""
            ) { updatedState ->
                Column(
                    modifier = Modifier.padding(25.dp,0.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text(
                        modifier = Modifier
                            .fillMaxWidth()
                            .basicMarquee(iterations = Int.MAX_VALUE)
                            .combinedClickable(
                                onClick = {},
                                onLongClick = {
                                    showSkipDialog = true
                                    VibrateOnce(context)
                                }
                            ),
                        text = updatedState.parentExercise.name,
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.title3,
                    )
                }

                SimplifiedHorizontalPager(
                    modifier = Modifier
                        .weight(1f)
                        .padding(0.dp, 20.dp, 0.dp, 0.dp),
                    pagerState = pagerState,
                    allowHorizontalScrolling = allowHorizontalScrolling,
                    updatedState = updatedState,
                    viewModel = viewModel,
                    completeOrSkipExerciseComposable = completeOrSkipExerciseComposable,
                    notAvailableTextComposable = notAvailableTextComposable,
                    onScrollEnabledChange = { allowHorizontalScrolling = it }
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

    CustomDialogYesOnLongPress(
        show = showConfirmDialog,
        title = "Complete exercise",
        message = "Do you want to save this data?",
        handleYesClick = {
            VibrateOnce(context)
            viewModel.storeSetData()
            viewModel.pushAndStoreWorkoutData(false,context){
                viewModel.upsertWorkoutRecord(state.set.id)
                viewModel.goToNextState()
            }

            showConfirmDialog=false
        },
        handleNoClick = {
            showConfirmDialog = false
            VibrateOnce(context)
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showConfirmDialog = false
        },
        holdTimeInMillis = 1000
    )

    CustomDialogYesOnLongPress(
        show = showSkipDialog,
        title = "Skip exercise",
        message = "Do you want to skip this exercise?",
        handleYesClick = {
            VibrateOnce(context)
            viewModel.pushAndStoreWorkoutData(false,context){
                viewModel.goToNextState()
            }
            showSkipDialog = false
        },
        handleNoClick = {
            showSkipDialog = false
            VibrateOnce(context)
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showSkipDialog = false
        },
        holdTimeInMillis = 1000
    )

    CustomDialogYesOnLongPress(
        show = showGoBackDialog,
        title = "Go to previous set",
        message = "Do you want to go back?",
        handleYesClick = {
            VibrateOnce(context)
            viewModel.goToPreviousSet()
            showGoBackDialog = false
        },
        handleNoClick = {
            showGoBackDialog = false
            VibrateOnce(context)
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showGoBackDialog = false
        },
        holdTimeInMillis = 1000
    )
}
