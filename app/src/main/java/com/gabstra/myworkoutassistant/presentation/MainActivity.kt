/* While this template provides a good starting point for using Wear Compose, you can always
 * take a look at https://github.com/android/wear-os-samples/tree/main/ComposeStarter and
 * https://github.com/android/wear-os-samples/tree/main/ComposeAdvanced to find the most up to date
 * changes to the libraries and their usages.
 */

package com.gabstra.myworkoutassistant.presentation

import android.os.Bundle
import android.util.Log
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
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.ExerciseGroup
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
                        val newWorkouts = getEnabledItems(workoutStoreRepository.getWorkoutStore().workouts)
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

        val mockWorkoutStore = "{  \"workouts\": [    {      \"name\": \"Upper Body (Strength & Hypertrophy Focus)\",      \"description\": \"Upper body workout focusing on strength and hypertrophy.\",      \"workoutComponents\": [        {          \"type\": \"Exercise\",          \"name\": \"Warm Up\",          \"restTimeInSec\": 0,          \"sets\": [            {              \"type\": \"TimedDurationSet\",              \"timeInMillis\": 300000,              \"autoStart\": false,              \"autoStop\": true            }          ],          \"enabled\": true        },        {          \"type\": \"Exercise\",          \"name\": \"Dumbbell Bench Press\",          \"restTimeInSec\": 120,          \"sets\": [            {              \"type\": \"WeightSet\",              \"reps\": 6,              \"weight\": 20            },            {              \"type\": \"WeightSet\",              \"reps\": 7,              \"weight\": 20            },            {              \"type\": \"WeightSet\",              \"reps\": 8,              \"weight\": 20            }          ],          \"enabled\": true        },        {          \"type\": \"Exercise\",          \"name\": \"Pull-Ups\",          \"restTimeInSec\": 120,          \"sets\": [            {              \"type\": \"BodyWeightSet\",              \"reps\": 10            },            {              \"type\": \"BodyWeightSet\",              \"reps\": 10            },            {              \"type\": \"BodyWeightSet\",              \"reps\": 10            }          ],          \"enabled\": true        },        {          \"type\": \"Exercise\",          \"name\": \"Dumbbell Rows\",          \"restTimeInSec\": 120,          \"sets\": [            {              \"type\": \"WeightSet\",              \"reps\": 8,              \"weight\": 15            },            {              \"type\": \"WeightSet\",              \"reps\": 9,              \"weight\": 15            },            {              \"type\": \"WeightSet\",              \"reps\": 10,              \"weight\": 15            }          ],          \"enabled\": true        },        {          \"type\": \"Exercise\",          \"name\": \"Shoulder Press\",          \"restTimeInSec\": 120,          \"sets\": [            {              \"type\": \"WeightSet\",              \"reps\": 6,              \"weight\": 10            },            {              \"type\": \"WeightSet\",              \"reps\": 7,              \"weight\": 10            },            {              \"type\": \"WeightSet\",              \"reps\": 8,              \"weight\": 10            }          ],          \"enabled\": true        },        {          \"type\": \"Exercise\",          \"name\": \"Bicep Curls\",          \"restTimeInSec\": 120,          \"sets\": [            {              \"type\": \"WeightSet\",              \"reps\": 10,              \"weight\": 8            },            {              \"type\": \"WeightSet\",              \"reps\": 11,              \"weight\": 8            },            {              \"type\": \"WeightSet\",              \"reps\": 12,              \"weight\": 8            }          ],          \"enabled\": true        },        {          \"type\": \"Exercise\",          \"name\": \"Tricep Overhead Extension\",          \"restTimeInSec\": 120,          \"sets\": [            {              \"type\": \"WeightSet\",              \"reps\": 10,              \"weight\": 8            },            {              \"type\": \"WeightSet\",              \"reps\": 11,              \"weight\": 8            },            {              \"type\": \"WeightSet\",              \"reps\": 12,              \"weight\": 8            }          ],          \"enabled\": true        }      ],      \"restTimeInSec\": 120,      \"enabled\": true    },    {      \"name\": \"Lower Body & Core (Strength & Hypertrophy Focus)\",      \"description\": \"Lower body and core workout focusing on strength and hypertrophy.\",      \"workoutComponents\": [        {          \"type\": \"Exercise\",          \"name\": \"Warm Up\",          \"restTimeInSec\": 0,          \"sets\": [            {              \"type\": \"TimedDurationSet\",              \"timeInMillis\": 300000,              \"autoStart\": false,              \"autoStop\": true            }          ],          \"enabled\": true        },        {          \"type\": \"Exercise\",          \"name\": \"Goblet Squats\",          \"restTimeInSec\": 120,          \"sets\": [            {              \"type\": \"WeightSet\",              \"reps\": 6,              \"weight\": 20            },            {              \"type\": \"WeightSet\",              \"reps\": 7,              \"weight\": 20            },            {              \"type\": \"WeightSet\",              \"reps\": 8,              \"weight\": 20            }          ],          \"enabled\": true        },        {          \"type\": \"Exercise\",          \"name\": \"Lunges\",          \"restTimeInSec\": 120,          \"sets\": [            {              \"type\": \"WeightSet\",              \"reps\": 8,              \"weight\": 15            },            {              \"type\": \"WeightSet\",              \"reps\": 9,              \"weight\": 15            },            {              \"type\": \"WeightSet\",              \"reps\": 10,              \"weight\": 15            }          ],          \"enabled\": true        },        {          \"type\": \"Exercise\",          \"name\": \"Nordic Hamstring Curls\",          \"restTimeInSec\": 120,          \"sets\": [            {              \"type\": \"BodyWeightSet\",              \"reps\": 6            },            {              \"type\": \"BodyWeightSet\",              \"reps\": 7            },            {              \"type\": \"BodyWeightSet\",              \"reps\": 8            }          ],          \"enabled\": true        },        {          \"type\": \"Exercise\",          \"name\": \"Calf Raises\",          \"restTimeInSec\": 120,          \"sets\": [            {              \"type\": \"BodyWeightSet\",              \"reps\": 12            },            {              \"type\": \"BodyWeightSet\",              \"reps\": 13            },            {              \"type\": \"BodyWeightSet\",              \"reps\": 15            }          ],          \"enabled\": true        },        {          \"type\": \"Exercise\",          \"name\": \"Hanging Leg Raises\",          \"restTimeInSec\": 120,          \"sets\": [            {              \"type\": \"BodyWeightSet\",              \"reps\": 10            },            {              \"type\": \"BodyWeightSet\",              \"reps\": 11            },            {              \"type\": \"BodyWeightSet\",              \"reps\": 12            }          ],          \"enabled\": true        }      ],      \"restTimeInSec\": 120,      \"enabled\": true    },    {      \"name\": \"Upper Body (Endurance & Stability Focus)\",      \"description\": \"Upper body workout focusing on endurance and stability.\",      \"workoutComponents\": [        {          \"type\": \"Exercise\",          \"name\": \"Warm Up\",          \"restTimeInSec\": 0,          \"sets\": [            {              \"type\": \"TimedDurationSet\",              \"timeInMillis\": 300000,              \"autoStart\": false,              \"autoStop\": true            }          ],          \"enabled\": true        },        {          \"type\": \"Exercise\",          \"name\": \"Dumbbell Flyes\",          \"restTimeInSec\": 90,          \"sets\": [            {              \"type\": \"WeightSet\",              \"reps\": 12,              \"weight\": 6            },            {              \"type\": \"WeightSet\",              \"reps\": 13,              \"weight\": 6            },            {              \"type\": \"WeightSet\",              \"reps\": 15,              \"weight\": 6            }          ],          \"enabled\": true        },        {          \"type\": \"Exercise\",          \"name\": \"Ring Rows\",          \"restTimeInSec\": 90,          \"sets\": [            {              \"type\": \"BodyWeightSet\",              \"reps\": 12            },            {              \"type\": \"BodyWeightSet\",              \"reps\": 13            },            {              \"type\": \"BodyWeightSet\",              \"reps\": 15            }          ],          \"enabled\": true        },        {          \"type\": \"Exercise\",          \"name\": \"Side Lateral Raises\",          \"restTimeInSec\": 90,          \"sets\": [            {              \"type\": \"WeightSet\",              \"reps\": 15,              \"weight\": 4            },            {              \"type\": \"WeightSet\",              \"reps\": 18,              \"weight\": 4            },            {              \"type\": \"WeightSet\",              \"reps\": 20,              \"weight\": 4            }          ],          \"enabled\": true        },        {          \"type\": \"Exercise\",          \"name\": \"Resistance Band Pull Aparts\",          \"restTimeInSec\": 90,          \"sets\": [            {              \"type\": \"BodyWeightSet\",              \"reps\": 15            },            {              \"type\": \"BodyWeightSet\",              \"reps\": 18            },            {              \"type\": \"BodyWeightSet\",              \"reps\": 20            }          ],          \"enabled\": true        },        {          \"type\": \"Exercise\",          \"name\": \"Hammer Curls\",          \"restTimeInSec\": 90,          \"sets\": [            {              \"type\": \"WeightSet\",              \"reps\": 12,              \"weight\": 8            },            {              \"type\": \"WeightSet\",              \"reps\": 13,              \"weight\": 8            },            {              \"type\": \"WeightSet\",              \"reps\": 15,              \"weight\": 8            }          ],          \"enabled\": true        },        {          \"type\": \"Exercise\",          \"name\": \"Ring Dips\",          \"restTimeInSec\": 90,          \"sets\": [            {              \"type\": \"BodyWeightSet\",              \"reps\": 12            },            {              \"type\": \"BodyWeightSet\",              \"reps\": 13            },            {              \"type\": \"BodyWeightSet\",              \"reps\": 15            }          ],          \"enabled\": true        }      ],      \"restTimeInSec\": 90,      \"enabled\": true    },    {      \"name\": \"Lower Body & Core (Endurance & Stability Focus)\",      \"description\": \"Lower body and core workout focusing on endurance and stability.\",      \"workoutComponents\": [        {          \"type\": \"Exercise\",          \"name\": \"Warm Up\",          \"restTimeInSec\": 0,          \"sets\": [            {              \"type\": \"TimedDurationSet\",              \"timeInMillis\": 300000,              \"autoStart\": false,              \"autoStop\": true            }          ],          \"enabled\": true        },        {          \"type\": \"Exercise\",          \"name\": \"Bulgarian Split Squats\",          \"restTimeInSec\": 90,          \"sets\": [            {              \"type\": \"BodyWeightSet\",              \"reps\": 12            },            {              \"type\": \"BodyWeightSet\",              \"reps\": 13            },            {              \"type\": \"BodyWeightSet\",              \"reps\": 15            }          ],          \"enabled\": true        },        {          \"type\": \"Exercise\",          \"name\": \"Single-leg Romanian Deadlifts\",          \"restTimeInSec\": 90,          \"sets\": [            {              \"type\": \"WeightSet\",              \"reps\": 12,              \"weight\": 10            },            {              \"type\": \"WeightSet\",              \"reps\": 13,              \"weight\": 10            },            {              \"type\": \"WeightSet\",              \"reps\": 15,              \"weight\": 10            }          ],          \"enabled\": true        },        {          \"type\": \"Exercise\",          \"name\": \"Glute Bridges\",          \"restTimeInSec\": 90,          \"sets\": [            {              \"type\": \"BodyWeightSet\",              \"reps\": 12            },            {              \"type\": \"BodyWeightSet\",              \"reps\": 13            },            {              \"type\": \"BodyWeightSet\",              \"reps\": 15            }          ],          \"enabled\": true        },        {          \"type\": \"Exercise\",          \"name\": \"Resistance Band Side Steps\",          \"restTimeInSec\": 90,          \"sets\": [            {              \"type\": \"BodyWeightSet\",              \"reps\": 15            },            {              \"type\": \"BodyWeightSet\",              \"reps\": 18            },            {              \"type\": \"BodyWeightSet\",              \"reps\": 20            }          ],          \"enabled\": true        },        {          \"type\": \"Exercise\",          \"name\": \"X-Ups\",          \"restTimeInSec\": 90,          \"sets\": [            {              \"type\": \"BodyWeightSet\",              \"reps\": 12            },            {              \"type\": \"BodyWeightSet\",              \"reps\": 13            },            {              \"type\": \"BodyWeightSet\",              \"reps\": 15            }          ],          \"enabled\": true        },        {          \"type\": \"Exercise\",          \"name\": \"Plank\",          \"restTimeInSec\": 90,          \"sets\": [            {              \"type\": \"TimedDurationSet\",              \"timeInMillis\": 30000,              \"autoStart\": true,              \"autoStop\": true            },            {              \"type\": \"TimedDurationSet\",              \"timeInMillis\": 45000,              \"autoStart\": true,              \"autoStop\": true            },            {              \"type\": \"TimedDurationSet\",              \"timeInMillis\": 60000,              \"autoStart\": true,              \"autoStop\": true            }          ],          \"enabled\": true        }      ],      \"restTimeInSec\": 90,      \"enabled\": true    },    {      \"name\": \"Cyclette HIIT Workout\",      \"description\": \"High-Intensity Interval Training on a Cyclette\",      \"workoutComponents\": [        {          \"type\": \"Exercise\",          \"name\": \"Warm Up\",          \"restTimeInSec\": 0,          \"sets\": [            {              \"type\": \"TimedDurationSet\",              \"timeInMillis\": 300000,              \"autoStart\": false,              \"autoStop\": true            }          ],          \"enabled\": true        },        {          \"type\": \"Exercise\",          \"name\": \"High-Intensity Cycling\",          \"restTimeInSec\": 60,          \"sets\": [            {              \"type\": \"TimedDurationSet\",              \"timeInMillis\": 30000,              \"autoStart\": true,              \"autoStop\": true            },            {              \"type\": \"TimedDurationSet\",              \"timeInMillis\": 30000,              \"autoStart\": true,              \"autoStop\": true            },            {              \"type\": \"TimedDurationSet\",              \"timeInMillis\": 30000,              \"autoStart\": true,              \"autoStop\": true            },            {              \"type\": \"TimedDurationSet\",              \"timeInMillis\": 30000,              \"autoStart\": true,              \"autoStop\": true            },            {              \"type\": \"TimedDurationSet\",              \"timeInMillis\": 30000,              \"autoStart\": true,              \"autoStop\": true            },            {              \"type\": \"TimedDurationSet\",              \"timeInMillis\": 30000,              \"autoStart\": true,              \"autoStop\": true            },            {              \"type\": \"TimedDurationSet\",              \"timeInMillis\": 30000,              \"autoStart\": true,              \"autoStop\": true            }          ],          \"enabled\": true        },        {          \"type\": \"Exercise\",          \"name\": \"Cool Down\",          \"restTimeInSec\": 0,          \"sets\": [            {              \"type\": \"TimedDurationSet\",              \"timeInMillis\": 300000,              \"autoStart\": true,              \"autoStop\": true            }          ],          \"enabled\": true        }      ],      \"restTimeInSec\": 0,      \"enabled\": true    }  ]}"

        workoutStoreRepository.saveWorkoutStoreFromJson(mockWorkoutStore)

        val workouts = getEnabledItems(workoutStoreRepository.getWorkoutStore().workouts)
        Log.d("WORKOUTS",workoutStoreRepository.getWorkoutStore().workouts.toString())
        appViewModel.updateWorkouts(workouts)
        appViewModel.initDataClient(dataClient)
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