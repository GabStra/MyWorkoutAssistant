package com.gabstra.myworkoutassistant

import android.app.Activity
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
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
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
import androidx.compose.ui.platform.LocalContext
import androidx.health.connect.client.HealthConnectClient
import com.gabstra.myworkoutassistant.screens.BarbellForm
import com.gabstra.myworkoutassistant.screens.DumbbellsForm
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
import com.gabstra.myworkoutassistant.shared.ExerciseInfo
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbells
import com.gabstra.myworkoutassistant.shared.equipments.Equipment
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.fromAppBackupToJSONPrettyPrint
import com.gabstra.myworkoutassistant.shared.fromJSONtoAppBackup
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.ui.theme.MyWorkoutAssistantTheme
import com.google.accompanist.systemuicontroller.rememberSystemUiController
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale
import java.util.UUID

class MyReceiver(
    private val appViewModel: AppViewModel,
    private val workoutStoreRepository: WorkoutStoreRepository,
    private val activity: Activity
) : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        activity.run {
            try{
                if(intent.getStringExtra(DataLayerListenerService.UPDATE_WORKOUTS) != null){
                    appViewModel.updateWorkoutStore(workoutStoreRepository.getWorkoutStore(),false)
                    appViewModel.triggerUpdate()
                }
            }catch (e: Exception) {
                Toast.makeText(context, "Error receiving workout history", Toast.LENGTH_SHORT)
                    .show()
            }
        }
    }
}

class MainActivity : ComponentActivity() {
    private val dataClient by lazy { Wearable.getDataClient(this) }

    private val db by lazy { AppDatabase.getDatabase(this) }

    private val appViewModel: AppViewModel by viewModels()

    private val workoutStoreRepository by lazy { WorkoutStoreRepository(this.filesDir) }

    private lateinit var myReceiver: BroadcastReceiver

    private val healthConnectClient by lazy { HealthConnectClient.getOrCreate(this) }

    override fun onStart() {
        super.onStart()
        appViewModel.updateWorkoutStore(workoutStoreRepository.getWorkoutStore())
    }

