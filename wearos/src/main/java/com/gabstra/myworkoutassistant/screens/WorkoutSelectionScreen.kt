package com.gabstra.myworkoutassistant.screens

import android.Manifest
import android.app.Activity
import android.app.AlarmManager
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.provider.Settings
import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.core.net.toUri
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.navigation.NavController
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnState
import androidx.wear.compose.foundation.lazy.items
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.ListHeader
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.OpenOnPhoneDialog
import androidx.wear.compose.material3.OpenOnPhoneDialogDefaults
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.ScrollIndicator
import androidx.wear.compose.material3.ScrollIndicatorDefaults
import androidx.wear.compose.material3.SurfaceTransformation
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.lazy.ResponsiveTransformationSpec
import androidx.wear.compose.material3.lazy.TransformationVariableSpec
import androidx.wear.compose.material3.lazy.rememberTransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import androidx.wear.compose.material3.openOnPhoneDialogCurvedText
import com.gabstra.myworkoutassistant.composables.ButtonWithText
import com.gabstra.myworkoutassistant.composables.PermissionRequestDialog
import com.gabstra.myworkoutassistant.composables.WearPrimaryButton
import com.gabstra.myworkoutassistant.composables.WearTonalContentButton
import com.gabstra.myworkoutassistant.composables.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composables.rememberWearCoroutineScope
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.openSettingsOnPhoneApp
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.MediumLightGray
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import com.gabstra.myworkoutassistant.shared.getVersionName
import com.gabstra.myworkoutassistant.shared.isReservedWorkoutPlanName
import com.gabstra.myworkoutassistant.shared.profile.Profiles
import com.gabstra.myworkoutassistant.shared.workout.presentation.resolveRecurringPrescriptionProgress
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.workout.presentation.orderWorkoutsForPresentation
import com.google.android.gms.wearable.DataClient
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import com.google.android.horologist.datalayer.watch.WearDataLayerAppHelper
import kotlinx.coroutines.launch
import kotlinx.coroutines.awaitCancellation
import java.util.Calendar
import java.util.UUID

private fun Workout.hasEnabledExerciseWithSet(): Boolean {
    // Workout must be active
    if (!isActive) return false
    
    // Get all exercises: direct exercises + exercises from supersets
    val allExercises = workoutComponents.filterIsInstance<Exercise>() +
        workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }
    
    // Check if any enabled exercise has at least one non-rest set
    return allExercises.any { exercise ->
        exercise.enabled && exercise.sets.any { it !is RestSet }
    }
}

internal data class WorkoutPlanSection(
    val plan: WorkoutPlan?,
    val workouts: List<Workout>,
)

/**
 * Builds the workout-selection sections.
 *
 * Plans are optional groupings: workouts whose plan is missing or named like the legacy
 * "Unassigned" sentinel are rendered as a single headerless section after the real plans. Reserved
 * plan names are normalized before visibility filtering, so their workouts stay visible even if the
 * legacy placeholder plan itself was hidden. Workouts owned by a hidden real plan stay hidden.
 */
