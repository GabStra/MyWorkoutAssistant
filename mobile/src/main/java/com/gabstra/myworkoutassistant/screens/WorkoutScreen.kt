package com.gabstra.myworkoutassistant.screens

import android.content.Context
import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.edit
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.workout.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.workout.ExerciseScreen
import com.gabstra.myworkoutassistant.workout.KeepOn
import com.gabstra.myworkoutassistant.workout.LoadingText
import com.gabstra.myworkoutassistant.workout.RestScreen
import com.gabstra.myworkoutassistant.workout.WorkoutCompleteScreen
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.delay

@OptIn(ExperimentalCoroutinesApi::class, ExperimentalMaterial3Api::class)
@Composable
fun WorkoutScreen(
    appViewModel: AppViewModel,
    workoutViewModel: WorkoutViewModel,
    hapticsViewModel: HapticsViewModel
)
{
    val context = LocalContext.current
    val screenState by workoutViewModel.screenState.collectAsState()
    val workoutState = screenState.workoutState
    val selectedWorkout = screenState.selectedWorkout
    val isPaused = screenState.isPaused
    val hasWorkoutRecord = screenState.hasWorkoutRecord
    
    // Fix: If WorkoutScreen is shown but there's no workout record and flag is stale, navigate back
    LaunchedEffect(hasWorkoutRecord) {
        val prefs = context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
        val isWorkoutInProgress = prefs.getBoolean("isWorkoutInProgress", false)
        if (isWorkoutInProgress && !hasWorkoutRecord) {
            prefs.edit { putBoolean("isWorkoutInProgress", false) }
            appViewModel.goBack()
        }
    }

    var showWorkoutInProgressDialog by remember { mutableStateOf(false) }
    val isCustomDialogOpen = screenState.isCustomDialogOpen

    BackHandler(true) {
        if (isCustomDialogOpen || showWorkoutInProgressDialog) return@BackHandler

        showWorkoutInProgressDialog = true
        workoutViewModel.pauseWorkout()
        workoutViewModel.lightScreenUp()
    }

    val enableDimming = screenState.enableDimming
    val outlineVariant = MaterialTheme.colorScheme.outlineVariant
    KeepOn(workoutViewModel,enableDimming = enableDimming) {
        Scaffold(
            topBar = {
                TopAppBar(
                    modifier = Modifier.drawBehind {
                        drawLine(
                            color = outlineVariant,
                            start = Offset(0f, size.height),
                            end = Offset(size.width, size.height),
                            strokeWidth = 1.dp.toPx()
                        )
                    },
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = Color.Transparent,
                        navigationIconContentColor = MaterialTheme.colorScheme.onBackground,
                        actionIconContentColor = MaterialTheme.colorScheme.onBackground
                    ),
                    title = {
                        Text(
                            modifier = Modifier
                                .fillMaxWidth()
                                .basicMarquee(iterations = Int.MAX_VALUE),
                            textAlign = TextAlign.Center,
                            text = selectedWorkout.name,
                            color = MaterialTheme.colorScheme.onBackground,
                        )
                    },
                    navigationIcon = {
                        IconButton(onClick = {
                            if (isCustomDialogOpen) return@IconButton

                            showWorkoutInProgressDialog = true
                            workoutViewModel.pauseWorkout()
                            workoutViewModel.lightScreenUp()
                        }) {
                            Icon(
                                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                                contentDescription = "Back"
                            )
                        }
                    },
                    actions = {
                        IconButton(modifier = Modifier.alpha(0f), onClick = {}) {
                            Icon(
                                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                                contentDescription = "Back"
                            )
                        }
                    }
                )
            }
        ) { it ->
            val stateTypeKey = remember(workoutState) {
                when (workoutState) {
                    is WorkoutState.Preparing -> "Preparing"
                    is WorkoutState.Set -> "Set"
                    is WorkoutState.Rest -> "Rest"
                    is WorkoutState.Completed -> "Completed"
                    is WorkoutState.CalibrationLoadSelection -> "CalibrationLoadSelection"
                    is WorkoutState.CalibrationRIRSelection -> "CalibrationRIRSelection"
                }
            }

            @Suppress("UnusedContentLambdaTargetStateParameter")
            AnimatedContent(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(it)
                    .padding(10.dp),
                targetState = stateTypeKey,
                transitionSpec = {
                    fadeIn(animationSpec = tween(500)) togetherWith fadeOut(
                        animationSpec = tween(
                            500
                        )
                    )
                }, label = "",
                contentAlignment = Alignment.Center
            ) { _ ->
                when (val state = workoutState) {
                    is WorkoutState.CalibrationLoadSelection -> {
                        // CalibrationLoadSelection is handled in wearos only
                        // Mobile version doesn't support calibration flow
                        Box(modifier = Modifier.fillMaxSize())
                    }
                    is WorkoutState.CalibrationRIRSelection -> {
                        // CalibrationRIRSelection is handled in wearos only
                        // Mobile version doesn't support calibration flow
                        Box(modifier = Modifier.fillMaxSize())
                    }
                    is WorkoutState.Preparing -> {
                        var currentMillis by remember { mutableIntStateOf(0) }
                        var hasTriggeredNextState by remember { mutableStateOf(false) }

                        LaunchedEffect(Unit) {
                            while (true) {
                                delay(1000)
                                currentMillis += 1000
                            }
                        }

                        LaunchedEffect(state.dataLoaded, currentMillis, isPaused, showWorkoutInProgressDialog) {
                            if (hasTriggeredNextState) {
                                return@LaunchedEffect
                            }

                            val isReady =
                                state.dataLoaded && currentMillis >= 3000

                            // Check if workout was explicitly started before auto-progressing
                            val prefs = context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
                            val isWorkoutInProgress = prefs.getBoolean("isWorkoutInProgress", false)

                            // Only auto-start if workout was explicitly started (isWorkoutInProgress is true)
                            // AND there's a workout record (to prevent auto-start from stale flags)
                            // and workout is not paused and exit dialog is not shown
                            if (isReady && isWorkoutInProgress && hasWorkoutRecord && !isPaused && !showWorkoutInProgressDialog) {
                                hasTriggeredNextState = true

                                workoutViewModel.lightScreenUp()
                                workoutViewModel.setWorkoutStart()
                            }
                        }

                        Box(
                            modifier = Modifier
                                .fillMaxSize(),
                            contentAlignment = Alignment.Center
                        ) {
                            LoadingText("Starting workout",MaterialTheme.typography.bodyLarge)
                        }
                    }

                    is WorkoutState.Set -> {
                        ExerciseScreen(
                            workoutViewModel,
                            hapticsViewModel,
                            state,
                            hearthRateChart = { }
                        )
                    }

                    is WorkoutState.Rest -> {
                        RestScreen(
                            workoutViewModel,
                            hapticsViewModel,
                            state,
                            { },
                            onTimerEnd = {
                                workoutViewModel.storeSetData()
                                workoutViewModel.pushAndStoreWorkoutData(false, context) {
                                    workoutViewModel.goToNextState()
                                    workoutViewModel.lightScreenUp()
                                }
                            }
                        )
                    }

                    is WorkoutState.Completed -> {
                        WorkoutCompleteScreen(
                            appViewModel,
                            workoutViewModel,
                            state,
                            hapticsViewModel
                        )
                    }
                }
            }
        }
        CustomDialogYesOnLongPress(
            show = showWorkoutInProgressDialog,
            title = "Workout in progress",
            handleYesClick = {
                hapticsViewModel.doGentleVibration()

                val prefs = context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
                prefs.edit { putBoolean("isWorkoutInProgress", false) }

                appViewModel.goBack()
                appViewModel.triggerUpdate()

                showWorkoutInProgressDialog = false
            },
            handleNoClick = {
                hapticsViewModel.doGentleVibration()
                showWorkoutInProgressDialog = false
                workoutViewModel.resumeWorkout()
            },
            closeTimerInMillis = 5000,
            handleOnAutomaticClose = {
                showWorkoutInProgressDialog = false
                workoutViewModel.resumeWorkout()
            },
            holdTimeInMillis = 1000,
            onVisibilityChange = { isVisible ->
                if (isVisible) {
                    workoutViewModel.setDimming(false)
                } else {
                    workoutViewModel.reEvaluateDimmingForCurrentState()
                }
            }
        )
    }
}

