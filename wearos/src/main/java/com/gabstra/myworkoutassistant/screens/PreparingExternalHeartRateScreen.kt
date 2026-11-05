package com.gabstra.myworkoutassistant.screens

import androidx.activity.compose.BackHandler
import com.gabstra.myworkoutassistant.presentation.theme.tertiaryContent
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
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
import com.gabstra.myworkoutassistant.composables.FullScreenLoadingIndicator
import com.gabstra.myworkoutassistant.composables.WearPrimaryButton
import com.gabstra.myworkoutassistant.composables.rememberWearCoroutineScope
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.ExternalHeartRateConnectionState
import com.gabstra.myworkoutassistant.data.ExternalHeartRateDeviceController
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

private const val EXTERNAL_HR_SKIP_DELAY_MS = 30_000

/** Fixed slot so a longer/shorter status never moves the spinner or the buttons. */
private val STATUS_LINE_HEIGHT = 66.dp

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
    val isSessionHydrationInFlight by viewModel.isSessionHydrationInFlightFlow.collectAsState()
    val connectionState by externalHeartRateController.connectionState.collectAsState()
    val source = selectedWorkout.heartRateSource
    val scope = rememberWearCoroutineScope()
    val context = LocalContext.current

    var currentMillis by remember { mutableIntStateOf(0) }
    var hasTriggeredNextState by remember { mutableStateOf(false) }
    val isStreaming = connectionState is ExternalHeartRateConnectionState.Streaming
    // Skip stays available whenever no heart-rate samples are arriving; the controller reports
    // Connected as soon as GATT subscribes, which alone doesn't mean the strap is sending data.
    val canSkip = !isStreaming && (
        currentMillis >= EXTERNAL_HR_SKIP_DELAY_MS ||
            connectionState is ExternalHeartRateConnectionState.Error ||
            connectionState is ExternalHeartRateConnectionState.MissingConfiguration
        )

    LaunchedEffect(source) {
        // Wait for any in-flight session hydration, but don't re-initialise when the hydration
        // flag flips: that reset the controller and silently cleared the user's Skip.
        snapshotFlow { isSessionHydrationInFlight }.first { !it }
        currentMillis = 0
        val config = viewModel.getExternalHeartRateConfig(source)
        externalHeartRateController.initialize(context, config)
        externalHeartRateController.connectToDevice()

        scope.launch {
            while (true) {
                delay(1000)
                currentMillis += 1000
                if (currentMillis >= EXTERNAL_HR_SKIP_DELAY_MS) {
                    break
                }
            }
        }
    }

    LaunchedEffect(
        connectionState,
        state.dataLoaded,
        currentMillis,
        hasWorkoutRecord,
        hasTriggeredNextState,
        isSessionHydrationInFlight
    ) {
        if (hasTriggeredNextState || isSessionHydrationInFlight) return@LaunchedEffect

        val isReady = isStreaming && state.dataLoaded && currentMillis >= 3000
        if (isReady) {
            if (!viewModel.isCurrentPreparingState(state)) {
                hasTriggeredNextState = true
                return@LaunchedEffect
            }
            hasTriggeredNextState = true
            viewModel.lightScreenUp()
            if (hasWorkoutRecord) {
                if (viewModel.consumeSkipNextResumeLastState()) {
                    viewModel.finishPreparedResume()
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
        ExternalHeartRateConnectionState.Idle -> "Preparing ${source.displayName()}"
    }.trimEnd('.')

    if (!canSkip || isStreaming) {
        // One stable line while connecting: the per-state messages flashed through
        // scanning/connecting/connected in well under a second on a fast link. Errors and
        // the skip hint still appear in the buttons view below.
        FullScreenLoadingIndicator(text = "Preparing ${source.displayName()}")
        return
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
                // Single status line in a fixed-height slot: no duplicate header, and the
                // buttons below stay put while the message changes length.
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .transformedHeight(this, spec)
                        .height(STATUS_LINE_HEIGHT),
                    contentAlignment = Alignment.Center
                ) {
                    StatusText(statusMessage)
                }
            }
            item {
                WearPrimaryButton(
                        modifier = Modifier
                            .fillMaxWidth()
                            .transformedHeight(this, spec),
                        transformation = SurfaceTransformation(spec),
                        text = "Skip",
                        onClick = {
                            if (hasTriggeredNextState || isSessionHydrationInFlight) {
                                return@WearPrimaryButton
                            }
                            hasTriggeredNextState = true
                            externalHeartRateController.skipConnectionForSession()
                            hapticsViewModel.doGentleVibration()

                            if (hasWorkoutRecord) {
                                if (viewModel.consumeSkipNextResumeLastState()) {
                                    viewModel.finishPreparedResume()
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

@Composable
private fun StatusText(message: String) {
    Text(
        modifier = Modifier.fillMaxWidth(),
        text = message,
        style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.tertiaryContent,
        textAlign = TextAlign.Center,
        maxLines = 3,
        overflow = TextOverflow.Ellipsis,
    )
}
