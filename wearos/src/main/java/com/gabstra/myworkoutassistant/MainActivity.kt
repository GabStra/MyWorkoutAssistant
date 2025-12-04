/* While this template provides a good starting point for using Wear Compose, you can always
 * take a look at https://github.com/android/wear-os-samples/tree/main/ComposeStarter and
 * https://github.com/android/wear-os-samples/tree/main/ComposeAdvanced to find the most up to date
 * changes to the libraries and their usages.
 */

package com.gabstra.myworkoutassistant

import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlarmManager
import android.app.KeyguardManager
import android.app.NotificationManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Bundle
import android.provider.Settings
import android.util.Log
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
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
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavController
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.wear.compose.material.CircularProgressIndicator
import androidx.wear.compose.material3.MaterialTheme
import com.gabstra.myworkoutassistant.composables.KeepOn
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
import com.gabstra.myworkoutassistant.presentation.theme.MyWorkoutAssistantTheme
import com.gabstra.myworkoutassistant.repository.SensorDataRepository
import com.gabstra.myworkoutassistant.scheduling.WorkoutAlarmScheduler
import com.gabstra.myworkoutassistant.screens.LoadingScreen
import com.gabstra.myworkoutassistant.composables.TutorialOverlay
import com.gabstra.myworkoutassistant.screens.WorkoutDetailScreen
import com.gabstra.myworkoutassistant.screens.WorkoutScreen
import com.gabstra.myworkoutassistant.screens.WorkoutSelectionScreen
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.viewmodels.HeartRateChangeViewModel
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.Wearable
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import com.google.android.horologist.data.WearDataLayerRegistry
import com.google.android.horologist.datalayer.watch.WearDataLayerAppHelper
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.UUID

