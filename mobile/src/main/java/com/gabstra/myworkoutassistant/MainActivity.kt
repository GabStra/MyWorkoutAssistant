package com.gabstra.myworkoutassistant

import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.navigation.NavController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
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

        appViewModel.updateWorkouts(workoutStoreRepository.getWorkoutStore().workouts)

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
}




@Composable
fun MyWorkoutAssistantNavHost(
    dataClient: DataClient,
    appViewModel: AppViewModel,
    workoutStoreRepository : WorkoutStoreRepository,
    db: AppDatabase
){
    val navController = rememberNavController()
    val context = LocalContext.current

    val exerciseHistoryDao= db.exerciseHistoryDao()
    val workoutHistoryDao= db.workoutHistoryDao()

    LaunchedEffect(appViewModel.workouts) {
        workoutStoreRepository.saveWorkoutStore(WorkoutStore(appViewModel.workouts))
        sendWorkoutStore(dataClient,WorkoutStore(appViewModel.workouts))
        Toast.makeText(context, "Automatic update", Toast.LENGTH_SHORT).show()
    }

    NavHost(navController, startDestination = Screen.Workouts.route) {
        composable(Screen.Workouts.route) {
            WorkoutsScreen(navController,appViewModel,
                onSaveClick={
                    workoutStoreRepository.saveWorkoutStore(WorkoutStore(appViewModel.workouts))
                    Toast.makeText(context, "Workouts saved", Toast.LENGTH_SHORT).show()
                },
                onSyncClick = {
                    sendWorkoutStore(dataClient,WorkoutStore(appViewModel.workouts))
                },
                onFileSelected = {
                    try {
                        context.contentResolver.openInputStream(it)?.use { inputStream ->
                            val reader = inputStream.bufferedReader()
                            val content = reader.readText()
                            workoutStoreRepository.saveWorkoutStoreFromJson(content)
                            appViewModel.updateWorkouts(workoutStoreRepository.getWorkoutStore().workouts)
                            Toast.makeText(context, "Workouts loaded from json", Toast.LENGTH_SHORT).show()
                        }
                    } catch (e: Exception) {
                        Toast.makeText(context, "Import failed", Toast.LENGTH_SHORT).show()
                    }
                }
            )
        }
        composable(Screen.NewWorkout.route) {
            WorkoutForm(
                onWorkoutUpsert = { newWorkout ->
                    appViewModel.addNewWorkout(newWorkout)
                    navController.popBackStack()
                },
                onCancel = { navController.popBackStack() },
            )
        }
        composable(Screen.EditWorkout.route) {backStackEntry ->
            val workoutId = backStackEntry.arguments?.getString("workoutId") ?: return@composable
            val originalWorkout = appViewModel.workouts.getOrNull(workoutId.toInt()) ?: return@composable
            WorkoutForm(
                onWorkoutUpsert = { updatedWorkout ->
                    appViewModel.updateWorkout(originalWorkout,updatedWorkout)
                    navController.popBackStack()
                },
                onCancel = {  navController.popBackStack() },
                workout = originalWorkout
            )
        }
        composable(Screen.WorkoutDetail.route) { backStackEntry ->
            // Retrieve the argument from the NavBackStackEntry
            val workoutId = backStackEntry.arguments?.getString("workoutId") ?: return@composable
            WorkoutDetailScreen(navController,appViewModel,workoutHistoryDao, workoutId.toInt()){
                if(!navController.popBackStack()){
                    navController.navigate(Screen.Workouts.route)
                }
            }
        }
        composable(Screen.ExerciseGroupDetail.route) { backStackEntry ->
            // Retrieve the argument from the NavBackStackEntry
            val workoutId = backStackEntry.arguments?.getString("workoutId") ?: return@composable
            val exerciseGroupId = backStackEntry.arguments?.getString("exerciseGroupId") ?: return@composable
            ExerciseGroupDetailScreen(navController,appViewModel, workoutId.toInt(),exerciseGroupId.toInt()){
                if(!navController.popBackStack()){
                    navController.navigate(Screen.getRoute(Screen.WorkoutDetail,workoutId.toInt()))
                }
            }
        }
        composable(Screen.NewExerciseGroup.route) { backStackEntry ->
            val workoutId = backStackEntry.arguments?.getString("workoutId") ?: return@composable
            val workout = appViewModel.workouts[workoutId.toInt()]
            ExerciseGroupForm(
                onExerciseGroupUpsert = { newExerciseGroup ->
                    appViewModel.addNewExerciseGroup(workout,newExerciseGroup)
                    navController.popBackStack()
                },
                onCancel = { navController.popBackStack() },
            )
        }
        composable(Screen.EditExerciseGroup.route) {backStackEntry ->
            val workoutId = backStackEntry.arguments?.getString("workoutId") ?: return@composable
            val exerciseGroupId = backStackEntry.arguments?.getString("exerciseGroupId") ?: return@composable
            val workout = appViewModel.workouts[workoutId.toInt()]
            val originalExerciseGroup = workout.exerciseGroups.getOrNull(exerciseGroupId.toInt()) ?: return@composable
            ExerciseGroupForm(
                onExerciseGroupUpsert = { updatedExerciseGroup ->
                    appViewModel.updateExerciseGroup(workout,originalExerciseGroup,updatedExerciseGroup)
                    navController.popBackStack()
                },
                onCancel = {  navController.popBackStack() },
                exerciseGroup = originalExerciseGroup
            )
        }
        composable(Screen.NewExercise.route) { backStackEntry ->
            val workoutId = backStackEntry.arguments?.getString("workoutId") ?: return@composable
            val exerciseGroupId = backStackEntry.arguments?.getString("exerciseGroupId") ?: return@composable
            val workout = appViewModel.workouts[workoutId.toInt()]
            val exerciseGroup = workout.exerciseGroups[exerciseGroupId.toInt()]
            ExerciseForm(
                onExerciseUpsert = { newExercise ->
                    appViewModel.addNewExercise(workout,exerciseGroup,newExercise)
                    navController.popBackStack()
                },
                onCancel = { navController.popBackStack() },
            )
        }
        composable(Screen.EditExercise.route) {backStackEntry ->
            val workoutId = backStackEntry.arguments?.getString("workoutId") ?: return@composable
            val exerciseGroupId = backStackEntry.arguments?.getString("exerciseGroupId") ?: return@composable
            val exerciseId = backStackEntry.arguments?.getString("exerciseId") ?: return@composable
            val workout = appViewModel.workouts[workoutId.toInt()]
            val exerciseGroup = workout.exerciseGroups[exerciseGroupId.toInt()]
            val originalExercise = exerciseGroup.exercises.getOrNull(exerciseId.toInt()) ?: return@composable
            ExerciseForm(
                onExerciseUpsert = { updatedExercise->
                    appViewModel.updateExercise(workout,exerciseGroup,originalExercise,updatedExercise)
                    navController.popBackStack()
                },
                onCancel = {  navController.popBackStack() },
                exercise = originalExercise
            )
        }
    }
}

