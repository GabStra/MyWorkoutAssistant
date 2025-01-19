/* While this template provides a good starting point for using Wear Compose, you can always
 * take a look at https://github.com/android/wear-os-samples/tree/main/ComposeStarter and
 * https://github.com/android/wear-os-samples/tree/main/ComposeAdvanced to find the most up to date
 * changes to the libraries and their usages.
 */

package com.gabstra.myworkoutassistant

import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Bundle
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.wear.compose.material.CircularProgressIndicator
import androidx.wear.compose.material.MaterialTheme
import com.gabstra.myworkoutassistant.composable.KeepOn
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.PolarViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.SensorDataViewModel
import com.gabstra.myworkoutassistant.data.SensorDataViewModelFactory
import com.gabstra.myworkoutassistant.data.cancelWorkoutInProgressNotification
import com.gabstra.myworkoutassistant.presentation.theme.MyWorkoutAssistantTheme
import com.gabstra.myworkoutassistant.repository.SensorDataRepository
import com.gabstra.myworkoutassistant.screens.LoadingScreen
import com.gabstra.myworkoutassistant.screens.WorkoutDetailScreen
import com.gabstra.myworkoutassistant.screens.WorkoutScreen
import com.gabstra.myworkoutassistant.screens.WorkoutSelectionScreen
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.Wearable
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import com.google.android.horologist.data.WearDataLayerRegistry
import com.google.android.horologist.datalayer.watch.WearDataLayerAppHelper
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

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
                throw exception
            }
        }
    }
}

class MainActivity : ComponentActivity() {
    private val dataClient by lazy { Wearable.getDataClient(this) }

    private val workoutStoreRepository by lazy { WorkoutStoreRepository(this.filesDir) }

    private val appViewModel: AppViewModel by viewModels()

    private lateinit var myReceiver: BroadcastReceiver

    @OptIn(ExperimentalHorologistApi::class)
    private lateinit var appHelper: WearDataLayerAppHelper

    override fun onDestroy() {
        super.onDestroy()
        cancelWorkoutInProgressNotification(this)
        if(::myReceiver.isInitialized) {
            unregisterReceiver(myReceiver)
        }
    }

    @OptIn(ExperimentalHorologistApi::class)
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        appViewModel.initDataClient(dataClient)
        val wearDataLayerRegistry  = WearDataLayerRegistry.fromContext(this, lifecycleScope)
        appHelper = WearDataLayerAppHelper(this, wearDataLayerRegistry, lifecycleScope)

        lateinit var myReceiver: MyReceiver

        setContent {
            WearApp(dataClient, appViewModel, appHelper, workoutStoreRepository){ navController ->
                myReceiver = MyReceiver(navController, appViewModel, workoutStoreRepository,this)
                val filter = IntentFilter(DataLayerListenerService.INTENT_ID)
                registerReceiver(myReceiver, filter, RECEIVER_NOT_EXPORTED)
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent) // Update the old intent
    }
}


@OptIn(ExperimentalHorologistApi::class)
@Composable
fun WearApp(dataClient: DataClient, appViewModel: AppViewModel, appHelper: WearDataLayerAppHelper,workoutStoreRepository: WorkoutStoreRepository, onNavControllerAvailable: (NavController) -> Unit) {
    MyWorkoutAssistantTheme {
        val navController = rememberNavController()
        val localContext = LocalContext.current
        appViewModel.initExerciseHistoryDao(localContext)
        appViewModel.initWorkoutHistoryDao(localContext)
        appViewModel.initWorkoutRecordDao(localContext)
        appViewModel.initExerciseInfoDao(localContext)

        var initialized by remember { mutableStateOf(false) }

        LaunchedEffect(Unit) {
            try{
                val workoutStore = workoutStoreRepository.getWorkoutStore()
                appViewModel.updateWorkoutStore(workoutStore)
            }catch(exception: Exception){
                Toast.makeText(localContext, "Failed to load workout repository", Toast.LENGTH_SHORT).show()
            }

            appViewModel.initWorkoutStoreRepository(workoutStoreRepository)
            initialized = true
        }

        onNavControllerAvailable(navController)

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
            LoadingScreen(appViewModel,"Loading workouts")

        }else{
            NavHost(
                navController,
                startDestination = Screen.WorkoutSelection.route,
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
                },
            ) {
                composable(Screen.WorkoutSelection.route) {
                    WorkoutSelectionScreen(dataClient,navController, appViewModel, appHelper)
                }
                composable(Screen.WorkoutDetail.route) {
                    WorkoutDetailScreen(navController, appViewModel, hrViewModel)
                }
                composable(Screen.Workout.route) {
                    val isPaused by appViewModel.isPaused

                    KeepOn(appViewModel,enableDimming = !isPaused){
                        WorkoutScreen(navController,appViewModel,hrViewModel,polarViewModel)
                    }
                }
                composable(Screen.Loading.route) {
                    val progress by appViewModel.backupProgress
                    val animatedProgress by animateFloatAsState(targetValue = progress, label = "")

                    CircularProgressIndicator(
                        progress = animatedProgress,
                        modifier = Modifier.fillMaxSize(),
                        strokeWidth = 4.dp,
                        indicatorColor = MaterialTheme.colors.primary,
                        trackColor = MaterialTheme.colors.background
                    )

                    LoadingScreen(appViewModel,"Syncing with phone")
                }
            }
        }
    }
}