class MyReceiver(
    private val navController: NavController,
    private val appViewModel: AppViewModel,
    private val workoutStoreRepository: WorkoutStoreRepository,
    private val activity: Activity
) : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        activity.run {
            try{
                val workoutStoreJson = intent.getStringExtra(DataLayerListenerService.WORKOUT_STORE_JSON)
                val appBackupEndJson = intent.getStringExtra(DataLayerListenerService.APP_BACKUP_END_JSON)

                val appBackupStartJson = intent.getStringExtra(DataLayerListenerService.APP_BACKUP_START_JSON)

                val appBackupFailed = intent.getStringExtra(DataLayerListenerService.APP_BACKUP_FAILED)

                val appBackupProgress = intent.getStringExtra(DataLayerListenerService.APP_BACKUP_PROGRESS_UPDATE)

                if(appBackupStartJson != null){
                    appViewModel.setBackupProgress(0f)

                    val currentRoute = navController.currentBackStackEntry?.destination?.route
                    if(currentRoute != Screen.Workout.route) {
                        navController.navigate(Screen.Loading.route)
                    }
                }

                if(workoutStoreJson != null || appBackupEndJson != null){
                    appViewModel.resetWorkoutStore()
                    appViewModel.updateWorkoutStore(workoutStoreRepository.getWorkoutStore())
                }

                if(workoutStoreJson != null){
                    Toast.makeText(context, "Workouts updated", Toast.LENGTH_SHORT).show()
                }

                if(appBackupEndJson != null){
                    val currentRoute = navController.currentBackStackEntry?.destination?.route
                    if(currentRoute != Screen.Workout.route){
                        navController.navigate(Screen.WorkoutSelection.route) {
                            popUpTo(0) { inclusive = true }
                        }
                    }else{
                        //Disabling this for now
                        //appViewModel.RefreshAndGoToLastState()
                    }

                    val scheduler = WorkoutAlarmScheduler(this)
                    scheduler.rescheduleAllWorkouts()
                }

                if (appBackupProgress != null) {
                    val progress = appBackupProgress.toFloat()
                    appViewModel.setBackupProgress(progress)
                }

                if(appBackupFailed != null){
                    val currentRoute = navController.currentBackStackEntry?.destination?.route
                    if(currentRoute == Screen.Loading.route){
                        Toast.makeText(context, "Sync failed", Toast.LENGTH_SHORT).show()
                        navController.navigate(Screen.WorkoutSelection.route) {
                            popUpTo(0) { inclusive = true }
                        }
                    }
                }

            }catch (exception: Exception) {
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

    @OptIn(ExperimentalHorologistApi::class)
    private lateinit var appHelper: WearDataLayerAppHelper

    override fun onDestroy() {
        super.onDestroy()

        // Don't clear isWorkoutInProgress flag here - it's already cleared when the workout
        // actually ends (in WorkoutScreen and WorkoutCompleteScreen). Clearing it here would
        // cause issues when navigating between activities (e.g., WorkoutAlarmActivity launching
        // MainActivity with FLAG_ACTIVITY_CLEAR_TOP) while a workout is still active.

        cancelWorkoutInProgressNotification(this)

        if(::myReceiver.isInitialized) {
            unregisterReceiver(myReceiver)
        }
    }

    override fun onResume() {
        super.onResume()

        val km = getSystemService(KEYGUARD_SERVICE) as KeyguardManager
        if (km.isKeyguardLocked) {
            km.requestDismissKeyguard(this, null) // callback optional
        }

        if(alarmManager.canScheduleExactAlarms()){
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
        val wearDataLayerRegistry  = WearDataLayerRegistry.fromContext(this, lifecycleScope)
        appHelper = WearDataLayerAppHelper(this, wearDataLayerRegistry, lifecycleScope)

        setContent {
            WearApp(dataClient, appViewModel,hapticsViewModel, heartRateChangeViewModel, appHelper, alarmManager, workoutStoreRepository){
                    navController ->
                if(::myReceiver.isInitialized) return@WearApp
                myReceiver = MyReceiver(navController, appViewModel, workoutStoreRepository,this)
                val filter = IntentFilter(DataLayerListenerService.INTENT_ID)
                registerReceiver(myReceiver, filter, RECEIVER_NOT_EXPORTED)
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent) // Update the old intent
        handleNotificationIntent(intent)
    }

    private fun handleNotificationIntent(intent: Intent) {
        Log.d("MainActivity", "Handling notification intent")

        if (intent.hasExtra("WORKOUT_ID")) {
            val workoutId = intent.getStringExtra("WORKOUT_ID")
            val scheduleId = intent.getStringExtra("SCHEDULE_ID")

            notificationManager.cancel(scheduleId.hashCode())

            // Check if a workout is already in progress
            val prefs = getSharedPreferences("workout_state", MODE_PRIVATE)
            val isWorkoutInProgress = prefs.getBoolean("isWorkoutInProgress", false)

            if (isWorkoutInProgress) {
                // A workout is already active, don't start a new one
                Log.d("MainActivity", "Workout already in progress, skipping notification intent")
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

        val navController = rememberNavController()
        val localContext = LocalContext.current
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
            try{
                val workoutStore = workoutStoreRepository.getWorkoutStore()
                appViewModel.updateWorkoutStore(workoutStore)
            }catch(exception: Exception){
                Log.e("MainActivity", "Failed to load workout repository", exception)
                Toast.makeText(localContext, "Failed to load workout repository", Toast.LENGTH_SHORT).show()
            }

            try {
                tutorialState = TutorialPreferences.load(localContext)
                startDestination = Screen.WorkoutSelection.route

                showWorkoutSelectionTutorial = !tutorialState.hasSeenWorkoutSelectionTutorial
                showWorkoutHeartRateTutorial = !tutorialState.hasSeenWorkoutHeartRateTutorial
                showSetScreenTutorial = !tutorialState.hasSeenSetScreenTutorial
                showRestScreenTutorial = !tutorialState.hasSeenRestScreenTutorial

                appViewModel.initWorkoutStoreRepository(workoutStoreRepository)

                val now = System.currentTimeMillis()
                if(now - startTime < 2000){
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
            if(appViewModel.executeStartWorkout.value == null) return@LaunchedEffect
            
            try {
                // Check if a workout is already in progress
                val prefs = localContext.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
                val isWorkoutInProgress = prefs.getBoolean("isWorkoutInProgress", false)
                
                val workoutStore = workoutStoreRepository.getWorkoutStore()
                val workout = workoutStore.workouts.find { it.globalId == appViewModel.executeStartWorkout.value }
                
                if (workout == null) {
                    Log.e("MainActivity", "Workout not found for id: ${appViewModel.executeStartWorkout.value}")
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

        val hrViewModel: SensorDataViewModel =  viewModel(
            factory = SensorDataViewModelFactory(
                sensorDataRepository = SensorDataRepository(localContext)
            )
        )
        hrViewModel.initApplicationContext(localContext)

        val polarViewModel: PolarViewModel = viewModel()

        val nodes by appHelper.connectedAndInstalledNodes.collectAsState(initial = emptyList())

        LaunchedEffect(nodes){
            try {
                appViewModel.phoneNode = nodes.firstOrNull()
                if(appViewModel.phoneNode != null){
                    //appViewModel.sendAll(localContext)
                }
            } catch (exception: Exception) {
                Log.e("MainActivity", "Error handling nodes update", exception)
            }
        }

        // Note: Swipe-to-dismiss prevention is handled in WorkoutScreen using BackHandler
        // Programmatic control via reflection is not reliable across all Wear OS versions

        if(!initialized || startDestination == null){
            LoadingScreen(appViewModel)
        }else{
            val enableDimming by appViewModel.enableDimming
            KeepOn(appViewModel,enableDimming = enableDimming){
                NavHost(
                    modifier = Modifier
                        .fillMaxSize(),
                    navController = navController,
                    startDestination = startDestination!!,
                    enterTransition = {
                        fadeIn(animationSpec = tween(500))
                    },
                    exitTransition = {
                        fadeOut(animationSpec = tween(500))
                    },
                    popEnterTransition= {
                        fadeIn(animationSpec = tween(500))
                    },
                    popExitTransition = {
                        fadeOut(animationSpec = tween(500))
                    }
                ) {
                    composable(Screen.WorkoutSelection.route) {
                        if (showWorkoutSelectionTutorial) {
                            TutorialOverlay(
                                visible = true,
                                text = "Select a Workout\nTap below to see details and start.\n\nList Header\nLong-press for version info.\nDouble-tap for data tools.",
                                onDismiss = {
                                    showWorkoutSelectionTutorial = false
                                    tutorialState = TutorialPreferences.update(localContext, tutorialState) {
                                        it.copy(hasSeenWorkoutSelectionTutorial = true)
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
                        WorkoutDetailScreen(navController, appViewModel, hapticsViewModel,hrViewModel)
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
                                tutorialState = TutorialPreferences.update(localContext, tutorialState) {
                                    it.copy(hasSeenWorkoutHeartRateTutorial = true)
                                }
                            },
                            showSetScreenTutorial = showSetScreenTutorial,
                            onDismissSetScreenTutorial = {
                                showSetScreenTutorial = false
                                tutorialState = TutorialPreferences.update(localContext, tutorialState) {
                                    it.copy(hasSeenSetScreenTutorial = true)
                                }
                            },
                            showRestScreenTutorial = showRestScreenTutorial,
                            onDismissRestScreenTutorial = {
                                showRestScreenTutorial = false
                                tutorialState = TutorialPreferences.update(localContext, tutorialState) {
                                    it.copy(hasSeenRestScreenTutorial = true)
                                }
                            }
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
                            trackColor = MaterialTheme.colorScheme.surfaceContainerHigh,
                        )

                        LoadingScreen(appViewModel,"Syncing with phone")
                    }
                }
            }
        }
    }
}
