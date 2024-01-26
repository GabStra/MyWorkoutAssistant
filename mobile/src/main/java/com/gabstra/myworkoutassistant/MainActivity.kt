package com.gabstra.myworkoutassistant

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.util.Log
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.gabstra.myworkoutassistant.screens.ExerciseDetailScreen
import com.gabstra.myworkoutassistant.screens.ExerciseForm
import com.gabstra.myworkoutassistant.screens.ExerciseGroupDetailScreen
import com.gabstra.myworkoutassistant.screens.ExerciseGroupForm
import com.gabstra.myworkoutassistant.screens.SetForm
import com.gabstra.myworkoutassistant.screens.SettingsScreen
import com.gabstra.myworkoutassistant.screens.WorkoutDetailScreen
import com.gabstra.myworkoutassistant.screens.WorkoutForm
import com.gabstra.myworkoutassistant.screens.WorkoutsScreen
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.fromWorkoutStoreToJSON
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.ExerciseGroup
import com.gabstra.myworkoutassistant.ui.theme.MyWorkoutAssistantTheme
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.Wearable

class MainActivity : ComponentActivity() {
    private val dataClient by lazy { Wearable.getDataClient(this) }

    private val db by lazy { AppDatabase.getDatabase(this)}

    private val appViewModel: AppViewModel by viewModels()

