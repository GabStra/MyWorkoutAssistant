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
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Check
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
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
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.composable.BodyWeightSetDataViewer

import com.gabstra.myworkoutassistant.composable.BodyWeightSetScreen
import com.gabstra.myworkoutassistant.composable.CustomDialog
import com.gabstra.myworkoutassistant.composable.CustomHorizontalPager
import com.gabstra.myworkoutassistant.composable.EnduranceSetScreen
import com.gabstra.myworkoutassistant.composable.ExerciseIndicator
import com.gabstra.myworkoutassistant.composable.TimedDurationSetScreen
import com.gabstra.myworkoutassistant.composable.WeightSetDataViewer
import com.gabstra.myworkoutassistant.composable.WeightSetScreen
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.VibrateOnce
import com.gabstra.myworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch


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

@OptIn(ExperimentalFoundationApi::class, ExperimentalComposeUiApi::class,
    ExperimentalAnimationApi::class, ExperimentalWearFoundationApi::class
)
@Composable
fun ExerciseScreen(
    viewModel: AppViewModel,
    state: WorkoutState.Set,
    onScreenLocked: () -> Unit,
    onScreenUnlocked: () -> Unit,
    hearthRateChart: @Composable () -> Unit
) {
    val context = LocalContext.current

    val scope = rememberCoroutineScope()

    var touchJob by remember { mutableStateOf<Job?>(null) }
    var showLockScreen by remember { mutableStateOf(false) }

    val exerciseIndex = viewModel.setsByExercise.keys.indexOfFirst { it === state.parentExercise }
    val totalExercises = viewModel.setsByExercise.keys.count()

    fun startTouchTimer() {
        touchJob?.cancel()
        touchJob = scope.launch {
            delay(5000)  // wait for 10 seconds
            showLockScreen=true
            onScreenLocked()
        }
    }

    var showConfirmDialog by remember { mutableStateOf(false) }
    var showGoBackDialog by remember { mutableStateOf(false) }
    var showSkipDialog by remember { mutableStateOf(false) }
    var showAddSetDialog by remember { mutableStateOf(false) }

    val exerciseSets = state.parentExercise.sets

    val setIndex = remember(state,exerciseSets) {
        exerciseSets.indexOfFirst { it === state.set }
    }

    val pagerState = rememberPagerState(
        initialPage = 1,
        pageCount = {
        3
    })


    LaunchedEffect(state) {
        pagerState.animateScrollToPage(1)
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
                enabled = !viewModel.isHistoryEmpty
            ) {
                Icon(imageVector = Icons.Default.ArrowBack, contentDescription = "B")
            }
            Spacer(modifier = Modifier.width(20.dp))
            Button(
                modifier = Modifier
                    .size(30.dp)
                    .clip(CircleShape),
                onClick ={
                    VibrateOnce(context) // Make sure this is a correctly implemented function to vibrate once.
                    showConfirmDialog =
                        true // Ensure you have state management to handle showing a dialog.
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

        /*
        Box(modifier = Modifier
            .fillMaxSize()
            .padding(0.dp, 20.dp, 0.dp, 25.dp), contentAlignment = Alignment.TopCenter){
            Row(modifier = Modifier.fillMaxWidth(),horizontalArrangement = Arrangement.Center) {
                Text(text="${exerciseIndex+1}/${totalExercises}",style = MaterialTheme.typography.body1)
                Spacer(modifier = Modifier.width(30.dp))
                Text( text="${setIndex+1}/${exerciseSets.count()}",style = MaterialTheme.typography.body1)
            }
        }
        */

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
                            .basicMarquee()
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

                CustomHorizontalPager(
                    modifier = Modifier
                        .weight(1f)
                        .padding(0.dp, 20.dp, 0.dp, 0.dp),
                    pagerState = pagerState,
                ) { page ->
                    when(page){
                        0 -> {
                            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center){
                                completeOrSkipExerciseComposable()
                            }

                        }
                        1 -> {
                            when(updatedState.set){
                                is WeightSet -> WeightSetScreen(
                                    modifier = Modifier.fillMaxSize(),
                                    state = updatedState,
                                    forceStopEditMode = showLockScreen,
                                    bottom = {  }
                                )
                                is BodyWeightSet -> BodyWeightSetScreen(
                                    modifier = Modifier.fillMaxSize(),
                                    state = updatedState,
                                    forceStopEditMode = showLockScreen,
                                    bottom = {  }
                                )
                                is TimedDurationSet -> TimedDurationSetScreen(
                                    modifier = Modifier.fillMaxSize(),
                                    state = updatedState,
                                    onTimerEnd = {
                                        viewModel.storeExecutedSetHistory(updatedState)
                                        viewModel.goToNextState()
                                    },
                                    bottom = {  }
                                )
                                is EnduranceSet -> EnduranceSetScreen(
                                    modifier = Modifier.fillMaxSize(),
                                    state = updatedState,
                                    onTimerEnd = {
                                        viewModel.storeExecutedSetHistory(updatedState)
                                        viewModel.goToNextState()
                                    },
                                    bottom = {  }
                                )
                            }
                        }
                        2 -> {
                            Box(modifier = Modifier
                                .fillMaxSize()
                                .padding(0.dp, 10.dp, 0.dp, 0.dp)){
                                Text(
                                    modifier = Modifier.fillMaxSize(),
                                    text = "Previous Set",
                                    style = MaterialTheme.typography.body1,
                                    textAlign = TextAlign.Center
                                )
                                Column(modifier = Modifier.padding(40.dp,25.dp,40.dp,0.dp),verticalArrangement = Arrangement.Top, horizontalAlignment = Alignment.End){
                                    if(updatedState.hasNoHistory){
                                        notAvailableTextComposable()
                                    }else {
                                        when(updatedState.set){
                                            is WeightSet -> WeightSetDataViewer(
                                                updatedState.previousSetData as WeightSetData
                                            )
                                            is BodyWeightSet -> BodyWeightSetDataViewer(
                                                updatedState.previousSetData as BodyWeightSetData
                                            )
                                            is TimedDurationSet -> notAvailableTextComposable()
                                            is EnduranceSet -> notAvailableTextComposable()
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

    /*
    LockScreen(
        show = showLockScreen,
        onUnlock = {
            onScreenUnlocked()
            startTouchTimer()
            showLockScreen = false
        }
    )
    */

    CustomDialog(
        show = showConfirmDialog,
        title = "Complete exercise",
        message = "Do you want to save this data?",
        handleYesClick = {
            VibrateOnce(context)
            viewModel.storeExecutedSetHistory(state)
            viewModel.goToNextState()
            showConfirmDialog=false
        },
        handleNoClick = {
            VibrateOnce(context)
            showConfirmDialog = false
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showConfirmDialog = false
        }
    )

    CustomDialog(
        show = showSkipDialog,
        title = "Skip exercise",
        message = "Do you want to skip this exercise?",
        handleYesClick = {
            VibrateOnce(context)
            viewModel.storeExecutedSetHistory(state)
            viewModel.goToNextState()
            showSkipDialog = false
        },
        handleNoClick = {
            VibrateOnce(context)
            showSkipDialog = false
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showSkipDialog = false
        }
    )

    CustomDialog(
        show = showGoBackDialog,
        title = "Go to previous set",
        message = "Do you want to go back?",
        handleYesClick = {
            VibrateOnce(context)
            viewModel.goToPreviousSet()
            showGoBackDialog = false
        },
        handleNoClick = {
            VibrateOnce(context)
            showGoBackDialog = false
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showGoBackDialog = false
        }
    )
}
