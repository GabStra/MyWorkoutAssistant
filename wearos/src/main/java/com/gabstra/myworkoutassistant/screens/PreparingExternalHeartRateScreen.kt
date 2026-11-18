package com.gabstra.myworkoutassistant.screens

import androidx.activity.compose.BackHandler
import com.gabstra.myworkoutassistant.presentation.theme.tertiaryContent
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
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
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.ExternalHeartRateConnectionState
import com.gabstra.myworkoutassistant.data.ExternalHeartRateDeviceController
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.HeartRateSource
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

private const val EXTERNAL_HR_SKIP_DELAY_MS = 30_000

/** Minimum slot height keeps the status compact while allowing larger type to wrap. */
private val STATUS_LINE_HEIGHT = 66.dp

@Composable
fun PreparingExternalHeartRateScreen(
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    navController: NavController,
    externalHeartRateControllers: List<ExternalHeartRateDeviceController>,
    hrViewModel: SensorDataViewModel,
    state: WorkoutState.Preparing,
    onReady: () -> Unit = {},
) {
    BackHandler(true) {
        // Do nothing while the chooser is visible.
    }

    val selectedWorkout by viewModel.selectedWorkout
    val hasWorkoutRecord by viewModel.hasWorkoutRecord.collectAsState()
    val isSessionHydrationInFlight by viewModel.isSessionHydrationInFlightFlow.collectAsState()
    val connectionStates = externalHeartRateControllers.map {
        it.connectionState.collectAsState()
    }
    val watchHeartRateSamples by hrViewModel.heartRateSampleCount.collectAsState()
    val watchEnabled = HeartRateSource.WATCH_SENSOR in selectedWorkout.enabledHeartRateSources
    val scope = rememberWearCoroutineScope()
    val context = LocalContext.current

    var currentMillis by remember { mutableIntStateOf(0) }
    var hasTriggeredNextState by remember { mutableStateOf(false) }
    val pendingIndices = externalHeartRateControllers.indices.filter {
        connectionStates[it].value !is ExternalHeartRateConnectionState.Streaming
    }
    val isStreaming = pendingIndices.isEmpty()
    // Each enabled strap plus (when enabled) the watch must be live before starting.
    val watchHeartRateReady = !watchEnabled ||
        isWatchHeartRateReady(watchHeartRateSamples, currentMillis)
    // Skip stays available whenever some heart-rate samples are not arriving; a controller
    // reports Connected as soon as GATT subscribes, which alone doesn't mean it is sending data.
    val hasBlockingError = pendingIndices.any { index ->
        val state = connectionStates[index].value
        state is ExternalHeartRateConnectionState.Error ||
            state is ExternalHeartRateConnectionState.MissingConfiguration
    }
    val canSkip = !isStreaming && (
        currentMillis >= EXTERNAL_HR_SKIP_DELAY_MS || hasBlockingError
        )

    LaunchedEffect(externalHeartRateControllers) {
        // Wait for any in-flight session hydration, but don't re-initialise when the hydration
        // flag flips: that reset the controller and silently cleared the user's Skip.
        snapshotFlow { isSessionHydrationInFlight }.first { !it }
        currentMillis = 0
        externalHeartRateControllers.forEach { controller ->
            // A link still streaming from the previous session is healthy: keep it instead of
            // tearing it down and making resume wait for a full reconnect.
            if (controller.connectionState.value !is ExternalHeartRateConnectionState.Streaming) {
                controller.initialize(context, viewModel.getExternalHeartRateConfig(controller.source))
                controller.connectToDevice()
            }
        }

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
        connectionStates.map { it.value },
        state.dataLoaded,
        currentMillis,
        hasWorkoutRecord,
        hasTriggeredNextState,
        isSessionHydrationInFlight,
        watchHeartRateSamples,
    ) {
        if (hasTriggeredNextState || isSessionHydrationInFlight) return@LaunchedEffect

        val isReady = isStreaming && watchHeartRateReady && state.dataLoaded && currentMillis >= 3000
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

    val pendingName = pendingIndices.firstOrNull()?.let {
        externalHeartRateControllers[it].source.displayName()
    }
    val loadingText = when {
        isStreaming && !watchHeartRateReady -> stringResource(R.string.wear_checking_heart_rate)
        isStreaming -> stringResource(R.string.wear_getting_workout_ready)
        pendingName != null -> stringResource(R.string.wear_connecting_to_device, pendingName)
        else -> stringResource(R.string.wear_connecting_to_sensor)
    }
    PreparingHeartRateContent(
        canSkip = canSkip,
        loadingText = loadingText,
        needsSensorSetup = pendingIndices.any {
            connectionStates[it].value is ExternalHeartRateConnectionState.MissingConfiguration
        },
        onSkip = skip@{
            if (hasTriggeredNextState || isSessionHydrationInFlight) {
                return@skip
            }
            hasTriggeredNextState = true
            externalHeartRateControllers.forEach { it.skipConnectionForSession() }
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
        onBack = back@{
            if (hasTriggeredNextState) return@back
            hapticsViewModel.doGentleVibration()
            externalHeartRateControllers.forEach { it.disconnectFromDevice() }
            navController.navigate(Screen.WorkoutSelection.route) {
                popUpTo(0) { inclusive = true }
            }
        },
    )
}

@Composable
internal fun PreparingHeartRateContent(
    canSkip: Boolean,
    loadingText: String,
    needsSensorSetup: Boolean = false,
    onSkip: () -> Unit,
    onBack: () -> Unit,
) {
    var connectionHelp by remember { mutableStateOf<String?>(null) }
    val sensorSetupMessage = stringResource(R.string.wear_hr_sensor_setup_help)
    val noSignalMessage = stringResource(R.string.wear_hr_no_signal_help)
    LaunchedEffect(canSkip, needsSensorSetup) {
        // Once a choice is offered, retry callbacks must not replace it or move its controls.
        if (canSkip && connectionHelp == null) {
            connectionHelp = if (needsSensorSetup) {
                sensorSetupMessage
            } else {
                noSignalMessage
            }
        }
    }
    val message = connectionHelp
    if (message == null) {
        FullScreenLoadingIndicator(text = loadingText)
    } else {
        ExternalHeartRateConnectionFallback(message, onSkip, onBack)
    }
}

@Composable
internal fun ExternalHeartRateConnectionFallback(
    statusMessage: String,
    onSkip: () -> Unit,
    onBack: () -> Unit,
) {
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
            modifier = Modifier.padding(horizontal = 20.dp),
            contentPadding = contentPadding,
            state = transformingLazyColumnState,
        ) {
            item {
                // Reserve room for short statuses; longer errors can wrap and scroll in full.
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .transformedHeight(this, spec)
                        .heightIn(min = STATUS_LINE_HEIGHT),
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
                    text = stringResource(R.string.wear_skip),
                    onClick = onSkip,
                )
            }
            item {
                ButtonWithText(
                    modifier = Modifier
                        .fillMaxWidth()
                        .transformedHeight(this, spec),
                    transformation = SurfaceTransformation(spec),
                    text = stringResource(R.string.wear_back),
                    onClick = onBack,
                )
            }
        }
    }
}

@Composable
private fun StatusText(message: String) {
    Text(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 7.5.dp),
        text = message,
        style = MaterialTheme.typography.bodyLarge,
        color = MaterialTheme.colorScheme.tertiaryContent,
        textAlign = TextAlign.Center,
    )
}
