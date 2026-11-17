package com.gabstra.myworkoutassistant.composables.workout.pages

import android.content.Intent
import com.gabstra.myworkoutassistant.composables.*
import com.gabstra.myworkoutassistant.presentation.theme.tertiaryContent

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
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
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.platform.LocalLocale
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnState
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
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.cancelWorkoutInProgressNotification
import com.gabstra.myworkoutassistant.shared.DarkOrange
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.MediumLightGray
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureDetailLevel
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSampleRate
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.sets.WeightedEffortSet
import com.gabstra.myworkoutassistant.shared.workout.model.WATCH_SESSION_STATE_RETURNED_HOME
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import kotlinx.coroutines.launch


@Composable
fun ControlsPage(
    updatedState: WorkoutState.Set,
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    navController: NavController,
    onBeforeGoHome: (() -> Unit)? = null,
    canChangeEquipment: Boolean = false,
    onChangeEquipmentClick: () -> Unit = {}
) {
    val isInspectionMode = LocalInspectionMode.current
    val isHistoryEmpty by viewModel.isHistoryEmpty.collectAsState()
    val screenState by viewModel.screenState.collectAsState()
    val motionCapture by viewModel.motionCaptureUiState.collectAsState()
    val currentWorkoutState = screenState.workoutState

    val context = LocalContext.current
    val scope = rememberWearCoroutineScope()

    val controlsPageDescription = stringResource(R.string.page_controls_cd)
    val startWithActionDescription = stringResource(R.string.page_controls_cd_start_with_action)
    val setOrderActionDescription = stringResource(R.string.page_controls_cd_set_order_action)
    val skipExerciseActionDescription = stringResource(R.string.page_controls_cd_skip_exercise_action)

    var showGoBackDialog by remember { mutableStateOf(false) }
    var showSkipExerciseDialog by remember { mutableStateOf(false) }
    var showStartWithDialog by remember { mutableStateOf(false) }
    // Order picker state: null = closed; non-null = positions chosen so far while
    // building the full member order.
    var orderBuilder by remember { mutableStateOf<List<Int>?>(null) }
    var showFinishEarlyDialog by remember { mutableStateOf(false) }
    var shouldResumeTimerAfterSkipDialog by remember { mutableStateOf(false) }
    var shouldResumeTimerAfterFinishEarlyDialog by remember { mutableStateOf(false) }

    val exercise = viewModel.exercisesById[updatedState.exerciseId]!!
    val exerciseSets = exercise.sets

    val setIndex = exerciseSets.indexOfFirst { it.id == updatedState.set.id }
    val isLastSet = setIndex == exerciseSets.size - 1

    val isMovementSet = updatedState.set is WeightSet || updatedState.set is BodyWeightSet || updatedState.set is WeightedEffortSet
    val isActiveSetPage =
        currentWorkoutState is WorkoutState.Set &&
            currentWorkoutState.exerciseId == updatedState.exerciseId &&
            currentWorkoutState.set.id == updatedState.set.id
    val nextWorkoutState by viewModel.nextWorkoutState.collectAsState()
    val cadenceSuperset = viewModel.getCurrentSupersetId()?.let { supersetId ->
        viewModel.selectedWorkout.value.workoutComponents
            .filterIsInstance<Superset>()
            .firstOrNull { it.id == supersetId }
    }
    val cadenceRotationOrder = cadenceSuperset?.let { viewModel.getSupersetRotationOrder(it.id) }.orEmpty()
    val cadenceStartName = cadenceSuperset?.exercises?.getOrNull(
        cadenceRotationOrder.firstOrNull() ?: 0
    )?.name.orEmpty()
    val memberCount = cadenceSuperset?.exercises?.size ?: 0
    val canChooseStartMember = cadenceSuperset != null && viewModel.canChooseSupersetStartMember()
    val scrollState = rememberScrollState()
    val showNavigationSection = !isHistoryEmpty || isActiveSetPage
    val showExerciseSection =
        (isMovementSet &&
            (exercise.exerciseType == ExerciseType.WEIGHT ||
                exercise.exerciseType == ExerciseType.BODY_WEIGHT) &&
            canChangeEquipment) ||
            (isMovementSet && isLastSet) ||
            isMovementSet

    LaunchedEffect(updatedState) {
        showGoBackDialog = false
        showSkipExerciseDialog = false
        showStartWithDialog = false
        orderBuilder = null
        showFinishEarlyDialog = false
        shouldResumeTimerAfterSkipDialog = false
        shouldResumeTimerAfterFinishEarlyDialog = false
        scrollState.scrollTo(0)
    }

    fun shouldPauseCurrentTimerForDialog(): Boolean {
        val currentSetState = currentWorkoutState as? WorkoutState.Set ?: return false
        return (currentSetState.set is TimedDurationSet || currentSetState.set is EnduranceSet) &&
            viewModel.workoutTimerService.isTimerRegistered(currentSetState.set.id)
    }

    fun pauseCurrentTimerForDialog() {
        if (shouldPauseCurrentTimerForDialog()) {
            viewModel.workoutTimerService.pauseTimer(updatedState.set.id)
        }
    }

    fun resumeCurrentTimerAfterDialog(shouldResume: Boolean) {
        if (
            shouldResume &&
            currentWorkoutState is WorkoutState.Set &&
            (currentWorkoutState.set is TimedDurationSet || currentWorkoutState.set is EnduranceSet) &&
            viewModel.workoutTimerService.isTimerRegistered(updatedState.set.id)
        ) {
            viewModel.workoutTimerService.resumeTimer(updatedState.set.id)
        }
    }

    val state: TransformingLazyColumnState = rememberTransformingLazyColumnState()
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
    val keepScreenOnOverride by viewModel.keepScreenOn

    ScreenScaffold(
        modifier = Modifier
            .fillMaxSize()
            .semantics { contentDescription = controlsPageDescription },
        scrollState = state,
        scrollIndicator = {
            ScrollIndicator(
                state = state,
                colors = ScrollIndicatorDefaults.colors(
                    indicatorColor = MaterialTheme.colorScheme.onBackground,
                    trackColor = MediumDarkGray
                )
            )
        }
    ) { _ ->
        TransformingLazyColumn(
            modifier = Modifier
                .padding(horizontal = 20.dp)
                .semantics { contentDescription = controlsPageDescription },
            contentPadding = WorkoutPagerPageSafeAreaPadding,
            state = state
        ) {
            if (showNavigationSection) {
                item {
                    ControlsPageSectionHeader(
                        text = stringResource(R.string.page_controls_section_navigation),
                        modifier = Modifier
                            .fillMaxWidth()
                            .then(
                                if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                    this,
                                    spec
                                )
                            )
                    )
                }
            }
            if (!isHistoryEmpty) {
                item {
                    ButtonWithText(
                        modifier = Modifier
                            .fillMaxWidth()
                            .then(
                                if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                    this,
                                    spec
                                )
                            ),
                        transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                        text = stringResource(R.string.page_controls_back),
                        onClick = {
                            hapticsViewModel.doGentleVibration()
                            // Handle go back for calibration flow:
                            // CalibrationRIRSelection → Set(isCalibrationSet) → CalibrationLoadSelection → previous non-Rest state
                            // Use undo() for CalibrationRIRSelection and Set(isCalibrationSet) to maintain proper state sequence
                            // Use goToPreviousNonRestState() for CalibrationLoadSelection to skip Rest states
                            when (currentWorkoutState) {
                                is WorkoutState.CalibrationRIRSelection -> {
                                    // Go back one step to calibration Set execution
                                    // undo() will move to Set(isCalibrationSet=true), calibration context updates to EXECUTING
                                    viewModel.undo()
                                    viewModel.lightScreenUp()
                                }

                                is WorkoutState.Set -> {
                                    if (currentWorkoutState.isCalibrationSet) {
                                        // Go back one step to CalibrationLoadSelection
                                        // undo() will move to CalibrationLoadSelection, calibration context updates to LOAD_SELECTION
                                        viewModel.undo()
                                        viewModel.lightScreenUp()
                                    } else {
                                        // Show dialog for non-calibration sets
                                        showGoBackDialog = true
                                    }
                                }

                                is WorkoutState.CalibrationLoadSelection -> {
                                    // Go back to previous non-Rest state (skipping Rest states)
                                    // This will typically be a Set from the previous exercise
                                    viewModel.goToPreviousNonRestStateWear()
                                    viewModel.lightScreenUp()
                                }

                                else -> {
                                    // Show dialog for other states
                                    showGoBackDialog = true
                                }
                            }
                        },
                        enabled = true,
                    )
                }
            }
            if (showNavigationSection && showExerciseSection) {
                item {
                    Spacer(modifier = Modifier.height(10.dp))
                }
            }
            if (showExerciseSection) {
                item {
                    ControlsPageSectionHeader(
                        text = stringResource(R.string.page_controls_section_exercise),
                        modifier = Modifier
                            .fillMaxWidth()
                            .then(
                                if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                    this,
                                    spec
                                )
                            )
                    )
                }
            }
            if (
                isMovementSet &&
                (exercise.exerciseType == ExerciseType.WEIGHT ||
                    exercise.exerciseType == ExerciseType.BODY_WEIGHT) &&
                canChangeEquipment
            ) {
                item {
                    ButtonWithText(
                        modifier = Modifier
                            .fillMaxWidth()
                            .then(
                                if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                    this,
                                    spec
                                )
                            ),
                        transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                        text = stringResource(R.string.page_controls_change_equipment),
                        onClick = {
                            hapticsViewModel.doGentleVibration()
                            onChangeEquipmentClick()
                        }
                    )
                }
            }
            if (isMovementSet && isLastSet) {
                item {
                    ButtonWithText(
                        modifier = Modifier
                            .fillMaxWidth()
                            .then(
                                if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                    this,
                                    spec
                                )
                            ),
                        transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                        text = stringResource(R.string.page_controls_add_rest_pause_set),
                        onClick = {
                            hapticsViewModel.doGentleVibration()
                            viewModel.storeSetData()
                            viewModel.pushAndStoreWorkoutData(false, context) {
                                viewModel.addNewRestPauseSet()
                            }
                        }
                    )
                }
            }
            if (isMovementSet) {
                item {
                    ButtonWithText(
                        modifier = Modifier
                            .fillMaxWidth()
                            .then(
                                if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                    this,
                                    spec
                                )
                            ),
                        transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                        text = stringResource(R.string.page_controls_add_set),
                        onClick = {
                            hapticsViewModel.doGentleVibration()
                            viewModel.storeSetData()
                            viewModel.pushAndStoreWorkoutData(false, context) {
                                viewModel.addNewSetStandard()
                            }
                        }
                    )
                }
            }
            if (showExerciseSection) {
                item {
                    Spacer(modifier = Modifier.height(10.dp))
                }
            }
            item {
                ControlsPageSectionHeader(
                    text = stringResource(R.string.page_controls_section_preferences),
                    modifier = Modifier
                        .fillMaxWidth()
                        .then(
                            if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                this,
                                spec
                            )
                        )
                )
            }
            item {
                val alertSoundEnabled = screenState.isAlertSoundEnabled
                val updateAlertSoundEnabled: (Boolean) -> Unit = { enabled ->
                    viewModel.setAlertSoundEnabled(enabled)
                    if (enabled) {
                        hapticsViewModel.doHardVibrationWithBeep()
                    } else {
                        hapticsViewModel.doGentleVibration()
                    }
                }

                WearTonalContentButton(
                    modifier = Modifier
                        .fillMaxWidth()
                        .then(
                            if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                this,
                                spec
                            )
                        ),
                    transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                    onClick = {
                        updateAlertSoundEnabled(!alertSoundEnabled)
                    }
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(5.dp)
                    ) {
                        Column(
                            modifier = Modifier.weight(1f),
                            verticalArrangement = Arrangement.spacedBy(2.5.dp)
                        ) {
                            Text(
                                text = stringResource(R.string.page_controls_alert_sound),
                                style = MaterialTheme.typography.bodyMedium,
                                textAlign = TextAlign.Start,
                            )
                            Text(
                                text = if (alertSoundEnabled) {
                                    stringResource(R.string.page_controls_alert_sound_on)
                                } else {
                                    stringResource(R.string.page_controls_alert_sound_off)
                                },
                                style = MaterialTheme.typography.bodySmall,
                                textAlign = TextAlign.Start,
                                color = MaterialTheme.colorScheme.tertiaryContent
                            )
                        }
                        Switch(
                            checked = alertSoundEnabled,
                            onCheckedChange = updateAlertSoundEnabled,
                            colors = SwitchDefaults.colors(
                                checkedThumbColor = MaterialTheme.colorScheme.onPrimary,
                                checkedTrackColor = MaterialTheme.colorScheme.primary,
                                checkedBorderColor = MaterialTheme.colorScheme.primary,
                                uncheckedThumbColor = MaterialTheme.colorScheme.onBackground,
                                uncheckedTrackColor = MediumLightGray,
                                uncheckedBorderColor = MaterialTheme.colorScheme.onBackground,
                            ),
                        )
                    }
                }
            }

            item {
                val calorieDisplayEnabled = viewModel.calorieDisplayEnabled.value
                val updateCalorieDisplayEnabled: (Boolean) -> Unit = { enabled ->
                    viewModel.setCalorieDisplayEnabled(enabled)
                    hapticsViewModel.doGentleVibration()
                }

                WearTonalContentButton(
                    modifier = Modifier
                        .fillMaxWidth()
                        .then(
                            if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                this,
                                spec
                            )
                        ),
                    transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                    onClick = {
                        updateCalorieDisplayEnabled(!calorieDisplayEnabled)
                    }
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(5.dp)
                    ) {
                        Column(
                            modifier = Modifier.weight(1f),
                            verticalArrangement = Arrangement.spacedBy(2.5.dp)
                        ) {
                            Text(
                                text = stringResource(R.string.page_controls_calories_timed_sets),
                                style = MaterialTheme.typography.bodyMedium,
                                textAlign = TextAlign.Start,
                            )
                            Text(
                                text = if (calorieDisplayEnabled) {
                                    stringResource(R.string.page_controls_calories_on)
                                } else {
                                    stringResource(R.string.page_controls_calories_off)
                                },
                                style = MaterialTheme.typography.bodySmall,
                                textAlign = TextAlign.Start,
                                color = MaterialTheme.colorScheme.tertiaryContent
                            )
                        }
                        Switch(
                            checked = calorieDisplayEnabled,
                            onCheckedChange = updateCalorieDisplayEnabled,
                            colors = SwitchDefaults.colors(
                                checkedThumbColor = MaterialTheme.colorScheme.onPrimary,
                                checkedTrackColor = MaterialTheme.colorScheme.primary,
                                checkedBorderColor = MaterialTheme.colorScheme.primary,
                                uncheckedThumbColor = MaterialTheme.colorScheme.onBackground,
                                uncheckedTrackColor = MediumLightGray,
                                uncheckedBorderColor = MaterialTheme.colorScheme.onBackground,
                            ),
                        )
                    }
                }
            }

            item {
                val activeSource by viewModel.activeHeartRateSource.collectAsState()
                val availableSources by viewModel.availableHeartRateSources.collectAsState()
                if (availableSources.size > 1) {
                    val activeIndex = availableSources.indexOf(activeSource).coerceAtLeast(0)
                    val nextSource = availableSources[(activeIndex + 1) % availableSources.size]

                    WearTonalContentButton(
                        modifier = Modifier
                            .fillMaxWidth()
                            .then(
                                if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                    this,
                                    spec
                                )
                            ),
                        transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                        onClick = {
                            viewModel.setActiveHrSource(nextSource)
                            hapticsViewModel.doGentleVibration()
                        }
                    ) {
                        Column(
                            modifier = Modifier.fillMaxWidth(),
                            verticalArrangement = Arrangement.spacedBy(2.5.dp)
                        ) {
                            Text(
                                text = stringResource(R.string.page_controls_live_heart_rate),
                                style = MaterialTheme.typography.bodyMedium,
                                textAlign = TextAlign.Start,
                            )
                            Text(
                                text = stringResource(
                                    R.string.page_controls_hr_source_hint,
                                    activeSource.shortName(),
                                    nextSource.shortName()
                                ),
                                style = MaterialTheme.typography.bodySmall,
                                textAlign = TextAlign.Start,
                                color = MaterialTheme.colorScheme.tertiaryContent
                            )
                        }
                    }
                }
            }

            item {
                val useSamsungHeartRate = viewModel.useSamsungHeartRate.value
                val updateUseSamsungHeartRate: (Boolean) -> Unit = { enabled ->
                    viewModel.setUseSamsungHeartRate(enabled)
                    hapticsViewModel.doGentleVibration()
                }

                WearTonalContentButton(
                    modifier = Modifier
                        .fillMaxWidth()
                        .then(
                            if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                this,
                                spec
                            )
                        ),
                    transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                    onClick = {
                        updateUseSamsungHeartRate(!useSamsungHeartRate)
                    }
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(5.dp)
                    ) {
                        Column(
                            modifier = Modifier.weight(1f),
                            verticalArrangement = Arrangement.spacedBy(2.5.dp)
                        ) {
                            Text(
                                text = stringResource(R.string.page_controls_samsung_heart_rate),
                                style = MaterialTheme.typography.bodyMedium,
                                textAlign = TextAlign.Start,
                            )
                            Text(
                                text = if (useSamsungHeartRate) {
                                    stringResource(R.string.page_controls_samsung_hr_on)
                                } else {
                                    stringResource(R.string.page_controls_samsung_hr_off)
                                },
                                style = MaterialTheme.typography.bodySmall,
                                textAlign = TextAlign.Start,
                                color = MaterialTheme.colorScheme.tertiaryContent
                            )
                        }
                        Switch(
                            checked = useSamsungHeartRate,
                            onCheckedChange = updateUseSamsungHeartRate,
                            colors = SwitchDefaults.colors(
                                checkedThumbColor = MaterialTheme.colorScheme.onPrimary,
                                checkedTrackColor = MaterialTheme.colorScheme.primary,
                                checkedBorderColor = MaterialTheme.colorScheme.primary,
                                uncheckedThumbColor = MaterialTheme.colorScheme.onBackground,
                                uncheckedTrackColor = MediumLightGray,
                                uncheckedBorderColor = MaterialTheme.colorScheme.onBackground,
                            ),
                        )
                    }
                }
            }

            item {
                val motionEnabled = motionCapture.collectionEnabled
                val toggleMotionCapture: (Boolean) -> Unit = { value ->
                    viewModel.setMotionCaptureEnabledForSession(value)
                    hapticsViewModel.doGentleVibration()
                }

                WearTonalContentButton(
                    modifier = Modifier
                        .fillMaxWidth()
                        .then(
                            if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                this,
                                spec
                            )
                        ),
                    transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                    onClick = { toggleMotionCapture(!motionEnabled) }
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(5.dp)
                    ) {
                        Column(
                            modifier = Modifier.weight(1f),
                            verticalArrangement = Arrangement.spacedBy(2.5.dp)
                        ) {
                            Text(
                                text = stringResource(R.string.page_controls_record_motion),
                                style = MaterialTheme.typography.bodyMedium,
                                textAlign = TextAlign.Start,
                            )
                            Text(
                                text = if (motionEnabled) {
                                    stringResource(R.string.page_controls_motion_on)
                                } else {
                                    stringResource(R.string.page_controls_motion_off)
                                },
                                style = MaterialTheme.typography.bodySmall,
                                textAlign = TextAlign.Start,
                                color = MaterialTheme.colorScheme.tertiaryContent
                            )
                        }
                        Switch(
                            checked = motionEnabled,
                            onCheckedChange = toggleMotionCapture,
                            colors = SwitchDefaults.colors(
                                checkedThumbColor = MaterialTheme.colorScheme.onPrimary,
                                checkedTrackColor = MaterialTheme.colorScheme.primary,
                                checkedBorderColor = MaterialTheme.colorScheme.primary,
                                uncheckedThumbColor = MaterialTheme.colorScheme.onBackground,
                                uncheckedTrackColor = MediumLightGray,
                                uncheckedBorderColor = MaterialTheme.colorScheme.onBackground,
                            ),
                        )
                    }
                }
            }

            if (motionCapture.collectionEnabled) {
                item {
                    val detailLevel = motionCapture.detailLevel
                    val nextDetailLevel = if (detailLevel == MotionCaptureDetailLevel.FULL) {
                        MotionCaptureDetailLevel.CORE
                    } else {
                        MotionCaptureDetailLevel.FULL
                    }

                    WearTonalContentButton(
                        modifier = Modifier
                            .fillMaxWidth()
                            .then(
                                if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                    this,
                                    spec
                                )
                            ),
                        transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                        onClick = {
                            viewModel.setMotionCaptureDetailLevelForSession(nextDetailLevel)
                            hapticsViewModel.doGentleVibration()
                        }
                    ) {
                        Column(
                            modifier = Modifier.fillMaxWidth(),
                            verticalArrangement = Arrangement.spacedBy(2.5.dp)
                        ) {
                            Text(
                                text = stringResource(R.string.page_controls_motion_detail),
                                style = MaterialTheme.typography.bodyMedium,
                                textAlign = TextAlign.Start,
                            )
                            Text(
                                text = if (detailLevel == MotionCaptureDetailLevel.FULL) {
                                    stringResource(R.string.page_controls_motion_detail_full)
                                } else {
                                    stringResource(R.string.page_controls_motion_detail_core)
                                },
                                style = MaterialTheme.typography.bodySmall,
                                textAlign = TextAlign.Start,
                                color = MaterialTheme.colorScheme.tertiaryContent
                            )
                        }
                    }
                }

                item {
                    val sampleRate = motionCapture.sampleRate
                    val nextSampleRate = if (sampleRate == MotionCaptureSampleRate.HZ_50) {
                        MotionCaptureSampleRate.HZ_25
                    } else {
                        MotionCaptureSampleRate.HZ_50
                    }

                    WearTonalContentButton(
                        modifier = Modifier
                            .fillMaxWidth()
                            .then(
                                if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                    this,
                                    spec
                                )
                            ),
                        transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                        onClick = {
                            viewModel.setMotionCaptureSampleRateForSession(nextSampleRate)
                            hapticsViewModel.doGentleVibration()
                        }
                    ) {
                        Column(
                            modifier = Modifier.fillMaxWidth(),
                            verticalArrangement = Arrangement.spacedBy(2.5.dp)
                        ) {
                            Text(
                                text = stringResource(R.string.page_controls_motion_rate),
                                style = MaterialTheme.typography.bodyMedium,
                                textAlign = TextAlign.Start,
                            )
                            Text(
                                text = if (sampleRate == MotionCaptureSampleRate.HZ_50) {
                                    stringResource(R.string.page_controls_motion_rate_50)
                                } else {
                                    stringResource(R.string.page_controls_motion_rate_25)
                                },
                                style = MaterialTheme.typography.bodySmall,
                                textAlign = TextAlign.Start,
                                color = MaterialTheme.colorScheme.tertiaryContent
                            )
                        }
                    }
                }
            }

            item {
                // SysUI owns the per-app Now Bar style ("icon" vs "icon + text"). Only the
                // exported settings entry point is reachable, so this row opens it; with
                // "icon + text" the watch face shows the Now Bar card, which carries our timer.
                WearTonalContentButton(
                    modifier = Modifier
                        .fillMaxWidth()
                        .then(
                            if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                this,
                                spec
                            )
                        ),
                    transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                    onClick = {
                        hapticsViewModel.doGentleVibration()
                        try {
                            context.startActivity(
                                Intent("com.samsung.android.wearable.sysui.W_NOWBAR_SETTINGS")
                                    .setPackage("com.samsung.android.wearable.sysui")
                            )
                        } catch (exception: Exception) {
                            android.util.Log.e("ControlsPage", "Now Bar settings unavailable", exception)
                        }
                    }
                ) {
                    Column(
                        modifier = Modifier.fillMaxWidth(),
                        verticalArrangement = Arrangement.spacedBy(2.5.dp)
                    ) {
                        Text(
                            text = stringResource(R.string.page_controls_watch_face_timer),
                            style = MaterialTheme.typography.bodyMedium,
                            textAlign = TextAlign.Start,
                        )
                        Text(
                            text = stringResource(R.string.page_controls_watch_face_hint),
                            style = MaterialTheme.typography.bodySmall,
                            textAlign = TextAlign.Start,
                            color = MaterialTheme.colorScheme.tertiaryContent
                        )
                    }
                }
            }

            item {
                val exerciseDefaultKeepOn = exercise.keepScreenOn
                val statusText = when {
                    exerciseDefaultKeepOn -> stringResource(R.string.page_controls_screen_exercise_forced)
                    !exerciseDefaultKeepOn && !keepScreenOnOverride -> stringResource(R.string.page_controls_screen_can_dim)
                    else -> stringResource(R.string.page_controls_screen_stays_on)
                }
                val isSwitchEnabled = !exerciseDefaultKeepOn
                val switchChecked = exerciseDefaultKeepOn || keepScreenOnOverride

                WearTonalContentButton(
                    enabled = isSwitchEnabled,
                    modifier = Modifier
                        .fillMaxWidth()
                        .then(
                            if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                this,
                                spec
                            )
                        ),
                    transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                    onClick = {
                        hapticsViewModel.doGentleVibration()
                        viewModel.toggleKeepScreenOn()
                    }
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(5.dp)
                    ) {
                        Column(
                            modifier = Modifier.weight(1f),
                            verticalArrangement = Arrangement.spacedBy(2.5.dp)
                        ) {
                            Text(
                                text = stringResource(R.string.page_controls_keep_screen_on),
                                style = MaterialTheme.typography.bodyMedium,
                                textAlign = TextAlign.Start,
                            )
                            Text(
                                text = statusText,
                                style = MaterialTheme.typography.bodySmall,
                                textAlign = TextAlign.Start,
                                color = MaterialTheme.colorScheme.tertiaryContent
                            )
                        }
                        Switch(
                            checked = switchChecked,
                            onCheckedChange = {
                                hapticsViewModel.doGentleVibration()
                                viewModel.toggleKeepScreenOn()
                            },
                            enabled = isSwitchEnabled,
                            colors = SwitchDefaults.colors(
                                checkedThumbColor = MaterialTheme.colorScheme.onPrimary,
                                checkedTrackColor = MaterialTheme.colorScheme.primary,
                                checkedBorderColor = MaterialTheme.colorScheme.primary,
                                uncheckedThumbColor = MaterialTheme.colorScheme.onBackground,
                                uncheckedTrackColor = MediumLightGray,
                                uncheckedBorderColor = MaterialTheme.colorScheme.onBackground,
                                disabledCheckedThumbColor = MaterialTheme.colorScheme.onPrimary,
                                disabledCheckedTrackColor = DarkOrange,
                                disabledCheckedBorderColor = DarkOrange,
                            ),
                            modifier = Modifier
                        )
                    }
                }
            }
            item {
                Spacer(modifier = Modifier.height(10.dp))
            }
            item {
                ControlsPageSectionHeader(
                    text = stringResource(R.string.page_controls_section_session),
                    modifier = Modifier
                        .fillMaxWidth()
                        .then(
                            if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                this,
                                spec
                            )
                        )
                )
            }
            if (canChooseStartMember) {
                item {
                    ButtonWithText(
                        modifier = Modifier
                            .semantics { contentDescription = startWithActionDescription }
                            .fillMaxWidth()
                            .then(
                                if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                    this,
                                    spec
                                )
                            ),
                        transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                        text = stringResource(R.string.page_controls_start_with, cadenceStartName),
                        onClick = {
                            hapticsViewModel.doGentleVibration()
                            showStartWithDialog = true
                        }
                    )
                }
                if (memberCount > 2) {
                    item {
                        ButtonWithText(
                            modifier = Modifier
                                .semantics { contentDescription = setOrderActionDescription }
                                .fillMaxWidth()
                                .then(
                                    if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                        this,
                                        spec
                                    )
                                ),
                            transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                            text = stringResource(R.string.page_controls_set_order),
                            onClick = {
                                hapticsViewModel.doGentleVibration()
                                orderBuilder = emptyList()
                            }
                        )
                    }
                }
            }
            if (isActiveSetPage) {
                item {
                    ButtonWithText(
                        modifier = Modifier
                            .semantics { contentDescription = skipExerciseActionDescription }
                            .fillMaxWidth()
                            .then(
                                if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                    this,
                                    spec
                                )
                            ),
                        transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                        text = stringResource(R.string.page_controls_skip_exercise),
                        onClick = {
                            hapticsViewModel.doGentleVibration()
                            showSkipExerciseDialog = true
                        }
                    )
                }
            }
            item {
                ButtonWithText(
                    modifier = Modifier
                        .fillMaxWidth()
                        .then(
                            if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                this,
                                spec
                            )
                        ),
                    transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                    text = stringResource(R.string.page_controls_finish_early),
                    onClick = {
                        hapticsViewModel.doGentleVibration()
                        showFinishEarlyDialog = true
                    }
                )
            }
            item {
                ButtonWithText(
                    modifier = Modifier
                        .fillMaxWidth()
                        .then(
                            if (isInspectionMode) Modifier else Modifier.transformedHeight(
                                this,
                                spec
                            )
                        ),
                    transformation = if (isInspectionMode) null else SurfaceTransformation(spec),
                    text = stringResource(R.string.page_controls_go_home),
                    onClick = {
                        hapticsViewModel.doGentleVibration()
                        onBeforeGoHome?.invoke()
                        viewModel.stopWorkoutSessionHeartbeat()
                        viewModel.upsertWorkoutRecord(
                            updatedState.exerciseId,
                            updatedState.setIndex,
                            WATCH_SESSION_STATE_RETURNED_HOME
                        )
                        cancelWorkoutInProgressNotification(context)
                        scope.launch {
                            viewModel.flushWorkoutSync()
                        }

                        navController.navigate(Screen.WorkoutSelection.route) {
                            popUpTo(0) { inclusive = true }
                        }
                    }
                )
            }
        }
    }

    CustomDialogYesOnLongPress(
        show = showGoBackDialog,
        title = stringResource(R.string.page_controls_dialog_go_back_title),
        message = stringResource(R.string.page_controls_dialog_go_back_message),
        handleYesClick = {
            hapticsViewModel.doGentleVibration()
            viewModel.goToPreviousSetWear()
            viewModel.lightScreenUp()
        },
        handleNoClick = {
            showGoBackDialog = false
            hapticsViewModel.doGentleVibration()
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showGoBackDialog = false
        },
        onVisibilityChange = { isVisible ->
            if (isVisible) {
                viewModel.setDimming(false)
            } else {
                viewModel.reEvaluateDimmingForCurrentState()
            }
        }
    )

    val orderPickerVisible = showStartWithDialog || orderBuilder != null
    val orderStep = orderBuilder?.size ?: 0
    val memberNames = cadenceSuperset?.exercises?.map { it.name }.orEmpty()

    fun closeOrderPicker() {
        showStartWithDialog = false
        orderBuilder = null
    }

    SupersetStartMemberPickerOverlay(
        show = orderPickerVisible,
        title = when {
            orderBuilder == null -> stringResource(R.string.page_controls_picker_start_with)
            orderStep >= memberCount -> stringResource(R.string.page_controls_picker_order_set)
            else -> stringResource(R.string.page_controls_picker_order_of, orderStep + 1, memberCount)
        },
        options = memberNames.mapIndexed { index, name ->
            SupersetStartMemberOption(
                memberIndex = index,
                name = name,
                isCurrent = orderBuilder == null && index == (cadenceRotationOrder.firstOrNull() ?: 0)
            )
        }.filter { option -> orderBuilder?.contains(option.memberIndex) != true },
        onSelect = { memberIndex ->
            hapticsViewModel.doGentleVibration()
            val superset = cadenceSuperset
            val currentOrder = orderBuilder
            if (superset == null) {
                closeOrderPicker()
                return@SupersetStartMemberPickerOverlay
            }
            if (currentOrder == null) {
                // "Start with": rotate the stored order behind the chosen member.
                viewModel.setSupersetStartMemberWear(superset.id, memberIndex)
                closeOrderPicker()
                viewModel.lightScreenUp()
                return@SupersetStartMemberPickerOverlay
            }
            val next = currentOrder + memberIndex
            if (next.size >= memberCount) {
                viewModel.setSupersetRotationOrderWear(superset.id, next)
                orderBuilder = null
                viewModel.lightScreenUp()
            } else {
                orderBuilder = next
            }
        },
        onDismiss = { closeOrderPicker() }
    )

    CustomDialogYesOnLongPress(
        show = showSkipExerciseDialog,
        title = stringResource(R.string.page_controls_skip_exercise),
        message = stringResource(R.string.page_controls_dialog_skip_message),
        handleYesClick = {
            hapticsViewModel.doGentleVibration()
            showSkipExerciseDialog = false
            viewModel.skipCurrentExerciseWear(context)
            viewModel.lightScreenUp()
        },
        handleNoClick = {
            showSkipExerciseDialog = false
            shouldResumeTimerAfterSkipDialog = false
            hapticsViewModel.doGentleVibration()
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showSkipExerciseDialog = false
            shouldResumeTimerAfterSkipDialog = false
        },
        onVisibilityChange = { isVisible ->
            if (isVisible) {
                shouldResumeTimerAfterSkipDialog = shouldPauseCurrentTimerForDialog()
                pauseCurrentTimerForDialog()
                viewModel.setDimming(false)
            } else {
                resumeCurrentTimerAfterDialog(shouldResumeTimerAfterSkipDialog)
                shouldResumeTimerAfterSkipDialog = false
                viewModel.reEvaluateDimmingForCurrentState()
            }
        }
    )

    CustomDialogYesOnLongPress(
        show = showFinishEarlyDialog,
        title = stringResource(R.string.page_controls_finish_early),
        message = stringResource(R.string.page_controls_dialog_finish_early_message),
        handleYesClick = {
            hapticsViewModel.doGentleVibration()
            showFinishEarlyDialog = false
            viewModel.finishWorkoutEarlyWear(context)
            viewModel.lightScreenUp()
        },
        handleNoClick = {
            showFinishEarlyDialog = false
            shouldResumeTimerAfterFinishEarlyDialog = false
            hapticsViewModel.doGentleVibration()
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            showFinishEarlyDialog = false
            shouldResumeTimerAfterFinishEarlyDialog = false
        },
        onVisibilityChange = { isVisible ->
            if (isVisible) {
                shouldResumeTimerAfterFinishEarlyDialog = shouldPauseCurrentTimerForDialog()
                pauseCurrentTimerForDialog()
                viewModel.setDimming(false)
            } else {
                resumeCurrentTimerAfterDialog(shouldResumeTimerAfterFinishEarlyDialog)
                shouldResumeTimerAfterFinishEarlyDialog = false
                viewModel.reEvaluateDimmingForCurrentState()
            }
        }
    )
}

@Composable
private fun ControlsPageSectionHeader(
    text: String,
    modifier: Modifier = Modifier
) {
    val currentLocale = LocalLocale.current.platformLocale
    Text(
        text = text.uppercase(currentLocale),
        modifier = modifier.padding(horizontal = 25.dp),
        style = workoutSectionLabelTextStyle(),
        color = MaterialTheme.colorScheme.onBackground,
        textAlign = TextAlign.Center
    )
}
