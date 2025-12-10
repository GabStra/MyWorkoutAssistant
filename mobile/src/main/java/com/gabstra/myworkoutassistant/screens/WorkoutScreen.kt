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
    val workoutState by workoutViewModel.workoutState.collectAsState()
    val selectedWorkout by workoutViewModel.selectedWorkout

    var showWorkoutInProgressDialog by remember { mutableStateOf(false) }
    val isCustomDialogOpen by workoutViewModel.isCustomDialogOpen.collectAsState()

    BackHandler(true) {
        if (isCustomDialogOpen || showWorkoutInProgressDialog) return@BackHandler

        showWorkoutInProgressDialog = true
        workoutViewModel.pauseWorkout()
        workoutViewModel.lightScreenUp()
    }

    val enableDimming by workoutViewModel.enableDimming
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
                    colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent),
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


            AnimatedContent(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(it)
                    .padding(10.dp),
                targetState = workoutState,
                transitionSpec = {
                    fadeIn(animationSpec = tween(500)) togetherWith fadeOut(
                        animationSpec = tween(
                            500
                        )
                    )
                }, label = "",
                contentAlignment = Alignment.Center
            ) { updatedWorkoutState ->
                when (updatedWorkoutState) {
                    is WorkoutState.Preparing -> {
                        var currentMillis by remember { mutableIntStateOf(0) }
                        var hasTriggeredNextState by remember { mutableStateOf(false) }

                        LaunchedEffect(Unit) {
                            while (true) {
                                delay(1000)
                                currentMillis += 1000
                            }
                        }

                        LaunchedEffect(updatedWorkoutState.dataLoaded, currentMillis) {
                            if (hasTriggeredNextState) {
                                return@LaunchedEffect
                            }

                            val isReady =
                                updatedWorkoutState.dataLoaded && currentMillis >= 3000

                            if (isReady) {
                                hasTriggeredNextState = true

                                workoutViewModel.lightScreenUp()
                                workoutViewModel.goToNextState()
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
                            updatedWorkoutState,
                            hearthRateChart = { }
                        )
                    }

                    is WorkoutState.Rest -> {
                        RestScreen(
                            workoutViewModel,
                            hapticsViewModel,
                            updatedWorkoutState,
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
                            updatedWorkoutState,
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