    override fun onDestroy(){
        super.onDestroy()
        db.close()
        if(::myReceiver.isInitialized) {
            unregisterReceiver(myReceiver)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        myReceiver = MyReceiver(appViewModel, workoutStoreRepository,this)
        val filter = IntentFilter(DataLayerListenerService.INTENT_ID)
        registerReceiver(myReceiver, filter, RECEIVER_NOT_EXPORTED)

        setContent {
            MyWorkoutAssistantTheme {
                // A surface container using the 'background' color from the theme
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    MyWorkoutAssistantNavHost(dataClient, appViewModel, workoutStoreRepository, db,healthConnectClient)
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

@OptIn(FlowPreview::class)
@Composable
fun MyWorkoutAssistantNavHost(
    dataClient: DataClient,
    appViewModel: AppViewModel,
    workoutStoreRepository: WorkoutStoreRepository,
    db: AppDatabase,
    healthConnectClient: HealthConnectClient
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
    val exerciseInfoDao = db.exerciseInfoDao()

    val updateMobileFlow = appViewModel.updateMobileFlow

    LaunchedEffect(appViewModel.workoutStore) {
        workoutStoreRepository.saveWorkoutStore(appViewModel.workoutStore)
    }

    val equipments by appViewModel.equipmentsFlow.collectAsState()
    LaunchedEffect(equipments) {
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

                            val newWorkoutStore = appBackup.WorkoutStore.copy(workouts = allowedWorkouts)

                            val deleteAndInsertJob = launch {
                                workoutHistoryDao.deleteAll()
                                setHistoryDao.deleteAll()
                                exerciseInfoDao.deleteAll()

                                val validWorkoutHistories = appBackup.WorkoutHistories.filter { workoutHistory ->
                                    allowedWorkouts.any { workout -> workout.id == workoutHistory.workoutId }
                                }

                                workoutHistoryDao.insertAll(*validWorkoutHistories.toTypedArray())

                                val validSetHistories = appBackup.SetHistories.filter { setHistory ->
                                    validWorkoutHistories.any { workoutHistory -> workoutHistory.id == setHistory.workoutHistoryId }
                                }

                                setHistoryDao.insertAll(*validSetHistories.toTypedArray())

                                val allExercises = allowedWorkouts.flatMap { workout -> workout.workoutComponents.filterIsInstance<Exercise>() }

                                val validExerciseInfos = appBackup.ExerciseInfos.filter { allExercises.any { exercise -> exercise.id == it.id } }
                                exerciseInfoDao.insertAll(*validExerciseInfos.toTypedArray())
                            }

                            // Wait for the delete and insert operations to complete
                            deleteAndInsertJob.join()

                            appViewModel.updateWorkoutStore(newWorkoutStore)
                            workoutStoreRepository.saveWorkoutStore(newWorkoutStore)
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

    try{

    }catch (e: Exception){
        Log.e("MainActivity", "Error showing workout detail", e)
        Toast.makeText(context, "Error showing workout detail", Toast.LENGTH_SHORT).show()
    }

    AnimatedContent(
        targetState = appViewModel.currentScreenData,
        transitionSpec = {
            fadeIn(animationSpec = tween(500)) togetherWith fadeOut(animationSpec = tween(500))
        }, label = ""
    ) { currentScreen ->
        when (currentScreen) {
            is ScreenData.Workouts -> {
                WorkoutsScreen(
                    appViewModel,
                    workoutHistoryDao,
                    setHistoryDao,
                    healthConnectClient,
                    onSyncClick = {
                        scope.launch {
                            withContext(Dispatchers.IO){
                                val workoutHistories = workoutHistoryDao.getAllWorkoutHistories()

                                val allowedWorkouts = appViewModel.workoutStore.workouts.filter { workout ->
                                    workout.isActive || (!workout.isActive && workoutHistories.any { it.workoutId == workout.id })
                                }

                                val validWorkoutHistories = workoutHistories.filter { workoutHistory ->
                                    allowedWorkouts.any { workout -> workout.id == workoutHistory.workoutId } && workoutHistory.isDone
                                }

                                val setHistories = setHistoryDao.getAllSetHistories().filter{ setHistory ->
                                    validWorkoutHistories.any { it.id == setHistory.workoutHistoryId }
                                }

                                val exerciseInfos = exerciseInfoDao.getAllExerciseInfos()
                                val appBackup = AppBackup(appViewModel.workoutStore, validWorkoutHistories, setHistories, exerciseInfos)
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
                                val sdf = SimpleDateFormat("dd_MM_yyyy_HH_mm_ss", Locale.getDefault())
                                val currentDate = sdf.format(Date())
                                val filename = "my_workout_history_$currentDate.json"

                                val workoutHistories = workoutHistoryDao.getAllWorkoutHistories()

                                val allowedWorkouts = appViewModel.workoutStore.workouts.filter { workout ->
                                    workout.isActive || (!workout.isActive && workoutHistories.any { it.workoutId == workout.id })
                                }

                                val validWorkoutHistories = workoutHistories.filter { workoutHistory ->
                                    allowedWorkouts.any { workout -> workout.id == workoutHistory.workoutId }
                                }

                                val setHistories = setHistoryDao.getAllSetHistories().filter{ setHistory ->
                                    validWorkoutHistories.any { it.id == setHistory.workoutHistoryId }
                                }
                                val exerciseInfos = exerciseInfoDao.getAllExerciseInfos()

                                val appBackup = AppBackup(appViewModel.workoutStore.copy(workouts = allowedWorkouts), validWorkoutHistories, setHistories,exerciseInfos)
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
                            appViewModel.triggerUpdate()
                        }
                    },
                    onSyncToHealthConnectClick = {
                        scope.launch {
                            try{
                                val currentYear = Calendar.getInstance().get(Calendar.YEAR)
                                val age =  currentYear - appViewModel.workoutStore.birthDateYear
                                val weight = appViewModel.workoutStore.weightKg

                                sendWorkoutsToHealthConnect(
                                    healthConnectClient = healthConnectClient,
                                    workouts = appViewModel.workouts,
                                    workoutHistoryDao = workoutHistoryDao,
                                    updateAll = true,
                                    age = age,
                                    weightKg = weight
                                )
                                Toast.makeText(context, "Synced to HealthConnect", Toast.LENGTH_SHORT).show()
                            }catch (e: Exception){
                                Log.e("MainActivity", "Error syncing to HealthConnect", e)
                                Toast.makeText(context, "Error syncing to HealthConnect", Toast.LENGTH_SHORT).show()
                            }
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
                val screenData = currentScreen as ScreenData.EditWorkout
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
                val screenData = currentScreen as ScreenData.WorkoutDetail
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
                    setHistoryDao,
                    exerciseInfoDao,
                    selectedWorkout,
                ) {
                    appViewModel.goBack()
                }

            }

            is ScreenData.WorkoutHistory -> {
                val screenData = currentScreen as ScreenData.WorkoutHistory
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
                val screenData = currentScreen as ScreenData.ExerciseDetail
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
                val screenData = currentScreen as ScreenData.ExerciseHistory
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
                val screenData = currentScreen as ScreenData.NewExercise
                val workouts by appViewModel.workoutsFlow.collectAsState()

                var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!
                var currentWorkout = selectedWorkout

                while(!currentWorkout.isActive){
                    val nextWorkout = workouts.find { it.id == currentWorkout.nextVersionId }!!
                    currentWorkout = nextWorkout
                }

                selectedWorkout = currentWorkout

                ExerciseForm(
                    appViewModel,
                    onExerciseUpsert = { newExercise ->
                        appViewModel.addWorkoutComponent(selectedWorkout, newExercise)
                        appViewModel.goBack()
                    },
                    onCancel = { appViewModel.goBack() },
                    allowSettingDoNotStoreHistory = true
                )
            }

            is ScreenData.EditExercise -> {
                val screenData = currentScreen as ScreenData.EditExercise
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

                Log.d("EditExercise", "selectedExercise: $selectedExercise")

                ExerciseForm(
                    appViewModel,
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
                val screenData = currentScreen as ScreenData.NewSet
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
                    viewModel = appViewModel
                )
            }

            is ScreenData.NewRestSet -> {
                val screenData = currentScreen as ScreenData.NewRestSet
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
                    onRestSetUpsert = { newRestSet ->
                        val oldSets = parentExercise.sets.filter { it !is RestSet }
                        val modifiedSets = oldSets
                            .flatMapIndexed { index, element ->
                                if (index != oldSets.size - 1) {
                                    listOf(element, newRestSet.copy(id = java.util.UUID.randomUUID()))
                                } else {
                                    listOf(element)
                                }
                            }

                        val updatedExercise = parentExercise.copy(sets = modifiedSets)

                        appViewModel.updateWorkoutComponent(
                            selectedWorkout,
                            parentExercise,
                            updatedExercise
                        )

                        appViewModel.goBack()
                    },
                    onCancel = {
                        appViewModel.goBack()
                    },
                )
            }

            is ScreenData.EditRestSet -> {
                val screenData = currentScreen as ScreenData.EditRestSet
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
                val screenData = currentScreen as ScreenData.NewRest
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
                        val oldWorkoutComponents = selectedWorkout.workoutComponents.filter { it !is Rest }

                        val modifiedWorkoutComponents = oldWorkoutComponents
                            .flatMapIndexed { index, element ->
                                if (index != oldWorkoutComponents.size - 1) {
                                    listOf(element, newRest.copy(id = java.util.UUID.randomUUID()))
                                } else {
                                    listOf(element)
                                }
                            }

                        val updatedWorkout = selectedWorkout.copy(workoutComponents = modifiedWorkoutComponents)
                        appViewModel.updateWorkout(selectedWorkout, updatedWorkout)
                        appViewModel.goBack()
                    },
                    onCancel = { appViewModel.goBack() },
                )
            }

            is ScreenData.EditRest -> {
                val screenData = currentScreen as ScreenData.EditRest
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
                    rest = screenData.selectedRest
                )
            }

            //CURRENTLY DISABLED
            is ScreenData.EditSet -> {
                val screenData = currentScreen as ScreenData.EditSet
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
                    viewModel = appViewModel
                )
            }

            is ScreenData.NewEquipment -> {
                val screenData = currentScreen as ScreenData.NewEquipment
                val equipments by appViewModel.equipmentsFlow.collectAsState()

                when (screenData.equipmentType) {
                    EquipmentType.BARBELL -> {
                        BarbellForm(onBarbellUpsert = { newBarbell ->
                            val newEquipments = equipments + newBarbell
                            appViewModel.updateEquipments(newEquipments)
                            appViewModel.goBack()
                        }, onCancel = { appViewModel.goBack() })
                    }
                    EquipmentType.DUMBBELLS -> {
                        DumbbellsForm(onDumbbellsUpsert = { newDumbbells ->
                            val newEquipments = equipments + newDumbbells
                            appViewModel.updateEquipments(newEquipments)
                            appViewModel.goBack()
                        }, onCancel = { appViewModel.goBack() })
                    }
                }
            }

            is ScreenData.EditEquipment -> {
                val screenData = currentScreen as ScreenData.EditEquipment
                val equipments by appViewModel.equipmentsFlow.collectAsState()

                when (screenData.equipmentType) {
                    EquipmentType.BARBELL -> {
                        val selectedBarbell = equipments.find { it.id == screenData.equipmentId } as Barbell
                        BarbellForm(onBarbellUpsert = { updatedBarbell ->
                            val updatedEquipments = equipments.map { equipment ->
                                if (equipment.id == selectedBarbell.id) updatedBarbell else equipment
                            }
                            appViewModel.updateEquipments(updatedEquipments)
                            appViewModel.goBack()
                        }, onCancel = { appViewModel.goBack() }, barbell = selectedBarbell)
                    }
                    EquipmentType.DUMBBELLS -> {
                        val selectedDumbbells = equipments.find { it.id == screenData.equipmentId } as Dumbbells
                        DumbbellsForm(onDumbbellsUpsert = { updatedDumbbells ->
                            val updatedEquipments = equipments.map { equipment ->
                                if (equipment.id == selectedDumbbells.id) updatedDumbbells else equipment
                            }
                            appViewModel.updateEquipments(updatedEquipments)
                            appViewModel.goBack()
                        }, onCancel = { appViewModel.goBack() }, dumbbells = selectedDumbbells)
                    }
                }
            }
        }
    }
}

