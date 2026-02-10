package com.gabstra.myworkoutassistant

import android.Manifest
import android.content.ActivityNotFoundException
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.Settings
import android.util.Log
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.EnterTransition
import androidx.compose.animation.ExitTransition
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import androidx.core.content.edit
import androidx.health.connect.client.HealthConnectClient
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import com.gabstra.myworkoutassistant.composables.LoadingScreen
import com.gabstra.myworkoutassistant.composables.StandardDialog
import com.gabstra.myworkoutassistant.composables.WorkoutPlanNameDialog
import com.gabstra.myworkoutassistant.screens.ErrorLogsScreen
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
import com.gabstra.myworkoutassistant.screens.equipments.AccessoryForm
import com.gabstra.myworkoutassistant.screens.equipments.BarbellForm
import com.gabstra.myworkoutassistant.screens.equipments.DumbbellForm
import com.gabstra.myworkoutassistant.screens.equipments.DumbbellsForm
import com.gabstra.myworkoutassistant.screens.equipments.MachineForm
import com.gabstra.myworkoutassistant.screens.equipments.PlateLoadedCableForm
import com.gabstra.myworkoutassistant.screens.equipments.WeightVestForm
import com.gabstra.myworkoutassistant.sync.MobileSyncToWatchWorker
import com.gabstra.myworkoutassistant.shared.AppBackup
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.BackupFileType
import com.gabstra.myworkoutassistant.shared.ExerciseInfoDao
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import com.gabstra.myworkoutassistant.shared.WorkoutRecordDao
import com.gabstra.myworkoutassistant.shared.WorkoutScheduleDao
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.detectBackupFileType
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbell
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbells
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.equipments.Machine
import com.gabstra.myworkoutassistant.shared.equipments.PlateLoadedCable
import com.gabstra.myworkoutassistant.shared.equipments.WeightVest
import com.gabstra.myworkoutassistant.shared.fromAppBackupToJSONPrettyPrint
import com.gabstra.myworkoutassistant.shared.fromJSONToWorkoutStore
import com.gabstra.myworkoutassistant.shared.fromJSONtoAppBackup
import com.gabstra.myworkoutassistant.shared.fromWorkoutStoreToJSON
import com.gabstra.myworkoutassistant.shared.BackupCleanupAction
import com.gabstra.myworkoutassistant.shared.determineBackupCleanupAction
import com.gabstra.myworkoutassistant.shared.migrateWorkoutStoreSetIdsIfNeeded
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.utils.ScheduleConflictChecker
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.ui.theme.MyWorkoutAssistantTheme
import com.google.accompanist.systemuicontroller.rememberSystemUiController
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

class MainActivity : ComponentActivity() {
    private val dataClient by lazy { Wearable.getDataClient(this) }

    private val db by lazy { AppDatabase.getDatabase(this) }

    // Mutex to serialize sync operations and prevent interleaving DataItems
    companion object {
        internal val syncMutex = Mutex()
    }

    private lateinit var appViewModel: AppViewModel

    private lateinit var workoutViewModel: WorkoutViewModel

    private lateinit var hapticsViewModel: HapticsViewModel

    private val workoutStoreRepository by lazy { WorkoutStoreRepository(this.filesDir) }

    private lateinit var myReceiver: BroadcastReceiver

    private val healthConnectClient by lazy { HealthConnectClient.getOrCreate(this) }

    private var backupCleanupAttempted = false

    /** Scope for restore operations; not tied to lifecycle so restore can complete even if activity is recreated (e.g. rotation). */
    internal val restoreScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val readStoragePermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) {
                runBackupCleanup()
            } else {
                Toast.makeText(
                    this,
                    "Storage access denied; backup cleanup skipped",
                    Toast.LENGTH_SHORT
                ).show()
            }
        }

    private val manageAllFilesAccessLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
            if (hasDownloadsAccess()) {
                runBackupCleanup()
            } else {
                Toast.makeText(
                    this,
                    "All files access denied; backup cleanup skipped",
                    Toast.LENGTH_SHORT
                ).show()
            }
        }

    private val showFilePermissionDialog = mutableStateOf(false)

    override fun onStart() {
        super.onStart()
    }

    override fun onResume() {
        super.onResume()
        // Safety check: if permissions are available but cleanup hasn't run, run it now
        if (!backupCleanupAttempted && hasDownloadsAccess()) {
            runBackupCleanup()
        }
    }

    override fun onPause() {
        super.onPause()
        // Flush any pending debounced saves when app is paused
        // Only saves if a save was actually scheduled (flushWorkoutSave is a no-op if no save is pending)
        if (::appViewModel.isInitialized) {
            lifecycleScope.launch {
                appViewModel.flushWorkoutSave(this@MainActivity, workoutStoreRepository, db)
            }
        }
    }

    override fun onStop() {
        super.onStop()
        // Defensive flush on stop as well
        // Only saves if a save was actually scheduled (flushWorkoutSave is a no-op if no save is pending)
        if (::appViewModel.isInitialized) {
            lifecycleScope.launch {
                appViewModel.flushWorkoutSave(this@MainActivity, workoutStoreRepository, db)
            }
        }
    }

    override fun finish() {
        // #region agent log
        val stack = Log.getStackTraceString(Throwable())
        Log.w("WorkoutHistDebug", "MainActivity.finish ActivityId=${System.identityHashCode(this)} isFinishing=$isFinishing --- CAUSE (stack trace):")
        Log.w("WorkoutHistDebug", stack.take(2000))
        // #endregion
        super.finish()
    }

    override fun onDestroy() {
        // #region agent log
        Log.d("WorkoutHistDebug", "MainActivity.onDestroy ActivityId=${System.identityHashCode(this)} isFinishing=$isFinishing")
        // #endregion
        super.onDestroy()
        if (::myReceiver.isInitialized) {
            unregisterReceiver(myReceiver)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // #region agent log
        val intentAction = intent?.action ?: "null"
        val intentComponent = intent?.component?.shortClassName ?: "null"
        Log.d("WorkoutHistDebug", "MainActivity.onCreate ActivityId=${System.identityHashCode(this)} intent.action=$intentAction intent.component=$intentComponent")
        // #endregion

        appViewModel = ViewModelProvider(this, ViewModelProvider.AndroidViewModelFactory.getInstance(application))[AppViewModel::class.java]
        workoutViewModel = ViewModelProvider(this)[WorkoutViewModel::class.java]
        appViewModel.triggerUpdate()
        hapticsViewModel = ViewModelProvider(
            this,
            HapticsViewModelFactory(applicationContext)
        )[HapticsViewModel::class.java]

        myReceiver = MobileDataLayerReceiver(
            appViewModel = appViewModel,
            workoutViewModel = workoutViewModel,
            workoutStoreRepository = workoutStoreRepository,
            activity = this
        )
        val filter = IntentFilter(DataLayerListenerService.INTENT_ID)
        registerReceiver(myReceiver, filter, RECEIVER_NOT_EXPORTED)

        // Consume back until Compose BackHandler is registered (prevents finish() when a back
        // is delivered to this Activity before first composition, e.g. after reopening from launcher).
        onBackPressedDispatcher.addCallback(
            this,
            object : OnBackPressedCallback(true) {
                override fun handleOnBackPressed() {
                    // Consumed; Compose BackHandler will handle back once it is registered.
                }
            }
        )

        // Clean up duplicate backup files once at app startup (after storage access check)
        requestBackupCleanup()

        setContent {
            val context = LocalContext.current
            val showDialog by showFilePermissionDialog
            
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
                    
                    FilePermissionDialog(
                        show = showDialog,
                        onDismiss = { showFilePermissionDialog.value = false },
                        onConfirm = {
                            showFilePermissionDialog.value = false
                            launchAllFilesAccessSettings()
                        },
                        context = context
                    )
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent) // Update the old intent
        MainActivityIntentRouter.route(intent, appViewModel)
    }

    private fun requestBackupCleanup() {
        when (
            determineBackupCleanupAction(
                hasDownloadsAccess = hasDownloadsAccess(),
                sdkInt = Build.VERSION.SDK_INT
            )
        ) {
            BackupCleanupAction.RUN_CLEANUP -> runBackupCleanup()
            BackupCleanupAction.SHOW_ALL_FILES_RATIONALE -> showAllFilesAccessRationale()
            BackupCleanupAction.REQUEST_READ_STORAGE_PERMISSION -> {
                readStoragePermissionLauncher.launch(Manifest.permission.READ_EXTERNAL_STORAGE)
            }
        }
    }

    private fun runBackupCleanup() {
        backupCleanupAttempted = true
        lifecycleScope.launch(Dispatchers.IO) {
            cleanupDuplicateBackupFilesByContent(this@MainActivity)
        }
    }

    internal fun hasDownloadsAccess(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            Environment.isExternalStorageManager()
        } else {
            ContextCompat.checkSelfPermission(
                this,
                Manifest.permission.READ_EXTERNAL_STORAGE
            ) == android.content.pm.PackageManager.PERMISSION_GRANTED
        }
    }

    private fun showAllFilesAccessRationale() {
        showFilePermissionDialog.value = true
    }

    private fun launchAllFilesAccessSettings() {
        val uri = Uri.parse("package:$packageName")
        val intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION).apply {
            data = uri
        }
        try {
            manageAllFilesAccessLauncher.launch(intent)
        } catch (e: ActivityNotFoundException) {
            val fallbackIntent = Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION)
            manageAllFilesAccessLauncher.launch(fallbackIntent)
        }
    }

}