/*@OptIn(ExperimentalPermissionsApi::class)
@Composable
fun MainScreen(dataClient: DataClient){
    val appViewModel:AppViewModel = viewModel()

    val appState by appViewModel.appState
    val filesViewModel: FilesViewModel = viewModel()
    val context = LocalContext.current

    when(appState){
        is AppState.WorkoutList -> {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(MaterialTheme.colorScheme.background) // Set the background color to black
            ){
                WorkoutListScreen(dataClient,appViewModel,filesViewModel)
            }
        }
        is AppState.NewWorkout -> {
            WorkoutForm(
                onWorkoutUpsert = {
                    val workout = it.copy(id=filesViewModel.workouts.value.size)
                    filesViewModel.addWorkout(context.filesDir,workout){
                        syncWorkoutsWithDevice(dataClient,filesViewModel)
                        appViewModel.setState(AppState.WorkoutList)
                    }
                },
                onCancel = { appViewModel.setState(AppState.WorkoutList) },
            )
        }
        is AppState.EditWorkout -> {
            WorkoutForm(
                onWorkoutUpsert = {
                    val workout = it.copy(id= (appState as AppState.EditWorkout).selectedWorkout.id)
                    filesViewModel.editWorkout(context.filesDir,workout){
                        syncWorkoutsWithDevice(dataClient,filesViewModel)
                    }
                    appViewModel.setState(AppState.WorkoutList)
                },
                onCancel = { appViewModel.setState(AppState.WorkoutList) },
                onDelete = {
                    filesViewModel.deleteWorkout(context.filesDir,it){
                        syncWorkoutsWithDevice(dataClient,filesViewModel)
                    }
                    appViewModel.setState(AppState.WorkoutList)
                },
                onEditExerciseGroup = {
                    appViewModel.setState(AppState.WorkoutDetail(selectedWorkout = it))
                },
                workout = (appState as AppState.EditWorkout).selectedWorkout
            )
        }
        is AppState.WorkoutDetail ->{
            WorkoutDetailScreen(
                dataClient,
                appViewModel,
                filesViewModel,
                selectedWorkout = (appState as AppState.WorkoutDetail).selectedWorkout
            )
        }
        is AppState.NewExerciseGroup -> {
            val selectedWorkout= (appState as AppState.NewExerciseGroup).selectedWorkout
            ExerciseGroupForm(
                onExerciseGroupUpsert = {
                    val exerciseGroup = it.copy(id=selectedWorkout.exercises.size)
                    val editedWorkout = selectedWorkout.copy(exercises = selectedWorkout.exercises + exerciseGroup)
                    filesViewModel.editWorkout(context.filesDir,editedWorkout){
                        syncWorkoutsWithDevice(dataClient,filesViewModel)
                        appViewModel.setState(AppState.WorkoutDetail(selectedWorkout = editedWorkout))
                    }
                },
                onCancel = { appViewModel.setState(AppState.WorkoutDetail(selectedWorkout = selectedWorkout)) },
            )
        }
        is AppState.EditExerciseGroup -> {
            val selectedWorkout= (appState as AppState.EditExerciseGroup).selectedWorkout
            ExerciseGroupForm(
                onExerciseGroupUpsert = {
                    val updatedExercises = selectedWorkout.exercises.map { exercise ->
                        if (exercise.id == it.id) it else exercise
                    }
                    val newWorkout = selectedWorkout.copy(exercises = updatedExercises)
                    filesViewModel.editWorkout(context.filesDir,newWorkout){
                        syncWorkoutsWithDevice(dataClient,filesViewModel)
                        appViewModel.setState(AppState.WorkoutDetail(selectedWorkout = newWorkout))
                    }
                },
                onCancel = { appViewModel.setState(AppState.WorkoutDetail(selectedWorkout = selectedWorkout)) },
                onDelete = {
                    val updatedExercises = selectedWorkout.exercises.filter { exercise ->
                        exercise.id != it.id
                    }
                    val newWorkout = selectedWorkout.copy(exercises = updatedExercises)
                    filesViewModel.editWorkout(context.filesDir,newWorkout){
                        syncWorkoutsWithDevice(dataClient,filesViewModel)
                        appViewModel.setState(AppState.WorkoutDetail(selectedWorkout = newWorkout))
                    }
                },
                onEditExercise = {
                    appViewModel.setState(AppState.ExerciseGroupDetail(selectedWorkout = selectedWorkout, selectedExerciseGroup = it))
                },
                exerciseGroup = (appState as AppState.EditExerciseGroup).selectedExerciseGroup
            )
        }
        is AppState.ExerciseGroupDetail ->{
            ExerciseGroupDetailScreen(
                dataClient,
                appViewModel,
                filesViewModel,
                selectedWorkout = (appState as AppState.ExerciseGroupDetail).selectedWorkout,
                selectedExerciseGroup = (appState as AppState.ExerciseGroupDetail).selectedExerciseGroup,
            )
        }
        is AppState.NewExercise -> {
            val selectedWorkout= (appState as AppState.NewExercise).selectedWorkout
            val selectedExerciseGroup= (appState as AppState.NewExercise).selectedExerciseGroup
            ExerciseForm(
                onExerciseUpsert = {
                    val exercise = it.copy(id=selectedExerciseGroup.exercises.size)
                    val editedExerciseGroup = selectedExerciseGroup.copy(exercises = selectedExerciseGroup.exercises + exercise)
                    val updatedExercises = selectedWorkout.exercises.map { exerciseGroup ->
                        if (exerciseGroup.id == editedExerciseGroup.id) editedExerciseGroup else exerciseGroup
                    }
                    val newWorkout = selectedWorkout.copy(exercises = updatedExercises)
                    filesViewModel.editWorkout(context.filesDir,newWorkout){
                        syncWorkoutsWithDevice(dataClient,filesViewModel)
                        appViewModel.setState(AppState.ExerciseGroupDetail(selectedWorkout = newWorkout,selectedExerciseGroup= editedExerciseGroup))
                    }
                },
                onCancel = { appViewModel.setState(AppState.ExerciseGroupDetail(selectedWorkout = selectedWorkout,selectedExerciseGroup= selectedExerciseGroup)) },
            )
        }
        is AppState.EditExercise -> {
            val selectedWorkout= (appState as AppState.EditExercise).selectedWorkout
            val selectedExerciseGroup= (appState as AppState.EditExercise).selectedExerciseGroup
            ExerciseForm(
                onExerciseUpsert = {
                    val updatedExercises = selectedExerciseGroup.exercises.map { exercise ->
                        if (exercise.id == it.id) it else exercise
                    }

                    val editedExerciseGroup = selectedExerciseGroup.copy(exercises = updatedExercises)
                    val updatedExerciseGroups = selectedWorkout.exercises.map { exerciseGroup ->
                        if (exerciseGroup.id == editedExerciseGroup.id) editedExerciseGroup else exerciseGroup
                    }
                    val newWorkout = selectedWorkout.copy(exercises = updatedExerciseGroups)
                    filesViewModel.editWorkout(context.filesDir,newWorkout){
                        syncWorkoutsWithDevice(dataClient,filesViewModel)
                        appViewModel.setState(AppState.ExerciseGroupDetail(selectedWorkout = newWorkout,selectedExerciseGroup= editedExerciseGroup))
                    }
                },
                onCancel = { appViewModel.setState(AppState.ExerciseGroupDetail(selectedWorkout = selectedWorkout,selectedExerciseGroup= selectedExerciseGroup)) },
                onDelete = {
                    val updatedExercises = selectedExerciseGroup.exercises.filter { exercise ->
                        exercise.id != it.id
                    }

                    val editedExerciseGroup = selectedExerciseGroup.copy(exercises = updatedExercises)
                    val updatedExerciseGroups = selectedWorkout.exercises.map { exerciseGroup ->
                        if (exerciseGroup.id == editedExerciseGroup.id) editedExerciseGroup else exerciseGroup
                    }
                    val newWorkout = selectedWorkout.copy(exercises = updatedExerciseGroups)
                    filesViewModel.editWorkout(context.filesDir,newWorkout){
                        syncWorkoutsWithDevice(dataClient,filesViewModel)
                        appViewModel.setState(AppState.ExerciseGroupDetail(selectedWorkout = newWorkout,selectedExerciseGroup= editedExerciseGroup))
                    }
                },
                exercise = (appState as AppState.EditExercise).selectedExercise
            )
        }
        else -> {}
    }
}*/