internal fun buildWorkoutSelectionSections(
    workouts: List<Workout>,
    plans: List<WorkoutPlan>,
    visiblePlanIds: Collection<UUID>?,
): List<WorkoutPlanSection> {
    val allPlanById = plans.associateBy { it.id }
    val visiblePlans = plans.filter { plan ->
        !isReservedWorkoutPlanName(plan.name) &&
            (visiblePlanIds == null || plan.id in visiblePlanIds)
    }
    val grouped = linkedMapOf<WorkoutPlan?, MutableList<Workout>>()
    visiblePlans.forEach { plan -> grouped[plan] = mutableListOf() }
    grouped[null] = mutableListOf()

    workouts.forEach { workout ->
        val assignedPlanId = workout.workoutPlanId
        val assignedPlan = assignedPlanId?.let(allPlanById::get)
        val sectionPlan = assignedPlan?.takeUnless { isReservedWorkoutPlanName(it.name) }
        if (sectionPlan != null && visiblePlanIds != null && sectionPlan.id !in visiblePlanIds) {
            return@forEach
        }
        grouped.getOrPut(sectionPlan) { mutableListOf() }.add(workout)
    }

    return grouped
        .filterValues { it.isNotEmpty() }
        .map { (plan, sectionWorkouts) ->
            WorkoutPlanSection(
                plan = plan,
                workouts = sectionWorkouts.sortedBy { it.order },
            )
        }
        .sortedWith(
            compareBy<WorkoutPlanSection>(
                { it.plan == null },
                { it.plan?.order ?: Int.MAX_VALUE },
            )
        )
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun WorkoutListItem(
    modifier: Modifier,
    workout: Workout,
    onItemClick: () -> Unit,
    transformation: SurfaceTransformation,
) {
    ButtonWithText(
        modifier = modifier,
        transformation = transformation,
        text = workout.name,
        onClick = { onItemClick() }
    )
}

@Composable
fun rememberNotificationPermissionState(): State<Boolean> {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current

    // Create mutable state to track permission status
    val permissionState = remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.POST_NOTIFICATIONS
            ) == PackageManager.PERMISSION_GRANTED
        )
    }

    // Update permission state when lifecycle resumes
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                permissionState.value = ContextCompat.checkSelfPermission(
                    context,
                    Manifest.permission.POST_NOTIFICATIONS
                ) == PackageManager.PERMISSION_GRANTED
            }
        }

        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
        }
    }

    return permissionState
}

@Composable
fun NotificationPermissionHandler(content: @Composable (Boolean, () -> Unit) -> Unit) {
    val context = LocalContext.current
    val permissionState = rememberNotificationPermissionState().value

    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { isGranted ->
        // This will be called when the user responds to the permission dialog
        // The state will be updated on the next lifecycle resume
    }

    val requestPermission = {
        permissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    content(permissionState, requestPermission)
}

@Composable
fun rememberCanScheduleExactAlarmsState(context: Context): State<Boolean> {
    val alarmManager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
    val lifecycleOwner = LocalLifecycleOwner.current
    val canScheduleState = remember { mutableStateOf(alarmManager.canScheduleExactAlarms()) }

    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                canScheduleState.value = alarmManager.canScheduleExactAlarms()
            }
        }

        lifecycleOwner.lifecycle.addObserver(observer)

        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
        }
    }

    return canScheduleState
}

@Composable
fun rememberCanUseFullScreenIntentState(context: Context): State<Boolean> {
    val notificationManager = context.getSystemService(NotificationManager::class.java)
    val lifecycleOwner = LocalLifecycleOwner.current
    val permissionState = remember {
        mutableStateOf(notificationManager.canUseFullScreenIntent())
    }

    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                permissionState.value = notificationManager.canUseFullScreenIntent()
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    return permissionState
}

