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
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.health.connect.client.HealthConnectClient
import com.gabstra.myworkoutassistant.screens.ExerciseDetailScreen
import com.gabstra.myworkoutassistant.screens.ExerciseForm
import com.gabstra.myworkoutassistant.screens.ExerciseHistoryScreen
import com.gabstra.myworkoutassistant.screens.RestForm
import com.gabstra.myworkoutassistant.screens.RestSetForm
import com.gabstra.myworkoutassistant.screens.SetForm
import com.gabstra.myworkoutassistant.screens.SettingsScreen
import com.gabstra.myworkoutassistant.screens.SupersetForm
import com.gabstra.myworkoutassistant.screens.WorkoutDetailScreen
import com.gabstra.myworkoutassistant.screens.WorkoutForm
import com.gabstra.myworkoutassistant.screens.WorkoutHistoryScreen
import com.gabstra.myworkoutassistant.screens.WorkoutScreen
import com.gabstra.myworkoutassistant.screens.WorkoutsScreen
import com.gabstra.myworkoutassistant.screens.equipments.BarbellForm
import com.gabstra.myworkoutassistant.screens.equipments.DumbbellForm
import com.gabstra.myworkoutassistant.screens.equipments.DumbbellsForm
import com.gabstra.myworkoutassistant.screens.equipments.MachineForm
import com.gabstra.myworkoutassistant.screens.equipments.PlateLoadedCableForm
import com.gabstra.myworkoutassistant.screens.equipments.WeightVestForm
import com.gabstra.myworkoutassistant.shared.AppBackup
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.DarkGray
import com.gabstra.myworkoutassistant.shared.WorkoutSchedule
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbell
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbells
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.equipments.Machine
import com.gabstra.myworkoutassistant.shared.equipments.PlateLoadedCable
import com.gabstra.myworkoutassistant.shared.equipments.WeightVest
import com.gabstra.myworkoutassistant.shared.fromAppBackupToJSONPrettyPrint
import com.gabstra.myworkoutassistant.shared.fromJSONtoAppBackup
import com.gabstra.myworkoutassistant.shared.fromWorkoutStoreToJSON
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.ui.theme.MyWorkoutAssistantTheme
import com.google.accompanist.systemuicontroller.rememberSystemUiController
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

class MyReceiver(
    private val appViewModel: AppViewModel,
    private val workoutViewModel: WorkoutViewModel,
    private val workoutStoreRepository: WorkoutStoreRepository,
    private val activity: Activity
) : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        activity.run {
            try{
                if(intent.getStringExtra(DataLayerListenerService.UPDATE_WORKOUTS) != null){
                    val workoutStore = workoutStoreRepository.getWorkoutStore()

                    val healthConnectClient = HealthConnectClient.getOrCreate(this)
                    val db = AppDatabase.getDatabase(this)
                    var workoutHistoryDao = db.workoutHistoryDao()

                    val scope = CoroutineScope(Dispatchers.IO)

                    scope.launch {
                        appViewModel.updateWorkoutStore(workoutStore,false)
                        workoutViewModel.updateWorkoutStore(workoutStore)

                        appViewModel.triggerUpdate()

                        try{
                            val currentYear = Calendar.getInstance().get(Calendar.YEAR)
                            val workoutStore = workoutStoreRepository.getWorkoutStore()

                            val age =  currentYear - workoutStore.birthDateYear
                            val weight = workoutStore.weightKg

                            sendWorkoutsToHealthConnect(
                                healthConnectClient = healthConnectClient,
                                workouts = workoutStore.workouts,
                                workoutHistoryDao = workoutHistoryDao,
                                age = age,
                                weightKg = weight
                            )
                        }catch (exception: Exception){
                            Log.e("MyWorkoutAssistant", "Error sending workouts to HealthConnect", exception)
                        }
                    }
                }
            }catch (e: Exception) {
                Log.e("MyWorkoutAssistant", "Error in MyReceiver", e)
            }
        }
    }
}