@Composable
fun FilePermissionDialog(
    show: Boolean,
    onDismiss: () -> Unit,
    onConfirm: () -> Unit,
    context: Context
) {
    if (show) {
        StandardDialog(
            onDismissRequest = onDismiss,
            title = "Allow access to Downloads",
            body = {
                Text(
                    "To clean duplicate backup files in Downloads, the app needs all files access " +
                        "so it can list and delete old backup copies."
                )
            },
            confirmText = "Continue",
            onConfirm = onConfirm,
            dismissText = "Not now",
            onDismissButton = {
                Toast.makeText(
                    context,
                    "All files access not granted; backup cleanup skipped",
                    Toast.LENGTH_SHORT
                ).show()
                onDismiss()
            }
        )
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
    val lifecycleOwner = LocalLifecycleOwner.current

    // Load workout store once and initialize DAOs only once, not on every recomposition
    LaunchedEffect(Unit) {
        appViewModel.loadWorkoutStore()
        workoutViewModel.initExerciseHistoryDao(context)
        workoutViewModel.initWorkoutHistoryDao(context)
        workoutViewModel.initWorkoutScheduleDao(context)
        workoutViewModel.initWorkoutRecordDao(context)
        workoutViewModel.initExerciseInfoDao(context)
        workoutViewModel.initExerciseSessionProgressionDao(context)
        workoutViewModel.initWorkoutStoreRepository(workoutStoreRepository)
    }

    val systemUiController = rememberSystemUiController()
    val backgroundColor = MaterialTheme.colorScheme.background

    DisposableEffect(systemUiController, backgroundColor) {
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
    val updateMobileSignal by updateMobileFlow.collectAsState()

    val initialDataLoaded by appViewModel.isInitialDataLoaded.collectAsState(initial = false)
    var downloadsAccessGranted by remember {
        mutableStateOf((context as? MainActivity)?.hasDownloadsAccess() ?: false)
    }

    DisposableEffect(lifecycleOwner, context) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                downloadsAccessGranted =
                    (context as? MainActivity)?.hasDownloadsAccess() ?: false
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
        }
    }

    LaunchedEffect(updateMobileSignal) {
        if (updateMobileSignal != null) {
            workoutViewModel.updateWorkoutStore(appViewModel.workoutStore)
        }
    }

    // Sync WorkoutViewModel when initial load has completed, then run incomplete workouts check
    LaunchedEffect(initialDataLoaded) {
        if (!initialDataLoaded) return@LaunchedEffect
        workoutViewModel.updateWorkoutStore(appViewModel.workoutStore)
        val prefs = context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
        val isWorkoutInProgress = prefs.getBoolean("isWorkoutInProgress", false)
        if (!isWorkoutInProgress) {
            try {
                val incompleteWorkouts = workoutViewModel.getIncompleteWorkouts()
                if (incompleteWorkouts.isNotEmpty()) {
                    appViewModel.showResumeWorkoutDialog(incompleteWorkouts)
                }
            } catch (exception: Exception) {
            }
        }
    }

    val scope = rememberCoroutineScope()
    val firstBackHandlerRegistrationTime = remember { System.currentTimeMillis() }

    BackHandler(enabled = true) {
        // #region agent log
        Log.d("WorkoutHistDebug", "BackHandler invoked ActivityId=${(context as? android.app.Activity)?.let { System.identityHashCode(it) } ?: -1}")
        // #endregion
        scope.launch {
            appViewModel.flushWorkoutSave(context)
            val canGoBack = appViewModel.goBack()
            // #region agent log
            Log.d("WorkoutHistDebug", "BackHandler canGoBack=$canGoBack")
            // #endregion
            if (!canGoBack) {
                val ageMs = System.currentTimeMillis() - firstBackHandlerRegistrationTime
                if (ageMs < 1500) {
                    // Activity just opened; likely a stale back delivered before user interaction.
                    // Consume without finishing to avoid closing the app immediately after reopen.
                    Log.d("WorkoutHistDebug", "BackHandler: not finishing, activity just opened (ageMs=$ageMs)")
                    return@launch
                }
                Log.d("WorkoutHistDebug", "BackHandler calling finish()")
                (context as? ComponentActivity)?.finish()
            }
        }
    }

    var isSyncing by remember { mutableStateOf(false) }
    
    // Timeout mechanism to clear stuck sync state after 10 seconds
    LaunchedEffect(isSyncing) {
        if (isSyncing) {
            delay(10000L) // 10 seconds timeout
            if (isSyncing) {
                // Only reset if still syncing (sync didn't complete)
                isSyncing = false
            }
        }
    }
    
    var showPlanNameDialog by remember { mutableStateOf(false) }
    var pendingImportedWorkoutStore by remember {
        mutableStateOf<com.gabstra.myworkoutassistant.shared.WorkoutStore?>(
            null
        )
    }

    val workoutStorePickerLauncher =
        rememberLauncherForActivityResult(contract = ActivityResultContracts.OpenDocument()) { uri: Uri? ->
            uri?.let {
                try {
                    context.contentResolver.openInputStream(it)?.use { inputStream ->
                        val reader = inputStream.bufferedReader()
                        val content = reader.readText()
                        val importedWorkoutStore = fromJSONToWorkoutStore(content)

                        // Check if there are any workouts in the imported store
                        if (importedWorkoutStore.workouts.isEmpty()) {
                            Toast.makeText(
                                context,
                                "Cannot import workout plan: No workouts found in file",
                                Toast.LENGTH_SHORT
                            ).show()
                            return@let
                        }

                        pendingImportedWorkoutStore = importedWorkoutStore
                        showPlanNameDialog = true
                    }
                } catch (e: Exception) {
                    Toast.makeText(
                        context,
                        "Failed to read file: ${e.message}",
                        Toast.LENGTH_SHORT
                    ).show()
                }
            }
        }

    WorkoutPlanNameDialog(
        show = showPlanNameDialog,
        onDismiss = {
            showPlanNameDialog = false
            pendingImportedWorkoutStore = null
        },
        onConfirm = { planName ->
            showPlanNameDialog = false
            val importedWorkoutStore = pendingImportedWorkoutStore ?: return@WorkoutPlanNameDialog
            pendingImportedWorkoutStore = null

            scope.launch {
                try {
                    val existingWorkoutsCount = appViewModel.workouts.size
                    val existingEquipmentCount = appViewModel.equipments.size
                    val existingAccessoriesCount = appViewModel.accessoryEquipments.size

                    // Create new workout plan
                    val newPlanId = java.util.UUID.randomUUID()
                    val nextOrder =
                        (appViewModel.getAllWorkoutPlans().maxOfOrNull { it.order } ?: -1) + 1
                    val newPlan = WorkoutPlan(
                        id = newPlanId,
                        name = planName,
                        workoutIds = importedWorkoutStore.workouts.map { it.id },
                        order = nextOrder
                    )

                    // Set workoutPlanId on all imported workouts
                    val workoutsWithPlanId = importedWorkoutStore.workouts.map { workout ->
                        workout.copy(workoutPlanId = newPlanId)
                    }
                    val importedWorkoutStoreWithPlan = importedWorkoutStore.copy(
                        workouts = workoutsWithPlanId,
                        workoutPlans = listOf(newPlan)
                    )

                    // Merge with existing data
                    // The merge function correctly handles adding the plan from importedWorkoutStoreWithPlan
                    appViewModel.importWorkoutStore(importedWorkoutStoreWithPlan)

                    // Save to repository
                    workoutStoreRepository.saveWorkoutStore(appViewModel.workoutStore)
                    val migratedWorkoutStore = migrateWorkoutStoreSetIdsIfNeeded(
                        appViewModel.workoutStore,
                        db,
                        workoutStoreRepository
                    )
                    appViewModel.updateWorkoutStore(migratedWorkoutStore)

                    val newWorkoutsCount = appViewModel.workouts.size
                    val newEquipmentCount = appViewModel.equipments.size
                    val newAccessoriesCount = appViewModel.accessoryEquipments.size
                    val addedWorkouts = newWorkoutsCount - existingWorkoutsCount
                    val addedEquipment = newEquipmentCount - existingEquipmentCount
                    val addedAccessories = newAccessoriesCount - existingAccessoriesCount

                    val message = buildString {
                        append("Imported workout plan: $planName")
                        append("\n$addedWorkouts workout(s)")
                        if (addedEquipment > 0) append(", $addedEquipment equipment item(s)")
                        if (addedAccessories > 0) append(", $addedAccessories accessory item(s)")
                    }

                    Toast.makeText(
                        context,
                        message,
                        Toast.LENGTH_SHORT
                    ).show()
                } catch (e: Exception) {
                    Toast.makeText(
                        context,
                        "Failed to import workout plan: ${e.message}",
                        Toast.LENGTH_SHORT
                    ).show()
                }
            }
        }
    )

    /**
     * Helper function to restore from an AppBackup.
     * This function handles all the database operations and view model updates.
     */
    suspend fun restoreFromAppBackup(
        appBackup: AppBackup,
        context: Context,
        appViewModel: AppViewModel,
        workoutViewModel: WorkoutViewModel,
        workoutStoreRepository: WorkoutStoreRepository,
        db: AppDatabase,
        workoutHistoryDao: WorkoutHistoryDao,
        setHistoryDao: SetHistoryDao,
        exerciseInfoDao: ExerciseInfoDao,
        workoutScheduleDao: WorkoutScheduleDao,
        workoutRecordDao: WorkoutRecordDao,
        healthConnectClient: HealthConnectClient,
        successToastMessage: String = "Data restored from backup"
    ) {
        withContext(Dispatchers.IO + NonCancellable) {
            try {

                val allowedWorkouts = appBackup.WorkoutStore.workouts.filter { workout ->
                workout.isActive || (!workout.isActive && (appBackup.WorkoutHistories
                    ?: emptyList()).any { it.workoutId == workout.id })
            }

            val newWorkoutStore = appBackup.WorkoutStore.copy(
                workouts = allowedWorkouts
            )

            val deleteAndInsertJob = coroutineScope {
                async {
                    try {
                        val BATCH_SIZE = 80
                        var allWorkoutHistories = workoutHistoryDao.getAllWorkoutHistories()

                        try {
                            deleteWorkoutHistoriesFromHealthConnect(
                                allWorkoutHistories,
                                healthConnectClient
                            )
                        } catch (e: Exception) {
                            withContext(Dispatchers.Main) {
                                Toast.makeText(
                                    context,
                                    "Failed to delete workout histories from HealthConnect",
                                    Toast.LENGTH_SHORT
                                ).show()
                            }
                        }

                        workoutHistoryDao.deleteAll()
                        setHistoryDao.deleteAll()
                        exerciseInfoDao.deleteAll()
                        workoutScheduleDao.deleteAll()
                        workoutRecordDao.deleteAll()
                        db.exerciseSessionProgressionDao().deleteAll()
                        db.errorLogDao().deleteAll()

                        val validWorkoutHistories =
                            (appBackup.WorkoutHistories ?: emptyList()).filter { workoutHistory ->
                                allowedWorkouts.any { workout -> workout.id == workoutHistory.workoutId }
                            }

                        validWorkoutHistories.chunked(BATCH_SIZE).forEach { chunk ->
                            workoutHistoryDao.insertAll(*chunk.toTypedArray())
                        }

                        val validSetHistories =
                            (appBackup.SetHistories ?: emptyList()).filter { setHistory ->
                                validWorkoutHistories.any { workoutHistory -> workoutHistory.id == setHistory.workoutHistoryId }
                            }

                        validSetHistories.chunked(BATCH_SIZE).forEach { chunk ->
                            setHistoryDao.insertAll(*chunk.toTypedArray())
                        }

                        val allExercises = allowedWorkouts.flatMap { workout ->
                            workout.workoutComponents.filterIsInstance<Exercise>() + workout.workoutComponents.filterIsInstance<Superset>()
                                .flatMap { it.exercises }
                        }

                        val validExerciseInfos = (appBackup.ExerciseInfos
                            ?: emptyList()).filter { allExercises.any { exercise -> exercise.id == it.id } }

                        validExerciseInfos.chunked(BATCH_SIZE).forEach { chunk ->
                            exerciseInfoDao.insertAll(*chunk.toTypedArray())
                        }

                        val validWorkoutSchedules = (appBackup.WorkoutSchedules
                            ?: emptyList()).filter { allowedWorkouts.any { workout -> workout.globalId == it.workoutId } }

                        validWorkoutSchedules.chunked(BATCH_SIZE).forEach { chunk ->
                            workoutScheduleDao.insertAll(*chunk.toTypedArray())
                        }

                        if (appBackup.WorkoutRecords != null) {
                            val validWorkoutRecords =
                                appBackup.WorkoutRecords.filter { allowedWorkouts.any { workout -> workout.id == it.workoutId } }

                            validWorkoutRecords.chunked(BATCH_SIZE).forEach { chunk ->
                                workoutRecordDao.insertAll(*chunk.toTypedArray())
                            }
                        }

                        val validExerciseSessionProgressions =
                            (appBackup.ExerciseSessionProgressions
                                ?: emptyList()).filter { progression ->
                                validWorkoutHistories.any { it.id == progression.workoutHistoryId }
                            }

                        validExerciseSessionProgressions.chunked(BATCH_SIZE).forEach { chunk ->
                            db.exerciseSessionProgressionDao().insertAll(*chunk.toTypedArray())
                        }

                        // Restore error logs if present in backup
                        val errorLogs = appBackup.ErrorLogs
                        if (errorLogs != null && errorLogs.isNotEmpty()) {
                            errorLogs.chunked(BATCH_SIZE).forEach { chunk ->
                                db.errorLogDao().insertAll(*chunk.toTypedArray())
                            }
                        }
                        true
                    } catch (e: Exception) {
                        Log.e("MainActivity", "Error during restore database operations: ${e.javaClass.simpleName}. " +
                                "Message: ${e.message}, " +
                                "Cause: ${e.cause?.javaClass?.simpleName ?: "none"}, " +
                                "Stack trace:\n${Log.getStackTraceString(e)}", e)
                        false
                    }
                }
            }

            // Wait for the delete and insert operations to complete
            val restoreSuccess = try {
                deleteAndInsertJob.await()
            } catch (e: CancellationException) {
                // Job was cancelled (e.g., activity destroyed) - this is expected
                Log.d("MainActivity", "Restore operation cancelled (likely activity destroyed): ${e.message}")
                return@withContext
            } catch (e: Exception) {
                Log.e("MainActivity", "Error awaiting restore job: ${e.javaClass.simpleName}. " +
                        "Message: ${e.message}, " +
                        "Cause: ${e.cause?.javaClass?.simpleName ?: "none"}, " +
                        "Stack trace:\n${Log.getStackTraceString(e)}", e)
                false
            }

            if (restoreSuccess) {
                // Backfill ExerciseSessionProgression entries for workouts that don't have them but should
                /*backfillExerciseSessionProgressions(
                    workoutStore = newWorkoutStore,
                    workoutHistoryDao = workoutHistoryDao,
                    setHistoryDao = setHistoryDao,
                    exerciseInfoDao = exerciseInfoDao,
                    exerciseSessionProgressionDao = db.exerciseSessionProgressionDao(),
                    db = db
                )*/

                // Migrate the workout store before updating view models to ensure
                // "Unassigned" plan is created for workouts without a plan
                try {
                    val planMigratedWorkoutStore =
                        workoutStoreRepository.migrateWorkoutStore(newWorkoutStore)
                    val migratedWorkoutStore = migrateWorkoutStoreSetIdsIfNeeded(
                        planMigratedWorkoutStore,
                        db,
                        workoutStoreRepository
                    )

                    workoutStoreRepository.saveWorkoutStore(migratedWorkoutStore)

                    withContext(Dispatchers.Main) {
                        appViewModel.updateWorkoutStore(migratedWorkoutStore)
                        workoutViewModel.updateWorkoutStore(migratedWorkoutStore)
                        appViewModel.triggerUpdate()

                        // Show the success toast after all operations are complete
                        Toast.makeText(context, successToastMessage, Toast.LENGTH_SHORT).show()
                    }
                } catch (e: Exception) {
                    Log.e("MainActivity", "Error during restore migration: ${e.javaClass.simpleName}. " +
                            "Message: ${e.message}, " +
                            "Cause: ${e.cause?.javaClass?.simpleName ?: "none"}, " +
                            "Stack trace:\n${Log.getStackTraceString(e)}", e)
                    withContext(Dispatchers.Main) {
                        Toast.makeText(
                            context,
                            "Failed to restore workout history from backup: ${e.message ?: "Migration error"}",
                            Toast.LENGTH_LONG
                        ).show()
                    }
                }
            } else {
                withContext(Dispatchers.Main) {
                    Toast.makeText(
                        context,
                        "Failed to restore workout history from backup",
                        Toast.LENGTH_SHORT
                    ).show()
                }
            }
            } catch (e: CancellationException) {
                // Job was cancelled (e.g., activity destroyed) - this is expected
                Log.d("MainActivity", "Restore operation cancelled (likely activity destroyed): ${e.message}")
            } catch (e: Exception) {
                Log.e("MainActivity", "Error during restore: ${e.javaClass.simpleName}. " +
                        "Message: ${e.message}, " +
                        "Cause: ${e.cause?.javaClass?.simpleName ?: "none"}, " +
                        "Stack trace:\n${Log.getStackTraceString(e)}", e)
                withContext(Dispatchers.Main) {
                    Toast.makeText(
                        context,
                        "Failed to restore backup: ${e.message ?: "Invalid backup file format"}",
                        Toast.LENGTH_LONG
                    ).show()
                }
            }
        }
    }

    LaunchedEffect(initialDataLoaded, downloadsAccessGranted) {
        if (!initialDataLoaded || !downloadsAccessGranted) return@LaunchedEffect

        val prefs = context.getSharedPreferences("startup_restore", Context.MODE_PRIVATE)
        val alreadyChecked = prefs.getBoolean("auto_restore_checked", false)
        if (alreadyChecked) return@LaunchedEffect

        val hasCurrentData =
            appViewModel.workoutStore.workouts.isNotEmpty() ||
                appViewModel.workoutStore.workoutPlans.isNotEmpty() ||
                appViewModel.workoutStore.equipments.isNotEmpty() ||
                appViewModel.workoutStore.accessoryEquipments.isNotEmpty()

        prefs.edit { putBoolean("auto_restore_checked", true) }
        if (hasCurrentData) return@LaunchedEffect

        val appBackup = loadLatestBackupFromDownloads(context) ?: return@LaunchedEffect
        restoreFromAppBackup(
            appBackup = appBackup,
            context = context,
            appViewModel = appViewModel,
            workoutViewModel = workoutViewModel,
            workoutStoreRepository = workoutStoreRepository,
            db = db,
            workoutHistoryDao = workoutHistoryDao,
            setHistoryDao = setHistoryDao,
            exerciseInfoDao = exerciseInfoDao,
            workoutScheduleDao = workoutScheduleDao,
            workoutRecordDao = workoutRecordDao,
            healthConnectClient = healthConnectClient,
            successToastMessage = "Data restored from backup because local data was empty"
        )
    }

    val jsonPickerLauncher =
        rememberLauncherForActivityResult(contract = ActivityResultContracts.OpenDocument()) { uri: Uri? ->
            uri?.let {
                try {
                    context.contentResolver.openInputStream(it)?.use { inputStream ->
                        val reader = inputStream.bufferedReader()
                        val content = reader.readText()

                        // Validate file type before attempting to parse
                        val fileType = detectBackupFileType(content)
                        when (fileType) {
                            BackupFileType.WORKOUT_STORE -> {
                                Toast.makeText(
                                    context,
                                    "This is a workout plan file. Please use 'Import Workout Plan' instead.",
                                    Toast.LENGTH_LONG
                                ).show()
                                return@let
                            }

                            BackupFileType.UNKNOWN -> {
                                Toast.makeText(
                                    context,
                                    "Invalid backup file format. Please select a valid backup file.",
                                    Toast.LENGTH_LONG
                                ).show()
                                return@let
                            }

                            BackupFileType.APP_BACKUP -> {
                                // File type is valid, proceed with restore
                            }
                        }

                        val appBackup = try {
                            fromJSONtoAppBackup(content)
                        } catch (e: Exception) {
                            throw e
                        }

                        // Use restoreScope so restore completes even if activity is destroyed/recreated (e.g. rotation)
                        val scope = (context as? MainActivity)?.restoreScope ?: lifecycleOwner.lifecycleScope
                        scope.launch {
                            restoreFromAppBackup(
                                appBackup = appBackup,
                                context = context,
                                appViewModel = appViewModel,
                                workoutViewModel = workoutViewModel,
                                workoutStoreRepository = workoutStoreRepository,
                                db = db,
                                workoutHistoryDao = workoutHistoryDao,
                                setHistoryDao = setHistoryDao,
                                exerciseInfoDao = exerciseInfoDao,
                                workoutScheduleDao = workoutScheduleDao,
                                workoutRecordDao = workoutRecordDao,
                                healthConnectClient = healthConnectClient
                            )
                        }
                    }
                } catch (e: CancellationException) {
                    // Job was cancelled (e.g., activity destroyed) - this is expected
                } catch (e: Exception) {
                    e.printStackTrace()
                    Toast.makeText(
                        context,
                        "Failed to restore backup: ${e.message ?: "Invalid backup file format"}",
                        Toast.LENGTH_LONG
                    ).show()
                }
            }
        }

    val backupSaveLauncher =
        rememberLauncherForActivityResult(contract = ActivityResultContracts.CreateDocument("application/json")) { uri: Uri? ->
            uri?.let {
                scope.launch {
                    try {
                        withContext(Dispatchers.IO) {
                            val appBackup = createAppBackup(appViewModel.workoutStore, db)
                            if (appBackup == null) {
                                withContext(Dispatchers.Main) {
                                    Toast.makeText(
                                        context,
                                        "No data to backup",
                                        Toast.LENGTH_SHORT
                                    ).show()
                                }
                                return@withContext
                            }

                            val jsonString = fromAppBackupToJSONPrettyPrint(appBackup)
                            context.contentResolver.openOutputStream(it)?.use { outputStream ->
                                outputStream.write(jsonString.toByteArray())
                            }
                        }
                        Toast.makeText(
                            context,
                            "Backup saved successfully",
                            Toast.LENGTH_SHORT
                        ).show()
                    } catch (e: Exception) {
                        e.printStackTrace()
                        Toast.makeText(
                            context,
                            "Failed to save backup: ${e.message ?: "Unknown error"}",
                            Toast.LENGTH_LONG
                        ).show()
                    }
                }
            }
        }


    val syncWithWatch = {
        scope.launch {
            MobileSyncToWatchWorker.enqueue(context)
            isSyncing = true
        }
    }

    // Collect workouts once at the parent level to avoid recomposition cascades inside AnimatedContent
    val workoutsForNavigation by appViewModel.workoutsFlow.collectAsState()
    val saveableStateHolder = rememberSaveableStateHolder()
    val isInitialDataLoaded by appViewModel.isInitialDataLoaded.collectAsState()

    if (!isInitialDataLoaded) {
        LoadingScreen()
    } else {
        AnimatedContent(
            modifier = Modifier
                .fillMaxSize()
                .background(MaterialTheme.colorScheme.background),
            targetState = appViewModel.currentScreenData,
            transitionSpec = {
                // Use instant transition to eliminate black screen during fade
                EnterTransition.None togetherWith ExitTransition.None
            }, label = ""
        ) { currentScreen ->
            saveableStateHolder.SaveableStateProvider(currentScreen.toSaveableKey()) {
                when (currentScreen) {
                    is ScreenData.Workouts -> {
                        WorkoutsScreen(
                            appViewModel,
                            workoutHistoryDao,
                            setHistoryDao,
                            workoutScheduleDao,
                            healthConnectClient,
                            isSyncing = isSyncing,
                            onSyncClick = {
                                syncWithWatch()
                            },
                            onOpenSettingsClick = {
                                appViewModel.setScreenData(ScreenData.Settings())
                            },
                            onBackupClick = {
                                val sdf = SimpleDateFormat("yyyy-MM-dd_HH-mm-ss", Locale.getDefault())
                                val currentDate = sdf.format(Date())
                                val filename = "workout_backup_$currentDate.json"
                                backupSaveLauncher.launch(filename)
                            },
                            onRestoreClick = {
                                jsonPickerLauncher.launch(arrayOf("application/json"))
                            },
                            onImportWorkoutsClick = {
                                workoutStorePickerLauncher.launch(arrayOf("application/json"))
                            },
                            onExportWorkouts = {
                                val sdf =
                                    SimpleDateFormat("dd_MM_yyyy_HH_mm_ss", Locale.getDefault())
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
                            onExportWorkoutPlan = {
                                scope.launch {
                                    try {
                                        withContext(Dispatchers.IO) {
                                            exportWorkoutPlanToMarkdown(
                                                context,
                                                appViewModel.workoutStore
                                            )
                                        }
                                    } catch (e: Exception) {
                                        Toast.makeText(
                                            context,
                                            "Export failed: ${e.message}",
                                            Toast.LENGTH_SHORT
                                        ).show()
                                    }
                                }
                            },
                            onExportEquipment = {
                                scope.launch {
                                    try {
                                        val filename = withContext(Dispatchers.IO) {
                                            exportEquipmentToDownloads(
                                                context,
                                                appViewModel.workoutStore
                                            )
                                        }
                                        Toast.makeText(
                                            context,
                                            "Equipment exported to: $filename",
                                            Toast.LENGTH_SHORT
                                        ).show()
                                    } catch (e: Exception) {
                                        Toast.makeText(
                                            context,
                                            "Export failed: ${e.message}",
                                            Toast.LENGTH_SHORT
                                        ).show()
                                    }
                                }
                            },
                            onClearUnfinishedWorkouts = {
                                scope.launch {
                                    val unfinishedWorkoutHistories =
                                        workoutHistoryDao.getAllUnfinishedWorkoutHistories()

                                    try {

                                        deleteWorkoutHistoriesFromHealthConnect(
                                            unfinishedWorkoutHistories,
                                            healthConnectClient
                                        )
                                    } catch (e: Exception) {
                                        Toast.makeText(
                                            context,
                                            "Failed to delete workout histories from HealthConnect",
                                            Toast.LENGTH_SHORT
                                        ).show()
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
                                            val allWorkoutHistories =
                                                workoutHistoryDao.getAllWorkoutHistories()
                                            deleteWorkoutHistoriesFromHealthConnect(
                                                allWorkoutHistories,
                                                healthConnectClient
                                            )
                                        } catch (e: Exception) {
                                            Toast.makeText(
                                                context,
                                                "Failed to delete workout histories from HealthConnect",
                                                Toast.LENGTH_SHORT
                                            ).show()
                                        }

                                        workoutHistoryDao.deleteAll()
                                        setHistoryDao.deleteAll()
                                    }
                                    Toast.makeText(context, "Histories cleared", Toast.LENGTH_SHORT)
                                        .show()

                                    appViewModel.updateWorkoutStore(workoutStoreRepository.getWorkoutStore())
                                    appViewModel.triggerUpdate()
                                }
                            },
                            onSyncToHealthConnectClick = {
                                scope.launch {
                                    try {
                                        withContext(Dispatchers.IO) {
                                            val currentYear =
                                                Calendar.getInstance().get(Calendar.YEAR)
                                            val age =
                                                currentYear - appViewModel.workoutStore.birthDateYear
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
                                        Toast.makeText(
                                            context,
                                            "Synced with HealthConnect",
                                            Toast.LENGTH_SHORT
                                        ).show()
                                    } catch (e: Exception) {
                                        Toast.makeText(
                                            context,
                                            "Error syncing with HealthConnect",
                                            Toast.LENGTH_SHORT
                                        ).show()
                                    }
                                }
                            },
                            onClearAllExerciseInfo = {
                                scope.launch {
                                    withContext(Dispatchers.IO) {
                                        exerciseInfoDao.deleteAll()
                                    }
                                    Toast.makeText(
                                        context,
                                        "All exercise info cleared",
                                        Toast.LENGTH_SHORT
                                    ).show()
                                }
                            },
                            onViewErrorLogs = {
                                appViewModel.setScreenData(ScreenData.ErrorLogs())
                            },
                            selectedTabIndex = appViewModel.selectedHomeTab
                        )
                    }

                    is ScreenData.Settings -> {
                        var isSaving by remember { mutableStateOf(false) }
                        SettingsScreen(
                            onSave = { newWorkoutStore ->
                                if (isSaving) return@SettingsScreen
                                isSaving = true
                                scope.launch {
                                    try {
                                        appViewModel.updateWorkoutStore(newWorkoutStore)
                                        appViewModel.scheduleWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.flushWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        syncWithWatch()
                                        Toast.makeText(context, "Settings saved", Toast.LENGTH_SHORT)
                                            .show()
                                        appViewModel.goBack()
                                    } finally {
                                        isSaving = false
                                    }
                                }
                            },
                            onCancel = {
                                appViewModel.goBack()
                            },
                            workoutStore = appViewModel.workoutStore,
                            healthConnectClient = healthConnectClient,
                            isSaving = isSaving
                        )
                    }

                    is ScreenData.ErrorLogs -> {
                        ErrorLogsScreen(
                            errorLogDao = db.errorLogDao(),
                            dataClient = dataClient,
                            onBack = {
                                scope.launch {
                                    appViewModel.flushWorkoutSave(
                                        context,
                                        workoutStoreRepository,
                                        db
                                    )
                                    appViewModel.goBack()
                                }
                            }
                        )
                    }

                    is ScreenData.Workout -> {
                        WorkoutScreen(
                            appViewModel,
                            workoutViewModel,
                            hapticsViewModel
                        )
                    }

                    is ScreenData.NewWorkout -> {
                        val screenData = currentScreen as ScreenData.NewWorkout
                        var isSaving by remember { mutableStateOf(false) }
                        WorkoutForm(
                            onWorkoutUpsert = { newWorkout, schedules ->
                                if (isSaving) return@WorkoutForm
                                isSaving = true
                                scope.launch {
                                    try {
                                        // Check for conflicts before saving
                                        val allExistingSchedules = withContext(Dispatchers.IO) {
                                            workoutScheduleDao.getAllSchedules()
                                        }

                                        val conflicts =
                                            ScheduleConflictChecker.checkScheduleConflicts(
                                                newSchedules = schedules,
                                                existingSchedules = allExistingSchedules
                                            )

                                        if (conflicts.isNotEmpty()) {
                                            val errorMessage =
                                                ScheduleConflictChecker.formatConflictMessage(
                                                    conflicts
                                                )
                                            withContext(Dispatchers.Main) {
                                                Toast.makeText(
                                                    context,
                                                    errorMessage,
                                                    Toast.LENGTH_LONG
                                                ).show()
                                            }
                                            return@launch
                                        }

                                        appViewModel.addNewWorkout(newWorkout)

                                        // Update plan's workoutIds if workoutPlanId is set
                                        val workoutPlanId = newWorkout.workoutPlanId
                                        if (workoutPlanId != null) {
                                            val plan =
                                                appViewModel.getWorkoutPlanById(workoutPlanId)
                                            if (plan != null && !plan.workoutIds.contains(newWorkout.id)) {
                                                val updatedPlan =
                                                    plan.copy(workoutIds = plan.workoutIds + newWorkout.id)
                                                appViewModel.updateWorkoutPlan(updatedPlan)
                                            }
                                        }

                                        withContext(Dispatchers.IO) {
                                            workoutScheduleDao.insertAll(*schedules.toTypedArray())
                                        }
                                        appViewModel.scheduleWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.flushWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.goBack()
                                    } finally {
                                        isSaving = false
                                    }
                                }
                            },
                            onCancel = {
                                scope.launch {
                                    appViewModel.flushWorkoutSave(
                                        context,
                                        workoutStoreRepository,
                                        db
                                    )
                                    appViewModel.goBack()
                                }
                            },
                            isSaving = isSaving,
                            workoutPlanId = screenData.workoutPlanId,
                        )
                    }

                    is ScreenData.EditWorkout -> {
                        val screenData = currentScreen as ScreenData.EditWorkout
                        val workouts by appViewModel.workoutsFlow.collectAsState()
                        val selectedWorkout = workouts.find { it.id == screenData.workoutId }!!
                        var isSaving by remember { mutableStateOf(false) }

                        val existingSchedules by produceState(
                            initialValue = emptyList(),
                            key1 = selectedWorkout.globalId
                        ) {
                            value =
                                workoutScheduleDao.getSchedulesByWorkoutId(selectedWorkout.globalId)
                        }

                        WorkoutForm(
                            onWorkoutUpsert = { updatedWorkout, schedules ->
                                if (isSaving) return@WorkoutForm
                                isSaving = true
                                scope.launch {
                                    try {
                                        // Check for conflicts before saving
                                        // Exclude schedules for this workout since we're replacing them
                                        val allExistingSchedules = withContext(Dispatchers.IO) {
                                            workoutScheduleDao.getAllSchedules()
                                                .filter { it.workoutId != selectedWorkout.globalId }
                                        }

                                        val conflicts =
                                            ScheduleConflictChecker.checkScheduleConflicts(
                                                newSchedules = schedules,
                                                existingSchedules = allExistingSchedules
                                            )

                                        if (conflicts.isNotEmpty()) {
                                            val errorMessage =
                                                ScheduleConflictChecker.formatConflictMessage(
                                                    conflicts
                                                )
                                            withContext(Dispatchers.Main) {
                                                Toast.makeText(
                                                    context,
                                                    errorMessage,
                                                    Toast.LENGTH_LONG
                                                ).show()
                                            }
                                            return@launch
                                        }

                                        val hasHistory = withContext(Dispatchers.IO) {
                                            workoutHistoryDao.workoutHistoryExistsByWorkoutId(
                                                selectedWorkout.id
                                            )
                                        }
                                        appViewModel.updateWorkoutVersioned(
                                            selectedWorkout,
                                            updatedWorkout,
                                            hasHistory
                                        )
                                        withContext(Dispatchers.IO) {
                                            workoutScheduleDao.deleteAllByWorkoutId(selectedWorkout.globalId)
                                            workoutScheduleDao.insertAll(*schedules.toTypedArray())
                                        }
                                        appViewModel.scheduleWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.flushWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.goBack()
                                    } finally {
                                        isSaving = false
                                    }
                                }
                            },
                            onCancel = {
                                appViewModel.goBack()
                            },
                            workout = selectedWorkout,
                            isSaving = isSaving,
                            existingSchedules = existingSchedules
                        )
                    }

                    is ScreenData.WorkoutDetail -> {
                        val screenData = currentScreen as ScreenData.WorkoutDetail
                        // Use pre-collected workouts from parent scope to avoid recomposition
                        val workouts = workoutsForNavigation

                        val selectedWorkout = remember(screenData.workoutId, workouts) {
                            var currentWorkout = workouts.find { it.id == screenData.workoutId }!!

                            while (!currentWorkout.isActive) {
                                if (currentWorkout.nextVersionId == null) {
                                    // Active workout not found - will navigate back via LaunchedEffect
                                    break
                                }

                                val nextWorkout =
                                    workouts.find { it.id == currentWorkout.nextVersionId }
                                if (nextWorkout == null) {
                                    // Active workout not found - will navigate back via LaunchedEffect
                                    break
                                }

                                currentWorkout = nextWorkout
                            }

                            currentWorkout
                        }

                        LaunchedEffect(selectedWorkout.isActive, selectedWorkout.nextVersionId) {
                            if (!selectedWorkout.isActive && selectedWorkout.nextVersionId == null) {
                                appViewModel.goBack()
                            }
                        }

                        // Use key() to stabilize the composable and prevent recreation on parent recomposition
                        key(screenData.workoutId) {
                            WorkoutDetailScreen(
                                appViewModel,
                                workoutViewModel,
                                workoutHistoryDao,
                                workoutRecordDao,
                                setHistoryDao,
                                exerciseInfoDao,
                                workoutScheduleDao,
                                selectedWorkout,
                            ) {
                                appViewModel.goBack()
                            }
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

                        while (!currentWorkout.isActive) {
                            val nextWorkout =
                                workouts.find { it.id == currentWorkout.nextVersionId }!!
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
                            workoutHistoryDao,
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

                        while (!currentWorkout.isActive) {
                            val nextWorkout =
                                workouts.find { it.id == currentWorkout.nextVersionId }!!
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

                        while (!currentWorkout.isActive) {
                            val nextWorkout =
                                workouts.find { it.id == currentWorkout.nextVersionId }!!
                            currentWorkout = nextWorkout
                        }

                        selectedWorkout = currentWorkout

                        var isSaving by remember { mutableStateOf(false) }
                        ExerciseForm(
                            appViewModel,
                            onExerciseUpsert = { newExercise ->
                                if (isSaving) return@ExerciseForm
                                isSaving = true
                                scope.launch {
                                    try {
                                        val hasHistory = withContext(Dispatchers.IO) {
                                            workoutHistoryDao.workoutHistoryExistsByWorkoutId(
                                                selectedWorkout.id
                                            )
                                        }
                                        appViewModel.addWorkoutComponentVersioned(
                                            selectedWorkout,
                                            newExercise,
                                            hasHistory
                                        )
                                        appViewModel.scheduleWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.flushWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.goBack()
                                    } finally {
                                        isSaving = false
                                    }
                                }
                            },
                            onCancel = {
                                scope.launch {
                                    appViewModel.flushWorkoutSave(
                                        context,
                                        workoutStoreRepository,
                                        db
                                    )
                                    appViewModel.goBack()
                                }
                            },
                            allowSettingDoNotStoreHistory = true,
                            isSaving = isSaving
                        )
                    }

                    is ScreenData.NewSuperset -> {
                        val screenData = currentScreen as ScreenData.NewSuperset
                        val workouts by appViewModel.workoutsFlow.collectAsState()

                        var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!
                        var currentWorkout = selectedWorkout

                        while (!currentWorkout.isActive) {
                            val nextWorkout =
                                workouts.find { it.id == currentWorkout.nextVersionId }!!
                            currentWorkout = nextWorkout
                        }

                        selectedWorkout = currentWorkout

                        var isSaving by remember { mutableStateOf(false) }
                        SupersetForm(
                            onSupersetUpsert = { newSuperset ->
                                if (isSaving) return@SupersetForm
                                isSaving = true
                                val newWorkoutComponents =
                                    selectedWorkout.workoutComponents.filter { item ->
                                        newSuperset.exercises.none { it.id == item.id }
                                    } + newSuperset

                                val adjustedComponents =
                                    ensureRestSeparatedByExercises(newWorkoutComponents)
                                val updatedWorkout =
                                    selectedWorkout.copy(workoutComponents = adjustedComponents)
                                scope.launch {
                                    try {
                                        val hasHistory = withContext(Dispatchers.IO) {
                                            workoutHistoryDao.workoutHistoryExistsByWorkoutId(
                                                selectedWorkout.id
                                            )
                                        }
                                        appViewModel.updateWorkoutVersioned(
                                            selectedWorkout,
                                            updatedWorkout,
                                            hasHistory
                                        )
                                        appViewModel.scheduleWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.flushWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.goBack()
                                    } finally {
                                        isSaving = false
                                    }
                                }
                            },
                            onCancel = {
                                scope.launch {
                                    appViewModel.flushWorkoutSave(
                                        context,
                                        workoutStoreRepository,
                                        db
                                    )
                                    appViewModel.goBack()
                                }
                            },
                            availableExercises = selectedWorkout.workoutComponents.filterIsInstance<Exercise>(),
                            isSaving = isSaving
                        )
                    }

                    is ScreenData.EditExercise -> {
                        val screenData = currentScreen as ScreenData.EditExercise
                        val workouts by appViewModel.workoutsFlow.collectAsState()

                        var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!

                        var currentWorkout = selectedWorkout

                        while (!currentWorkout.isActive) {
                            val nextWorkout =
                                workouts.find { it.id == currentWorkout.nextVersionId }!!
                            currentWorkout = nextWorkout
                        }

                        selectedWorkout = currentWorkout

                        val selectedExercise = findWorkoutComponentByIdInWorkout(
                            selectedWorkout,
                            screenData.selectedExerciseId
                        ) as Exercise

                        var isSaving by remember { mutableStateOf(false) }
                        ExerciseForm(
                            appViewModel,
                            onExerciseUpsert = { updatedExercise ->
                                if (isSaving) return@ExerciseForm
                                isSaving = true
                                scope.launch {
                                    try {
                                        val hasHistory = withContext(Dispatchers.IO) {
                                            workoutHistoryDao.workoutHistoryExistsByWorkoutId(
                                                selectedWorkout.id
                                            )
                                        }
                                        appViewModel.updateWorkoutComponentVersioned(
                                            selectedWorkout,
                                            selectedExercise,
                                            updatedExercise,
                                            hasHistory
                                        )
                                        appViewModel.scheduleWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.flushWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.goBack()
                                    } finally {
                                        isSaving = false
                                    }
                                }
                            },
                            onCancel = {
                                appViewModel.goBack()
                            },
                            exercise = selectedExercise,
                            allowSettingDoNotStoreHistory = true,
                            isSaving = isSaving
                        )
                    }

                    is ScreenData.EditSuperset -> {
                        val screenData = currentScreen as ScreenData.EditSuperset
                        val workouts by appViewModel.workoutsFlow.collectAsState()

                        var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!

                        var currentWorkout = selectedWorkout

                        while (!currentWorkout.isActive) {
                            val nextWorkout =
                                workouts.find { it.id == currentWorkout.nextVersionId }!!
                            currentWorkout = nextWorkout
                        }

                        selectedWorkout = currentWorkout

                        val selectedSuperset = findWorkoutComponentByIdInWorkout(
                            selectedWorkout,
                            screenData.selectedSupersetId
                        ) as Superset

                        var isSaving by remember { mutableStateOf(false) }
                        SupersetForm(
                            onSupersetUpsert = { updatedSuperset ->
                                if (isSaving) return@SupersetForm
                                isSaving = true
                                scope.launch {
                                    try {
                                        val hasHistory = withContext(Dispatchers.IO) {
                                            workoutHistoryDao.workoutHistoryExistsByWorkoutId(
                                                selectedWorkout.id
                                            )
                                        }
                                        appViewModel.updateWorkoutComponentVersioned(
                                            selectedWorkout,
                                            selectedSuperset,
                                            updatedSuperset,
                                            hasHistory
                                        )
                                        appViewModel.scheduleWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.flushWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.goBack()
                                    } finally {
                                        isSaving = false
                                    }
                                }
                            },
                            onCancel = {
                                appViewModel.goBack()
                            },
                            availableExercises = selectedWorkout.workoutComponents.filterIsInstance<Exercise>(),
                            superset = selectedSuperset,
                            isSaving = isSaving
                        )
                    }

                    is ScreenData.NewSet -> {
                        val screenData = currentScreen as ScreenData.NewSet
                        val workouts by appViewModel.workoutsFlow.collectAsState()
                        var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!

                        var currentWorkout = selectedWorkout

                        while (!currentWorkout.isActive) {
                            val nextWorkout =
                                workouts.find { it.id == currentWorkout.nextVersionId }!!
                            currentWorkout = nextWorkout
                        }

                        selectedWorkout = currentWorkout

                        val parentExercise = findWorkoutComponentByIdInWorkout(
                            selectedWorkout,
                            screenData.parentExerciseId
                        ) as Exercise
                        var isSaving by remember { mutableStateOf(false) }
                        SetForm(
                            onSetUpsert = { updatedSet ->
                                if (isSaving) return@SetForm
                                isSaving = true
                                scope.launch {
                                    try {
                                        val hasHistory = withContext(Dispatchers.IO) {
                                            workoutHistoryDao.workoutHistoryExistsByWorkoutId(
                                                selectedWorkout.id
                                            )
                                        }
                                        appViewModel.addSetToExerciseVersioned(
                                            selectedWorkout,
                                            parentExercise,
                                            updatedSet,
                                            hasHistory
                                        )
                                        appViewModel.scheduleWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.flushWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.goBack()
                                    } finally {
                                        isSaving = false
                                    }
                                }
                            },
                            onCancel = {
                                scope.launch {
                                    appViewModel.flushWorkoutSave(
                                        context,
                                        workoutStoreRepository,
                                        db
                                    )
                                    appViewModel.goBack()
                                }
                            },
                            exerciseType = parentExercise.exerciseType,
                            viewModel = appViewModel,
                            exercise = parentExercise,
                            isSaving = isSaving
                        )
                    }

                    is ScreenData.NewRestSet -> {
                        val screenData = currentScreen as ScreenData.NewRestSet
                        val workouts by appViewModel.workoutsFlow.collectAsState()
                        var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!

                        var currentWorkout = selectedWorkout

                        while (!currentWorkout.isActive) {
                            val nextWorkout =
                                workouts.find { it.id == currentWorkout.nextVersionId }!!
                            currentWorkout = nextWorkout
                        }

                        selectedWorkout = currentWorkout

                        val parentExercise = findWorkoutComponentByIdInWorkout(
                            selectedWorkout,
                            screenData.parentExerciseId
                        ) as Exercise
                        var isSaving by remember { mutableStateOf(false) }
                        RestSetForm(
                            onRestSetUpsert = { newRestSet ->
                                if (isSaving) return@RestSetForm
                                isSaving = true
                                val oldSets = parentExercise.sets.filter { it !is RestSet }
                                val modifiedSets = oldSets
                                    .flatMapIndexed { index, element ->
                                        if (index != oldSets.size - 1) {
                                            listOf(
                                                element,
                                                newRestSet.copy(id = java.util.UUID.randomUUID())
                                            )
                                        } else {
                                            listOf(element)
                                        }
                                    }

                                val updatedExercise = parentExercise.copy(sets = modifiedSets)

                                scope.launch {
                                    try {
                                        val hasHistory = withContext(Dispatchers.IO) {
                                            workoutHistoryDao.workoutHistoryExistsByWorkoutId(
                                                selectedWorkout.id
                                            )
                                        }
                                        appViewModel.updateWorkoutComponentVersioned(
                                            selectedWorkout,
                                            parentExercise,
                                            updatedExercise,
                                            hasHistory
                                        )
                                        appViewModel.scheduleWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.flushWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.goBack()
                                    } finally {
                                        isSaving = false
                                    }
                                }
                            },
                            onCancel = {
                                appViewModel.goBack()
                            },
                            isSaving = isSaving
                        )
                    }

                    is ScreenData.EditRestSet -> {
                        val screenData = currentScreen as ScreenData.EditRestSet
                        val workouts by appViewModel.workoutsFlow.collectAsState()

                        var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!

                        var currentWorkout = selectedWorkout

                        while (!currentWorkout.isActive) {
                            val nextWorkout =
                                workouts.find { it.id == currentWorkout.nextVersionId }!!
                            currentWorkout = nextWorkout
                        }

                        selectedWorkout = currentWorkout

                        val parentExercise = findWorkoutComponentByIdInWorkout(
                            selectedWorkout,
                            screenData.parentExerciseId
                        ) as Exercise
                        var isSaving by remember { mutableStateOf(false) }
                        RestSetForm(
                            onRestSetUpsert = { updatedSet ->
                                if (isSaving) return@RestSetForm
                                isSaving = true
                                scope.launch {
                                    try {
                                        val hasHistory = withContext(Dispatchers.IO) {
                                            workoutHistoryDao.workoutHistoryExistsByWorkoutId(
                                                selectedWorkout.id
                                            )
                                        }
                                        appViewModel.updateSetInExerciseVersioned(
                                            selectedWorkout,
                                            parentExercise,
                                            screenData.selectedRestSet,
                                            updatedSet,
                                            hasHistory
                                        )
                                        appViewModel.scheduleWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.flushWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.goBack()
                                    } finally {
                                        isSaving = false
                                    }
                                }
                            },
                            onCancel = {
                                appViewModel.goBack()
                            },
                            restSet = screenData.selectedRestSet,
                            isSaving = isSaving
                        )
                    }

                    is ScreenData.NewRest -> {
                        val screenData = currentScreen as ScreenData.NewRest
                        val workouts by appViewModel.workoutsFlow.collectAsState()

                        var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!
                        var currentWorkout = selectedWorkout

                        while (!currentWorkout.isActive) {
                            val nextWorkout =
                                workouts.find { it.id == currentWorkout.nextVersionId }!!
                            currentWorkout = nextWorkout
                        }

                        selectedWorkout = currentWorkout

                        var isSaving by remember { mutableStateOf(false) }
                        RestForm(
                            onRestUpsert = { newRest ->
                                if (isSaving) return@RestForm
                                isSaving = true
                                val oldWorkoutComponents =
                                    selectedWorkout.workoutComponents.filter { it !is Rest }

                                val modifiedWorkoutComponents = oldWorkoutComponents
                                    .flatMapIndexed { index, element ->
                                        if (index != oldWorkoutComponents.size - 1) {
                                            listOf(
                                                element,
                                                newRest.copy(id = java.util.UUID.randomUUID())
                                            )
                                        } else {
                                            listOf(element)
                                        }
                                    }

                                val adjustedComponents =
                                    ensureRestSeparatedByExercises(modifiedWorkoutComponents)

                                val updatedWorkout =
                                    selectedWorkout.copy(workoutComponents = adjustedComponents)
                                scope.launch {
                                    try {
                                        val hasHistory = withContext(Dispatchers.IO) {
                                            workoutHistoryDao.workoutHistoryExistsByWorkoutId(
                                                selectedWorkout.id
                                            )
                                        }
                                        appViewModel.updateWorkoutVersioned(
                                            selectedWorkout,
                                            updatedWorkout,
                                            hasHistory
                                        )
                                        appViewModel.scheduleWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.flushWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.goBack()
                                    } finally {
                                        isSaving = false
                                    }
                                }
                            },
                            onCancel = {
                                scope.launch {
                                    appViewModel.flushWorkoutSave(
                                        context,
                                        workoutStoreRepository,
                                        db
                                    )
                                    appViewModel.goBack()
                                }
                            },
                            isSaving = isSaving
                        )
                    }

                    is ScreenData.EditRest -> {
                        val screenData = currentScreen as ScreenData.EditRest
                        val workouts by appViewModel.workoutsFlow.collectAsState()

                        var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!

                        var currentWorkout = selectedWorkout

                        while (!currentWorkout.isActive) {
                            val nextWorkout =
                                workouts.find { it.id == currentWorkout.nextVersionId }!!
                            currentWorkout = nextWorkout
                        }

                        selectedWorkout = currentWorkout

                        var isSaving by remember { mutableStateOf(false) }
                        RestForm(
                            onRestUpsert = { newRest ->
                                if (isSaving) return@RestForm
                                isSaving = true
                                scope.launch {
                                    try {
                                        val hasHistory = withContext(Dispatchers.IO) {
                                            workoutHistoryDao.workoutHistoryExistsByWorkoutId(
                                                selectedWorkout.id
                                            )
                                        }
                                        appViewModel.updateWorkoutComponentVersioned(
                                            selectedWorkout,
                                            screenData.selectedRest,
                                            newRest,
                                            hasHistory
                                        )
                                        appViewModel.scheduleWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.flushWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.goBack()
                                    } finally {
                                        isSaving = false
                                    }
                                }
                            },
                            onCancel = {
                                appViewModel.goBack()
                            },
                            rest = screenData.selectedRest,
                            isSaving = isSaving,
                            workout = selectedWorkout
                        )
                    }

                    is ScreenData.InsertRestSetAfter -> {
                        val screenData = currentScreen as ScreenData.InsertRestSetAfter
                        val workouts by appViewModel.workoutsFlow.collectAsState()
                        var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!

                        var currentWorkout = selectedWorkout
                        while (!currentWorkout.isActive) {
                            val nextWorkout =
                                workouts.find { it.id == currentWorkout.nextVersionId }!!
                            currentWorkout = nextWorkout
                        }

                        selectedWorkout = currentWorkout

                        val parentExercise = findWorkoutComponentByIdInWorkout(
                            selectedWorkout,
                            screenData.exerciseId
                        ) as Exercise

                        val afterSetIndex =
                            parentExercise.sets.indexOfFirst { it.id == screenData.afterSetId }

                        if (afterSetIndex < 0) {
                            LaunchedEffect(Unit) {
                                appViewModel.goBack()
                            }
                        }

                        var isSaving by remember { mutableStateOf(false) }

                        if (afterSetIndex >= 0) {
                            RestSetForm(
                                onRestSetUpsert = { newRestSet ->
                                    if (isSaving) return@RestSetForm
                                    isSaving = true
                                    val newSets = parentExercise.sets.toMutableList().apply {
                                        add(
                                            afterSetIndex + 1,
                                            newRestSet.copy(id = java.util.UUID.randomUUID())
                                        )
                                    }

                                    val adjustedComponents = ensureRestSeparatedBySets(newSets)
                                    val updatedExercise = parentExercise.copy(
                                        sets = adjustedComponents,
                                        requiredAccessoryEquipmentIds = parentExercise.requiredAccessoryEquipmentIds
                                            ?: emptyList()
                                    )

                                    scope.launch {
                                        try {
                                            val hasHistory = withContext(Dispatchers.IO) {
                                                workoutHistoryDao.workoutHistoryExistsByWorkoutId(
                                                    selectedWorkout.id
                                                )
                                            }
                                            appViewModel.updateWorkoutComponentVersioned(
                                                selectedWorkout,
                                                parentExercise,
                                                updatedExercise,
                                                hasHistory
                                            )
                                            appViewModel.scheduleWorkoutSave(
                                                context,
                                                workoutStoreRepository,
                                                db
                                            )
                                            appViewModel.flushWorkoutSave(
                                                context,
                                                workoutStoreRepository,
                                                db
                                            )
                                            appViewModel.goBack()
                                        } finally {
                                            isSaving = false
                                        }
                                    }
                                },
                                onCancel = {
                                    scope.launch {
                                        appViewModel.flushWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.goBack()
                                    }
                                },
                                isSaving = isSaving
                            )
                        }
                    }

                    is ScreenData.InsertRestAfter -> {
                        val screenData = currentScreen as ScreenData.InsertRestAfter
                        val workouts by appViewModel.workoutsFlow.collectAsState()

                        var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!
                        var currentWorkout = selectedWorkout

                        while (!currentWorkout.isActive) {
                            val nextWorkout =
                                workouts.find { it.id == currentWorkout.nextVersionId }!!
                            currentWorkout = nextWorkout
                        }

                        selectedWorkout = currentWorkout

                        val afterComponentIndex =
                            selectedWorkout.workoutComponents.indexOfFirst { it.id == screenData.afterComponentId }

                        if (afterComponentIndex < 0) {
                            LaunchedEffect(Unit) {
                                appViewModel.goBack()
                            }
                        }

                        var isSaving by remember { mutableStateOf(false) }

                        if (afterComponentIndex >= 0) {
                            RestForm(
                                onRestUpsert = { newRest ->
                                    if (isSaving) return@RestForm
                                    isSaving = true
                                    val newWorkoutComponents =
                                        selectedWorkout.workoutComponents.toMutableList().apply {
                                            add(
                                                afterComponentIndex + 1,
                                                newRest.copy(id = java.util.UUID.randomUUID())
                                            )
                                        }

                                    val adjustedComponents =
                                        ensureRestSeparatedByExercises(newWorkoutComponents)
                                    val updatedWorkout =
                                        selectedWorkout.copy(workoutComponents = adjustedComponents)

                                    scope.launch {
                                        try {
                                            val hasHistory = withContext(Dispatchers.IO) {
                                                workoutHistoryDao.workoutHistoryExistsByWorkoutId(
                                                    selectedWorkout.id
                                                )
                                            }
                                            appViewModel.updateWorkoutVersioned(
                                                selectedWorkout,
                                                updatedWorkout,
                                                hasHistory
                                            )
                                            appViewModel.scheduleWorkoutSave(
                                                context,
                                                workoutStoreRepository,
                                                db
                                            )
                                            appViewModel.flushWorkoutSave(
                                                context,
                                                workoutStoreRepository,
                                                db
                                            )
                                            appViewModel.goBack()
                                        } finally {
                                            isSaving = false
                                        }
                                    }
                                },
                                onCancel = {
                                    scope.launch {
                                        appViewModel.flushWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.goBack()
                                    }
                                },
                                isSaving = isSaving
                            )
                        }
                    }

                    is ScreenData.EditSet -> {
                        val screenData = currentScreen as ScreenData.EditSet
                        val workouts by appViewModel.workoutsFlow.collectAsState()

                        var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!

                        var currentWorkout = selectedWorkout

                        while (!currentWorkout.isActive) {
                            val nextWorkout =
                                workouts.find { it.id == currentWorkout.nextVersionId }!!
                            currentWorkout = nextWorkout
                        }

                        selectedWorkout = currentWorkout

                        val parentExercise = findWorkoutComponentByIdInWorkout(
                            selectedWorkout,
                            screenData.parentExerciseId
                        ) as Exercise
                        var isSaving by remember { mutableStateOf(false) }
                        SetForm(
                            onSetUpsert = { updatedSet ->
                                if (isSaving) return@SetForm
                                isSaving = true
                                scope.launch {
                                    try {
                                        val hasHistory = withContext(Dispatchers.IO) {
                                            workoutHistoryDao.workoutHistoryExistsByWorkoutId(
                                                selectedWorkout.id
                                            )
                                        }
                                        appViewModel.updateSetInExerciseVersioned(
                                            selectedWorkout,
                                            parentExercise,
                                            screenData.selectedSet,
                                            updatedSet,
                                            hasHistory
                                        )
                                        appViewModel.scheduleWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.flushWorkoutSave(
                                            context,
                                            workoutStoreRepository,
                                            db
                                        )
                                        appViewModel.goBack()
                                    } finally {
                                        isSaving = false
                                    }
                                }
                            },
                            onCancel = {
                                appViewModel.goBack()
                            },
                            set = screenData.selectedSet,
                            exerciseType = parentExercise.exerciseType,
                            viewModel = appViewModel,
                            exercise = parentExercise,
                            isSaving = isSaving
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

                            EquipmentType.ACCESSORY -> {
                                val accessories by appViewModel.accessoryEquipmentsFlow.collectAsState()
                                AccessoryForm(onUpsert = { new ->
                                    val newAccessories = accessories + new
                                    appViewModel.updateAccessoryEquipments(newAccessories)
                                    appViewModel.goBack()
                                }, onCancel = { appViewModel.goBack() })
                            }

                            EquipmentType.IRONNECK -> appViewModel.goBack()
                        }
                    }

                    is ScreenData.EditEquipment -> {
                        val screenData = currentScreen as ScreenData.EditEquipment
                        val equipments by appViewModel.equipmentsFlow.collectAsState()
                        val accessories by appViewModel.accessoryEquipmentsFlow.collectAsState()

                        when (screenData.equipmentType) {
                            EquipmentType.GENERIC -> throw NotImplementedError()
                            EquipmentType.BARBELL -> {
                                val selectedBarbell =
                                    equipments.find { it.id == screenData.equipmentId } as Barbell
                                BarbellForm(onUpsert = { updatedBarbell ->
                                    val updatedEquipments = equipments.map { equipment ->
                                        if (equipment.id == selectedBarbell.id) updatedBarbell else equipment
                                    }
                                    appViewModel.updateEquipments(updatedEquipments)
                                    appViewModel.goBack()
                                }, onCancel = { appViewModel.goBack() }, barbell = selectedBarbell)
                            }

                            EquipmentType.DUMBBELLS -> {
                                val selectedDumbbells =
                                    equipments.find { it.id == screenData.equipmentId } as Dumbbells
                                DumbbellsForm(
                                    onUpsert = { updatedDumbbells ->
                                        val updatedEquipments = equipments.map { equipment ->
                                            if (equipment.id == selectedDumbbells.id) updatedDumbbells else equipment
                                        }
                                        appViewModel.updateEquipments(updatedEquipments)
                                        appViewModel.goBack()
                                    },
                                    onCancel = { appViewModel.goBack() },
                                    dumbbells = selectedDumbbells
                                )
                            }

                            EquipmentType.DUMBBELL -> {
                                val selectedDumbbell =
                                    equipments.find { it.id == screenData.equipmentId } as Dumbbell
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
                                val selectedCable =
                                    equipments.find { it.id == screenData.equipmentId } as PlateLoadedCable
                                PlateLoadedCableForm(
                                    onUpsert = { updatedCable ->
                                        val updatedEquipments = equipments.map { equipment ->
                                            if (equipment.id == selectedCable.id) updatedCable else equipment
                                        }
                                        appViewModel.updateEquipments(updatedEquipments)
                                        appViewModel.goBack()
                                    },
                                    onCancel = { appViewModel.goBack() },
                                    plateLoadedCable = selectedCable
                                )
                            }

                            EquipmentType.WEIGHTVEST -> {
                                val selectedVest =
                                    equipments.find { it.id == screenData.equipmentId } as WeightVest
                                WeightVestForm(onUpsert = { updatedVest ->
                                    val updatedEquipments = equipments.map { equipment ->
                                        if (equipment.id == selectedVest.id) updatedVest else equipment
                                    }
                                    appViewModel.updateEquipments(updatedEquipments)
                                    appViewModel.goBack()
                                }, onCancel = { appViewModel.goBack() }, weightVest = selectedVest)
                            }

                            EquipmentType.MACHINE -> {
                                val selectedMachine =
                                    equipments.find { it.id == screenData.equipmentId } as Machine
                                MachineForm(onUpsert = { updatedMachine ->
                                    val updatedEquipments = equipments.map { equipment ->
                                        if (equipment.id == selectedMachine.id) updatedMachine else equipment
                                    }
                                    appViewModel.updateEquipments(updatedEquipments)
                                    appViewModel.goBack()
                                }, onCancel = { appViewModel.goBack() }, machine = selectedMachine)
                            }

                            EquipmentType.ACCESSORY -> {
                                val selectedAccessory =
                                    accessories.find { it.id == screenData.equipmentId }!!
                                AccessoryForm(
                                    onUpsert = { updatedAccessory ->
                                        val updatedAccessories = accessories.map { accessory ->
                                            if (accessory.id == selectedAccessory.id) updatedAccessory else accessory
                                        }
                                        appViewModel.updateAccessoryEquipments(updatedAccessories)
                                        appViewModel.goBack()
                                    },
                                    onCancel = { appViewModel.goBack() },
                                    accessory = selectedAccessory
                                )
                            }

                            EquipmentType.IRONNECK -> appViewModel.goBack()
                        }
                    }
                }
            }

            // Resume workout dialog
            val showResumeDialog by appViewModel.showResumeWorkoutDialog
            val incompleteWorkouts by appViewModel.incompleteWorkouts

            com.gabstra.myworkoutassistant.workout.ResumeWorkoutDialog(
                show = showResumeDialog,
                incompleteWorkouts = incompleteWorkouts,
                onDismiss = {
                    appViewModel.hideResumeWorkoutDialog()
                },
                onResumeWorkout = { workoutId ->
                    appViewModel.hideResumeWorkoutDialog()
                    workoutViewModel.setSelectedWorkoutId(workoutId)
                    workoutViewModel.resumeWorkoutFromRecord()
                    val prefs = context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
                    prefs.edit { putBoolean("isWorkoutInProgress", true) }
                    appViewModel.setScreenData(ScreenData.Workout(workoutId))
                }
            )
        }
    }
}