    private val workoutStoreRepository by lazy { WorkoutStoreRepository(this.filesDir) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        appViewModel.updateWorkoutStore(workoutStoreRepository.getWorkoutStore())

        setContent {
            MyWorkoutAssistantTheme {
                // A surface container using the 'background' color from the theme
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    MyWorkoutAssistantNavHost(dataClient,appViewModel,workoutStoreRepository,db)
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent) // Update the old intent
        val receivedValue = intent.getStringExtra("page")
        receivedValue?.let { page ->
            when(page){
                "workouts" -> {
                    appViewModel.setScreenData(ScreenData.Workouts())
                }
                "settings" -> {
                    appViewModel.setScreenData(ScreenData.Settings())
                }
            }
        }
    }

}

@Composable
fun MyWorkoutAssistantNavHost(
    dataClient: DataClient,
    appViewModel: AppViewModel,
    workoutStoreRepository : WorkoutStoreRepository,
    db: AppDatabase
){
    val context = LocalContext.current

    //val exerciseHistoryDao = db.setHistoryDao()
    val workoutHistoryDao= db.workoutHistoryDao()

    LaunchedEffect(appViewModel.workouts) {
        workoutStoreRepository.saveWorkoutStore(appViewModel.workoutStore)
        sendWorkoutStore(dataClient,appViewModel.workoutStore)
        Toast.makeText(context, "Automatic update", Toast.LENGTH_SHORT).show()
    }

    BackHandler(enabled = true) {
        val canGoBack = appViewModel.goBack()
        if (!canGoBack) {
            (context as? ComponentActivity)?.finish()
        }
    }

    when(appViewModel.currentScreenData){
        is ScreenData.Workouts -> {
            WorkoutsScreen(appViewModel,
                onSaveClick={
                    val jsonString = fromWorkoutStoreToJSON(appViewModel.workoutStore)
                    writeJsonToDownloadsFolder(context,"workout_store.json",jsonString)
                    Toast.makeText(context, "Workout Store saved to downloads folder", Toast.LENGTH_SHORT).show()
                },
                onSyncClick = {
                    sendWorkoutStore(dataClient,appViewModel.workoutStore)
                },
                onOpenSettingsClick = {
                    appViewModel.setScreenData(ScreenData.Settings())
                },
                onFileSelected = {
                    try {
                        context.contentResolver.openInputStream(it)?.use { inputStream ->
                            val reader = inputStream.bufferedReader()
                            val content = reader.readText()
                            workoutStoreRepository.saveWorkoutStoreFromJson(content)
                            appViewModel.updateWorkoutStore(workoutStoreRepository.getWorkoutStore())
                            Toast.makeText(context, "Workout Store loaded from json", Toast.LENGTH_SHORT).show()
                        }
                    } catch (e: Exception) {
                        Toast.makeText(context, "Import failed", Toast.LENGTH_SHORT).show()
                    }
                }
            )
        }
        is ScreenData.Settings ->{
            SettingsScreen(
                onSave = { newWorkoutStore ->
                    appViewModel.updateWorkoutStore(newWorkoutStore)
                    workoutStoreRepository.saveWorkoutStore(newWorkoutStore)
                    sendWorkoutStore(dataClient,appViewModel.workoutStore)
                    Toast.makeText(context, "Settings saved", Toast.LENGTH_SHORT).show()
                    appViewModel.goBack()
                },
                onCancel = {
                    appViewModel.goBack()
                },
                workoutStore = appViewModel.workoutStore
            )
        }
        is ScreenData.NewWorkout -> {
            WorkoutForm(
                onWorkoutUpsert = { newWorkout ->
                    appViewModel.addNewWorkout(newWorkout)
                    appViewModel.goBack()
                },
                onCancel = { appViewModel.goBack() },
            )
        }
        is ScreenData.EditWorkout -> {
            val screenData = appViewModel.currentScreenData as ScreenData.EditWorkout
            val workouts by appViewModel.workoutsFlow.collectAsState()
            val selectedWorkout = workouts.find { it.id == screenData.workoutId }!!
            WorkoutForm(
                onWorkoutUpsert = { updatedWorkout ->
                    appViewModel.updateWorkout(selectedWorkout,updatedWorkout)
                    appViewModel.goBack()
                },
                onCancel = {
                    appViewModel.goBack()
                },
                workout = selectedWorkout
            )
        }
        is ScreenData.WorkoutDetail -> {
            val screenData = appViewModel.currentScreenData as ScreenData.WorkoutDetail
            val workouts by appViewModel.workoutsFlow.collectAsState()

            val selectedWorkout = workouts.find { it.id == screenData.workoutId }!!
            Log.d("WorkoutDetailScreen","selectedWorkout: ${selectedWorkout.workoutComponents[0].enabled}")
            WorkoutDetailScreen(appViewModel,workoutHistoryDao,selectedWorkout,selectedWorkout.workoutComponents){
                appViewModel.goBack()
            }
        }
        is ScreenData.ExerciseGroupDetail -> {
            val screenData = appViewModel.currentScreenData as ScreenData.ExerciseGroupDetail
            val workouts by appViewModel.workoutsFlow.collectAsState()
            val selectedWorkout = workouts.find { it.id == screenData.workoutId }!!
            val selectedExerciseGroup = findWorkoutComponentByIdInWorkout(selectedWorkout,screenData.selectedExerciseGroupId) as ExerciseGroup
            ExerciseGroupDetailScreen(appViewModel, selectedWorkout,selectedExerciseGroup){
                appViewModel.goBack()
            }
        }
        is ScreenData.NewExerciseGroup -> {
            val screenData = appViewModel.currentScreenData as ScreenData.NewExerciseGroup
            val workouts by appViewModel.workoutsFlow.collectAsState()
            val selectedWorkout = workouts.find { it.id == screenData.workoutId }!!
            val parentExerciseGroup = if(screenData.parentExerciseGroupId != null) findWorkoutComponentByIdInWorkout(selectedWorkout,screenData.parentExerciseGroupId) as ExerciseGroup else null
            ExerciseGroupForm(
                onWorkoutComponentUpsert = { newExerciseGroup ->
                    if(parentExerciseGroup != null){
                        appViewModel.addWorkoutComponentToExerciseGroup(selectedWorkout,parentExerciseGroup,newExerciseGroup)
                    }else{
                        appViewModel.addWorkoutComponent(selectedWorkout,newExerciseGroup)
                    }
                    appViewModel.goBack()
                },
                onCancel = {
                    appViewModel.goBack()
                },
            )
        }
        is ScreenData.EditExerciseGroup -> {
            val screenData = appViewModel.currentScreenData as ScreenData.EditExerciseGroup
            val workouts by appViewModel.workoutsFlow.collectAsState()
            val selectedWorkout = workouts.find { it.id == screenData.workoutId }!!
            val selectedExerciseGroup = findWorkoutComponentByIdInWorkout(selectedWorkout,screenData.selectedExerciseGroupId) as ExerciseGroup
            ExerciseGroupForm(
                onWorkoutComponentUpsert = { updatedExerciseGroup ->
                    appViewModel.updateWorkoutComponent(selectedWorkout,selectedExerciseGroup,updatedExerciseGroup)
                    appViewModel.goBack()
                },
                onCancel = {
                    appViewModel.goBack()
                },
                exerciseGroup = selectedExerciseGroup
            )
        }
        is ScreenData.ExerciseDetail -> {
            val screenData = appViewModel.currentScreenData as ScreenData.ExerciseDetail
            val workouts by appViewModel.workoutsFlow.collectAsState()
            val selectedWorkout = workouts.find { it.id == screenData.workoutId }!!
            val selectedExercise = findWorkoutComponentByIdInWorkout(selectedWorkout,screenData.selectedExerciseId) as Exercise
            ExerciseDetailScreen(appViewModel, selectedWorkout,selectedExercise){
                appViewModel.goBack()
            }
        }
        is ScreenData.NewExercise -> {
            val screenData = appViewModel.currentScreenData as ScreenData.NewExercise
            val workouts by appViewModel.workoutsFlow.collectAsState()
            val selectedWorkout = workouts.find { it.id == screenData.workoutId }!!
            val parentExerciseGroup = if(screenData.parentExerciseGroupId != null) findWorkoutComponentByIdInWorkout(selectedWorkout,screenData.parentExerciseGroupId) as ExerciseGroup else null
            ExerciseForm(
                onExerciseUpsert = { newExercise ->
                    if(parentExerciseGroup != null){
                        appViewModel.addWorkoutComponentToExerciseGroup(selectedWorkout,parentExerciseGroup,newExercise)
                    }else{
                        appViewModel.addWorkoutComponent(selectedWorkout,newExercise)
                    }
                    appViewModel.goBack()
                },
                onCancel = { appViewModel.goBack() },
            )
        }
        is ScreenData.EditExercise -> {
            val screenData = appViewModel.currentScreenData as ScreenData.EditExercise
            val workouts by appViewModel.workoutsFlow.collectAsState()
            val selectedWorkout = workouts.find { it.id == screenData.workoutId }!!
            val selectedExercise = findWorkoutComponentByIdInWorkout(selectedWorkout,screenData.selectedExerciseId) as Exercise
            ExerciseForm(
                onExerciseUpsert = { updatedExercise ->
                    appViewModel.updateWorkoutComponent(selectedWorkout,selectedExercise,updatedExercise)
                    appViewModel.goBack()
                },
                onCancel = {
                    appViewModel.goBack()
                },
                exercise = selectedExercise
            )
        }

        is ScreenData.NewSet -> {
            val screenData = appViewModel.currentScreenData as ScreenData.NewSet
            val workouts by appViewModel.workoutsFlow.collectAsState()
            val selectedWorkout = workouts.find { it.id == screenData.workoutId }!!
            val parentExercise = findWorkoutComponentByIdInWorkout(selectedWorkout,screenData.parentExerciseId) as Exercise
            SetForm(
                onSetUpsert = { updatedSet ->
                    appViewModel.addSetToExercise(selectedWorkout,parentExercise,updatedSet)
                    appViewModel.goBack()
                },
                onCancel = {
                    appViewModel.goBack()
                },
            )
        }
        is ScreenData.EditSet -> {
            val screenData = appViewModel.currentScreenData as ScreenData.EditSet
            val workouts by appViewModel.workoutsFlow.collectAsState()
            val selectedWorkout = workouts.find { it.id == screenData.workoutId }!!
            val parentExercise = findWorkoutComponentByIdInWorkout(selectedWorkout,screenData.parentExerciseId) as Exercise
            SetForm(
                onSetUpsert = { updatedSet ->
                    appViewModel.updateSetInExercise(selectedWorkout,parentExercise,screenData.selectedSet,updatedSet)
                    appViewModel.goBack()
                },
                onCancel = {
                    appViewModel.goBack()
                },
                set = screenData.selectedSet
            )
        }
    }
}

