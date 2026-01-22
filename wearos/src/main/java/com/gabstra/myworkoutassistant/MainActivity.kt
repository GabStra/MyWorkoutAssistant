/* While this template provides a good starting point for using Wear Compose, you can always
 * take a look at https://github.com/android/wear-os-samples/tree/main/ComposeStarter and
 * https://github.com/android/wear-os-samples/tree/main/ComposeAdvanced to find the most up to date
 * changes to the libraries and their usages.
 */

package com.gabstra.myworkoutassistant

import android.app.Activity
import android.app.AlarmManager
import android.app.KeyguardManager
import android.app.NotificationManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.util.Log
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.net.toUri
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavController
import androidx.navigation.NavHostController
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.wear.compose.material.CircularProgressIndicator
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.navigation.SwipeDismissableNavHost
import androidx.wear.compose.navigation.composable
import androidx.wear.compose.navigation.rememberSwipeDismissableNavController
import com.gabstra.myworkoutassistant.composables.EdgeSwipeBackHandler
import com.gabstra.myworkoutassistant.composables.KeepOn
import com.gabstra.myworkoutassistant.composables.ResumeWorkoutDialog
import com.gabstra.myworkoutassistant.composables.TutorialOverlay
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModelFactory
import com.gabstra.myworkoutassistant.data.PolarViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.data.SensorDataViewModelFactory
import com.gabstra.myworkoutassistant.data.TutorialPreferences
import com.gabstra.myworkoutassistant.data.TutorialState
import com.gabstra.myworkoutassistant.data.cancelWorkoutInProgressNotification
import com.gabstra.myworkoutassistant.data.findActivity
import com.gabstra.myworkoutassistant.data.sendErrorLogsToMobile
import com.gabstra.myworkoutassistant.presentation.theme.MyWorkoutAssistantTheme
import com.gabstra.myworkoutassistant.repository.SensorDataRepository
import com.gabstra.myworkoutassistant.scheduling.WorkoutAlarmScheduler
import com.gabstra.myworkoutassistant.screens.LoadingScreen
import com.gabstra.myworkoutassistant.screens.WorkoutDetailScreen
import com.gabstra.myworkoutassistant.screens.WorkoutScreen
import com.gabstra.myworkoutassistant.screens.WorkoutSelectionScreen
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.viewmodels.HeartRateChangeViewModel
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.Wearable
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import com.google.android.horologist.data.WearDataLayerRegistry
import com.google.android.horologist.datalayer.watch.WearDataLayerAppHelper
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.UUID

