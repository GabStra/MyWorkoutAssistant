/* While this template provides a good starting point for using Wear Compose, you can always
 * take a look at https://github.com/android/wear-os-samples/tree/main/ComposeStarter and
 * https://github.com/android/wear-os-samples/tree/main/ComposeAdvanced to find the most up to date
 * changes to the libraries and their usages.
 */

package com.gabstra.myworkoutassistant.presentation

import android.os.Bundle
import android.view.WindowManager
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.gabstra.myhomeworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.MeasureDataViewModel
import com.gabstra.myworkoutassistant.data.MeasureDataViewModelFactory
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.data.findActivity
import com.gabstra.myworkoutassistant.data.getEnabledItems
import com.gabstra.myworkoutassistant.presentation.theme.MyWorkoutAssistantTheme
import com.gabstra.myworkoutassistant.repository.HealthServicesRepository
import com.gabstra.myworkoutassistant.screens.WorkoutDetailScreen
import com.gabstra.myworkoutassistant.screens.WorkoutScreen
import com.gabstra.myworkoutassistant.screens.WorkoutSelectionScreen
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.DataEvent
import com.google.android.gms.wearable.DataEventBuffer
import com.google.android.gms.wearable.DataMapItem
import com.google.android.gms.wearable.Wearable

class MainActivity : ComponentActivity(), DataClient.OnDataChangedListener{
    private val dataClient by lazy { Wearable.getDataClient(this) }

    private val workoutStoreRepository by lazy { WorkoutStoreRepository(this.filesDir) }

    private val appViewModel: AppViewModel by viewModels()

    override fun onDataChanged(dataEvents: DataEventBuffer) {
        for (event in dataEvents) {
            if (event.type == DataEvent.TYPE_CHANGED) {
                when(event.dataItem.uri.path){
                    "/workoutStore" -> {
                        val dataMap = DataMapItem.fromDataItem(event.dataItem).dataMap
                        val workoutStoreJson = dataMap.getString("json")
                        workoutStoreRepository.saveWorkoutStoreFromJson(workoutStoreJson!!)
                        val newWorkouts= getEnabledItems(workoutStoreRepository.getWorkoutStore().workouts)
                        appViewModel.updateWorkouts(newWorkouts)
                        Toast.makeText(this, "Update received", Toast.LENGTH_SHORT).show()
                    }
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        dataClient.addListener(this)
    }

    override fun onPause() {
        super.onPause()
        dataClient.removeListener(this)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val workouts= getEnabledItems(workoutStoreRepository.getWorkoutStore().workouts)
        appViewModel.updateWorkouts(workouts)
        setContent {
            WearApp(dataClient,appViewModel)
        }
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

@Composable
fun WearApp(dataClient: DataClient, appViewModel: AppViewModel) {
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

        NavHost(navController, startDestination = Screen.WorkoutSelection.route) {
            composable(Screen.WorkoutSelection.route) {
                WorkoutSelectionScreen(navController, appViewModel)
            }
            composable(Screen.WorkoutDetail.route) {
                WorkoutDetailScreen(navController, appViewModel, hrViewModel)
            }
            composable(Screen.Workout.route) {
                WorkoutScreen(dataClient,navController,appViewModel,hrViewModel)
            }
        }
    }
}