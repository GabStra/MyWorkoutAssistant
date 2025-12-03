package com.gabstra.myworkoutassistant.screens

import android.Manifest
import android.app.AlarmManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.provider.Settings
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.core.net.toUri
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.navigation.NavController
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnState
import androidx.wear.compose.foundation.lazy.items
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.ListHeader
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.OpenOnPhoneDialog
import androidx.wear.compose.material3.OpenOnPhoneDialogDefaults
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.SurfaceTransformation
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.lazy.rememberTransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import androidx.wear.compose.material3.openOnPhoneDialogCurvedText
import com.gabstra.myworkoutassistant.composables.ButtonWithText
import com.gabstra.myworkoutassistant.composables.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composables.TutorialOverlay
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.openSettingsOnPhoneApp
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.getVersionName
import com.google.android.gms.wearable.DataClient
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import com.google.android.horologist.datalayer.watch.WearDataLayerAppHelper
import kotlinx.coroutines.launch
import java.util.Calendar

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun WorkoutListItem(workout: Workout, onItemClick: () -> Unit, modifier: Modifier, transformation: SurfaceTransformation) {
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



@OptIn(ExperimentalHorologistApi::class, ExperimentalFoundationApi::class)
@Composable
fun WorkoutSelectionScreen(
    alarmManager: AlarmManager,
    dataClient: DataClient,
    navController: NavController,
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    appHelper: WearDataLayerAppHelper,
    showTutorial: Boolean,
    onDismissTutorial: () -> Unit
) {
    val workouts by viewModel.workouts.collectAsState()

    val sortedWorkouts = workouts.sortedBy { it.order }
    val currentYear = remember { Calendar.getInstance().get(Calendar.YEAR) }

    val userAge by viewModel.userAge
    val context = LocalContext.current
    val versionName = getVersionName(context);

    val canScheduleExactAlarms by rememberCanScheduleExactAlarmsState(context)

    var showClearData by remember { mutableStateOf(false) }
    var showOpenOnPhoneDialog by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    val state: TransformingLazyColumnState = rememberTransformingLazyColumnState()
    val spec = rememberTransformationSpec()

    ScreenScaffold(
        scrollState = state,
    ) { contentPadding ->
        Box {
            TransformingLazyColumn(
                contentPadding = contentPadding,
                state = state,
            ) {
                item {
                    ListHeader(
                        modifier = Modifier
                            .fillMaxWidth()
                            .transformedHeight(this, spec)
                            .animateItem(),
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
                                                "Build version code: $versionName",
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
                                text = "My Workout Assistant",
                                textAlign = TextAlign.Center,
                                style = MaterialTheme.typography.titleMedium,
                                color = MaterialTheme.colorScheme.onBackground
                            )
                        }
                    }
                }

                if (!canScheduleExactAlarms) {
                    item {
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .transformedHeight(this, spec)
                                .animateItem(),
                        ) {
                            Text(
                                modifier = Modifier
                                    .fillMaxWidth(),
                                text = "Enable Alarms for scheduled workouts",
                                textAlign = TextAlign.Center,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurface
                            )
                        }
                    }
                    item {
                        Spacer(modifier = Modifier.height(5.dp))
                    }
                    item {
                        Button(
                            modifier = Modifier
                                .fillMaxWidth()
                                .transformedHeight(this, spec)
                                .animateItem(),
                            transformation = SurfaceTransformation(spec),
                            onClick = {
                                hapticsViewModel.doGentleVibration()
                                val intent = Intent(
                                    Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM,
                                    "package:${context.packageName}".toUri()
                                )

                                context.startActivity(intent)
                            }
                        ) {
                            Text(
                                modifier = Modifier.fillMaxWidth(),
                                text = "Open Alarms Settings",
                                textAlign = TextAlign.Center,
                                style = MaterialTheme.typography.bodyLarge,
                            )
                        }
                    }
                }

                if (userAge == currentYear) {
                    item {
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .transformedHeight(this, spec)
                                .animateItem(),
                        ) {
                            if (viewModel.isPhoneConnectedAndHasApp) {
                                Text(
                                    modifier = Modifier
                                        .fillMaxWidth(),
                                    text = "Input your age on the mobile app",
                                    textAlign = TextAlign.Center,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurface
                                )
                            } else {
                                Text(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(horizontal = 5.dp, vertical = 10.dp),
                                    text = "Install the mobile app on your phone",
                                    textAlign = TextAlign.Center,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurface
                                )
                            }
                        }
                    }
                    item {
                        Spacer(modifier = Modifier.height(5.dp))
                    }
                    item {
                        Button(
                            modifier = Modifier
                                .fillMaxWidth()
                                .transformedHeight(this, spec)
                                .animateItem(),
                            transformation = SurfaceTransformation(spec),
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
                        ) {
                            Text(
                                modifier = Modifier.fillMaxWidth(),
                                text = "Open mobile app",
                                textAlign = TextAlign.Center,
                                style = MaterialTheme.typography.bodyLarge,
                            )
                        }
                    }


                } else {
                    if (sortedWorkouts.isEmpty()) {
                        item {
                            Text(
                                modifier = Modifier.fillMaxWidth(),
                                text = "No Workouts Available",
                                textAlign = TextAlign.Center,
                                style = MaterialTheme.typography.labelLarge,
                            )
                        }
                    } else {
                        items(
                            items = sortedWorkouts,
                            key = { workout -> workout.id }
                        ) { workout ->
                            WorkoutListItem(
                                workout = workout,
                                onItemClick = {
                                    hapticsViewModel.doGentleVibration()
                                    navController.navigate(Screen.WorkoutDetail.route)
                                    viewModel.setSelectedWorkoutId(workout.id)
                                },
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec)
                                    .animateItem(),
                                transformation = SurfaceTransformation(spec)
                            )
                        }
                    }
                }
            }

            TutorialOverlay(
                visible = showTutorial,
                text = "Select a Workout\nTap below to see details and start.\n\nList Header\nLong-press for version info.\nDouble-tap for data tools.",
                onDismiss = onDismissTutorial
            )
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
            title = "Clear Data",
            message = "Do you want to proceed?",
            handleYesClick = {
                hapticsViewModel.doGentleVibration()
                viewModel.resetAll()
                Toast
                    .makeText(
                        context,
                        "Data reset",
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
            holdTimeInMillis = 1000,
            onVisibilityChange = { isVisible ->
                if (isVisible) {
                    viewModel.setDimming(false)
                } else {
                    viewModel.reEvaluateDimmingForCurrentState()
                }
            }
        )
    }
}