class MainActivity : ComponentActivity() {
    private val dataClient by lazy { Wearable.getDataClient(this) }

    private val db by lazy { AppDatabase.getDatabase(this) }

    private val appViewModel: AppViewModel by viewModels()

    private val workoutViewModel: WorkoutViewModel by viewModels()

    private val hapticsViewModel: HapticsViewModel by viewModels {
        HapticsViewModelFactory(applicationContext)
    }

    private val workoutStoreRepository by lazy { WorkoutStoreRepository(this.filesDir) }

    private lateinit var myReceiver: BroadcastReceiver

    private val healthConnectClient by lazy { HealthConnectClient.getOrCreate(this) }

    override fun onStart() {
        super.onStart()
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

        myReceiver = MyReceiver(appViewModel, workoutViewModel,workoutStoreRepository,this)
        val filter = IntentFilter(DataLayerListenerService.INTENT_ID)
        registerReceiver(myReceiver, filter, RECEIVER_NOT_EXPORTED)

        setContent {
            MyWorkoutAssistantTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    MyWorkoutAssistantNavHost(
                        dataClient,
                        appViewModel,
                        workoutViewModel,
                        hapticsViewModel,
                        workoutStoreRepository,
                        db,
                        healthConnectClient
                    )
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
    workoutViewModel: WorkoutViewModel,
    hapticsViewModel: HapticsViewModel,
    workoutStoreRepository: WorkoutStoreRepository,
    db: AppDatabase,
    healthConnectClient: HealthConnectClient
) {
    val context = LocalContext.current

    val localContext = LocalContext.current
    workoutViewModel.initExerciseHistoryDao(localContext)
    workoutViewModel.initWorkoutHistoryDao(localContext)
    workoutViewModel.initWorkoutScheduleDao(localContext)
    workoutViewModel.initWorkoutRecordDao(localContext)
    workoutViewModel.initExerciseInfoDao(localContext)
    workoutViewModel.initWorkoutStoreRepository(workoutStoreRepository)

    val systemUiController = rememberSystemUiController()
    val backgroundColor = DarkGray

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
    val workoutScheduleDao = db.workoutScheduleDao()
    val workoutRecordDao = db.workoutRecordDao()

    val exerciseInfoDao = db.exerciseInfoDao()

    val updateMobileFlow = appViewModel.updateMobileFlow

    LaunchedEffect(Unit) {
        try{
            val workoutStore = workoutStoreRepository.getWorkoutStore()
            appViewModel.updateWorkoutStore(workoutStore)
            workoutViewModel.updateWorkoutStore(workoutStore)
        }catch (ex: Exception) {
            Log.e("MainActivity", "Error getting workout store", ex)
            Toast.makeText(context, "Error during startup, please check logs", Toast.LENGTH_SHORT).show()
        }
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
                                var allWorkoutHistories = workoutHistoryDao.getAllWorkoutHistories()

                                try {
                                    deleteWorkoutHistoriesFromHealthConnect(allWorkoutHistories,healthConnectClient)
                                }catch (e: Exception) {
                                    Log.e("MainActivity", "Error deleting workout histories from HealthConnect", e)
                                    Toast.makeText(context, "Failed to delete workout histories from HealthConnect", Toast.LENGTH_SHORT).show()
                                }

                                workoutHistoryDao.deleteAll()
                                setHistoryDao.deleteAll()
                                exerciseInfoDao.deleteAll()
                                workoutScheduleDao.deleteAll()
                                workoutRecordDao.deleteAll()

                                val validWorkoutHistories = appBackup.WorkoutHistories.filter { workoutHistory ->
                                    allowedWorkouts.any { workout -> workout.id == workoutHistory.workoutId }
                                }

                                workoutHistoryDao.insertAll(*validWorkoutHistories.toTypedArray())

                                val validSetHistories = appBackup.SetHistories.filter { setHistory ->
                                    validWorkoutHistories.any { workoutHistory -> workoutHistory.id == setHistory.workoutHistoryId }
                                }

                                setHistoryDao.insertAll(*validSetHistories.toTypedArray())

                                val allExercises = allowedWorkouts.flatMap { workout -> workout.workoutComponents.filterIsInstance<Exercise>() + workout.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises } }

                                val validExerciseInfos = appBackup.ExerciseInfos.filter { allExercises.any { exercise -> exercise.id == it.id } }
                                exerciseInfoDao.insertAll(*validExerciseInfos.toTypedArray())

                                val validWorkoutSchedules = appBackup.WorkoutSchedules.filter { allowedWorkouts.any { workout -> workout.globalId == it.workoutId } }
                                workoutScheduleDao.insertAll(*validWorkoutSchedules.toTypedArray())

                                if(appBackup.WorkoutRecords != null){
                                    val validWorkoutRecords = appBackup.WorkoutRecords.filter { allowedWorkouts.any { workout -> workout.id == it.workoutId } }
                                    workoutRecordDao.insertAll(*validWorkoutRecords.toTypedArray())
                                }
                            }

                            // Wait for the delete and insert operations to complete
                            deleteAndInsertJob.join()

                            appViewModel.updateWorkoutStore(newWorkoutStore)
                            workoutViewModel.updateWorkoutStore(newWorkoutStore)

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
                    Log.e("MainActivity", "Error importing data from backup", e)
                    Toast.makeText(context, "Failed to import data from backup", Toast.LENGTH_SHORT)
                        .show()
                }
            }
        }

    val syncWithWatch = {
        scope.launch {
            withContext(Dispatchers.IO){
                val workoutHistories = workoutHistoryDao.getAllWorkoutHistories()

                val allowedWorkouts = appViewModel.workoutStore.workouts.filter { workout ->
                    workout.isActive || (!workout.isActive && workoutHistories.any { it.workoutId == workout.id })
                }

                val adjustedWorkouts = allowedWorkouts.map { workout ->
                    val adjustedWorkoutComponents = workout.workoutComponents.map { workoutComponent ->
                        when (workoutComponent) {
                            is Exercise -> workoutComponent.copy(sets = ensureRestSeparatedBySets(workoutComponent.sets))
                            is Superset -> workoutComponent.copy(exercises = workoutComponent.exercises.map { exercise ->
                                exercise.copy(sets = ensureRestSeparatedBySets(exercise.sets))
                            })
                            is Rest -> workoutComponent
                        }
                    }

                    workout.copy(workoutComponents = ensureRestSeparatedByExercises(adjustedWorkoutComponents))
                }

                val workoutRecords = workoutRecordDao.getAll()

                val validWorkoutHistories = workoutHistories
                    .filter { workoutHistory -> allowedWorkouts.any { workout -> workout.id == workoutHistory.workoutId } && (workoutHistory.isDone || workoutRecords.any { it.workoutHistoryId == workoutHistory.id }) }
                    .groupBy { it.workoutId }
                    //IF FOR WHATEVER REASON WATCH NEEDS TO HAVE ALL HISTORIES, REMOVE THE FOLLOWING LINES
                    .mapNotNull { (_, histories) -> histories.maxByOrNull { it.startTime } }

                val setHistories = setHistoryDao.getAllSetHistories().filter{ setHistory ->
                    validWorkoutHistories.any { it.id == setHistory.workoutHistoryId }
                }

                val exerciseInfos = exerciseInfoDao.getAllExerciseInfos()
                val workoutSchedules = workoutScheduleDao.getAllSchedules()

                val appBackup = AppBackup(appViewModel.workoutStore.copy(workouts = adjustedWorkouts), validWorkoutHistories, setHistories, exerciseInfos,workoutSchedules,workoutRecords)
                sendAppBackup(dataClient, appBackup)
            }
            Toast.makeText(context, "Data sent to watch", Toast.LENGTH_SHORT).show()
        }
    }

    AnimatedContent(
        modifier = Modifier
            .fillMaxSize()
            .background(DarkGray),
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
                        syncWithWatch()
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
                                val workoutSchedules = workoutScheduleDao.getAllSchedules()

                                val workoutRecords = workoutRecordDao.getAll()

                                val appBackup = AppBackup(
                                    appViewModel.workoutStore.copy(workouts = allowedWorkouts),
                                    validWorkoutHistories,
                                    setHistories,
                                    exerciseInfos,
                                    workoutSchedules,
                                    workoutRecords
                                )

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
                    onExportWorkouts = {
                        val sdf = SimpleDateFormat("dd_MM_yyyy_HH_mm_ss", Locale.getDefault())
                        val currentDate = sdf.format(Date())
                        val filename = "workout_store_$currentDate.json"
                        val jsonString = fromWorkoutStoreToJSON(appViewModel.workoutStore)
                        writeJsonToDownloadsFolder(context, filename, jsonString)
                        Toast.makeText(
                            context,
                            "Workouts saved to downloads folder",
                            Toast.LENGTH_SHORT
                        ).show()
                    },
                    onClearUnfinishedWorkouts = {
                        scope.launch {
                            val unfinishedWorkoutHistories = workoutHistoryDao.getAllUnfinishedWorkoutHistories()

                            try {

                                deleteWorkoutHistoriesFromHealthConnect(unfinishedWorkoutHistories,healthConnectClient)
                            }catch (e: Exception) {
                                Log.e("MainActivity", "Error deleting workout histories from HealthConnect", e)
                                Toast.makeText(context, "Failed to delete workout histories from HealthConnect", Toast.LENGTH_SHORT).show()
                            }

                            for (history in unfinishedWorkoutHistories) {
                                workoutRecordDao.deleteByWorkoutHistoryId(history.id)
                            }
                            workoutHistoryDao.deleteAllUnfinished()
                            appViewModel.triggerUpdate()
                        }
                    },
                    onClearAllHistories = {
                        scope.launch {
                            withContext(Dispatchers.IO) {
                                try {
                                    val allWorkoutHistories = workoutHistoryDao.getAllWorkoutHistories()
                                    deleteWorkoutHistoriesFromHealthConnect(allWorkoutHistories,healthConnectClient)
                                }catch (e: Exception) {
                                    Log.e("MainActivity", "Error deleting workout histories from HealthConnect", e)
                                    Toast.makeText(context, "Failed to delete workout histories from HealthConnect", Toast.LENGTH_SHORT).show()
                                }

                                workoutHistoryDao.deleteAll()
                                setHistoryDao.deleteAll()
                            }
                            Toast.makeText(context, "Histories cleared", Toast.LENGTH_SHORT).show()

                            appViewModel.updateWorkoutStore(workoutStoreRepository.getWorkoutStore())
                            appViewModel.triggerUpdate()
                        }
                    },
                    onSyncToHealthConnectClick = {
                        scope.launch {
                            try{
                                withContext(Dispatchers.IO) {
                                    val currentYear = Calendar.getInstance().get(Calendar.YEAR)
                                    val age = currentYear - appViewModel.workoutStore.birthDateYear
                                    val weight = appViewModel.workoutStore.weightKg

                                    sendWorkoutsToHealthConnect(
                                        healthConnectClient = healthConnectClient,
                                        workouts = appViewModel.workouts,
                                        workoutHistoryDao = workoutHistoryDao,
                                        updateAll = true,
                                        age = age,
                                        weightKg = weight
                                    )
                                }
                                Toast.makeText(context, "Synced with HealthConnect", Toast.LENGTH_SHORT).show()
                            }catch (e: Exception){
                                Log.e("MainActivity", "Error syncing with HealthConnect", e)
                                Toast.makeText(context, "Error syncing with HealthConnect", Toast.LENGTH_SHORT).show()
                            }
                        }
                    },
                    onClearAllExerciseInfo = {
                        scope.launch {
                            withContext(Dispatchers.IO) {
                                exerciseInfoDao.deleteAll()
                            }
                            Toast.makeText(context, "All exercise info cleared", Toast.LENGTH_SHORT).show()
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
                        syncWithWatch()
                        Toast.makeText(context, "Settings saved", Toast.LENGTH_SHORT).show()
                        appViewModel.goBack()
                    },
                    onCancel = {
                        appViewModel.goBack()
                    },
                    workoutStore = appViewModel.workoutStore
                )
            }

            is ScreenData.Workout ->{
                WorkoutScreen(
                    appViewModel,
                    workoutViewModel,
                    hapticsViewModel
                )
            }

            is ScreenData.NewWorkout -> {
                WorkoutForm(
                    onWorkoutUpsert = { newWorkout, schedules ->
                        appViewModel.addNewWorkout(newWorkout)

                        scope.launch {
                            workoutScheduleDao.insertAll(*schedules.toTypedArray())
                        }

                        appViewModel.goBack()
                    },
                    onCancel = { appViewModel.goBack() },
                )
            }

            is ScreenData.EditWorkout -> {
                val screenData = currentScreen as ScreenData.EditWorkout
                val workouts by appViewModel.workoutsFlow.collectAsState()
                val selectedWorkout = workouts.find { it.id == screenData.workoutId }!!

                val existingSchedules by produceState<List<WorkoutSchedule>>(
                    initialValue = emptyList(),
                    key1 = selectedWorkout.globalId
                ) {
                    value = workoutScheduleDao.getSchedulesByWorkoutId(selectedWorkout.globalId)
                }

                WorkoutForm(
                    onWorkoutUpsert = { updatedWorkout, schedules ->
                        appViewModel.updateWorkoutOld(selectedWorkout, updatedWorkout)
                        scope.launch {
                            workoutScheduleDao.deleteAllByWorkoutId(selectedWorkout.globalId)
                            workoutScheduleDao.insertAll(*schedules.toTypedArray())
                        }
                        appViewModel.goBack()
                    },
                    onCancel = {
                        appViewModel.goBack()
                    },
                    workout = selectedWorkout,
                    existingSchedules = existingSchedules
                )
            }

            is ScreenData.WorkoutDetail -> {
                val screenData = currentScreen as ScreenData.WorkoutDetail
                val workouts by appViewModel.workoutsFlow.collectAsState()

                var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!

                var currentWorkout = selectedWorkout


                while(!currentWorkout.isActive){
                    if(currentWorkout.nextVersionId == null){
                        //Toast.makeText(context, "Active workout not found", Toast.LENGTH_SHORT).show()
                        appViewModel.goBack()
                        break
                    }

                    val nextWorkout = workouts.find { it.id == currentWorkout.nextVersionId }

                    if(nextWorkout == null){
                        //Toast.makeText(context, "Active workout not found", Toast.LENGTH_SHORT).show()
                        appViewModel.goBack()
                        break
                    }

                    currentWorkout = nextWorkout
                }

                selectedWorkout = currentWorkout

                WorkoutDetailScreen(
                    appViewModel,
                    workoutViewModel,
                    workoutHistoryDao,
                    workoutRecordDao,
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
                    healthConnectClient,
                    workoutHistoryDao,
                    workoutRecordDao,
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

            is ScreenData.NewSuperset -> {
                val screenData = currentScreen as ScreenData.NewSuperset
                val workouts by appViewModel.workoutsFlow.collectAsState()

                var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!
                var currentWorkout = selectedWorkout

                while(!currentWorkout.isActive){
                    val nextWorkout = workouts.find { it.id == currentWorkout.nextVersionId }!!
                    currentWorkout = nextWorkout
                }

                selectedWorkout = currentWorkout

                SupersetForm(
                    onSupersetUpsert = { newSuperset ->
                        val newWorkoutComponents = selectedWorkout.workoutComponents.filter { item ->
                            newSuperset.exercises.none { it === item }
                        } + newSuperset

                        val adjustedComponents =
                            ensureRestSeparatedByExercises(newWorkoutComponents)
                        val updatedWorkout = selectedWorkout.copy(workoutComponents = adjustedComponents)
                        appViewModel.updateWorkoutOld(selectedWorkout, updatedWorkout)

                        appViewModel.goBack()
                    },
                    onCancel = { appViewModel.goBack() },
                    availableExercises = selectedWorkout.workoutComponents.filterIsInstance<Exercise>()
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

            is ScreenData.EditSuperset -> {
                val screenData = currentScreen as ScreenData.EditSuperset
                val workouts by appViewModel.workoutsFlow.collectAsState()

                var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!

                var currentWorkout = selectedWorkout

                while(!currentWorkout.isActive){
                    val nextWorkout = workouts.find { it.id == currentWorkout.nextVersionId }!!
                    currentWorkout = nextWorkout
                }

                selectedWorkout = currentWorkout

                val selectedSuperset = findWorkoutComponentByIdInWorkout(
                    selectedWorkout,
                    screenData.selectedSupersetId
                ) as Superset

                SupersetForm(
                    onSupersetUpsert = { updatedSuperset ->
                        appViewModel.updateWorkoutComponentOld(
                            selectedWorkout,
                            selectedSuperset,
                            updatedSuperset
                        )
                        appViewModel.goBack()
                    },
                    onCancel = { appViewModel.goBack() },
                    availableExercises = selectedWorkout.workoutComponents.filterIsInstance<Exercise>(),
                    superset = selectedSuperset
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
                    viewModel = appViewModel,
                    exercise = parentExercise
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

                        appViewModel.updateWorkoutComponentOld(
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

                        val adjustedComponents =
                            ensureRestSeparatedByExercises(modifiedWorkoutComponents)

                        val updatedWorkout = selectedWorkout.copy(workoutComponents = adjustedComponents)
                        appViewModel.updateWorkoutOld(selectedWorkout, updatedWorkout)
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
                    viewModel = appViewModel,
                    exercise = parentExercise
                )
            }

            is ScreenData.NewEquipment -> {
                val screenData = currentScreen
                val equipments by appViewModel.equipmentsFlow.collectAsState()

                when (screenData.equipmentType) {
                    EquipmentType.GENERIC -> throw NotImplementedError()
                    EquipmentType.BARBELL -> {
                        BarbellForm(onUpsert = { new ->
                            val newEquipments = equipments + new
                            appViewModel.updateEquipments(newEquipments)
                            appViewModel.goBack()
                        }, onCancel = { appViewModel.goBack() })
                    }
                    EquipmentType.DUMBBELLS -> {
                        DumbbellsForm(onUpsert = { new ->
                            val newEquipments = equipments + new
                            appViewModel.updateEquipments(newEquipments)
                            appViewModel.goBack()
                        }, onCancel = { appViewModel.goBack() })
                    }
                    EquipmentType.DUMBBELL -> DumbbellForm(onUpsert = { new ->
                        val newEquipments = equipments + new
                        appViewModel.updateEquipments(newEquipments)
                        appViewModel.goBack()
                    }, onCancel = { appViewModel.goBack() })
                    EquipmentType.PLATELOADEDCABLE -> PlateLoadedCableForm(onUpsert = { new ->
                        val newEquipments = equipments + new
                        appViewModel.updateEquipments(newEquipments)
                        appViewModel.goBack()
                    }, onCancel = { appViewModel.goBack() })
                    EquipmentType.WEIGHTVEST -> WeightVestForm(onUpsert = { new ->
                        val newEquipments = equipments + new
                        appViewModel.updateEquipments(newEquipments)
                        appViewModel.goBack()
                    }, onCancel = { appViewModel.goBack() })
                    EquipmentType.MACHINE -> MachineForm(onUpsert = { new ->
                        val newEquipments = equipments + new
                        appViewModel.updateEquipments(newEquipments)
                        appViewModel.goBack()
                    }, onCancel = { appViewModel.goBack() })
                    EquipmentType.IRONNECK -> appViewModel.goBack()
                }
            }

            is ScreenData.EditEquipment -> {
                val screenData = currentScreen as ScreenData.EditEquipment
                val equipments by appViewModel.equipmentsFlow.collectAsState()

                when (screenData.equipmentType) {
                    EquipmentType.GENERIC -> throw NotImplementedError()
                    EquipmentType.BARBELL -> {
                        val selectedBarbell = equipments.find { it.id == screenData.equipmentId } as Barbell
                        BarbellForm(onUpsert = { updatedBarbell ->
                            val updatedEquipments = equipments.map { equipment ->
                                if (equipment.id == selectedBarbell.id) updatedBarbell else equipment
                            }
                            appViewModel.updateEquipments(updatedEquipments)
                            appViewModel.goBack()
                        }, onCancel = { appViewModel.goBack() }, barbell = selectedBarbell)
                    }
                    EquipmentType.DUMBBELLS -> {
                        val selectedDumbbells = equipments.find { it.id == screenData.equipmentId } as Dumbbells
                        DumbbellsForm(onUpsert = { updatedDumbbells ->
                            val updatedEquipments = equipments.map { equipment ->
                                if (equipment.id == selectedDumbbells.id) updatedDumbbells else equipment
                            }
                            appViewModel.updateEquipments(updatedEquipments)
                            appViewModel.goBack()
                        }, onCancel = { appViewModel.goBack() }, dumbbells = selectedDumbbells)
                    }

                    EquipmentType.DUMBBELL -> {
                        val selectedDumbbell = equipments.find { it.id == screenData.equipmentId } as Dumbbell
                        DumbbellForm(
                            onUpsert = { updatedDumbbell ->
                                val updatedEquipments = equipments.map { equipment ->
                                    if (equipment.id == selectedDumbbell.id) updatedDumbbell else equipment
                                }
                                appViewModel.updateEquipments(updatedEquipments)
                                appViewModel.goBack()
                            },
                            onCancel = { appViewModel.goBack() },
                            dumbbell = selectedDumbbell
                        )
                    }
                    EquipmentType.PLATELOADEDCABLE -> {
                        val selectedCable = equipments.find { it.id == screenData.equipmentId } as PlateLoadedCable
                        PlateLoadedCableForm(onUpsert = { updatedCable ->
                            val updatedEquipments = equipments.map { equipment ->
                                if (equipment.id == selectedCable.id) updatedCable else equipment
                            }
                            appViewModel.updateEquipments(updatedEquipments)
                            appViewModel.goBack()
                        }, onCancel = { appViewModel.goBack() }, plateLoadedCable = selectedCable)
                    }
                    EquipmentType.WEIGHTVEST -> {
                        val selectedVest = equipments.find { it.id == screenData.equipmentId } as WeightVest
                        WeightVestForm(onUpsert = { updatedVest ->
                            val updatedEquipments = equipments.map { equipment ->
                                if (equipment.id == selectedVest.id) updatedVest else equipment
                            }
                            appViewModel.updateEquipments(updatedEquipments)
                            appViewModel.goBack()
                        }, onCancel = { appViewModel.goBack() }, weightVest = selectedVest)
                    }
                    EquipmentType.MACHINE -> {
                        val selectedMachine = equipments.find { it.id == screenData.equipmentId } as Machine
                        MachineForm(onUpsert = { updatedMachine ->
                            val updatedEquipments = equipments.map { equipment ->
                                if (equipment.id == selectedMachine.id) updatedMachine else equipment
                            }
                            appViewModel.updateEquipments(updatedEquipments)
                            appViewModel.goBack()
                        }, onCancel = { appViewModel.goBack() }, machine = selectedMachine)
                    }
                    EquipmentType.IRONNECK -> TODO()
                }
            }
        }
    }
}