class MyReceiver(
    private val navController: NavController,
    private val appViewModel: AppViewModel,
    private val workoutStoreRepository: WorkoutStoreRepository,
    private val activity: Activity
) : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        activity.run {
            try {
                val workoutStoreJson =
                    intent.getStringExtra(DataLayerListenerService.WORKOUT_STORE_JSON)
                val appBackupEndJson =
                    intent.getStringExtra(DataLayerListenerService.APP_BACKUP_END_JSON)

                val appBackupStartJson =
                    intent.getStringExtra(DataLayerListenerService.APP_BACKUP_START_JSON)

                val appBackupFailed =
                    intent.getStringExtra(DataLayerListenerService.APP_BACKUP_FAILED)

                val appBackupProgress =
                    intent.getStringExtra(DataLayerListenerService.APP_BACKUP_PROGRESS_UPDATE)

                val syncComplete =
                    intent.getStringExtra(DataLayerListenerService.SYNC_COMPLETE)

                if (appBackupStartJson != null) {
                    Log.d("DataLayerSync", "Received APP_BACKUP_START_JSON - triggering loading screen")
                    appViewModel.setBackupProgress(0f)

                    val currentRoute = navController.currentBackStackEntry?.destination?.route
                    if (currentRoute != Screen.Workout.route) {
                        navController.navigate(Screen.Loading.route)
                    }
                }

                if (workoutStoreJson != null || appBackupEndJson != null) {
                    appViewModel.resetWorkoutStore()
                    appViewModel.updateWorkoutStore(workoutStoreRepository.getWorkoutStore())
                }

                if (workoutStoreJson != null) {
                    Toast.makeText(context, "Workouts updated", Toast.LENGTH_SHORT).show()
                }

                if (appBackupEndJson != null) {
                    Log.d("DataLayerSync", "Received APP_BACKUP_END_JSON - dismissing loading screen")
                    val currentRoute = navController.currentBackStackEntry?.destination?.route
                    if (currentRoute != Screen.Workout.route) {
                        navController.navigate(Screen.WorkoutSelection.route) {
                            popUpTo(0) { inclusive = true }
                        }
                    }

                    val scheduler = WorkoutAlarmScheduler(this)
                    scheduler.rescheduleAllWorkouts()
                }

                if (appBackupProgress != null) {
                    val progress = appBackupProgress.toFloat()
                    appViewModel.setBackupProgress(progress)
                }

                if (syncComplete != null) {
                    Log.d("DataLayerSync", "Received SYNC_COMPLETE - checking syncStatus before showing toast")
                    // Only show toast if SyncStatusBadge is not showing "Syncing..." and workout is not active
                    val workoutState = appViewModel.workoutState.value
                    val isWorkoutActive = workoutState !is WorkoutState.Completed
                    if (appViewModel.syncStatus.value != AppViewModel.SyncStatus.Syncing && !isWorkoutActive) {
                        Toast.makeText(context, "Sync completed", Toast.LENGTH_SHORT).show()
                    }
                }

                if (appBackupFailed != null) {
                    Log.d("DataLayerSync", "Received APP_BACKUP_FAILED - sync failed")
                    // Reset backup progress state and sync status
                    appViewModel.setBackupProgress(0f)
                    appViewModel.resetSyncStatus() // Clear stuck sync state
                    val currentRoute = navController.currentBackStackEntry?.destination?.route
                    if (currentRoute == Screen.Loading.route) {
                        navController.navigate(Screen.WorkoutSelection.route) {
                            popUpTo(0) { inclusive = true }
                        }
                    }
                    // Only show toast if SyncStatusBadge is not showing "Syncing..." and workout is not active
                    val workoutState = appViewModel.workoutState.value
                    val isWorkoutActive = workoutState !is WorkoutState.Completed
                    if (appViewModel.syncStatus.value != AppViewModel.SyncStatus.Syncing && !isWorkoutActive) {
                        Toast.makeText(context, "Sync failed", Toast.LENGTH_SHORT).show()
                    }
                }

            } catch (exception: Exception) {
                Log.e("MyReceiver", "Error processing data", exception)
            }
        }
    }
}

class MainActivity : ComponentActivity() {
    private val alarmManager by lazy { getSystemService(ALARM_SERVICE) as AlarmManager }

    private val notificationManager by lazy { getSystemService(NOTIFICATION_SERVICE) as NotificationManager }

    private val dataClient by lazy { Wearable.getDataClient(this) }

    private val workoutStoreRepository by lazy { WorkoutStoreRepository(this.filesDir) }

    private val appViewModel: AppViewModel by viewModels()

    private val hapticsViewModel: HapticsViewModel by viewModels {
        HapticsViewModelFactory(applicationContext)
    }

    private val heartRateChangeViewModel: HeartRateChangeViewModel by viewModels()

    private lateinit var myReceiver: BroadcastReceiver
    private lateinit var errorLogReceiver: BroadcastReceiver

    @OptIn(ExperimentalHorologistApi::class)
    private lateinit var appHelper: WearDataLayerAppHelper

    override fun onDestroy() {
        super.onDestroy()

        // Don't clear isWorkoutInProgress flag here - it's already cleared when the workout
        // actually ends (in WorkoutScreen and WorkoutCompleteScreen). Clearing it here would
        // cause issues when navigating between activities (e.g., WorkoutAlarmActivity launching
        // MainActivity with FLAG_ACTIVITY_CLEAR_TOP) while a workout is still active.

        cancelWorkoutInProgressNotification(this)

        if (::myReceiver.isInitialized) {
            unregisterReceiver(myReceiver)
        }
        if (::errorLogReceiver.isInitialized) {
            unregisterReceiver(errorLogReceiver)
        }
    }

    override fun onResume() {
        super.onResume()

        val km = getSystemService(KEYGUARD_SERVICE) as KeyguardManager
        if (km.isKeyguardLocked) {
            km.requestDismissKeyguard(this, null) // callback optional
        }

        if (alarmManager.canScheduleExactAlarms()) {
            val scheduler = WorkoutAlarmScheduler(this)
            scheduler.rescheduleAllWorkouts()
        }
    }

    @OptIn(ExperimentalHorologistApi::class)
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        appViewModel.initApplicationContext(applicationContext)