@OptIn(ExperimentalHorologistApi::class, ExperimentalFoundationApi::class)
@Composable
fun WorkoutSelectionScreen(
    alarmManager: AlarmManager,
    dataClient: DataClient,
    navController: NavController,
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    appHelper: WearDataLayerAppHelper,
) {
    val context = LocalContext.current
    
    // Handle back button press to close the app
    BackHandler {
        (context as? Activity)?.finish()
    }
    
    val workouts by viewModel.workouts.collectAsState()
    val motionCaptureState by viewModel.motionCaptureUiState.collectAsState()
    var completedWorkoutHistories by remember(viewModel) { mutableStateOf<List<WorkoutHistory>?>(null) }
    val lifecycleOwner = LocalLifecycleOwner.current
    LaunchedEffect(viewModel, lifecycleOwner, workouts) {
        lifecycleOwner.lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            completedWorkoutHistories = null
            completedWorkoutHistories = viewModel.getCompletedWorkoutHistoriesForCurrentProfile()
            awaitCancellation()
        }
    }
    
    // A profile can limit which plans this watch offers as workouts to do.
    val visiblePlanIds = viewModel.workoutStore.visibleWorkoutPlanIds

    // Plans are optional groupings; plan-less and legacy reserved-plan workouts form one
    // trailing headerless section.
    val workoutSections = remember(workouts, viewModel.workoutStore.workoutPlans, visiblePlanIds) {
        buildWorkoutSelectionSections(
            workouts = workouts.filter { it.hasEnabledExerciseWithSet() },
            plans = viewModel.workoutStore.workoutPlans,
            visiblePlanIds = visiblePlanIds,
        )
    }
    val currentYear = remember { Calendar.getInstance().get(Calendar.YEAR) }

    val userAge by viewModel.userAge
    val versionName = getVersionName(context);

    val canScheduleExactAlarms by rememberCanScheduleExactAlarmsState(context)
    val canUseFullScreenIntent by rememberCanUseFullScreenIntentState(context)

    var showClearData by remember { mutableStateOf(false) }
    var showOpenOnPhoneDialog by remember { mutableStateOf(false) }
    var showProfilePicker by remember { mutableStateOf(false) }
    var hasSelectablePhoneProfiles by remember(context) {
        mutableStateOf(Profiles.remoteActiveProfileId(context) != null && (Profiles.remoteProfileCount(context) ?: 0) > 1)
    }
    var selectedProfileName by remember(context) {
        mutableStateOf(Profiles.activeProfile(context).name.takeIf { Profiles.hasLocalProfileChoice(context) })
    }
    var reminderSettingsRationale by remember { mutableStateOf<Pair<Intent, String>?>(null) }
    val scope = rememberWearCoroutineScope()

    DisposableEffect(context) {
        val profileIndexObserver = Profiles.observeProfileIndex(context) { profileIndex ->
            hasSelectablePhoneProfiles =
                Profiles.remoteActiveProfileId(context) != null && (Profiles.remoteProfileCount(context) ?: 0) > 1
            selectedProfileName = profileIndex.profiles
                .firstOrNull { it.id == profileIndex.activeProfileId }
                ?.name
                ?.takeIf { Profiles.hasLocalProfileChoice(context) }
        }
        onDispose { profileIndexObserver.close() }
    }

    LaunchedEffect(showOpenOnPhoneDialog) {
        if (showOpenOnPhoneDialog) {
            viewModel.setDimming(false)
            viewModel.lightScreenUp()
        } else {
            viewModel.reEvaluateDimmingForCurrentState()
        }
    }

    LaunchedEffect(showProfilePicker) {
        if (showProfilePicker) {
            viewModel.setDimming(false)
        } else {
            viewModel.reEvaluateDimmingForCurrentState()
        }
    }

    reminderSettingsRationale?.let { (intent, message) ->
        PermissionRequestDialog(
            title = stringResource(R.string.wear_workout_reminders),
            message = message,
            continueLabel = stringResource(R.string.wear_open_settings),
            onContinue = {
                reminderSettingsRationale = null
                context.startActivity(intent)
            },
            onDismiss = { reminderSettingsRationale = null },
        )
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

    ScreenScaffold(
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
    ) { contentPadding ->
        Box {
            TransformingLazyColumn(
                contentPadding = contentPadding,
                state = state
            ) {
                item {
                    ListHeader(
                        modifier = Modifier
                            .transformedHeight(this, spec),
                        transformation = SurfaceTransformation(spec),
                    ) {
                        Row(
                            modifier = Modifier
                                .combinedClickable(
                                    onClick = {},
                                    onLongClick = {
                                        hapticsViewModel.doHardVibration()
                                        Toast
                                            .makeText(
                                                context,
                                                context.getString(R.string.wear_app_version_fmt, versionName),
                                                Toast.LENGTH_LONG
                                            )
                                            .show()
                                    },
                                    onDoubleClick = {
                                        showClearData = true
                                        hapticsViewModel.doHardVibrationTwice()
                                    }
                                ),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.Center
                        ) {
                            Text(
                                text = stringResource(R.string.app_name),
                                textAlign = TextAlign.Center,
                                style = MaterialTheme.typography.titleLarge,
                                color = MaterialTheme.colorScheme.onBackground
                            )
                        }
                    }
                }

                if (motionCaptureState.hasRequiredSensors &&
                    (!motionCaptureState.isCapturing || motionCaptureState.isFreeformCapture)
                ) {
                    item {
                        val freeformRecording = motionCaptureState.isFreeformCapture
                        val toggleFreeformCapture: () -> Unit = {
                            hapticsViewModel.doGentleVibration()
                            if (freeformRecording) {
                                viewModel.stopFreeformMotionCapture()
                            } else {
                                viewModel.startFreeformMotionCapture()
                            }
                        }
                        WearTonalContentButton(
                            modifier = Modifier
                                .fillMaxWidth()
                                .transformedHeight(this, spec),
                            transformation = SurfaceTransformation(spec),
                            onClick = { toggleFreeformCapture() }
                        ) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(5.dp)
                            ) {
                                Text(
                                    modifier = Modifier.weight(1f),
                                    text = stringResource(
                                        if (freeformRecording) {
                                            R.string.freeform_capture_recording
                                        } else {
                                            R.string.freeform_capture_record
                                        }
                                    ),
                                    style = MaterialTheme.typography.bodyMedium,
                                    textAlign = TextAlign.Start,
                                    color = if (freeformRecording) {
                                        MaterialTheme.colorScheme.primary
                                    } else {
                                        MaterialTheme.colorScheme.onBackground
                                    }
                                )
                                Switch(
                                    checked = freeformRecording,
                                    onCheckedChange = { toggleFreeformCapture() },
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
                }

                if (hasSelectablePhoneProfiles && selectedProfileName == null) {
                    item {
                        ButtonWithText(
                            modifier = Modifier
                                .transformedHeight(this, spec)
                                .animateItem(),
                            transformation = SurfaceTransformation(spec),
                            text = stringResource(R.string.wear_profiles),
                            onClick = {
                                hapticsViewModel.doGentleVibration()
                                showProfilePicker = true
                            }
                        )
                    }
                }

                selectedProfileName?.let { profileName ->
                    item {
                        val switchProfileCd = stringResource(R.string.wear_switch_profile_cd, profileName)
                        val selectedProfileCd = stringResource(R.string.wear_selected_profile_cd, profileName)
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .transformedHeight(this, spec),
                            contentAlignment = Alignment.Center,
                        ) {
                            val chipContent: @Composable () -> Unit = {
                                Text(
                                    modifier = Modifier.widthIn(max = 156.dp),
                                    text = profileName,
                                    textAlign = TextAlign.Center,
                                    style = MaterialTheme.typography.labelMedium,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                            }
                            if (hasSelectablePhoneProfiles) {
                                WearTonalContentButton(
                                    modifier = Modifier
                                        .widthIn(max = 180.dp)
                                        .heightIn(min = 48.dp)
                                        .semantics { contentDescription = switchProfileCd },
                                    onClick = {
                                        hapticsViewModel.doGentleVibration()
                                        showProfilePicker = true
                                    },
                                ) {
                                    chipContent()
                                }
                            } else {
                                Box(
                                    modifier = Modifier
                                        .widthIn(max = 180.dp)
                                        .heightIn(min = 48.dp)
                                        .clip(RoundedCornerShape(percent = 50))
                                        .background(MaterialTheme.colorScheme.secondaryContainer)
                                        .padding(horizontal = 12.dp, vertical = 6.dp)
                                        .semantics { contentDescription = selectedProfileCd },
                                    contentAlignment = Alignment.Center,
                                ) {
                                    chipContent()
                                }
                            }
                        }
                    }
                }

                if (hasSelectablePhoneProfiles || selectedProfileName != null) {
                    item {
                        Spacer(modifier = Modifier.height(8.dp))
                    }
                }

                if (!canScheduleExactAlarms) {
                    item {
                        Text(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 5.dp)
                                .transformedHeight(this, spec)
                                .animateItem(),
                            text = stringResource(R.string.wear_turn_on_reminders_hint),
                            textAlign = TextAlign.Center,
                            style = MaterialTheme.typography.bodySmall.copy(fontWeight = FontWeight.Normal),
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    item {
                        Spacer(modifier = Modifier.height(5.dp))
                    }
                    item {
                        WearPrimaryButton(
                            modifier = Modifier
                                .transformedHeight(this, spec)
                                .animateItem(),
                            transformation = SurfaceTransformation(spec),
                            text = stringResource(R.string.wear_open_reminder_settings),
                            onClick = {
                                hapticsViewModel.doGentleVibration()
                                reminderSettingsRationale = Intent(
                                    Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM,
                                    "package:${context.packageName}".toUri(),
                                ) to context.getString(R.string.wear_exact_alarms_rationale)
                            }
                        )
                    }
                }

                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE && !canUseFullScreenIntent) {
                    item {
                        Text(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 5.dp)
                                .transformedHeight(this, spec)
                                .animateItem(),
                            text = stringResource(R.string.wear_allow_full_screen_hint),
                            textAlign = TextAlign.Center,
                            style = MaterialTheme.typography.bodySmall.copy(fontWeight = FontWeight.Normal),
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    item {
                        WearPrimaryButton(
                            modifier = Modifier.transformedHeight(this, spec).animateItem(),
                            transformation = SurfaceTransformation(spec),
                            text = stringResource(R.string.wear_open_alarm_display_settings),
                            onClick = {
                                hapticsViewModel.doGentleVibration()
                                reminderSettingsRationale = Intent(
                                    Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT,
                                ).setData("package:${context.packageName}".toUri()) to
                                    context.getString(R.string.wear_full_screen_alarms_rationale)
                            },
                        )
                    }
                }

                if (userAge == currentYear) {
                    item {
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 5.dp)
                                .transformedHeight(this, spec)
                                .graphicsLayer { with(spec) { applyContainerTransformation(scrollProgress) } }
                        ) {
                            if (viewModel.isPhoneConnectedAndHasApp) {
                                Text(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .graphicsLayer { with(spec) { applyContentTransformation(scrollProgress) } },
                                    text = stringResource(R.string.wear_finish_setup_phone),
                                    textAlign = TextAlign.Center,
                                    style = MaterialTheme.typography.bodySmall.copy(fontWeight = FontWeight.Normal),
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            } else {
                                Text(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .graphicsLayer { with(spec) { applyContentTransformation(scrollProgress) } },
                                    text = stringResource(R.string.wear_open_phone_sync),
                                    textAlign = TextAlign.Center,
                                    style = MaterialTheme.typography.bodySmall.copy(fontWeight = FontWeight.Normal),
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                        }
                    }
                    if (viewModel.isPhoneConnectedAndHasApp) {
                        item {
                            WearPrimaryButton(
                                modifier = Modifier
                                    .transformedHeight(this, spec)
                                    .animateItem(),
                                transformation = SurfaceTransformation(spec),
                                text = stringResource(R.string.wear_open_phone_app),
                                onClick = {
                                    hapticsViewModel.doGentleVibration()
                                    showOpenOnPhoneDialog = true
                                    scope.launch {
                                        openSettingsOnPhoneApp(
                                            context,
                                            dataClient,
                                            viewModel.phoneNode!!,
                                            appHelper
                                        )
                                    }
                                }
                            )
                        }
                    }
                } else {
                    if (workoutSections.isEmpty()) {
                        item {
                            Box(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec)
                                    .graphicsLayer { with(spec) { applyContainerTransformation(scrollProgress) } }
                            ) {
                                Text(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .graphicsLayer { with(spec) { applyContentTransformation(scrollProgress) } },
                                    text = stringResource(R.string.wear_no_workouts),
                                    textAlign = TextAlign.Center,
                                    style = MaterialTheme.typography.bodySmall.copy(fontWeight = FontWeight.Normal),
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                        }
                    } else {
                        // Real plans get headers; the ungrouped section stays headerless.
                        workoutSections.forEachIndexed { index, section ->
                            val plan = section.plan
                            val planWorkouts = section.workouts
                            if (planWorkouts.isNotEmpty()) {
                                if (plan == null && workoutSections.getOrNull(index - 1)?.plan != null) {
                                    item {
                                        Spacer(modifier = Modifier.height(8.dp))
                                    }
                                }
                                if (plan != null) {
                                    item {
                                        ListHeader(
                                            modifier = Modifier
                                                .transformedHeight(this, spec),
                                            transformation = SurfaceTransformation(spec),
                                        ) {
                                            Text(
                                                // Plan names are user-authored content; never translate them.
                                                text = plan.name,
                                                textAlign = TextAlign.Center,
                                                style = MaterialTheme.typography.titleMedium,
                                                color = MaterialTheme.colorScheme.onBackground
                                            )
                                        }
                                    }
                                }
                                
                                val orderedWorkouts = orderWorkoutsForPresentation(planWorkouts)
                                val progressBySession = completedWorkoutHistories?.let { histories ->
                                    resolveRecurringPrescriptionProgress(
                                        workouts = orderedWorkouts.filter { it.enabled && it.isActive },
                                        histories = histories,
                                    )
                                }.orEmpty()
                                val displayedWorkouts = orderWorkoutsForPresentation(
                                    orderedWorkouts.filter { it.recurringSessionId == null } +
                                        orderedWorkouts
                                            .filter { it.recurringSessionId != null }
                                            .distinctBy { it.recurringSessionId }
                                            .map { first ->
                                                val sessionId = first.recurringSessionId
                                                val progress = sessionId?.let(progressBySession::get)
                                                val representativeId = progress?.suggestedWorkoutId
                                                    ?: progress?.firstWorkoutId
                                                orderedWorkouts.firstOrNull { it.id == representativeId }
                                                    ?: orderedWorkouts.firstOrNull {
                                                        it.recurringSessionId == sessionId && it.enabled && it.isActive
                                                    }
                                                    ?: first
                                            },
                                )
                                // Workouts in this plan
                                items(
                                    items = displayedWorkouts,
                                    key = { workout -> workout.id }
                                ) { workout ->
                                    val openWorkoutCd = stringResource(R.string.wear_open_workout_cd, workout.name)
                                    WorkoutListItem(
                                        workout = workout,
                                        onItemClick = {
                                            hapticsViewModel.doGentleVibration()
                                            navController.navigate(Screen.WorkoutDetail.route)
                                            viewModel.setSelectedWorkoutId(workout.id)
                                        },
                                        modifier = Modifier
                                            .semantics { contentDescription = openWorkoutCd }
                                            .fillMaxWidth()
                                            .transformedHeight(this, spec),
                                        transformation = SurfaceTransformation(spec)
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }

        val text = OpenOnPhoneDialogDefaults.text
        val style = OpenOnPhoneDialogDefaults.curvedTextStyle

        OpenOnPhoneDialog(
            visible = showOpenOnPhoneDialog,
            onDismissRequest = { showOpenOnPhoneDialog = false },
            curvedText = { openOnPhoneDialogCurvedText(text = text, style = style) },
        )

        CustomDialogYesOnLongPress(
            show = showClearData,
            title = stringResource(R.string.wear_clear_local_data),
            message = stringResource(R.string.wear_clear_local_data_message),
            handleYesClick = {
                hapticsViewModel.doGentleVibration()
                viewModel.resetAll()
                Toast
                    .makeText(
                        context,
                        context.getString(R.string.wear_all_data_reset),
                        Toast.LENGTH_SHORT
                    )
                    .show()
                showClearData = false
            },
            handleNoClick = {
                showClearData = false
                hapticsViewModel.doGentleVibration()
            },
            closeTimerInMillis = 5000,
            handleOnAutomaticClose = {
                showClearData = false
            },
            onVisibilityChange = { isVisible ->
                if (isVisible) {
                    viewModel.setDimming(false)
                } else {
                    viewModel.reEvaluateDimmingForCurrentState()
                }
            }
        )

        if (showProfilePicker) {
            ProfilePickerDialog(
                onDismiss = { showProfilePicker = false },
            )
        }
    }
}
