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
import android.os.Bundle
import android.provider.Settings
import android.util.Log
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
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
import androidx.core.content.edit
import androidx.core.net.toUri
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavController
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
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
import com.gabstra.myworkoutassistant.data.cancelWorkoutInProgressNotification
import com.gabstra.myworkoutassistant.presentation.theme.MyWorkoutAssistantTheme
import com.gabstra.myworkoutassistant.repository.SensorDataRepository
import com.gabstra.myworkoutassistant.scheduling.WorkoutAlarmScheduler
import com.gabstra.myworkoutassistant.screens.LoadingScreen
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

        val prefs = getSharedPreferences("workout_state", MODE_PRIVATE)
        val isWorkoutInProgress = prefs.getBoolean("isWorkoutInProgress", false)

        if(isWorkoutInProgress){
            prefs.edit { putBoolean("isWorkoutInProgress", false) }
        }

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

        var initialized by remember { mutableStateOf(false) }

        var startDestination by remember { mutableStateOf(Screen.WorkoutSelection.route) }

        LaunchedEffect(Unit) {
            val startTime = System.currentTimeMillis()
            try{
                val workoutStore = workoutStoreRepository.getWorkoutStore()
                appViewModel.updateWorkoutStore(workoutStore)
            }catch(exception: Exception){
                Toast.makeText(localContext, "Failed to load workout repository", Toast.LENGTH_SHORT).show()
            }

            appViewModel.initWorkoutStoreRepository(workoutStoreRepository)

            val now = System.currentTimeMillis()
            if(now - startTime < 2000){
                delay(2000 - (now - startTime))
            }

            initialized = true

            onNavControllerAvailable(navController)
        }

        LaunchedEffect(appViewModel.executeStartWorkout) {
            if(appViewModel.executeStartWorkout.value == null) return@LaunchedEffect
            val workoutStore = workoutStoreRepository.getWorkoutStore()
            val workout = workoutStore.workouts.find { it.globalId == appViewModel.executeStartWorkout.value }!!
            appViewModel.setSelectedWorkoutId(workout.id)
            startDestination = Screen.WorkoutDetail.route
        }

        val hrViewModel: SensorDataViewModel =  viewModel(
            factory = SensorDataViewModelFactory(
                sensorDataRepository = SensorDataRepository(localContext)
            )
        )

        val polarViewModel: PolarViewModel = viewModel()

        val nodes by appHelper.connectedAndInstalledNodes.collectAsState(initial = emptyList())

        LaunchedEffect(nodes){
            appViewModel.phoneNode = nodes.firstOrNull()
            if(appViewModel.phoneNode != null){
                //appViewModel.sendAll(localContext)
            }
        }

        if(!initialized){
            LoadingScreen(appViewModel)
        }else{
            val enableDimming by appViewModel.enableDimming
            KeepOn(appViewModel,enableDimming = enableDimming){
                NavHost(
                    modifier = Modifier
                        .fillMaxSize(),
                    navController = navController,
                    startDestination = startDestination,
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
                        WorkoutSelectionScreen(alarmManager,dataClient,navController, appViewModel,hapticsViewModel, appHelper)
                    }
                    composable(Screen.WorkoutDetail.route) {
                        WorkoutDetailScreen(navController, appViewModel, hapticsViewModel,hrViewModel)
                    }
                    composable(Screen.Workout.route) {
                        WorkoutScreen(navController,appViewModel,hapticsViewModel,heartRateChangeViewModel,hrViewModel,polarViewModel)
                    }
                    composable(Screen.Loading.route) {
                        val progress by appViewModel.backupProgress

                        CircularProgressIndicator(
                            progress = progress,
                            modifier = Modifier
                                .fillMaxSize(),
                            strokeWidth = 4.dp,
                            indicatorColor = MaterialTheme.colorScheme.primary,
                            trackColor = MaterialTheme.colorScheme.surfaceContainer,
                        )

                        LoadingScreen(appViewModel,"Syncing with phone")
                    }
                }
            }
        }
    }
}
