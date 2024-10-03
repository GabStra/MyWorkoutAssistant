package com.gabstra.myworkoutassistant

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
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
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import com.gabstra.myworkoutassistant.screens.ExerciseDetailScreen
import com.gabstra.myworkoutassistant.screens.ExerciseForm
import com.gabstra.myworkoutassistant.screens.ExerciseHistoryScreen
import com.gabstra.myworkoutassistant.screens.RestForm
import com.gabstra.myworkoutassistant.screens.RestSetForm
import com.gabstra.myworkoutassistant.screens.SetForm
import com.gabstra.myworkoutassistant.screens.SettingsScreen
import com.gabstra.myworkoutassistant.screens.WorkoutDetailScreen
import com.gabstra.myworkoutassistant.screens.WorkoutForm
import com.gabstra.myworkoutassistant.screens.WorkoutHistoryScreen
import com.gabstra.myworkoutassistant.screens.WorkoutsScreen
import com.gabstra.myworkoutassistant.shared.AppBackup
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.fromAppBackupToJSONPrettyPrint
import com.gabstra.myworkoutassistant.shared.fromJSONtoAppBackup
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.ui.theme.MyWorkoutAssistantTheme
import com.google.accompanist.systemuicontroller.rememberSystemUiController
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class MainActivity : ComponentActivity() {
    private val dataClient by lazy { Wearable.getDataClient(this) }

    private val db by lazy { AppDatabase.getDatabase(this) }

    private val appViewModel: AppViewModel by viewModels()

    private val workoutStoreRepository by lazy { WorkoutStoreRepository(this.filesDir) }

    private lateinit var myReceiver: BroadcastReceiver

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

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        myReceiver = object : BroadcastReceiver() {
            override fun onReceive(context: Context, intent: Intent) {
                try{
                    if( intent.getStringExtra(DataLayerListenerService.UPDATE_WORKOUTS) != null){
                        appViewModel.updateWorkoutStore(workoutStoreRepository.getWorkoutStore(),false)
                        appViewModel.triggerUpdate()
                        Toast.makeText(context, "Workout history received", Toast.LENGTH_SHORT).show()
                    }
                }catch (_: Exception) {
                }
            }
        }

        setContent {
            MyWorkoutAssistantTheme {
                // A surface container using the 'background' color from the theme
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    MyWorkoutAssistantNavHost(dataClient, appViewModel, workoutStoreRepository, db)
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent) // Update the old intent
        val receivedValue = intent.getStringExtra(DataLayerListenerService.PAGE)
        receivedValue?.let { page ->
            when (page) {
                "workouts" -> {
                    appViewModel.setScreenData(ScreenData.Workouts(1))
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
    workoutStoreRepository: WorkoutStoreRepository,
    db: AppDatabase
) {
    val context = LocalContext.current

    val systemUiController = rememberSystemUiController()
    val backgroundColor = MaterialTheme.colorScheme.background

    DisposableEffect(systemUiController,backgroundColor) {
        // Update all of the system bar colors to be transparent, and use
        // dark icons if we're in light theme
        systemUiController.setSystemBarsColor(
            color = backgroundColor,
            darkIcons = false
        )

        systemUiController.setNavigationBarColor(
            color = backgroundColor,
            darkIcons = false
        )

        // setStatusBarColor() and setNavigationBarColor() also exist

        onDispose {}
    }

    val setHistoryDao = db.setHistoryDao()
    val workoutHistoryDao = db.workoutHistoryDao()

    val updateMobile by appViewModel.updateMobileFlow.collectAsState(initial = null)

    LaunchedEffect(updateMobile) {
        if(updateMobile == null) return@LaunchedEffect

        val latestWorkoutHistories = appViewModel.workouts.filter { it -> it.isActive && it.enabled }.mapNotNull { workout ->
            workoutHistoryDao.getLatestWorkoutHistoryByWorkoutId(workout.id)
        }

        val setHistories = latestWorkoutHistories.flatMap { workoutHistory ->
            setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)
        }

        val workoutStore = appViewModel.workoutStore.copy(
            workouts = appViewModel.workouts.filter { it -> it.isActive && it.enabled }
        )

        val filteredAppBackup = AppBackup(workoutStore, latestWorkoutHistories, setHistories)

        sendAppBackup(dataClient, filteredAppBackup)
    }

    LaunchedEffect(appViewModel.workouts) {
        workoutStoreRepository.saveWorkoutStore(appViewModel.workoutStore)
    }

    BackHandler(enabled = true) {
        val canGoBack = appViewModel.goBack()
        if (!canGoBack) {
            (context as? ComponentActivity)?.finish()
        }
    }

    val scope = rememberCoroutineScope()

    val jsonPickerLauncher =
        rememberLauncherForActivityResult(contract = ActivityResultContracts.OpenDocument()) { uri: Uri? ->
            uri?.let {
                try {
                    context.contentResolver.openInputStream(it)?.use { inputStream ->
                        val reader = inputStream.bufferedReader()
                        val content = reader.readText()
                        val appBackup = fromJSONtoAppBackup(content)

                        scope.launch {
                            val allowedWorkouts = appBackup.WorkoutStore.workouts.filter { workout ->
                                workout.isActive || (!workout.isActive && appBackup.WorkoutHistories.any { it.workoutId == workout.id })
                            }

                            workoutStoreRepository.saveWorkoutStore( appBackup.WorkoutStore.copy(workouts = allowedWorkouts))

                            val deleteAndInsertJob = launch {
                                workoutHistoryDao.deleteAll()
                                setHistoryDao.deleteAll()

                                val validWorkoutHistories = appBackup.WorkoutHistories.filter { workoutHistory ->
                                    allowedWorkouts.any { workout -> workout.id == workoutHistory.workoutId }
                                }

                                workoutHistoryDao.insertAll(*validWorkoutHistories.toTypedArray())

                                val validSetHistories = appBackup.SetHistories.filter { setHistory ->
                                    validWorkoutHistories.any { workoutHistory -> workoutHistory.id == setHistory.workoutHistoryId }
                                }

                                setHistoryDao.insertAll(*validSetHistories.toTypedArray())
                            }

                            // Wait for the delete and insert operations to complete
                            deleteAndInsertJob.join()

                            appViewModel.updateWorkoutStore(workoutStoreRepository.getWorkoutStore())
                            appViewModel.triggerUpdate()

                            // Show the success toast after all operations are complete
                            Toast.makeText(
                                context,
                                "Data restored from backup",
                                Toast.LENGTH_SHORT
                            ).show()
                        }
                    }
                } catch (e: Exception) {
                    Toast.makeText(context, "Failed to import data from backup", Toast.LENGTH_SHORT)
                        .show()
                }
            }
        }

    when (appViewModel.currentScreenData) {
        is ScreenData.Workouts -> {
            WorkoutsScreen(
                appViewModel,
                workoutHistoryDao,
                setHistoryDao,
                onSyncClick = {
                    scope.launch {
                        withContext(Dispatchers.IO){
                            val latestWorkoutHistories = appViewModel.workouts.mapNotNull { workout ->
                                workoutHistoryDao.getLatestWorkoutHistoryByWorkoutId(workout.id)
                            }

                            val setHistories = latestWorkoutHistories.flatMap { workoutHistory ->
                                setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)
                            }

                            val appBackup = AppBackup(appViewModel.workoutStore, latestWorkoutHistories, setHistories)
                            sendAppBackup(dataClient, appBackup)
                        }
                        Toast.makeText(context, "Data sent to watch", Toast.LENGTH_SHORT).show()
                    }
                },
                onOpenSettingsClick = {
                    appViewModel.setScreenData(ScreenData.Settings())
                },
                onBackupClick = {
                    scope.launch {
                        try{
                            val sdf = SimpleDateFormat("dd_MM_yyyy", Locale.getDefault())
                            val currentDate = sdf.format(Date())
                            val filename = "my_workout_history_$currentDate.json"

                            val workoutHistories = workoutHistoryDao.getAllWorkoutHistories()
                            val setHistories = setHistoryDao.getAllSetHistories()
                            val appBackup = AppBackup(appViewModel.workoutStore, workoutHistories, setHistories)
                            val jsonString = fromAppBackupToJSONPrettyPrint(appBackup)
                            writeJsonToDownloadsFolder(context, filename, jsonString)
                            Toast.makeText(
                                context,
                                "Backup saved to downloads folder",
                                Toast.LENGTH_SHORT
                            ).show()
                        }catch (e: Exception){
                            Log.e("MainActivity", "Error saving backup", e)
                            Toast.makeText(
                                context,
                                "Backup failed",
                                Toast.LENGTH_SHORT
                            ).show()
                        }

                    }

                },
                onRestoreClick = {
                    jsonPickerLauncher.launch(arrayOf("application/json"))
                },
                onClearUnfinishedWorkouts = {
                    scope.launch {
                        workoutHistoryDao.deleteAllUnfinished()
                        appViewModel.triggerUpdate()
                    }
                },
                onClearAllHistories = {
                    scope.launch {
                        workoutHistoryDao.deleteAll()
                        setHistoryDao.deleteAll()
                        Toast.makeText(context, "All histories cleared", Toast.LENGTH_SHORT).show()

                        appViewModel.updateWorkoutStore(workoutStoreRepository.getWorkoutStore())
                    }
                },
                selectedTabIndex = appViewModel.selectedHomeTab
            )
        }

        is ScreenData.Settings -> {
            SettingsScreen(
                onSave = { newWorkoutStore ->
                    appViewModel.updateWorkoutStore(newWorkoutStore)
                    workoutStoreRepository.saveWorkoutStore(newWorkoutStore)
                    sendWorkoutStore(dataClient, appViewModel.workoutStore)
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
                    appViewModel.updateWorkoutOld(selectedWorkout, updatedWorkout)
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

            var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!

            var currentWorkout = selectedWorkout

            while(!currentWorkout.isActive){
                val nextWorkout = workouts.find { it.id == currentWorkout.nextVersionId }!!
                currentWorkout = nextWorkout
            }

            selectedWorkout = currentWorkout

            WorkoutDetailScreen(
                appViewModel,
                workoutHistoryDao,
                selectedWorkout,
            ) {
                appViewModel.goBack()
            }
        }

        is ScreenData.WorkoutHistory -> {
            val screenData = appViewModel.currentScreenData as ScreenData.WorkoutHistory
            val workouts by appViewModel.workoutsFlow.collectAsState()
            val selectedWorkout = workouts.find { it.id == screenData.workoutId }!!

            WorkoutHistoryScreen(
                appViewModel,
                workoutHistoryDao,
                screenData.workoutHistoryId,
                setHistoryDao,
                selectedWorkout,
            ) {
                appViewModel.goBack()
            }
        }

        is ScreenData.ExerciseDetail -> {
            val screenData = appViewModel.currentScreenData as ScreenData.ExerciseDetail
            val workouts by appViewModel.workoutsFlow.collectAsState()

            var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!
            var currentWorkout = selectedWorkout

            while(!currentWorkout.isActive){
                val nextWorkout = workouts.find { it.id == currentWorkout.nextVersionId }!!
                currentWorkout = nextWorkout
            }

            selectedWorkout = currentWorkout

            val selectedExercise = findWorkoutComponentByIdInWorkout(
                selectedWorkout,
                screenData.selectedExerciseId
            ) as Exercise

            ExerciseDetailScreen(
                appViewModel,
                selectedWorkout,
                setHistoryDao,
                selectedExercise
            ) {
                appViewModel.goBack()
            }
        }

        is ScreenData.ExerciseHistory -> {
            val screenData = appViewModel.currentScreenData as ScreenData.ExerciseHistory
            val workouts by appViewModel.workoutsFlow.collectAsState()
            var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!

            var currentWorkout = selectedWorkout

            while(!currentWorkout.isActive){
                val nextWorkout = workouts.find { it.id == currentWorkout.nextVersionId }!!
                currentWorkout = nextWorkout
            }

            selectedWorkout = currentWorkout

            val selectedExercise = findWorkoutComponentByIdInWorkout(
                selectedWorkout,
                screenData.selectedExerciseId
            ) as Exercise

            ExerciseHistoryScreen(
                appViewModel,
                selectedWorkout,
                workoutHistoryDao,
                setHistoryDao,
                selectedExercise
            ) {
                appViewModel.goBack()
            }
        }

        is ScreenData.NewExercise -> {
            val screenData = appViewModel.currentScreenData as ScreenData.NewExercise
            val workouts by appViewModel.workoutsFlow.collectAsState()

            var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!
            var currentWorkout = selectedWorkout

            while(!currentWorkout.isActive){
                val nextWorkout = workouts.find { it.id == currentWorkout.nextVersionId }!!
                currentWorkout = nextWorkout
            }

            selectedWorkout = currentWorkout

            ExerciseForm(
                onExerciseUpsert = { newExercise ->
                    appViewModel.addWorkoutComponent(selectedWorkout, newExercise)
                    appViewModel.goBack()
                },
                onCancel = { appViewModel.goBack() },
                allowSettingDoNotStoreHistory = true
            )
        }

        is ScreenData.EditExercise -> {
            val screenData = appViewModel.currentScreenData as ScreenData.EditExercise
            val workouts by appViewModel.workoutsFlow.collectAsState()

            var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!

            var currentWorkout = selectedWorkout

            while(!currentWorkout.isActive){
                val nextWorkout = workouts.find { it.id == currentWorkout.nextVersionId }!!
                currentWorkout = nextWorkout
            }

            selectedWorkout = currentWorkout

            val selectedExercise = findWorkoutComponentByIdInWorkout(
                selectedWorkout,
                screenData.selectedExerciseId
            ) as Exercise

            ExerciseForm(
                onExerciseUpsert = { updatedExercise ->
                    appViewModel.updateWorkoutComponentOld(
                        selectedWorkout,
                        selectedExercise,
                        updatedExercise
                    )
                    appViewModel.goBack()
                },
                onCancel = {
                    appViewModel.goBack()
                },
                exercise = selectedExercise,
                allowSettingDoNotStoreHistory = true
            )
        }

        is ScreenData.NewSet -> {
            val screenData = appViewModel.currentScreenData as ScreenData.NewSet
            val workouts by appViewModel.workoutsFlow.collectAsState()
            var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!

            var currentWorkout = selectedWorkout

            while(!currentWorkout.isActive){
                val nextWorkout = workouts.find { it.id == currentWorkout.nextVersionId }!!
                currentWorkout = nextWorkout
            }

            selectedWorkout = currentWorkout

            val parentExercise = findWorkoutComponentByIdInWorkout(
                selectedWorkout,
                screenData.parentExerciseId
            ) as Exercise
            SetForm(
                onSetUpsert = { updatedSet ->
                    appViewModel.addSetToExercise(selectedWorkout, parentExercise, updatedSet)
                    appViewModel.goBack()
                },
                onCancel = {
                    appViewModel.goBack()
                },
                exerciseType = parentExercise.exerciseType,
            )
        }

        is ScreenData.NewRestSet -> {
            val screenData = appViewModel.currentScreenData as ScreenData.NewRestSet
            val workouts by appViewModel.workoutsFlow.collectAsState()
            var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!

            var currentWorkout = selectedWorkout

            while(!currentWorkout.isActive){
                val nextWorkout = workouts.find { it.id == currentWorkout.nextVersionId }!!
                currentWorkout = nextWorkout
            }

            selectedWorkout = currentWorkout

            val parentExercise = findWorkoutComponentByIdInWorkout(
                selectedWorkout,
                screenData.parentExerciseId
            ) as Exercise
            RestSetForm(
                onRestSetUpsert = { updatedSet ->
                    appViewModel.addSetToExercise(selectedWorkout, parentExercise, updatedSet)
                    appViewModel.goBack()
                },
                onCancel = {
                    appViewModel.goBack()
                },
            )
        }

        is ScreenData.EditRestSet -> {
            val screenData = appViewModel.currentScreenData as ScreenData.EditRestSet
            val workouts by appViewModel.workoutsFlow.collectAsState()

            var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!

            var currentWorkout = selectedWorkout

            while(!currentWorkout.isActive){
                val nextWorkout = workouts.find { it.id == currentWorkout.nextVersionId }!!
                currentWorkout = nextWorkout
            }

            selectedWorkout = currentWorkout

            val parentExercise = findWorkoutComponentByIdInWorkout(
                selectedWorkout,
                screenData.parentExerciseId
            ) as Exercise
            RestSetForm(
                onRestSetUpsert = { updatedSet ->
                    appViewModel.updateSetInExercise(
                        selectedWorkout,
                        parentExercise,
                        screenData.selectedRestSet,
                        updatedSet
                    )
                    appViewModel.goBack()
                },
                onCancel = {
                    appViewModel.goBack()
                },
                restSet = screenData.selectedRestSet,
            )
        }

        is ScreenData.NewRest -> {
            val screenData = appViewModel.currentScreenData as ScreenData.NewRest
            val workouts by appViewModel.workoutsFlow.collectAsState()

            var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!
            var currentWorkout = selectedWorkout

            while(!currentWorkout.isActive){
                val nextWorkout = workouts.find { it.id == currentWorkout.nextVersionId }!!
                currentWorkout = nextWorkout
            }

            selectedWorkout = currentWorkout

            RestForm(
                onRestUpsert = { newRest ->
                    appViewModel.addWorkoutComponent(selectedWorkout, newRest)
                    appViewModel.goBack()
                },
                onCancel = { appViewModel.goBack() },
            )
        }

        is ScreenData.EditRest -> {
            val screenData = appViewModel.currentScreenData as ScreenData.EditRest
            val workouts by appViewModel.workoutsFlow.collectAsState()

            var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!

            var currentWorkout = selectedWorkout

            while(!currentWorkout.isActive){
                val nextWorkout = workouts.find { it.id == currentWorkout.nextVersionId }!!
                currentWorkout = nextWorkout
            }

            selectedWorkout = currentWorkout

            RestForm(
                onRestUpsert = { newRest ->
                    appViewModel.updateWorkoutComponentOld(selectedWorkout, screenData.selectedRest,newRest)
                    appViewModel.goBack()
                },
                onCancel = { appViewModel.goBack() },
            )
        }

        //CURRENTLY DISABLED
        is ScreenData.EditSet -> {
            val screenData = appViewModel.currentScreenData as ScreenData.EditSet
            val workouts by appViewModel.workoutsFlow.collectAsState()

            var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!

            var currentWorkout = selectedWorkout

            while(!currentWorkout.isActive){
                val nextWorkout = workouts.find { it.id == currentWorkout.nextVersionId }!!
                currentWorkout = nextWorkout
            }

            selectedWorkout = currentWorkout

            val parentExercise = findWorkoutComponentByIdInWorkout(
                selectedWorkout,
                screenData.parentExerciseId
            ) as Exercise
            SetForm(
                onSetUpsert = { updatedSet ->
                    appViewModel.updateSetInExercise(
                        selectedWorkout,
                        parentExercise,
                        screenData.selectedSet,
                        updatedSet
                    )
                    appViewModel.goBack()
                },
                onCancel = {
                    appViewModel.goBack()
                },
                set = screenData.selectedSet,
                exerciseType = parentExercise.exerciseType,
            )
        }
    }
}

