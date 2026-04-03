package com.gabstra.myworkoutassistant.screens

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.CircularProgressIndicator
import androidx.wear.compose.material3.ListHeader
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.ScrollIndicator
import androidx.wear.compose.material3.ScrollIndicatorDefaults
import androidx.wear.compose.material3.SurfaceTransformation
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.lazy.ResponsiveTransformationSpec
import androidx.wear.compose.material3.lazy.TransformationVariableSpec
import androidx.wear.compose.material3.lazy.rememberTransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import com.gabstra.myworkoutassistant.composables.ButtonWithText
import com.gabstra.myworkoutassistant.composables.LoadingText
import com.gabstra.myworkoutassistant.composables.WearPrimaryButton
import com.gabstra.myworkoutassistant.composables.rememberWearCoroutineScope
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.ExternalHeartRateConnectionState
import com.gabstra.myworkoutassistant.data.ExternalHeartRateDeviceController
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.isReady
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private const val EXTERNAL_HR_SKIP_DELAY_MS = 30_000

@Composable
fun PreparingExternalHeartRateScreen(
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    navController: NavController,
    externalHeartRateController: ExternalHeartRateDeviceController,
    state: WorkoutState.Preparing,
    onReady: () -> Unit = {},
) {
    BackHandler(true) {
        // Do nothing while the chooser is visible.
    }

    val selectedWorkout by viewModel.selectedWorkout
    val hasWorkoutRecord by viewModel.hasWorkoutRecord.collectAsState()
    val connectionState by externalHeartRateController.connectionState.collectAsState()
    val source = selectedWorkout.heartRateSource
    val scope = rememberWearCoroutineScope()
    val context = LocalContext.current

    var currentMillis by remember { mutableIntStateOf(0) }
    var canSkip by remember { mutableStateOf(false) }
    var hasTriggeredNextState by remember { mutableStateOf(false) }

    LaunchedEffect(source) {
        val config = viewModel.getExternalHeartRateConfig(source)
        externalHeartRateController.initialize(context, config)
        externalHeartRateController.connectToDevice()

        scope.launch {
            while (true) {
                delay(1000)
                currentMillis += 1000
                if (currentMillis >= EXTERNAL_HR_SKIP_DELAY_MS && !hasTriggeredNextState && !connectionState.isReady) {
                    canSkip = true
                    break
                }
            }
        }
    }

    LaunchedEffect(connectionState, state.dataLoaded, currentMillis, hasWorkoutRecord, hasTriggeredNextState) {
        if (hasTriggeredNextState) return@LaunchedEffect

        val isReady = connectionState.isReady && state.dataLoaded && currentMillis >= 3000
        if (isReady) {
            hasTriggeredNextState = true
            viewModel.lightScreenUp()
            if (hasWorkoutRecord) {
                if (viewModel.consumeSkipNextResumeLastState()) {
                    viewModel.resumeWorkout()
                } else {
                    viewModel.resumeLastState()
                }
            } else {
                viewModel.setWorkoutStart()
            }
            onReady()
        }
    }

    val statusMessage = when (connectionState) {
        is ExternalHeartRateConnectionState.Connecting ->
            (connectionState as ExternalHeartRateConnectionState.Connecting).message
        is ExternalHeartRateConnectionState.Connected ->
            (connectionState as ExternalHeartRateConnectionState.Connected).message
        is ExternalHeartRateConnectionState.Streaming ->
            (connectionState as ExternalHeartRateConnectionState.Streaming).message
        is ExternalHeartRateConnectionState.MissingConfiguration ->
            (connectionState as ExternalHeartRateConnectionState.MissingConfiguration).message
        is ExternalHeartRateConnectionState.Error ->
            (connectionState as ExternalHeartRateConnectionState.Error).message
        is ExternalHeartRateConnectionState.Skipped ->
            (connectionState as ExternalHeartRateConnectionState.Skipped).message
        ExternalHeartRateConnectionState.Idle -> "Preparing ${source.displayName()}..."
    }

    val transformingLazyColumnState = rememberTransformingLazyColumnState()
    val spec = rememberTransformationSpec(
        ResponsiveTransformationSpec.smallScreen(
            containerAlpha = TransformationVariableSpec(1f),
            contentAlpha = TransformationVariableSpec(1f),
            scale = TransformationVariableSpec(0.75f)
        ),
        ResponsiveTransformationSpec.largeScreen(
            containerAlpha = TransformationVariableSpec(1f),
            contentAlpha = TransformationVariableSpec(1f),
            scale = TransformationVariableSpec(0.6f)
        )
    )

    ScreenScaffold(
        scrollState = transformingLazyColumnState,
        scrollIndicator = {
            ScrollIndicator(
                state = transformingLazyColumnState,
                colors = ScrollIndicatorDefaults.colors(
                    indicatorColor = MaterialTheme.colorScheme.onBackground,
                    trackColor = MediumDarkGray
                )
            )
        }
    ) { contentPadding ->
        TransformingLazyColumn(
            contentPadding = contentPadding,
            state = transformingLazyColumnState,
        ) {
            item {
                ListHeader(
                    modifier = Modifier
                        .fillMaxWidth()
                        .transformedHeight(this, spec),
                    transformation = SurfaceTransformation(spec)
                ) {
                    Text(
                        modifier = Modifier.fillMaxWidth(),
                        text = "Getting your ${source.displayName()} ready",
                        style = MaterialTheme.typography.titleMedium,
                        textAlign = TextAlign.Center
                    )
                }
            }

            if (!canSkip || connectionState.isReady) {
                item {
                    Column(
                        modifier = Modifier.fillMaxWidth(),
                        verticalArrangement = Arrangement.Center,
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        CircularProgressIndicator()
                        Spacer(Modifier.height(8.dp))
                        LoadingText(baseText = "Connecting")
                        Spacer(Modifier.height(8.dp))
                        Text(
                            modifier = Modifier.fillMaxWidth(),
                            text = statusMessage,
                            style = MaterialTheme.typography.bodySmall,
                            textAlign = TextAlign.Center
                        )
                    }
                }
            } else {
                item {
                    Text(
                        modifier = Modifier
                            .fillMaxWidth()
                            .transformedHeight(this, spec),
                        text = statusMessage,
                        style = MaterialTheme.typography.bodySmall,
                        textAlign = TextAlign.Center
                    )
                }
                item {
                    WearPrimaryButton(
                        modifier = Modifier
                            .fillMaxWidth()
                            .transformedHeight(this, spec),
                        transformation = SurfaceTransformation(spec),
                        text = "Skip",
                        onClick = {
                            if (hasTriggeredNextState) return@WearPrimaryButton
                            hasTriggeredNextState = true
                            externalHeartRateController.skipConnectionForSession()
                            hapticsViewModel.doGentleVibration()

                            if (hasWorkoutRecord) {
                                if (viewModel.consumeSkipNextResumeLastState()) {
                                    viewModel.resumeWorkout()
                                } else {
                                    viewModel.resumeLastState()
                                }
                            } else {
                                viewModel.setWorkoutStart()
                            }

                            viewModel.lightScreenUp()
                            onReady()
                        },
                    )
                }
                item {
                    ButtonWithText(
                        modifier = Modifier
                            .fillMaxWidth()
                            .transformedHeight(this, spec),
                        transformation = SurfaceTransformation(spec),
                        text = "Back",
                        onClick = {
                            if (hasTriggeredNextState) return@ButtonWithText
                            hapticsViewModel.doGentleVibration()
                            externalHeartRateController.disconnectFromDevice()
                            navController.navigate(Screen.WorkoutSelection.route) {
                                popUpTo(0) { inclusive = true }
                            }
                        }
                    )
                }
            }
        }
    }
}
