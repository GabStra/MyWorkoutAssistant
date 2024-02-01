/* While this template provides a good starting point for using Wear Compose, you can always
 * take a look at https://github.com/android/wear-os-samples/tree/main/ComposeStarter and
 * https://github.com/android/wear-os-samples/tree/main/ComposeAdvanced to find the most up to date
 * changes to the libraries and their usages.
 */

package com.gabstra.myworkoutassistant

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Bundle
import android.util.Log
import android.view.WindowManager
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.MeasureDataViewModel
import com.gabstra.myworkoutassistant.data.MeasureDataViewModelFactory
import com.gabstra.myworkoutassistant.data.PolarViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.findActivity
import com.gabstra.myworkoutassistant.presentation.theme.MyWorkoutAssistantTheme
import com.gabstra.myworkoutassistant.repository.HealthServicesRepository
import com.gabstra.myworkoutassistant.screens.WorkoutDetailScreen
import com.gabstra.myworkoutassistant.screens.WorkoutScreen
import com.gabstra.myworkoutassistant.screens.WorkoutSelectionScreen
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.fromJSONtoAppBackup
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.Wearable
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import com.google.android.horologist.data.WearDataLayerRegistry
import com.google.android.horologist.datalayer.watch.WearDataLayerAppHelper

class MainActivity : ComponentActivity() {
    private val dataClient by lazy { Wearable.getDataClient(this) }

    private val workoutStoreRepository by lazy { WorkoutStoreRepository(this.filesDir) }

    private val appViewModel: AppViewModel by viewModels()

    private lateinit var myReceiver: BroadcastReceiver

    @OptIn(ExperimentalHorologistApi::class)
    private lateinit var appHelper: WearDataLayerAppHelper

    override fun onStart() {
        super.onStart()
        val filter = IntentFilter(DataLayerListenerService.INTENT_ID)
        registerReceiver(myReceiver, filter, RECEIVER_NOT_EXPORTED)
        appViewModel.updateWorkoutStore(workoutStoreRepository.getWorkoutStore())
    }

    override fun onStop() {
        super.onStop()
        unregisterReceiver(myReceiver)
    }

    @OptIn(ExperimentalHorologistApi::class)
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        appViewModel.initDataClient(dataClient)
        val wearDataLayerRegistry  = WearDataLayerRegistry.fromContext(this, lifecycleScope)
        appHelper = WearDataLayerAppHelper(this, wearDataLayerRegistry, lifecycleScope)

        myReceiver = object : BroadcastReceiver() {
            override fun onReceive(context: Context, intent: Intent) {
                try{
                    val workoutStoreJson = intent.getStringExtra("workoutStoreJson")
                    val appBackupJson = intent.getStringExtra("appBackupJson")

                    if(workoutStoreJson != null || appBackupJson != null){
                        appViewModel.updateWorkoutStore(workoutStoreRepository.getWorkoutStore())
                    }

                    if(workoutStoreJson != null){
                        Toast.makeText(context, "Workouts updated", Toast.LENGTH_SHORT).show()
                    }

                    if(appBackupJson != null){
                        Toast.makeText(context, "Data received", Toast.LENGTH_SHORT).show()
                    }
                }catch (exception: Exception) {
                    Log.d("MainActivity", "Exception: $exception")
                }

            }
        }

        setContent {
            WearApp(dataClient, appViewModel, appHelper)
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent) // Update the old intent

    }
}

@Composable
fun KeepScreenOn() {
    val context = LocalContext.current
    val activity = context.findActivity()
    val window = activity?.window

    DisposableEffect(Unit) {
        window?.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        onDispose {
            window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
    }
}

@OptIn(ExperimentalHorologistApi::class)
@Composable
fun WearApp(dataClient: DataClient, appViewModel: AppViewModel, appHelper: WearDataLayerAppHelper) {
    MyWorkoutAssistantTheme {
        val navController = rememberNavController()
        val localContext = LocalContext.current
        appViewModel.initExerciseHistoryDao(localContext)
        appViewModel.initWorkoutHistoryDao(localContext)

        val hrViewModel: MeasureDataViewModel =  viewModel(
            factory = MeasureDataViewModelFactory(
                healthServicesRepository = HealthServicesRepository(localContext)
            )
        )

        val polarViewModel: PolarViewModel = viewModel()

        val nodes by appHelper.connectedAndInstalledNodes.collectAsState(initial = emptyList())

        LaunchedEffect(nodes){
            appViewModel.phoneNode = nodes.firstOrNull()
        }

        NavHost(navController, startDestination = Screen.WorkoutSelection.route) {
            composable(Screen.WorkoutSelection.route) {
                WorkoutSelectionScreen(dataClient,navController, appViewModel, appHelper)
            }
            composable(Screen.WorkoutDetail.route) {
                WorkoutDetailScreen(navController, appViewModel, hrViewModel)
            }
            composable(Screen.Workout.route) {
                WorkoutScreen(navController,appViewModel,hrViewModel,polarViewModel)
            }
        }
    }
}