        val nm = this.getSystemService(NotificationManager::class.java)
        if (!nm.canUseFullScreenIntent()) {
            this.startActivity(
                Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT)
                    .setData("package:${this.packageName}".toUri())
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
        }

        lifecycleScope.launch(Dispatchers.IO) {
            val prefs = getSharedPreferences("workout_state", MODE_PRIVATE)
            prefs.getBoolean("isWorkoutInProgress", false)
        }

        setShowWhenLocked(true)
        setTurnScreenOn(true)

        // Handle intent if app was launched from notification
        handleNotificationIntent(intent)

        appViewModel.initDataClient(dataClient)
        val wearDataLayerRegistry = WearDataLayerRegistry.fromContext(this, lifecycleScope)
        appHelper = WearDataLayerAppHelper(this, wearDataLayerRegistry, lifecycleScope)

        // Add lifecycle observer to flush pending syncs on pause/stop
        lifecycle.addObserver(object : LifecycleEventObserver {
            override fun onStateChanged(source: LifecycleOwner, event: Lifecycle.Event) {
                when (event) {
                    Lifecycle.Event.ON_PAUSE -> {
                        lifecycleScope.launch {
                            appViewModel.flushWorkoutSync()
                        }
                    }
                    Lifecycle.Event.ON_STOP -> {
                        lifecycleScope.launch {
                            appViewModel.flushWorkoutSync()
                        }
                    }
                    else -> {}
                }
            }
        })

        setContent {
            WearApp(
                dataClient,
                appViewModel,
                hapticsViewModel,
                heartRateChangeViewModel,
                appHelper,
                alarmManager,
                workoutStoreRepository
            ) { navController ->
                if (::myReceiver.isInitialized) return@WearApp
                myReceiver = MyReceiver(navController, appViewModel, workoutStoreRepository, this)
                val filter = IntentFilter(DataLayerListenerService.INTENT_ID)
                registerReceiver(myReceiver, filter, RECEIVER_NOT_EXPORTED)
                
                // Register receiver for error log sync
                errorLogReceiver = object : BroadcastReceiver() {
                    override fun onReceive(context: Context, intent: Intent) {
                        if (intent.action == MyApplication.ERROR_LOGGED_ACTION) {
                            lifecycleScope.launch(Dispatchers.IO) {
                                try {
                                    val errorLogs = (applicationContext as? MyApplication)?.getErrorLogs() ?: emptyList()
                                    if (errorLogs.isNotEmpty()) {
                                        val success = sendErrorLogsToMobile(dataClient, errorLogs)
                                        if (success) {
                                            withContext(Dispatchers.Main) {
                                                Toast.makeText(
                                                    this@MainActivity,
                                                    "Synced ${errorLogs.size} error log(s) to mobile",
                                                    Toast.LENGTH_SHORT
                                                ).show()
                                            }
                                            (applicationContext as? MyApplication)?.clearErrorLogs()
                                        }
                                    }
                                } catch (exception: Exception) {
                                    Log.e("MainActivity", "Error syncing error logs on error", exception)
                                }
                            }
                        }
                    }
                }
                val errorLogFilter = IntentFilter(MyApplication.ERROR_LOGGED_ACTION)
                registerReceiver(errorLogReceiver, errorLogFilter, RECEIVER_NOT_EXPORTED)
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent) // Update the old intent
        handleNotificationIntent(intent)
    }

    private fun handleNotificationIntent(intent: Intent) {
        if (intent.hasExtra("WORKOUT_ID")) {
            val workoutId = intent.getStringExtra("WORKOUT_ID")
            val scheduleId = intent.getStringExtra("SCHEDULE_ID")

            notificationManager.cancel(scheduleId.hashCode())

            // Check if a workout is already in progress
            val prefs = getSharedPreferences("workout_state", MODE_PRIVATE)
            val isWorkoutInProgress = prefs.getBoolean("isWorkoutInProgress", false)

            if (isWorkoutInProgress) {
                return
            }

            if (workoutId != null) {
                val uuid = UUID.fromString(workoutId)

                val workoutStore = workoutStoreRepository.getWorkoutStore()
                val workout = workoutStore.workouts.find { it.globalId == uuid }

                if (workout != null) {
                    appViewModel.triggerStartWorkout(uuid)
                }
            }
        }
    }
}

@OptIn(ExperimentalHorologistApi::class)
@Composable
fun WearApp(
    dataClient: DataClient,
    appViewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    heartRateChangeViewModel: HeartRateChangeViewModel,
    appHelper: WearDataLayerAppHelper,
    alarmManager: AlarmManager,
    workoutStoreRepository: WorkoutStoreRepository,
    onNavControllerAvailable: (NavHostController) -> Unit
) {
    MyWorkoutAssistantTheme {
        val localContext = LocalContext.current
        val navController = rememberSwipeDismissableNavController()
        val navBackStackEntry by navController.currentBackStackEntryAsState()
        val currentRoute = navBackStackEntry?.destination?.route
        val userSwipeEnabled = currentRoute != null &&
            currentRoute != Screen.Workout.route &&
            currentRoute != Screen.Loading.route
        val enableManualSwipe =
            userSwipeEnabled && Build.VERSION.SDK_INT > Build.VERSION_CODES.VANILLA_ICE_CREAM
        val activity = localContext.findActivity()
        LaunchedEffect(currentRoute, userSwipeEnabled) {
            Log.d(
                "MainActivity",
                "SwipeDismissableNavHost userSwipeEnabled=$userSwipeEnabled route=$currentRoute"
            )
        }

        appViewModel.initExerciseHistoryDao(localContext)
        appViewModel.initWorkoutHistoryDao(localContext)
        appViewModel.initWorkoutScheduleDao(localContext)
        appViewModel.initWorkoutRecordDao(localContext)
        appViewModel.initExerciseInfoDao(localContext)
        appViewModel.initExerciseSessionProgressionDao(localContext)

        var initialized by remember { mutableStateOf(false) }

        var startDestination by remember { mutableStateOf<String?>(null) }

        var tutorialState by remember { mutableStateOf(TutorialState()) }

        var showWorkoutSelectionTutorial by remember { mutableStateOf(false) }
        var showWorkoutHeartRateTutorial by remember { mutableStateOf(false) }
        var showSetScreenTutorial by remember { mutableStateOf(false) }
        var showRestScreenTutorial by remember { mutableStateOf(false) }

        LaunchedEffect(Unit) {
            val startTime = System.currentTimeMillis()
            try {
                val workoutStore = workoutStoreRepository.getWorkoutStore()
                appViewModel.updateWorkoutStore(workoutStore)
            } catch (exception: Exception) {
                Log.e("MainActivity", "Failed to load workout repository", exception)
                Toast.makeText(
                    localContext,
                    "Failed to load workout repository",
                    Toast.LENGTH_SHORT
                ).show()
            }

            try {
                tutorialState = TutorialPreferences.load(localContext)
                startDestination = Screen.WorkoutSelection.route

                showWorkoutSelectionTutorial = !tutorialState.hasSeenWorkoutSelectionTutorial
                showWorkoutHeartRateTutorial = !tutorialState.hasSeenWorkoutHeartRateTutorial
                showSetScreenTutorial = !tutorialState.hasSeenSetScreenTutorial
                showRestScreenTutorial = !tutorialState.hasSeenRestScreenTutorial
                //showCoachmarks = !tutorialState.hasSeenCoachmarkTutorial

                if (!tutorialState.hasSeenCoachmarkTutorial) {
                    tutorialState = TutorialPreferences.update(localContext, tutorialState) {
                        it.copy(hasSeenCoachmarkTutorial = true)
                    }
                }

                appViewModel.initWorkoutStoreRepository(workoutStoreRepository)

                // Check for incomplete workouts
                val prefs = localContext.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
                val isWorkoutInProgress = prefs.getBoolean("isWorkoutInProgress", false)

                if (!isWorkoutInProgress) {
                    try {
                        val incompleteWorkouts = appViewModel.getIncompleteWorkouts()
                        if (incompleteWorkouts.isNotEmpty()) {
                            appViewModel.showResumeWorkoutDialog(incompleteWorkouts)
                        }
                    } catch (exception: Exception) {
                        Log.e("MainActivity", "Error checking for incomplete workouts", exception)
                    }
                }

                val now = System.currentTimeMillis()
                if (now - startTime < 2000) {
                    delay(2000 - (now - startTime))
                }

                initialized = true

                onNavControllerAvailable(navController)
            } catch (exception: Exception) {
                Log.e("MainActivity", "Error initializing workout store repository", exception)
                initialized = true // Still set initialized to prevent blocking the UI
            }
        }

        LaunchedEffect(appViewModel.executeStartWorkout) {
            if (appViewModel.executeStartWorkout.value == null) return@LaunchedEffect

            try {
                // Check if a workout is already in progress
                val prefs =
                    localContext.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
                val isWorkoutInProgress = prefs.getBoolean("isWorkoutInProgress", false)

                val workoutStore = workoutStoreRepository.getWorkoutStore()
                val workout =
                    workoutStore.workouts.find { it.globalId == appViewModel.executeStartWorkout.value }

                if (workout == null) {
                    Log.e(
                        "MainActivity",
                        "Workout not found for id: ${appViewModel.executeStartWorkout.value}"
                    )
                    return@LaunchedEffect
                }

                appViewModel.setSelectedWorkoutId(workout.id)

                if (isWorkoutInProgress) {
                    // A workout is already active, navigate to WorkoutScreen instead
                    startDestination = Screen.Workout.route
                    navController.navigate(Screen.Workout.route) {
                        popUpTo(0) { inclusive = true }
                    }
                } else {
                    startDestination = Screen.WorkoutDetail.route
                }
            } catch (exception: Exception) {
                Log.e("MainActivity", "Error executing start workout", exception)
            }
        }

        val hrViewModel: SensorDataViewModel = viewModel(
            factory = SensorDataViewModelFactory(
                sensorDataRepository = SensorDataRepository(localContext)
            )
        )
        hrViewModel.initApplicationContext(localContext)

        val polarViewModel: PolarViewModel = viewModel()

        val nodes by appHelper.connectedAndInstalledNodes.collectAsState(initial = emptyList())

        LaunchedEffect(nodes) {
            try {
                val phoneNode = nodes.firstOrNull()
                appViewModel.phoneNode = phoneNode
                appViewModel.onPhoneConnectionChanged(phoneNode != null)
                if (appViewModel.phoneNode != null) {
                    //appViewModel.sendAll(localContext)
                }
            } catch (exception: Exception) {
                Log.e("MainActivity", "Error handling nodes update", exception)
            }
        }

        // Sync error logs when app opens and phone is connected
        LaunchedEffect(nodes) {
            val phoneNode = nodes.firstOrNull() ?: return@LaunchedEffect

            launch(Dispatchers.IO) {
                try {
                    val errorLogs =
                        (localContext.applicationContext as? MyApplication)?.getErrorLogs()
                            ?: emptyList()
                    if (errorLogs.isNotEmpty()) {
                        val success = sendErrorLogsToMobile(dataClient, errorLogs)
                        if (success) {
                            withContext(Dispatchers.Main) {
                                Toast.makeText(
                                    localContext,
                                    "Sent ${errorLogs.size} error log(s) to mobile",
                                    Toast.LENGTH_SHORT
                                ).show()
                            }
                        } else {
                            Log.e("MainActivity", "Failed to sync error logs to mobile")
                        }
                    }
                } catch (exception: Exception) {
                    Log.e("MainActivity", "Error syncing error logs", exception)
                }
            }
        }

        if (!initialized || startDestination == null) {
            LoadingScreen(appViewModel)
        } else {
            val enableDimming by appViewModel.enableDimming
            KeepOn(appViewModel, enableDimming = enableDimming) {
                EdgeSwipeBackHandler(
                    enabled = enableManualSwipe,
                    onSwipe = {
                        val swipeRoute = navController.currentBackStackEntry?.destination?.route
                        if (swipeRoute == Screen.WorkoutSelection.route) {
                            Toast.makeText(localContext, "Returning to watch face", Toast.LENGTH_SHORT).show()
                            activity?.finish()
                        } else {
                            navController.popBackStack()
                        }
                    }
                ) {
                    SwipeDismissableNavHost(
                        modifier = Modifier.fillMaxSize(),
                        navController = navController,
                        startDestination = startDestination!!,
                        userSwipeEnabled = userSwipeEnabled
                    ) {
                        composable(Screen.WorkoutSelection.route) {
                            if (showWorkoutSelectionTutorial) {
                                TutorialOverlay(
                                    visible = true,
                                    text = "Welcome!\nTap any workout to see details and start.\n\nQuick tips\nLong-press the header for app info.\nDouble-tap the header for sync tools.",
                                    onDismiss = {
                                        showWorkoutSelectionTutorial = false
                                        tutorialState = TutorialPreferences.update(
                                            localContext,
                                            tutorialState
                                        ) {
                                            it.copy(hasSeenWorkoutSelectionTutorial = true)
                                        }
                                    },
                                    hapticsViewModel = hapticsViewModel,
                                    onVisibilityChange = { isVisible ->
                                        if (isVisible) {
                                            appViewModel.setDimming(false)
                                        } else {
                                            appViewModel.reEvaluateDimmingForCurrentState()
                                        }
                                    }
                                )
                            } else {
                                WorkoutSelectionScreen(
                                    alarmManager,
                                    dataClient,
                                    navController,
                                    appViewModel,
                                    hapticsViewModel,
                                    appHelper,
                                )
                            }
                        }
                        composable(Screen.WorkoutDetail.route) {
                            WorkoutDetailScreen(
                                navController,
                                appViewModel,
                                hapticsViewModel,
                                hrViewModel
                            )
                        }
                        composable(Screen.Workout.route) {
                            WorkoutScreen(
                                navController,
                                appViewModel,
                                hapticsViewModel,
                                heartRateChangeViewModel,
                                hrViewModel,
                                polarViewModel,
                                showHeartRateTutorial = showWorkoutHeartRateTutorial,
                                onDismissHeartRateTutorial = {
                                    showWorkoutHeartRateTutorial = false
                                    tutorialState =
                                        TutorialPreferences.update(
                                            localContext,
                                            tutorialState
                                        ) {
                                            it.copy(hasSeenWorkoutHeartRateTutorial = true)
                                        }
                                },
                                showSetScreenTutorial = showSetScreenTutorial,
                                onDismissSetScreenTutorial = {
                                    showSetScreenTutorial = false
                                    tutorialState =
                                        TutorialPreferences.update(
                                            localContext,
                                            tutorialState
                                        ) {
                                            it.copy(hasSeenSetScreenTutorial = true)
                                        }
                                },
                                showRestScreenTutorial = showRestScreenTutorial,
                                onDismissRestScreenTutorial = {
                                    showRestScreenTutorial = false
                                    tutorialState =
                                        TutorialPreferences.update(
                                            localContext,
                                            tutorialState
                                        ) {
                                            it.copy(hasSeenRestScreenTutorial = true)
                                        }
                                },
                            )
                        }
                        composable(Screen.Loading.route) {
                            val progress by appViewModel.backupProgress
                            val animatedProgress by animateFloatAsState(
                                targetValue = progress,
                                animationSpec = tween(durationMillis = 400)
                            )

                            CircularProgressIndicator(
                                progress = animatedProgress,
                                modifier = Modifier
                                    .fillMaxSize(),
                                strokeWidth = 4.dp,
                                indicatorColor = MaterialTheme.colorScheme.primary,
                                trackColor = MediumDarkGray,
                            )

                            LoadingScreen(appViewModel, "Syncing with phone")
                        }
                    }
                }
            }

            // Resume workout dialog
            val showResumeDialog by appViewModel.showResumeWorkoutDialog
            val incompleteWorkouts by appViewModel.incompleteWorkouts

            val basePermissions = listOf(
                android.Manifest.permission.BODY_SENSORS,
                android.Manifest.permission.BLUETOOTH_SCAN,
                android.Manifest.permission.BLUETOOTH_CONNECT,
                android.Manifest.permission.ACCESS_FINE_LOCATION,
                android.Manifest.permission.ACCESS_COARSE_LOCATION,
                android.Manifest.permission.POST_NOTIFICATIONS
            )

            val permissionLauncherResume =
                androidx.activity.compose.rememberLauncherForActivityResult(
                    androidx.activity.result.contract.ActivityResultContracts.RequestMultiplePermissions()
                ) { result ->
                    if (result.all { it.value }) {
                        val workoutId = appViewModel.selectedWorkoutId.value
                        if (workoutId != null) {
                            appViewModel.resumeWorkoutFromRecord()
                            val prefs = localContext.getSharedPreferences(
                                "workout_state",
                                Context.MODE_PRIVATE
                            )
                            prefs.edit()
                                .putBoolean("isWorkoutInProgress", true)
                                .apply()
                            navController.navigate(Screen.Workout.route)
                        }
                    }
                }

            ResumeWorkoutDialog(
                show = showResumeDialog,
                hapticsViewModel = hapticsViewModel,
                incompleteWorkouts = incompleteWorkouts,
                onDismiss = {
                    appViewModel.hideResumeWorkoutDialog()
                },
                onResumeWorkout = { incompleteWorkout ->
                    appViewModel.hideResumeWorkoutDialog()
                    appViewModel.prepareResumeWorkout(incompleteWorkout)
                    permissionLauncherResume.launch(basePermissions.toTypedArray())
                }
            )
        }
    }
}
