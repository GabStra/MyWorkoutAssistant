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
import androidx.activity.OnBackPressedCallback
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.EnterTransition
import androidx.compose.animation.ExitTransition
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.zIndex
import androidx.compose.ui.unit.dp
import androidx.core.content.edit
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.RestingHeartRateRecord
import androidx.health.connect.client.records.Vo2MaxRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.TotalCaloriesBurnedRecord
import androidx.health.connect.client.records.WeightRecord
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.lifecycleScope
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.composables.LoadingScreen
import com.gabstra.myworkoutassistant.composables.ContentSubtitle
import com.gabstra.myworkoutassistant.composables.AppPrimaryOutlinedButton
import com.gabstra.myworkoutassistant.composables.StandardDialog
import com.gabstra.myworkoutassistant.composables.SyncStatusBadge
import com.gabstra.myworkoutassistant.composables.LocalBreadcrumbContent
import com.gabstra.myworkoutassistant.insights.LiteRtLmModelStore
import com.gabstra.myworkoutassistant.insights.LiteRtLmBackendPreference
import com.gabstra.myworkoutassistant.insights.RemoteOpenAiConfig
import com.gabstra.myworkoutassistant.insights.WorkoutInsightsMode
import com.gabstra.myworkoutassistant.insights.WorkoutInsightsSettingsStore
import com.gabstra.myworkoutassistant.screens.ErrorLogsScreen
import com.gabstra.myworkoutassistant.screens.ExternalWorkoutSessionDetailScreen
import com.gabstra.myworkoutassistant.screens.ExerciseDetailScreen
import com.gabstra.myworkoutassistant.screens.ExerciseForm
import com.gabstra.myworkoutassistant.screens.applyRecurringExerciseEdit
import com.gabstra.myworkoutassistant.screens.sanitizeRecurringTrackMetadata
import com.gabstra.myworkoutassistant.screens.ExerciseLibraryPickerScreen
import com.gabstra.myworkoutassistant.screens.ExerciseDefinitionForm
import com.gabstra.myworkoutassistant.shared.ExerciseDefinition
import com.gabstra.myworkoutassistant.shared.allExercisePrescriptions
import com.gabstra.myworkoutassistant.shared.duplicatePrescription
import com.gabstra.myworkoutassistant.shared.effectiveFamilyId
import com.gabstra.myworkoutassistant.shared.normalizeExerciseFamilyMovementOwnership
import com.gabstra.myworkoutassistant.shared.normalizedForImport
import com.gabstra.myworkoutassistant.shared.materializeDefinition
import com.gabstra.myworkoutassistant.shared.resolveExerciseVariation
import com.gabstra.myworkoutassistant.screens.HistoryChatScreen
import com.gabstra.myworkoutassistant.screens.HistoryChatScreenMode
import com.gabstra.myworkoutassistant.screens.RestForm
import com.gabstra.myworkoutassistant.screens.RestSetForm
import com.gabstra.myworkoutassistant.screens.SensorSessionDetailScreen
import com.gabstra.myworkoutassistant.screens.SensorSessionsScreen
import com.gabstra.myworkoutassistant.screens.SetForm
import com.gabstra.myworkoutassistant.screens.SettingsScreen
import com.gabstra.myworkoutassistant.screens.SupersetForm
import com.gabstra.myworkoutassistant.screens.WorkoutDetailScreen
import com.gabstra.myworkoutassistant.screens.WorkoutForm
import com.gabstra.myworkoutassistant.screens.formatScheduleConflictMessage
import com.gabstra.myworkoutassistant.screens.recurringPrescriptionDisplayLabel
import com.gabstra.myworkoutassistant.screens.WorkoutScreen
import com.gabstra.myworkoutassistant.screens.WorkoutsScreen
import com.gabstra.myworkoutassistant.screens.PlansScreen
import com.gabstra.myworkoutassistant.screens.equipments.AccessoryForm
import com.gabstra.myworkoutassistant.screens.equipments.BarbellForm
import com.gabstra.myworkoutassistant.screens.equipments.CardioMachineForm
import com.gabstra.myworkoutassistant.screens.equipments.DumbbellForm
import com.gabstra.myworkoutassistant.screens.equipments.DumbbellsForm
import com.gabstra.myworkoutassistant.screens.equipments.MachineForm
import com.gabstra.myworkoutassistant.screens.equipments.PlateLoadedCableForm
import com.gabstra.myworkoutassistant.screens.equipments.WeightVestForm
import com.gabstra.myworkoutassistant.shared.AppBackup
import com.gabstra.myworkoutassistant.shared.mergedWithPersonalSettingsOf
import com.gabstra.myworkoutassistant.shared.FullBackup
import com.gabstra.myworkoutassistant.shared.fromFullBackupToJSON
import com.gabstra.myworkoutassistant.shared.fromJSONToFullBackup
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.BackupFileType
import com.gabstra.myworkoutassistant.shared.ExerciseInfoDao
import com.gabstra.myworkoutassistant.shared.RestHistoryDao
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.workout.history.importing.WorkoutHistoryImportPackage
import com.gabstra.myworkoutassistant.shared.workout.history.importing.WorkoutHistoryImportService
import com.gabstra.myworkoutassistant.shared.workout.history.knownDurationSecondsOrNull
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import com.gabstra.myworkoutassistant.shared.WorkoutRecordDao
import com.gabstra.myworkoutassistant.shared.WorkoutScheduleDao
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRecurringMetadataIssue
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRecurringMetadataIssueCode
import com.gabstra.myworkoutassistant.shared.WorkoutStoreValidationException
import com.gabstra.myworkoutassistant.shared.convertUnassignedPlansToUngroupedWorkouts
import com.gabstra.myworkoutassistant.shared.profile.Profiles
import java.io.File
import com.gabstra.myworkoutassistant.shared.detectBackupFileType
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.CardioMachine
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbell
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbells
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.equipments.Machine
import com.gabstra.myworkoutassistant.shared.equipments.PlateLoadedCable
import com.gabstra.myworkoutassistant.shared.equipments.WeightVest
import com.gabstra.myworkoutassistant.shared.export.WorkoutDataExportRange
import com.gabstra.myworkoutassistant.shared.fromAppBackupToJSONPrettyPrint
import com.gabstra.myworkoutassistant.shared.fromBackupJsonToAppBackup
import com.gabstra.myworkoutassistant.shared.fromJSONToWorkoutPlanPackage
import com.gabstra.myworkoutassistant.shared.fromWorkoutStoreToJSON
import com.gabstra.myworkoutassistant.shared.motion.restoreExerciseMovementBackups
import com.gabstra.myworkoutassistant.shared.motion.requireExerciseMovementPayloads
import com.gabstra.myworkoutassistant.shared.sanitizeRestPlacementInSetHistoriesByWorkoutAndExercise
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.validateWorkoutStoreForRuntimeUse
import com.gabstra.myworkoutassistant.shared.utils.ScheduleConflictChecker
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.sync.BackupCoordinator
import com.gabstra.myworkoutassistant.sync.PhoneToWatchSyncCoordinator
import com.gabstra.myworkoutassistant.ui.theme.MyWorkoutAssistantTheme
import com.gabstra.myworkoutassistant.formatTime
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
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.withContext
import kotlinx.coroutines.yield
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle

@Composable
private fun PermissionRequirementRow(
    label: String,
    granted: Boolean
) {
    Row(
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Checkbox(
            checked = granted,
            onCheckedChange = null,
            colors = CheckboxDefaults.colors().copy(
                checkedCheckmarkColor = MaterialTheme.colorScheme.onPrimary,
                uncheckedBorderColor = MaterialTheme.colorScheme.primary
            )
        )
        Text(
            text = label
        )
    }
}

private fun Throwable.toMainActivityToastMessage(
    intro: String,
    fallbackDetail: String
): String {
    val detail = message?.trim()?.takeIf { it.isNotEmpty() } ?: fallbackDetail
    return "$intro $detail"
}

private fun WorkoutStoreValidationException.toUserFacingMessage(context: Context): String {
    val sections = mutableListOf<String>()
    if (duplicateSetIdIssues.isNotEmpty()) {
        sections += buildString {
            append(context.getString(R.string.loc_validation_duplicate_set_ids_intro))
            append("\n\n")
            append(
                duplicateSetIdIssues.take(3).joinToString("\n\n") { issue ->
                    context.getString(
                        R.string.loc_validation_duplicate_set_id_block,
                        issue.workoutName,
                        issue.setId.toString(),
                        issue.exerciseNames.joinToString(", "),
                    )
                }
            )
            val remaining = duplicateSetIdIssues.size - 3
            if (remaining > 0) {
                append("\n\n")
                append(context.getString(R.string.loc_validation_duplicate_set_ids_more, remaining))
            }
        }
    }
    if (recurringMetadataIssues.isNotEmpty()) {
        sections += buildString {
            append(context.getString(R.string.loc_validation_recurring_intro))
            append("\n")
            append(
                recurringMetadataIssues.take(5).joinToString("\n") { issue ->
                    context.getString(
                        R.string.loc_validation_recurring_issue_line,
                        issue.toUserFacingText(context),
                    )
                }
            )
            val remaining = recurringMetadataIssues.size - 5
            if (remaining > 0) {
                append("\n")
                append(context.getString(R.string.loc_validation_recurring_more, remaining))
            }
        }
    }
    return sections.joinToString("\n\n")
}

private fun WorkoutStoreRecurringMetadataIssue.toUserFacingText(context: Context): String =
    when (code) {
        WorkoutStoreRecurringMetadataIssueCode.FIXED_PRESCRIBED_LOAD_UNSUPPORTED_SETS ->
            context.getString(
                R.string.loc_validation_recurring_fixed_prescribed_load_unsupported,
                workoutName,
                exerciseName.orEmpty(),
            )
        WorkoutStoreRecurringMetadataIssueCode.MISSING_RECURRING_SESSION_ID ->
            context.getString(
                R.string.loc_validation_recurring_missing_session_id,
                workoutName,
            )
        WorkoutStoreRecurringMetadataIssueCode.NON_POSITIVE_PRESCRIPTION_ORDINAL ->
            context.getString(
                R.string.loc_validation_recurring_non_positive_ordinal,
                workoutName,
            )
        WorkoutStoreRecurringMetadataIssueCode.DUPLICATE_PRESCRIPTION_ORDINAL ->
            context.getString(
                R.string.loc_validation_recurring_duplicate_ordinal,
                workoutName,
                prescriptionOrdinal ?: 0,
            )
        WorkoutStoreRecurringMetadataIssueCode.DUPLICATE_RECURRING_EXERCISE_SLOT_IDS ->
            context.getString(
                R.string.loc_validation_recurring_duplicate_slot_ids,
                workoutName,
            )
        WorkoutStoreRecurringMetadataIssueCode.LAST_WORKING_LOAD_MISSING_SLOT_ID ->
            context.getString(
                R.string.loc_validation_recurring_last_load_missing_slot_id,
                workoutName,
                exerciseName.orEmpty(),
            )
        WorkoutStoreRecurringMetadataIssueCode.LAST_WORKING_LOAD_UNSUPPORTED_SETS ->
            context.getString(
                R.string.loc_validation_recurring_last_load_unsupported_sets,
                workoutName,
                exerciseName.orEmpty(),
            )
        WorkoutStoreRecurringMetadataIssueCode.CONFLICTING_RECURRING_SLOT_IDENTITY ->
            context.getString(
                R.string.loc_validation_recurring_conflicting_slot_identity,
                recurringExerciseSlotId?.toString().orEmpty(),
            )
    }

private data class PendingWorkoutHistoryImport(
    val targetProfileId: String,
    val targetProfileName: String,
    val payload: WorkoutHistoryImportPackage,
)

/**
 * Prepares the shared half of a full backup for restore without discarding legacy one-sided
 * plan membership. The repository will apply the same conservative repair when it persists or
 * loads the data, but the in-memory union is also used to build each profile's restore input, so
 * it must be repaired here first. Authoritative conversion remains reserved for explicit user
 * moves and deletes.
 */
internal fun FullBackup.sharedStoreForRestore(): WorkoutStore =
    sharedStore.convertUnassignedPlansToUngroupedWorkouts(
        repairPlanOnlyMembership = true,
    )


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

    private val workoutStoreRepository get() = WorkoutStoreRepository.forActiveProfile(this)

    private lateinit var myReceiver: BroadcastReceiver

    private val healthConnectClient by lazy { HealthConnectClient.getOrCreate(this) }

    /** Scope for restore operations; not tied to lifecycle so restore can complete even if activity is recreated (e.g. rotation). */
    internal val restoreScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onStart() {
        super.onStart()
    }

    override fun onPause() {
        super.onPause()
        // Flush any pending debounced saves when app is paused
        // Only saves if a save was actually scheduled (flushWorkoutSave is a no-op if no save is pending)
        if (::appViewModel.isInitialized) {
            lifecycleScope.launch {
                appViewModel.flushWorkoutSave(this@MainActivity, workoutStoreRepository, db)
                BackupCoordinator.flushPendingBackup(this@MainActivity)
                PhoneToWatchSyncCoordinator.flushDebouncedSyncToWatch(this@MainActivity)
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
                BackupCoordinator.flushPendingBackup(this@MainActivity)
                PhoneToWatchSyncCoordinator.flushDebouncedSyncToWatch(this@MainActivity)
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
        enableEdgeToEdge()
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
        MainActivityIntentRouter.route(intent, appViewModel)

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

        PhoneToWatchSyncCoordinator.install(applicationContext)

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
        MainActivityIntentRouter.route(intent, appViewModel)
    }

}

/**
 * Bumped whenever a restore applies insights settings from a backup, so the
 * Settings screen state re-derives from preferences instead of overwriting
 * the restored values on the next save.
 */
private var insightsSettingsRestoredStamp by mutableStateOf(0)

/**
 * Applies insights settings carried in a backup. Null fields (older backups,
 * or settings that were unset when the backup was taken) leave the current
 * device preferences untouched.
 */
private fun applyInsightsSettingsFromBackup(appBackup: AppBackup, context: Context) {
    var appliedAny = false
    appBackup.MobileLlmEnabled?.let {
        WorkoutInsightsSettingsStore.setEnabled(context, it)
        appliedAny = true
    }
    appBackup.WorkoutInsightsMode
        ?.let { modeName -> WorkoutInsightsMode.entries.firstOrNull { it.name == modeName } }
        ?.let {
            WorkoutInsightsSettingsStore.setMode(context, it)
            appliedAny = true
        }
    if (appBackup.RemoteInsightsBaseUrl != null ||
        appBackup.RemoteInsightsApiKey != null ||
        appBackup.RemoteInsightsModel != null
    ) {
        WorkoutInsightsSettingsStore.setRemoteConfig(
            context,
            RemoteOpenAiConfig(
                baseUrl = appBackup.RemoteInsightsBaseUrl.orEmpty(),
                apiKey = appBackup.RemoteInsightsApiKey.orEmpty(),
                model = appBackup.RemoteInsightsModel.orEmpty(),
            )
        )
        appliedAny = true
    }
    appBackup.WorkoutInsightsCustomInstructions?.let {
        WorkoutInsightsSettingsStore.setCustomInstructions(context, it)
        appliedAny = true
    }
    if (appliedAny) {
        insightsSettingsRestoredStamp++
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
        workoutViewModel.initRestHistoryDao(context)
        workoutViewModel.initWorkoutHistoryDao(context)
        workoutViewModel.initWorkoutScheduleDao(context)
        workoutViewModel.initWorkoutRecordDao(context)
        workoutViewModel.initExerciseInfoDao(context)
        workoutViewModel.initExerciseSessionProgressionDao(context)
        workoutViewModel.initWorkoutStoreRepository(workoutStoreRepository)
    }

    val setHistoryDao = db.setHistoryDao()
    val restHistoryDao = db.restHistoryDao()
    val workoutHistoryDao = db.workoutHistoryDao()
    val workoutScheduleDao = db.workoutScheduleDao()
    val workoutRecordDao = db.workoutRecordDao()

    val exerciseInfoDao = db.exerciseInfoDao()
    val exerciseSessionProgressionDao = db.exerciseSessionProgressionDao()

    val updateMobileFlow = appViewModel.updateMobileFlow
    val updateMobileSignal by updateMobileFlow.collectAsState()

    val initialDataLoaded by appViewModel.isInitialDataLoaded.collectAsState(initial = false)
    val workoutStoreValidationError by appViewModel.workoutStoreValidationError.collectAsState(initial = null)
    val scope = rememberCoroutineScope()

    val clearAllIncompleteSessions: () -> Unit = {
        scope.launch {
            val unfinishedWorkoutHistories =
                workoutHistoryDao.getAllUnfinishedWorkoutHistories()

            try {
                deleteWorkoutHistoriesFromHealthConnect(
                    context,
                    unfinishedWorkoutHistories,
                    healthConnectClient
                )
            } catch (e: Exception) {
                Toast.makeText(
                    context,
                    context.getString(R.string.main_health_connect_remove_unfinished_error),
                    Toast.LENGTH_SHORT
                ).show()
            }

            for (history in unfinishedWorkoutHistories) {
                workoutRecordDao.deleteByWorkoutHistoryId(history.id)
            }
            workoutHistoryDao.deleteAllUnfinished()
            appViewModel.triggerUpdate()
        }
    }

    val requiredHealthPermissions = remember {
        setOf(
            HealthPermission.getWritePermission(ExerciseSessionRecord::class),
            HealthPermission.getWritePermission(HeartRateRecord::class),
            HealthPermission.getReadPermission(ExerciseSessionRecord::class),
            HealthPermission.getReadPermission(HeartRateRecord::class),
            HealthPermission.getReadPermission(RestingHeartRateRecord::class),
            HealthPermission.getReadPermission(Vo2MaxRecord::class),
            HealthPermission.getWritePermission(TotalCaloriesBurnedRecord::class),
            HealthPermission.getWritePermission(WeightRecord::class),
            HealthPermission.getReadPermission(SleepSessionRecord::class),
        )
    }

    var hasHealthPermissions by remember { mutableStateOf(false) }
    var showPrerequisitesDialog by remember { mutableStateOf(false) }
    var deferHealthPermissionPrompt by remember { mutableStateOf(true) }
    var showStartupRestorePickerPrompt by remember { mutableStateOf(false) }
    var isRestoringBackup by remember { mutableStateOf(false) }
    val manualSyncUiState by PhoneToWatchSyncCoordinator.manualSyncUiState.collectAsState()
    val isSyncing = manualSyncUiState != null
    val isSyncingToWatch by PhoneToWatchSyncCoordinator.isSyncingToWatch.collectAsState()

    suspend fun refreshPermissionState(showDialogWhenMissing: Boolean) {
        val grantedPermissions = try {
            healthConnectClient.permissionController.getGrantedPermissions()
        } catch (_: Exception) {
            emptySet()
        }
        val missingPermissions = requiredHealthPermissions - grantedPermissions
        hasHealthPermissions = missingPermissions.isEmpty()
        appViewModel.setHealthPermissions(hasHealthPermissions)
        appViewModel.setHealthPermissionsChecked()

        if (hasHealthPermissions) {
            showPrerequisitesDialog = false
        }
    }

    val healthPermissionLauncher = rememberLauncherForActivityResult(
        PermissionController.createRequestPermissionResultContract()
    ) {
        scope.launch {
            refreshPermissionState(showDialogWhenMissing = true)
        }
    }

    DisposableEffect(lifecycleOwner, context) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                scope.launch {
                    refreshPermissionState(showDialogWhenMissing = true)
                }
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

    LaunchedEffect(Unit) {
        refreshPermissionState(showDialogWhenMissing = true)
    }

    // Sync WorkoutViewModel when initial load has completed
    LaunchedEffect(initialDataLoaded) {
        if (!initialDataLoaded) return@LaunchedEffect
        workoutViewModel.updateWorkoutStore(appViewModel.workoutStore)
    }

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

    var isExportingWorkoutDataForLlm by remember { mutableStateOf(false) }
    var workoutDataExportStatus by remember { mutableStateOf(context.getString(R.string.main_exporting_workout_data)) }

    LaunchedEffect(
        hasHealthPermissions,
        deferHealthPermissionPrompt,
        showStartupRestorePickerPrompt,
        isRestoringBackup,
        isSyncing,
    ) {
        showPrerequisitesDialog = shouldShowStartupPrerequisitesDialog(
            hasHealthPermissions = hasHealthPermissions,
            deferHealthPermissionPrompt = deferHealthPermissionPrompt,
            isRestorePromptVisible = showStartupRestorePickerPrompt,
            isRestoringBackup = isRestoringBackup,
            isSyncingWithWatch = isSyncing,
        )
    }

    if (showPrerequisitesDialog && !isSyncing && !isRestoringBackup) {
        StandardDialog(
            onDismissRequest = {},
            title = context.getString(R.string.main_permissions_required_title),
            body = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(context.getString(R.string.main_permissions_required_body))
                    PermissionRequirementRow(
                        label = context.getString(R.string.main_health_connect_permissions),
                        granted = hasHealthPermissions
                    )
                }
            },
            confirmText = context.getString(R.string.main_continue),
            onConfirm = {
                showPrerequisitesDialog = false
                if (!hasHealthPermissions) {
                    try {
                        healthPermissionLauncher.launch(requiredHealthPermissions)
                    } catch (e: Exception) {
                        Toast.makeText(
                            context,
                            e.toMainActivityToastMessage(
                                intro = context.getString(R.string.main_open_permission_prompt_error),
                                fallbackDetail = context.getString(R.string.main_please_try_again)
                            ),
                            Toast.LENGTH_SHORT
                        ).show()
                        scope.launch {
                            refreshPermissionState(showDialogWhenMissing = true)
                        }
                    }
                }
            },
            showDismiss = false
        )
    }
    
    var importPlanResultMessage by remember { mutableStateOf<String?>(null) }
    var pendingHistoryImport by remember { mutableStateOf<PendingWorkoutHistoryImport?>(null) }
    var isImportingHistory by remember { mutableStateOf(false) }

    val workoutStorePickerLauncher =
        rememberLauncherForActivityResult(contract = ActivityResultContracts.OpenDocument()) { uri: Uri? ->
            uri?.let {
                try {
                    context.contentResolver.openInputStream(it)?.use { inputStream ->
                        val reader = inputStream.bufferedReader()
                        val content = reader.readText()
                        val importFormat = runCatching { JSONObject(content).optString("format") }.getOrNull()
                        if (importFormat == WorkoutHistoryImportPackage.FORMAT) {
                            val payload = WorkoutHistoryImportPackage.fromJson(content)
                            val profile = Profiles.activeProfile(context)
                            val targetProfileId = profile.id
                            scope.launch {
                                try {
                                    val store = withContext(Dispatchers.IO) {
                                        WorkoutStoreRepository(
                                            Profiles.directory(context, targetProfileId),
                                            context.filesDir,
                                        ).getWorkoutStore()
                                    }
                                    WorkoutHistoryImportService.validate(store, targetProfileId, payload)
                                    pendingHistoryImport = PendingWorkoutHistoryImport(
                                        targetProfileId = targetProfileId,
                                        targetProfileName = profile.name,
                                        payload = payload,
                                    )
                                } catch (e: Exception) {
                                    Toast.makeText(
                                        context,
                                        e.toMainActivityToastMessage(
                                            intro = context.getString(R.string.main_review_history_error),
                                            fallbackDetail = context.getString(R.string.main_choose_another_file)
                                        ),
                                        Toast.LENGTH_LONG
                                    ).show()
                                }
                            }
                            return@let
                        }
                        val fileType = detectBackupFileType(content)
                        when (fileType) {
                            BackupFileType.FULL_BACKUP,
                            BackupFileType.APP_BACKUP,
                            BackupFileType.INCREMENTAL_APP_BACKUP -> {
                                Toast.makeText(
                                    context,
                                    context.getString(R.string.main_file_is_backup),
                                    Toast.LENGTH_SHORT
                                ).show()
                                return@let
                            }
                            BackupFileType.WORKOUT_STORE -> {
                                Toast.makeText(
                                    context,
                                    context.getString(R.string.main_file_is_full_export_not_plan),
                                    Toast.LENGTH_SHORT
                                ).show()
                                return@let
                            }
                            BackupFileType.EXERCISE_LIBRARY_PACKAGE -> {
                                Toast.makeText(
                                    context,
                                    context.getString(R.string.main_file_is_exercise_library),
                                    Toast.LENGTH_SHORT
                                ).show()
                                return@let
                            }
                            BackupFileType.UNKNOWN -> {
                                Toast.makeText(
                                    context,
                                    context.getString(R.string.main_file_not_valid_plan_package),
                                    Toast.LENGTH_SHORT
                                ).show()
                                return@let
                            }
                            BackupFileType.WORKOUT_PLAN_PACKAGE -> Unit
                        }
                        val importedWorkoutPlanPackage = fromJSONToWorkoutPlanPackage(content)

                        if (importedWorkoutPlanPackage.name.isBlank()) {
                            Toast.makeText(
                                context,
                                context.getString(R.string.main_plan_package_missing_name),
                                Toast.LENGTH_SHORT
                            ).show()
                            return@let
                        }

                        if (importedWorkoutPlanPackage.workouts.isEmpty()) {
                            Toast.makeText(
                                context,
                                context.getString(R.string.main_file_no_workouts),
                                Toast.LENGTH_SHORT
                            ).show()
                            return@let
                        }

                        scope.launch {
                            try {
                                val existingWorkoutsCount = appViewModel.workouts.size
                                val existingEquipmentCount = appViewModel.equipments.size
                                val existingAccessoriesCount = appViewModel.accessoryEquipments.size
                                val importedMovementCount = importedWorkoutPlanPackage.exerciseMovements.size

                                val newPlanId = java.util.UUID.randomUUID()
                                val nextOrder =
                                    (appViewModel.getAllWorkoutPlans().maxOfOrNull { it.order } ?: -1) + 1
                                val newPlan = WorkoutPlan(
                                    id = newPlanId,
                                    name = importedWorkoutPlanPackage.name,
                                    workoutIds = importedWorkoutPlanPackage.workouts.map { it.id },
                                    order = nextOrder,
                                    suggestNextPrescription = importedWorkoutPlanPackage.suggestNextPrescription,
                                )

                                val workoutsWithPlanId = importedWorkoutPlanPackage.workouts.map { workout ->
                                    workout.copy(workoutPlanId = newPlanId)
                                }
                                val currentWorkoutStore = appViewModel.workoutStore
                                val importedDefinitions =
                                    importedWorkoutPlanPackage.exerciseDefinitions.normalizedForImport()
                                val existingDefinitionsById = currentWorkoutStore.exerciseDefinitions.associateBy { it.id }
                                importedDefinitions.forEach { importedDefinition ->
                                    val existingDefinition = existingDefinitionsById[importedDefinition.id]
                                    // Same rule the library merge applies: only the movement binding may
                                    // differ, because normalisation assigns it.
                                    require(
                                        existingDefinition == null ||
                                            existingDefinition.copy(
                                                movementRef = importedDefinition.movementRef
                                            ) == importedDefinition
                                    ) {
                                        context.getString(
                                            R.string.main_definition_conflict,
                                            importedDefinition.id
                                        )
                                    }
                                }
                                val importedWorkoutStoreWithPlan = currentWorkoutStore.copy(
                                    workouts = workoutsWithPlanId,
                                    exerciseDefinitions = (
                                        currentWorkoutStore.exerciseDefinitions +
                                            importedDefinitions
                                        ).distinctBy { it.id },
                                    equipments = importedWorkoutPlanPackage.equipments,
                                    accessoryEquipments = importedWorkoutPlanPackage.accessoryEquipments,
                                    workoutPlans = listOf(newPlan)
                                ).normalizeExerciseFamilyMovementOwnership()

                                withContext(Dispatchers.IO) {
                                    restoreExerciseMovementBackups(
                                        context = context,
                                        movementBackups = importedWorkoutPlanPackage.exerciseMovements
                                    )
                                    requireExerciseMovementPayloads(context, importedWorkoutStoreWithPlan)
                                }

                                appViewModel.importWorkoutStore(importedWorkoutStoreWithPlan)

                                // Same persistence path as the library import: debounced save plus a
                                // backup snapshot and the phone-to-watch trigger.
                                appViewModel.scheduleWorkoutSave(context)

                                val newWorkoutsCount = appViewModel.workouts.size
                                val newEquipmentCount = appViewModel.equipments.size
                                val newAccessoriesCount = appViewModel.accessoryEquipments.size
                                val addedWorkouts = newWorkoutsCount - existingWorkoutsCount
                                val addedEquipment = newEquipmentCount - existingEquipmentCount
                                val addedAccessories = newAccessoriesCount - existingAccessoriesCount

                                val message = buildString {
                                    append(
                                        context.getString(
                                            R.string.main_import_plan_result,
                                            importedWorkoutPlanPackage.name
                                        )
                                    )
                                    append(
                                        context.getString(
                                            R.string.main_import_plan_result_workouts,
                                            addedWorkouts
                                        )
                                    )
                                    if (addedEquipment > 0) {
                                        append(
                                            context.getString(
                                                R.string.main_import_plan_result_equipment,
                                                addedEquipment
                                            )
                                        )
                                    }
                                    if (addedAccessories > 0) {
                                        append(
                                            context.getString(
                                                R.string.main_import_plan_result_accessories,
                                                addedAccessories
                                            )
                                        )
                                    }
                                    if (importedMovementCount > 0) {
                                        append(
                                            context.getString(
                                                R.string.main_import_plan_result_movements,
                                                importedMovementCount
                                            )
                                        )
                                    }
                                }

                                importPlanResultMessage = message
                            } catch (e: Exception) {
                                Toast.makeText(
                                    context,
                                    e.toMainActivityToastMessage(
                                        intro = context.getString(R.string.main_import_plan_error),
                                        fallbackDetail = context.getString(R.string.main_please_try_again)
                                    ),
                                    Toast.LENGTH_SHORT
                                ).show()
                            }
                        }
                    }
                } catch (e: Exception) {
                    Toast.makeText(
                        context,
                        e.toMainActivityToastMessage(
                            intro = context.getString(R.string.main_read_file_error),
                            fallbackDetail = context.getString(R.string.main_choose_another_file)
                        ),
                        Toast.LENGTH_SHORT
                    ).show()
                }
            }
        }

    importPlanResultMessage?.let { message ->
        StandardDialog(
            onDismissRequest = { importPlanResultMessage = null },
            title = context.getString(R.string.main_plan_imported_title),
            body = { Text(message) },
            confirmText = context.getString(R.string.common_ok),
            onConfirm = { importPlanResultMessage = null },
            showDismiss = false
        )
    }

    pendingHistoryImport?.let { pending ->
        StandardDialog(
            onDismissRequest = { if (!isImportingHistory) pendingHistoryImport = null },
            title = context.getString(R.string.main_import_history_title),
            body = {
                val dateFormatter = DateTimeFormatter.ofLocalizedDate(FormatStyle.MEDIUM)
                    .withLocale(Locale.getDefault())
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text(pending.targetProfileName, style = MaterialTheme.typography.titleMedium)
                    Text(
                        context.getString(
                            R.string.main_import_history_sessions_sets,
                            pending.payload.workoutHistories.size,
                            pending.payload.setHistories.size
                        )
                    )
                    pending.payload.workoutHistories.forEach { history ->
                        val workout = appViewModel.workouts.firstOrNull {
                            it.id == history.workoutId && it.globalId == history.globalId
                        }
                        val duration = history.knownDurationSecondsOrNull()
                            ?.takeIf { it > 0 }
                        Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                            Text(
                                workout?.let {
                                    if (it.recurringSessionId != null) {
                                        "${recurringPrescriptionDisplayLabel(it, context.getString(R.string.prescription))} · ${it.name}"
                                    } else {
                                        it.name
                                    }
                                } ?: context.getString(R.string.main_workout_fallback),
                                style = MaterialTheme.typography.bodyLarge,
                            )
                            Text(
                                buildString {
                                    append(history.date.format(dateFormatter))
                                    duration?.let {
                                        append(
                                            context.getString(
                                                R.string.main_import_history_duration,
                                                formatTime(it)
                                            )
                                        )
                                    }
                                },
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }
            },
            confirmText = if (isImportingHistory) {
                context.getString(R.string.main_importing)
            } else {
                context.getString(R.string.main_import_history_title)
            },
            onConfirm = {
                if (!isImportingHistory) {
                    isImportingHistory = true
                    scope.launch {
                        try {
                            val activeProfileId = Profiles.activeProfileId(context)
                            require(activeProfileId == pending.targetProfileId) {
                                context.getString(R.string.main_import_history_profile_changed)
                            }
                            val store = withContext(Dispatchers.IO) {
                                WorkoutStoreRepository(
                                    Profiles.directory(context, pending.targetProfileId),
                                    context.filesDir,
                                ).getWorkoutStore()
                            }
                            WorkoutHistoryImportService.validate(
                                store,
                                pending.targetProfileId,
                                pending.payload,
                            )
                            val result = WorkoutHistoryImportService.append(
                                context,
                                store,
                                pending.targetProfileId,
                                pending.payload,
                            )
                            appViewModel.loadWorkoutHistories(appViewModel.workouts)
                            pendingHistoryImport = null
                            Toast.makeText(
                                context,
                                context.getString(
                                    R.string.main_import_history_result,
                                    result.insertedHistories,
                                    result.insertedSets
                                ),
                                Toast.LENGTH_LONG
                            ).show()
                        } catch (e: Exception) {
                            Toast.makeText(
                                context,
                                e.toMainActivityToastMessage(
                                    intro = context.getString(R.string.main_import_history_error),
                                    fallbackDetail = context.getString(R.string.main_review_profile_and_file)
                                ),
                                Toast.LENGTH_LONG
                            ).show()
                        } finally {
                            isImportingHistory = false
                        }
                    }
                }
            },
            dismissText = context.getString(R.string.common_cancel),
            onDismissButton = { if (!isImportingHistory) pendingHistoryImport = null },
            confirmEnabled = !isImportingHistory,
        )
    }

    workoutStoreValidationError?.let { validationError ->
        StandardDialog(
            onDismissRequest = { appViewModel.clearWorkoutStoreValidationError() },
            title = context.getString(R.string.main_workout_data_error_title),
            body = { Text(validationError.toUserFacingMessage(context)) },
            confirmText = context.getString(R.string.common_ok),
            onConfirm = { appViewModel.clearWorkoutStoreValidationError() },
            showDismiss = false
        )
    }

    /**
     * Helper function to restore from an AppBackup.
     * This function handles all the database operations and view model updates.
     */
    /**
     * Restores one profile's backup into [profileId].
     *
     * A full-backup restore calls this once per profile with [skipProfileIdentityCheck] and
     * [applyToViewModels] false, and [persistSharedContent] false because the union shared store
     * was already written once. This single path keeps owning all the row validation.
     */
    suspend fun restoreFromAppBackup(
        appBackup: AppBackup,
        context: Context,
        appViewModel: AppViewModel,
        workoutViewModel: WorkoutViewModel,
        profileId: String,
        healthConnectClient: HealthConnectClient,
        skipProfileIdentityCheck: Boolean = false,
        applyToViewModels: Boolean = true,
        persistSharedContent: Boolean = true,
        successToastMessage: String? = null
    ): Boolean {
        return withContext(Dispatchers.IO + NonCancellable) {
            val db = AppDatabase.getDatabase(context, profileId)
            val workoutHistoryDao = db.workoutHistoryDao()
            val setHistoryDao = db.setHistoryDao()
            val restHistoryDao = db.restHistoryDao()
            val exerciseInfoDao = db.exerciseInfoDao()
            val workoutScheduleDao = db.workoutScheduleDao()
            val workoutRecordDao = db.workoutRecordDao()
            val workoutStoreRepository =
                if (profileId == Profiles.activeProfileId(context)) {
                    WorkoutStoreRepository.forActiveProfile(context)
                } else {
                    WorkoutStoreRepository(Profiles.directory(context, profileId), context.filesDir)
                }
            try {
                // A restore replaces the whole store, so pouring another profile's backup into
                // the active one would take over its history and body metrics. Refuse only when
                // that owner still exists here — after a reinstall the id is gone and the data
                // belongs to whoever is restoring it.
                val activeProfileId = Profiles.activeProfileId(context)
                val backupProfileId = appBackup.ProfileId
                if (!skipProfileIdentityCheck && backupProfileId != null && backupProfileId != activeProfileId) {
                    val localProfiles = Profiles.profiles(context)
                    val owner = localProfiles.firstOrNull { it.id == backupProfileId }
                        ?: appBackup.ProfileName?.let { name ->
                            localProfiles.firstOrNull { it.name.equals(name, ignoreCase = true) }
                        }
                    if (owner != null) {
                        Log.w(
                            "BackupRestore",
                            "Refusing to restore ${owner.name}'s backup while $activeProfileId is active"
                        )
                        withContext(Dispatchers.Main) {
                            Toast.makeText(
                                context,
                                context.getString(
                                    R.string.main_backup_belongs_to_profile,
                                    owner.name
                                ),
                                Toast.LENGTH_LONG
                            ).show()
                        }
                        return@withContext false
                    }
                    Log.i(
                        "BackupRestore",
                        "Restoring ${appBackup.ProfileName ?: backupProfileId} into $activeProfileId " +
                            "(that profile does not exist on this device)"
                    )
                }

                // A restore replaces the shared library for every profile on this device, so keep
                // the previous copy before it is overwritten.
                runCatching {
                    val sharedStore = File(context.filesDir, "workout_store.json")
                    if (sharedStore.exists()) {
                        sharedStore.copyTo(
                            File(context.filesDir, "workout_store.json.pre-restore"),
                            overwrite = true,
                        )
                    }
                }

                // Keep every backup workout: an inactive template can still own schedules,
                // records or a legacy "Unassigned" membership that must be converted, not dropped.
                val newWorkoutStore = appBackup.restoredWorkoutStore()
                val restoredWorkouts = newWorkoutStore.workouts
                restoreExerciseMovementBackups(
                    context = context,
                    movementBackups = appBackup.ExerciseMovements.orEmpty()
                )
                requireExerciseMovementPayloads(context, newWorkoutStore)

                // Migrate and validate before deleting any rows: a rejected backup must leave the
                // current histories in place instead of producing a partial restore.
                val planMigratedWorkoutStore =
                    workoutStoreRepository.migrateWorkoutStore(newWorkoutStore)
                validateWorkoutStoreForRuntimeUse(planMigratedWorkoutStore)

                val deleteAndInsertJob = coroutineScope {
                async {
                    try {
                        val BATCH_SIZE = 80
                        var allWorkoutHistories = workoutHistoryDao.getAllWorkoutHistories()

                        try {
                            deleteWorkoutHistoriesFromHealthConnect(
                                context,
                                allWorkoutHistories,
                                healthConnectClient
                            )
                        } catch (e: Exception) {
                            withContext(Dispatchers.Main) {
                                Toast.makeText(
                                    context,
                                    context.getString(R.string.main_remove_existing_history_error),
                                    Toast.LENGTH_SHORT
                                ).show()
                            }
                        }

                        workoutHistoryDao.deleteAll()
                        setHistoryDao.deleteAll()
                        restHistoryDao.deleteAll()
                        exerciseInfoDao.deleteAll()
                        workoutScheduleDao.deleteAll()
                        workoutRecordDao.deleteAll()
                        db.exerciseSessionProgressionDao().deleteAll()
                        db.errorLogDao().deleteAll()

                        val validWorkoutHistories =
                            appBackup.WorkoutHistories.filter { workoutHistory ->
                                restoredWorkouts.any { workout -> workout.id == workoutHistory.workoutId }
                            }

                        validWorkoutHistories.chunked(BATCH_SIZE).forEach { chunk ->
                            workoutHistoryDao.insertAll(*chunk.toTypedArray())
                        }

                        val validSetHistories = sanitizeRestPlacementInSetHistoriesByWorkoutAndExercise(
                            appBackup.SetHistories.filter { setHistory ->
                                validWorkoutHistories.any { workoutHistory -> workoutHistory.id == setHistory.workoutHistoryId }
                            }
                        )

                        validSetHistories.chunked(BATCH_SIZE).forEach { chunk ->
                            setHistoryDao.insertAll(*chunk.toTypedArray())
                        }

                        val validRestHistories = (appBackup.RestHistories ?: emptyList()).filter { rest ->
                            rest.workoutHistoryId != null &&
                                validWorkoutHistories.any { wh -> wh.id == rest.workoutHistoryId }
                        }
                        validRestHistories.chunked(BATCH_SIZE).forEach { chunk ->
                            restHistoryDao.insertAll(*chunk.toTypedArray())
                        }

                        val allExercises = restoredWorkouts.flatMap { workout ->
                            workout.workoutComponents.filterIsInstance<Exercise>() + workout.workoutComponents.filterIsInstance<Superset>()
                                .flatMap { it.exercises }
                        }

                        val validExerciseInfos = appBackup.ExerciseInfos.filter { allExercises.any { exercise -> exercise.id == it.id } }

                        validExerciseInfos.chunked(BATCH_SIZE).forEach { chunk ->
                            exerciseInfoDao.insertAll(*chunk.toTypedArray())
                        }

                        val validWorkoutSchedules = appBackup.WorkoutSchedules.filter { restoredWorkouts.any { workout -> workout.globalId == it.workoutId } }

                        validWorkoutSchedules.chunked(BATCH_SIZE).forEach { chunk ->
                            workoutScheduleDao.insertAll(*chunk.toTypedArray())
                        }

                        val validWorkoutRecords =
                            appBackup.WorkoutRecords.filter { restoredWorkouts.any { workout -> workout.id == it.workoutId } }

                        validWorkoutRecords.chunked(BATCH_SIZE).forEach { chunk ->
                            workoutRecordDao.insertAll(*chunk.toTypedArray())
                        }

                        val validExerciseSessionProgressions =
                            appBackup.ExerciseSessionProgressions.filter { progression ->
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
                return@withContext false
            } catch (e: Exception) {
                Log.e("MainActivity", "Error awaiting restore job: ${e.javaClass.simpleName}. " +
                        "Message: ${e.message}, " +
                        "Cause: ${e.cause?.javaClass?.simpleName ?: "none"}, " +
                        "Stack trace:\n${Log.getStackTraceString(e)}", e)
                false
            }

            if (restoreSuccess) {
                if (applyToViewModels) applyInsightsSettingsFromBackup(appBackup, context)

                // Backfill ExerciseSessionProgression entries for workouts that don't have them but should
                /*backfillExerciseSessionProgressions(
                    workoutStore = newWorkoutStore,
                    workoutHistoryDao = workoutHistoryDao,
                    setHistoryDao = setHistoryDao,
                    exerciseInfoDao = exerciseInfoDao,
                    exerciseSessionProgressionDao = db.exerciseSessionProgressionDao(),
                    db = db
                )*/

                // Persist the validated, migration-applied store. A full-backup restore has
                // already written the union shared library, so it writes this profile's personal
                // half only and cannot drop another profile's workouts.
                try {
                    if (persistSharedContent) {
                        workoutStoreRepository.saveWorkoutStore(planMigratedWorkoutStore)
                    } else {
                        workoutStoreRepository.savePersonalSettings(planMigratedWorkoutStore)
                    }

                    if (applyToViewModels) {
                        withContext(Dispatchers.Main) {
                            appViewModel.updateWorkoutStore(
                                planMigratedWorkoutStore,
                                repairPlanOnlyMembership = true,
                            )
                            workoutViewModel.updateWorkoutStore(planMigratedWorkoutStore)
                            appViewModel.triggerUpdate()

                            // Show the success toast after all operations are complete
                            Toast.makeText(
                                context,
                                successToastMessage
                                    ?: context.getString(R.string.main_backup_restored),
                                Toast.LENGTH_SHORT
                            ).show()
                        }
                        // Persist the restored state and enqueue the normal non-blocking sync path.
                        // Only an explicit user action should opt into the blocking manual-sync UI.
                        appViewModel.flushWorkoutSave(context)
                        PhoneToWatchSyncCoordinator.onPhoneDataPersisted(context)
                    }
                    true
                } catch (e: Exception) {
                    Log.e("MainActivity", "Error during restore migration: ${e.javaClass.simpleName}. " +
                            "Message: ${e.message}, " +
                            "Cause: ${e.cause?.javaClass?.simpleName ?: "none"}, " +
                            "Stack trace:\n${Log.getStackTraceString(e)}", e)
                    withContext(Dispatchers.Main) {
                        Toast.makeText(
                            context,
                            e.toMainActivityToastMessage(
                                intro = context.getString(R.string.main_restore_migration_partial_error),
                                fallbackDetail = context.getString(R.string.main_review_data_try_again)
                            ),
                            Toast.LENGTH_LONG
                        ).show()
                    }
                    false
                }
            } else {
                withContext(Dispatchers.Main) {
                    Toast.makeText(
                        context,
                        context.getString(R.string.main_restore_history_error),
                        Toast.LENGTH_SHORT
                    ).show()
                }
                false
            }
            } catch (e: CancellationException) {
                // Job was cancelled (e.g., activity destroyed) - this is expected
                Log.d("MainActivity", "Restore operation cancelled (likely activity destroyed): ${e.message}")
                false
            } catch (e: Exception) {
                Log.e("MainActivity", "Error during restore: ${e.javaClass.simpleName}. " +
                        "Message: ${e.message}, " +
                        "Cause: ${e.cause?.javaClass?.simpleName ?: "none"}, " +
                        "Stack trace:\n${Log.getStackTraceString(e)}", e)
                withContext(Dispatchers.Main) {
                    Toast.makeText(
                        context,
                        e.toMainActivityToastMessage(
                            intro = context.getString(R.string.main_restore_backup_error),
                            fallbackDetail = context.getString(R.string.main_choose_valid_backup)
                        ),
                        Toast.LENGTH_LONG
                    ).show()
                }
                false
            }
        }
    }

    /**
     * Rebuilds the whole install from a full backup: shared content once, every profile with its
     * own history, then device-wide settings and sensor recordings. Profiles that are not in the
     * file are removed, so this must only run from an explicit user action.
     */
    suspend fun restoreFullBackup(
        fullBackup: FullBackup,
        context: Context,
        appViewModel: AppViewModel,
        workoutViewModel: WorkoutViewModel,
        healthConnectClient: HealthConnectClient,
    ): Boolean = withContext(Dispatchers.IO + NonCancellable) {
        if (fullBackup.profiles.isEmpty()) return@withContext false

        // Shared content and payloads first: every profile below is restored on top of them.
        // This is the only write of the union shared library; each profile then saves just its
        // personal half, so a profile has no way to overwrite another profile's workouts.
        // Use the conservative repair because this is imported backup data: legacy one-sided
        // plan membership must survive until the repository sees and reconciles it. The
        // authoritative conversion is reserved for explicit user moves/deletes.
        val restoredSharedStore = fullBackup.sharedStoreForRestore()
        writeSharedStore(context, restoredSharedStore)
        restoreFullBackupPayloads(context, fullBackup)

        var allRestored = true
        fullBackup.profiles.forEach { profileBackup ->
            Profiles.ensureProfile(context, profileBackup.profileId, profileBackup.profileName)
            val merged = restoredSharedStore
                .mergedWithPersonalSettingsOf(profileBackup.backup.WorkoutStore)
            val restored = restoreFromAppBackup(
                appBackup = profileBackup.backup.copy(WorkoutStore = merged),
                context = context,
                appViewModel = appViewModel,
                workoutViewModel = workoutViewModel,
                profileId = profileBackup.profileId,
                healthConnectClient = healthConnectClient,
                skipProfileIdentityCheck = true,
                applyToViewModels = false,
                persistSharedContent = false,
                successToastMessage = "",
            )
            if (!restored) allRestored = false
        }
        if (!allRestored) return@withContext false

        // Deletions last: a failure above leaves the previous profiles untouched.
        val keptIds = fullBackup.profiles.map { it.profileId }.toSet()
        val targetActiveProfileId = fullBackup.activeProfileId
            ?.takeIf { it in keptIds }
            ?: keptIds.first()
        Profiles.setActiveProfile(context, targetActiveProfileId)
        Profiles.profiles(context)
            .filter { it.id !in keptIds }
            .forEach { Profiles.delete(context, it.id) }

        restoreFullBackupSettings(context, fullBackup.settings)
        true
    }

    fun resolveStartupRestoreGate() {
        deferHealthPermissionPrompt = false
    }

    LaunchedEffect(initialDataLoaded) {
        if (!initialDataLoaded) return@LaunchedEffect

        // Only the default profile offers the startup restore prompt: switching profile restarts
        // the app, and a Downloads backup belongs to whichever profile wrote it.
        if (Profiles.activeProfileId(context) != Profiles.DEFAULT_PROFILE_ID) {
            resolveStartupRestoreGate()
            return@LaunchedEffect
        }

        val suffix = activeProfileBackupSuffix(context)
        val prefs = context.getSharedPreferences("startup_restore", Context.MODE_PRIVATE)
        val alreadyChecked = prefs.getBoolean("auto_restore_checked$suffix", false)
        if (alreadyChecked) {
            resolveStartupRestoreGate()
            return@LaunchedEffect
        }

        // Only this profile's own metrics count as "already set up": the shared library is the
        // same for everyone, so keying off it would skip restoring a brand-new profile.
        val hasCurrentData = appViewModel.workoutStore.let { store ->
            store.birthDateYear != 0 || store.weightKg > 0.0
        }

        if (hasCurrentData) {
            prefs.edit { putBoolean("auto_restore_checked$suffix", true) }
            resolveStartupRestoreGate()
            return@LaunchedEffect
        }

        val appBackup = loadLatestBackupFromDownloads(context)
        if (appBackup == null) {
            val alreadyPrompted = prefs.getBoolean("restore_picker_prompt_shown$suffix", false)
            if (!alreadyPrompted) {
                prefs.edit { putBoolean("restore_picker_prompt_shown$suffix", true) }
                showStartupRestorePickerPrompt = true
            } else {
                resolveStartupRestoreGate()
            }
            return@LaunchedEffect
        }

        val restored = restoreFromAppBackup(
            appBackup = appBackup,
            context = context,
            appViewModel = appViewModel,
            workoutViewModel = workoutViewModel,
            profileId = Profiles.activeProfileId(context),
            healthConnectClient = healthConnectClient,
            successToastMessage = context.getString(R.string.main_backup_restored_auto)
        )
        if (restored) {
            prefs.edit { putBoolean("auto_restore_checked", true) }
        }
        resolveStartupRestoreGate()
    }

    val jsonPickerLauncher =
        rememberLauncherForActivityResult(contract = ActivityResultContracts.OpenDocument()) { uri: Uri? ->
            val selectedUri = uri ?: run {
                resolveStartupRestoreGate()
                return@rememberLauncherForActivityResult
            }
            if (isRestoringBackup) return@rememberLauncherForActivityResult

            // Use restoreScope so restore completes even if activity is destroyed/recreated (e.g. rotation).
            val restoreScope = (context as? MainActivity)?.restoreScope ?: lifecycleOwner.lifecycleScope
            restoreScope.launch {
                isRestoringBackup = true
                try {
                    val content = withContext(Dispatchers.IO) {
                        context.contentResolver.openInputStream(selectedUri)?.use { inputStream ->
                            inputStream.bufferedReader().readText()
                        }
                    } ?: throw IllegalStateException(
                        context.getString(R.string.main_open_selected_file_error)
                    )

                    // Validate file type before attempting to parse.
                    val fileType = detectBackupFileType(content)
                    when (fileType) {
                        BackupFileType.WORKOUT_PLAN_PACKAGE -> {
                            withContext(Dispatchers.Main) {
                                Toast.makeText(
                                    context,
                                    context.getString(R.string.main_file_is_plan_package),
                                    Toast.LENGTH_LONG
                                ).show()
                            }
                            return@launch
                        }

                        BackupFileType.WORKOUT_STORE -> {
                            withContext(Dispatchers.Main) {
                                Toast.makeText(
                                    context,
                                    context.getString(R.string.main_file_is_workout_export_not_backup),
                                    Toast.LENGTH_LONG
                                ).show()
                            }
                            return@launch
                        }

                        BackupFileType.EXERCISE_LIBRARY_PACKAGE -> {
                            withContext(Dispatchers.Main) {
                                Toast.makeText(
                                    context,
                                    context.getString(R.string.main_file_is_exercise_library),
                                    Toast.LENGTH_LONG
                                ).show()
                            }
                            return@launch
                        }

                        BackupFileType.UNKNOWN -> {
                            withContext(Dispatchers.Main) {
                                Toast.makeText(
                                    context,
                                    context.getString(R.string.main_file_not_valid_backup),
                                    Toast.LENGTH_LONG
                                ).show()
                            }
                            return@launch
                        }

                        BackupFileType.APP_BACKUP,
                        BackupFileType.INCREMENTAL_APP_BACKUP -> {
                            // File type is valid, proceed with restore.
                        }

                        BackupFileType.FULL_BACKUP -> {
                            // Valid; handled below, since it rebuilds every profile.
                        }
                    }

                    setAutomaticRestoreDocumentUri(context, selectedUri)

                    if (fileType == BackupFileType.FULL_BACKUP) {
                        val fullBackup = withContext(Dispatchers.IO) {
                            fromJSONToFullBackup(content)
                        }
                        val restored = restoreFullBackup(
                            fullBackup = fullBackup,
                            context = context,
                            appViewModel = appViewModel,
                            workoutViewModel = workoutViewModel,
                            healthConnectClient = healthConnectClient,
                        )
                        if (restored) {
                            // Profiles, databases and preferences all changed under the running
                            // app, so relaunch instead of patching live state.
                            withContext(Dispatchers.Main) {
                                Toast.makeText(
                                    context,
                                    context.getString(R.string.main_backup_restored_restarting),
                                    Toast.LENGTH_SHORT
                                ).show()
                                val relaunch = Intent(context, MainActivity::class.java)
                                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
                                context.startActivity(relaunch)
                            }
                        } else {
                            withContext(Dispatchers.Main) {
                                Toast.makeText(
                                    context,
                                    context.getString(R.string.main_restore_backup_error),
                                    Toast.LENGTH_LONG
                                ).show()
                            }
                        }
                        return@launch
                    }

                    val appBackup = fromBackupJsonToAppBackup(content)

                    restoreFromAppBackup(
                        appBackup = appBackup,
                        context = context,
                        appViewModel = appViewModel,
                        workoutViewModel = workoutViewModel,
                        profileId = Profiles.activeProfileId(context),
                        healthConnectClient = healthConnectClient
                    )
                } catch (e: CancellationException) {
                    // Job was cancelled (e.g., activity destroyed) - this is expected.
                } catch (e: Exception) {
                    withContext(Dispatchers.Main) {
                        Toast.makeText(
                            context,
                            e.toMainActivityToastMessage(
                                intro = context.getString(R.string.main_restore_backup_error),
                                fallbackDetail = context.getString(R.string.main_choose_valid_backup)
                            ),
                            Toast.LENGTH_LONG
                        ).show()
                    }
                } finally {
                    isRestoringBackup = false
                    resolveStartupRestoreGate()
                }
            }
        }

    if (showStartupRestorePickerPrompt) {
        StandardDialog(
            onDismissRequest = {
                showStartupRestorePickerPrompt = false
                resolveStartupRestoreGate()
            },
            title = context.getString(R.string.main_restore_backup_prompt_title),
            body = {
                Text(
                    text = context.getString(R.string.main_restore_backup_prompt_body),
                    style = MaterialTheme.typography.bodyLarge,
                )
            },
            confirmText = context.getString(R.string.main_choose_file),
            onConfirm = {
                showStartupRestorePickerPrompt = false
                jsonPickerLauncher.launch(arrayOf("application/json"))
            },
            dismissText = context.getString(R.string.main_not_now),
            onDismissButton = {
                showStartupRestorePickerPrompt = false
                resolveStartupRestoreGate()
            }
        )
    }

    var configuredLiteRtModelPath by remember {
        mutableStateOf(LiteRtLmModelStore.getConfiguredModelPath(context))
    }
    var configuredLiteRtModelName by remember {
        mutableStateOf(LiteRtLmModelStore.getConfiguredModelName(context))
    }
    var mobileLlmEnabled by remember(insightsSettingsRestoredStamp) {
        mutableStateOf(WorkoutInsightsSettingsStore.isEnabled(context))
    }
    var workoutInsightsMode by remember(insightsSettingsRestoredStamp) {
        mutableStateOf(WorkoutInsightsSettingsStore.getMode(context))
    }
    var liteRtBackendPreference by remember {
        mutableStateOf(LiteRtLmModelStore.getBackendPreference(context))
    }
    var remoteInsightsConfig by remember(insightsSettingsRestoredStamp) {
        mutableStateOf(WorkoutInsightsSettingsStore.getRemoteConfig(context))
    }
    var workoutInsightsCustomInstructions by remember(insightsSettingsRestoredStamp) {
        mutableStateOf(WorkoutInsightsSettingsStore.getCustomInstructions(context))
    }
    var isImportingLiteRtModel by remember { mutableStateOf(false) }

    val liteRtModelPickerLauncher =
        rememberLauncherForActivityResult(contract = ActivityResultContracts.OpenDocument()) { uri: Uri? ->
            uri ?: return@rememberLauncherForActivityResult
            if (isImportingLiteRtModel) return@rememberLauncherForActivityResult
            scope.launch {
                isImportingLiteRtModel = true
                try {
                    val importedName = withContext(Dispatchers.IO) {
                        LiteRtLmModelStore.importModel(context, uri)
                    }
                    configuredLiteRtModelPath = LiteRtLmModelStore.getConfiguredModelPath(context)
                    configuredLiteRtModelName = LiteRtLmModelStore.getConfiguredModelName(context)
                    Toast.makeText(
                        context,
                        context.getString(R.string.main_model_imported, importedName),
                        Toast.LENGTH_SHORT
                    ).show()
                } catch (e: Exception) {
                    Toast.makeText(
                        context,
                        e.message ?: context.getString(R.string.main_model_import_error),
                        Toast.LENGTH_SHORT
                    ).show()
                } finally {
                    isImportingLiteRtModel = false
                }
            }
        }

    var showBackupKindDialog by remember { mutableStateOf(false) }
    var backupForGenerator by remember { mutableStateOf(false) }

    val backupSaveLauncher =
        rememberLauncherForActivityResult(contract = ActivityResultContracts.CreateDocument("application/json")) { uri: Uri? ->
            uri?.let {
                scope.launch {
                    try {
                        withContext(Dispatchers.IO) {
                            val nothingToBackUp: suspend () -> Unit = {
                                withContext(Dispatchers.Main) {
                                    Toast.makeText(
                                        context,
                                        context.getString(R.string.main_nothing_to_backup),
                                        Toast.LENGTH_SHORT
                                    ).show()
                                }
                            }

                            val jsonString = if (backupForGenerator) {
                                // Single profile in the legacy AppBackup shape the workout
                                // generator reads: shared library + this profile's history.
                                val appBackup = createAppBackup(
                                    appViewModel.workoutStore,
                                    db,
                                    context,
                                )
                                if (appBackup == null) {
                                    nothingToBackUp()
                                    return@withContext
                                }
                                fromAppBackupToJSONPrettyPrint(appBackup)
                            } else {
                                val fullBackup = createFullBackup(context)
                                if (fullBackup == null) {
                                    nothingToBackUp()
                                    return@withContext
                                }
                                fromFullBackupToJSON(fullBackup)
                            }
                            context.contentResolver.openOutputStream(it)?.use { outputStream ->
                                outputStream.write(jsonString.toByteArray())
                            }
                        }
                        Toast.makeText(context, context.getString(R.string.main_backup_saved), Toast.LENGTH_SHORT).show()
                    } catch (e: Exception) {
                        e.printStackTrace()
                        Toast.makeText(
                            context,
                            e.toMainActivityToastMessage(
                                intro = context.getString(R.string.main_save_backup_error),
                                fallbackDetail = context.getString(R.string.main_please_try_again)
                            ),
                            Toast.LENGTH_LONG
                        ).show()
                    }
                }
            }
        }



    if (showBackupKindDialog) {
        StandardDialog(
            onDismissRequest = { showBackupKindDialog = false },
            title = context.getString(R.string.main_save_backup_title),
            body = {
                Column {
                    ContentSubtitle(context.getString(R.string.main_whole_device_backup_desc))
                    AppPrimaryOutlinedButton(
                        text = context.getString(R.string.main_whole_device_backup),
                        onClick = {
                            showBackupKindDialog = false
                            backupForGenerator = false
                            backupSaveLauncher.launch(buildWorkoutStoreBackupFileName("_full"))
                        },
                        modifier = Modifier.fillMaxWidth()
                    )
                    ContentSubtitle(
                        text = context.getString(R.string.main_generator_backup_desc),
                        modifier = Modifier.padding(top = Spacing.sm)
                    )
                    AppPrimaryOutlinedButton(
                        text = context.getString(
                            R.string.main_generator_backup,
                            Profiles.activeProfile(context).name
                        ),
                        onClick = {
                            showBackupKindDialog = false
                            backupForGenerator = true
                            backupSaveLauncher.launch(
                                buildWorkoutStoreBackupFileName(
                                    "_generator" + activeProfileNameFileSuffix(context)
                                )
                            )
                        },
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            },
            showConfirm = false,
            showDismiss = false,
        )
    }

    val syncWithWatch = {
        scope.launch {
            appViewModel.flushWorkoutSave(context)
            val syncStarted = PhoneToWatchSyncCoordinator.requestManualSyncToWatch(context)
            if (!syncStarted) {
                Toast.makeText(
                    context,
                    context.getString(R.string.main_wear_not_installed),
                    Toast.LENGTH_SHORT
                ).show()
            }
        }
    }

    // Collect workouts once at the parent level to avoid recomposition cascades inside AnimatedContent
    val workoutsForNavigation by appViewModel.workoutsFlow.collectAsState()
    val resolveWorkoutForExerciseScreen = remember(workoutsForNavigation) {
        { workoutId: java.util.UUID, exerciseId: java.util.UUID ->
            val requestedWorkout = workoutsForNavigation.find { it.id == workoutId }
            if (requestedWorkout == null) {
                null
            } else {
                val workoutCandidates = buildList {
                    addAll(
                        workoutsForNavigation.filter {
                            it.globalId == requestedWorkout.globalId && it.isActive
                        }
                    )
                    add(requestedWorkout)
                    addAll(
                        workoutsForNavigation.filter {
                            it.id != requestedWorkout.id &&
                                it.globalId == requestedWorkout.globalId &&
                                !it.isActive
                        }
                    )
                }.distinctBy { it.id }

                workoutCandidates.firstOrNull {
                    findWorkoutComponentByIdInWorkout(it, exerciseId) is Exercise
                } ?: requestedWorkout
            }
        }
    }
    val saveableStateHolder = rememberSaveableStateHolder()
    val isInitialDataLoaded by appViewModel.isInitialDataLoaded.collectAsState()

    if (!isInitialDataLoaded || isRestoringBackup) {
        LoadingScreen()
    } else {
        CompositionLocalProvider(
            LocalBreadcrumbContent provides { NavigationBreadcrumbs(appViewModel) }
        ) {
            Box(modifier = Modifier.fillMaxSize()) {
                AnimatedContent(
                modifier = Modifier
                    .fillMaxSize()
                    .background(MaterialTheme.colorScheme.background),
                targetState = appViewModel.currentScreenData,
            // Keep AnimatedContent's notion of screen identity aligned with SaveableStateHolder.
            // Equivalent ScreenData instances can be new objects, but they must not register
            // duplicate saveable-state buckets while both old/new content are composed.
            contentKey = { screen -> screen.screenIdentityKey() },
            transitionSpec = {
                // Use instant transition to eliminate black screen during fade
                EnterTransition.None togetherWith ExitTransition.None
            }, label = ""
        ) { currentScreen ->
            saveableStateHolder.SaveableStateProvider(currentScreen.screenIdentityKey()) {
                when (currentScreen) {
                    is ScreenData.Workouts, is ScreenData.SessionPrescriptions -> {
                        val focusedRecurringSessionId =
                            (currentScreen as? ScreenData.SessionPrescriptions)?.sessionId
                        WorkoutsScreen(
                            appViewModel,
                            workoutHistoryDao,
                            setHistoryDao,
                            workoutScheduleDao,
                            healthConnectClient,
                            isSyncing = isSyncing,
                            syncPhase = manualSyncUiState?.phase,
                            syncProgress = manualSyncUiState?.progress,
                            isExportingWorkoutDataForLlm = isExportingWorkoutDataForLlm,
                            workoutDataExportStatus = workoutDataExportStatus,
                            onSyncClick = {
                                syncWithWatch()
                            },
                            onCancelSync = {
                                PhoneToWatchSyncCoordinator.cancelManualSyncToWatch(context)
                            },
                            onOpenSettingsClick = {
                                appViewModel.setScreenData(ScreenData.Settings())
                            },
                            onBackupClick = { showBackupKindDialog = true },
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
                                    context.getString(R.string.main_workout_export_saved),
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
                                            e.toMainActivityToastMessage(
                                                intro = context.getString(R.string.main_export_plan_error),
                                                fallbackDetail = context.getString(R.string.main_please_try_again)
                                            ),
                                            Toast.LENGTH_SHORT
                                        ).show()
                                    }
                                }
                            },
                            onExportWorkoutDataForLlm = { exportRange: WorkoutDataExportRange ->
                                scope.launch {
                                    workoutDataExportStatus = context.getString(
                                        R.string.main_export_preparing,
                                        exportRange.label.lowercase(Locale.getDefault())
                                    )
                                    isExportingWorkoutDataForLlm = true
                                    yield()
                                    try {
                                        withContext(Dispatchers.IO) {
                                            exportAllWorkoutDataToMarkdown(
                                                context = context,
                                                workoutHistoryDao = workoutHistoryDao,
                                                setHistoryDao = setHistoryDao,
                                                restHistoryDao = restHistoryDao,
                                                exerciseSessionProgressionDao = exerciseSessionProgressionDao,
                                                workoutStore = appViewModel.workoutStore,
                                                exportRange = exportRange,
                                                onProgress = { status ->
                                                    withContext(Dispatchers.Main) {
                                                        workoutDataExportStatus = status
                                                    }
                                                }
                                            )
                                        }
                                    } catch (e: Exception) {
                                        Toast.makeText(
                                            context,
                                            e.toMainActivityToastMessage(
                                                intro = context.getString(R.string.main_export_data_error),
                                                fallbackDetail = context.getString(R.string.main_please_try_again)
                                            ),
                                            Toast.LENGTH_SHORT
                                        ).show()
                                    } finally {
                                        isExportingWorkoutDataForLlm = false
                                        workoutDataExportStatus =
                                            context.getString(R.string.main_exporting_workout_data)
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
                                            context.getString(
                                                R.string.main_equipment_export_saved,
                                                filename
                                            ),
                                            Toast.LENGTH_SHORT
                                        ).show()
                                    } catch (e: Exception) {
                                        Toast.makeText(
                                            context,
                                            e.toMainActivityToastMessage(
                                                intro = context.getString(R.string.main_export_equipment_error),
                                                fallbackDetail = context.getString(R.string.main_please_try_again)
                                            ),
                                            Toast.LENGTH_SHORT
                                        ).show()
                                    }
                                }
                            },
                            onClearAllHistories = {
                                scope.launch {
                                    withContext(Dispatchers.IO) {
                                        try {
                                            val allWorkoutHistories =
                                                workoutHistoryDao.getAllWorkoutHistories()
                                            deleteWorkoutHistoriesFromHealthConnect(
                                                context,
                                                allWorkoutHistories,
                                                healthConnectClient
                                            )
                                        } catch (e: Exception) {
                                            Toast.makeText(
                                                context,
                                                context.getString(R.string.main_remove_history_error),
                                                Toast.LENGTH_SHORT
                                            ).show()
                                        }

                                        workoutHistoryDao.deleteAll()
                                        setHistoryDao.deleteAll()
                                    }
                                    Toast.makeText(
                                        context,
                                        context.getString(R.string.main_history_cleared),
                                        Toast.LENGTH_SHORT
                                    )
                                        .show()

                                    appViewModel.updateWorkoutStore(
                                        workoutStoreRepository.getWorkoutStore(),
                                        repairPlanOnlyMembership = true,
                                    )
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
                                                context = context,
                                                healthConnectClient = healthConnectClient,
                                                workouts = appViewModel.workouts,
                                                workoutHistoryDao = workoutHistoryDao,
                                                updateAll = true,
                                                age = age,
                                                weightKg = weight,
                                                female = appViewModel.workoutStore.sex,
                                                vo2MaxMlKgMin = appViewModel.workoutStore.estimatedVo2MaxMlKgMin
                                            )
                                        }
                                        Toast.makeText(
                                            context,
                                            context.getString(R.string.main_synced_health_connect),
                                            Toast.LENGTH_SHORT
                                        ).show()
                                    } catch (e: Exception) {
                                        Toast.makeText(
                                            context,
                                            context.getString(R.string.main_sync_health_connect_error),
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
                                        context.getString(R.string.main_exercise_info_cleared),
                                        Toast.LENGTH_SHORT
                                    ).show()
                                }
                            },
                            onViewErrorLogs = {
                                appViewModel.setScreenData(ScreenData.ErrorLogs())
                            },
                            onViewSensorSessions = {
                                appViewModel.setScreenData(ScreenData.SensorSessions())
                            },
                            selectedTabIndex = appViewModel.selectedHomeTab,
                            focusedRecurringSessionId = focusedRecurringSessionId,
                        )
                    }

                    is ScreenData.Plans -> {
                        PlansScreen(appViewModel)
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
                                        Toast.makeText(
                                            context,
                                            context.getString(R.string.main_settings_saved),
                                            Toast.LENGTH_SHORT
                                        )
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
                            mobileLlmEnabled = mobileLlmEnabled,
                            workoutInsightsMode = workoutInsightsMode,
                            liteRtModelPath = configuredLiteRtModelPath,
                            liteRtModelName = configuredLiteRtModelName,
                            liteRtBackendPreference = liteRtBackendPreference,
                            remoteInsightsConfig = remoteInsightsConfig,
                            workoutInsightsCustomInstructions = workoutInsightsCustomInstructions,
                            onImportLiteRtModel = {
                                liteRtModelPickerLauncher.launch(LiteRtLmModelStore.pickerMimeTypes)
                            },
                            onSaveInsightsSettings = { enabled, mode, backendPreference, remoteConfig, customInstructions ->
                                WorkoutInsightsSettingsStore.setEnabled(context, enabled)
                                WorkoutInsightsSettingsStore.setMode(context, mode)
                                LiteRtLmModelStore.setBackendPreference(context, backendPreference)
                                WorkoutInsightsSettingsStore.setRemoteConfig(context, remoteConfig)
                                WorkoutInsightsSettingsStore.setCustomInstructions(context, customInstructions)
                                mobileLlmEnabled = enabled
                                workoutInsightsMode = mode
                                liteRtBackendPreference = backendPreference
                                remoteInsightsConfig = remoteConfig
                                workoutInsightsCustomInstructions = customInstructions.trim()
                            },
                            onClearLiteRtModel = {
                                LiteRtLmModelStore.clearConfiguredModel(context)
                                configuredLiteRtModelPath = null
                                configuredLiteRtModelName = null
                                Toast.makeText(
                                    context,
                                    context.getString(R.string.main_model_cleared),
                                    Toast.LENGTH_SHORT
                                )
                                    .show()
                            },
                            isSaving = isSaving,
                            isImportingLiteRtModel = isImportingLiteRtModel
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

                    is ScreenData.SensorSessions -> {
                        SensorSessionsScreen(
                            syncDao = db.motionCaptureSyncDao(),
                            onBack = {
                                scope.launch {
                                    appViewModel.flushWorkoutSave(
                                        context,
                                        workoutStoreRepository,
                                        db
                                    )
                                    appViewModel.goBack()
                                }
                            },
                            onOpenSession = { sessionId ->
                                appViewModel.setScreenData(ScreenData.SensorSessionDetail(sessionId))
                            }
                        )
                    }

                    is ScreenData.SensorSessionDetail -> {
                        val sessionDetailData = currentScreen
                        SensorSessionDetailScreen(
                            sessionId = sessionDetailData.sessionId,
                            sessionDao = db.motionCaptureSessionDao(),
                            syncDao = db.motionCaptureSyncDao(),
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
                        val screenData = currentScreen
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
                                            val errorMessage = formatScheduleConflictMessage(
                                                context,
                                                conflicts,
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
                            availableExternalHeartRateSources = appViewModel.workoutStore.externalHeartRateConfigs
                                .map { it.source }
                                .toSet(),
                        )
                    }

                    is ScreenData.EditWorkout -> {
                        val screenData = currentScreen
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
                                            val errorMessage = formatScheduleConflictMessage(
                                                context,
                                                conflicts,
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
                            existingSchedules = existingSchedules,
                            availableExternalHeartRateSources = appViewModel.workoutStore.externalHeartRateConfigs
                                .map { it.source }
                                .toSet(),
                        )
                    }

                    is ScreenData.WorkoutDetail -> {
                        val screenData = currentScreen
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
                                healthConnectClient,
                                workoutViewModel,
                                workoutHistoryDao,
                                workoutRecordDao,
                                setHistoryDao,
                                restHistoryDao,
                                exerciseSessionProgressionDao,
                                exerciseInfoDao,
                                workoutScheduleDao,
                                selectedWorkout,
                                initialSelectedTabIndex = screenData.selectedTabIndex,
                                initialWorkoutHistoryId = screenData.workoutHistoryId,
                                onClearAllIncompleteSessions = clearAllIncompleteSessions
                            ) {
                                appViewModel.goBack()
                            }
                        }

                    }

                    is ScreenData.WorkoutHistory -> {
                        val screenData = currentScreen
                        val workouts by appViewModel.workoutsFlow.collectAsState()
                        val selectedWorkout = workouts.find { it.id == screenData.workoutId }!!

                        WorkoutDetailScreen(
                            appViewModel = appViewModel,
                            healthConnectClient = healthConnectClient,
                            workoutViewModel = workoutViewModel,
                            workoutHistoryDao = workoutHistoryDao,
                            workoutRecordDao = workoutRecordDao,
                            setHistoryDao = setHistoryDao,
                            restHistoryDao = restHistoryDao,
                            exerciseSessionProgressionDao = exerciseSessionProgressionDao,
                            exerciseInfoDao = exerciseInfoDao,
                            workoutScheduleDao = workoutScheduleDao,
                            workout = selectedWorkout,
                            initialSelectedTabIndex = screenData.selectedTabIndex,
                            initialWorkoutHistoryId = screenData.workoutHistoryId,
                            onClearAllIncompleteSessions = clearAllIncompleteSessions
                        ) {
                            appViewModel.goBack()
                        }
                    }

                    is ScreenData.ExternalWorkoutSession -> {
                        ExternalWorkoutSessionDetailScreen(
                            appViewModel = appViewModel,
                            sessionId = currentScreen.externalSessionId,
                        ) {
                            appViewModel.goBack()
                        }
                    }

                    is ScreenData.ExerciseDetail -> {
                        val screenData = currentScreen
                        val selectedWorkout = resolveWorkoutForExerciseScreen(
                            screenData.workoutId,
                            screenData.selectedExerciseId
                        )
                        if (selectedWorkout == null) {
                            LaunchedEffect(screenData.workoutId) { appViewModel.goBack() }
                        } else {
                            val selectedExercise = findWorkoutComponentByIdInWorkout(
                                selectedWorkout,
                                screenData.selectedExerciseId
                            ) as? Exercise

                            if (selectedExercise == null) {
                                LaunchedEffect(
                                    screenData.workoutId,
                                    screenData.selectedExerciseId
                                ) {
                                    appViewModel.goBack()
                                }
                            } else {
                                ExerciseDetailScreen(
                                    appViewModel,
                                    selectedWorkout,
                                    workoutHistoryDao,
                                    setHistoryDao,
                                    restHistoryDao,
                                    selectedExercise,
                                    initialSelectedTabIndex = screenData.selectedTabIndex,
                                    initialWorkoutHistoryId = screenData.workoutHistoryId,
                                ) {
                                    appViewModel.goBack()
                                }
                            }
                        }
                    }

                    is ScreenData.ExerciseHistory -> {
                        val screenData = currentScreen
                        val selectedWorkout = resolveWorkoutForExerciseScreen(
                            screenData.workoutId,
                            screenData.selectedExerciseId
                        )
                        if (selectedWorkout == null) {
                            LaunchedEffect(screenData.workoutId) { appViewModel.goBack() }
                        } else {
                            val selectedExercise = findWorkoutComponentByIdInWorkout(
                                selectedWorkout,
                                screenData.selectedExerciseId
                            ) as? Exercise

                            if (selectedExercise == null) {
                                LaunchedEffect(
                                    screenData.workoutId,
                                    screenData.selectedExerciseId
                                ) {
                                    appViewModel.goBack()
                                }
                            } else {
                                ExerciseDetailScreen(
                                    appViewModel = appViewModel,
                                    workout = selectedWorkout,
                                    workoutHistoryDao = workoutHistoryDao,
                                    setHistoryDao = setHistoryDao,
                                    restHistoryDao = restHistoryDao,
                                    exercise = selectedExercise,
                                    initialSelectedTabIndex = screenData.selectedTabIndex +
                                        if (selectedExercise.movementRef == null) 1 else 2,
                                    initialWorkoutHistoryId = screenData.workoutHistoryId,
                                ) {
                                    appViewModel.goBack()
                                }
                            }
                        }
                    }

                    is ScreenData.HistoryChatExercise -> {
                        if (!MobileLlmFeatureFlags.isEnabled(context)) {
                            LaunchedEffect(currentScreen) {
                                appViewModel.goBack()
                            }
                            LoadingScreen()
                        } else {
                            val screenData = currentScreen
                            HistoryChatScreen(
                                mode = HistoryChatScreenMode.Exercise(
                                    workoutId = screenData.workoutId,
                                    exerciseId = screenData.exerciseId,
                                ),
                                appViewModel = appViewModel,
                                workoutHistoryDao = workoutHistoryDao,
                                workoutRecordDao = workoutRecordDao,
                                setHistoryDao = setHistoryDao,
                                restHistoryDao = restHistoryDao,
                                exerciseSessionProgressionDao = exerciseSessionProgressionDao,
                                onGoBack = { appViewModel.goBack() },
                            )
                        }
                    }

                    is ScreenData.HistoryChatWorkoutSession -> {
                        if (!MobileLlmFeatureFlags.isEnabled(context)) {
                            LaunchedEffect(currentScreen) {
                                appViewModel.goBack()
                            }
                            LoadingScreen()
                        } else {
                            val screenData = currentScreen
                            HistoryChatScreen(
                                mode = HistoryChatScreenMode.WorkoutSession(
                                    workoutId = screenData.workoutId,
                                    workoutHistoryId = screenData.workoutHistoryId,
                                ),
                                appViewModel = appViewModel,
                                workoutHistoryDao = workoutHistoryDao,
                                workoutRecordDao = workoutRecordDao,
                                setHistoryDao = setHistoryDao,
                                restHistoryDao = restHistoryDao,
                                exerciseSessionProgressionDao = exerciseSessionProgressionDao,
                                onGoBack = { appViewModel.goBack() },
                            )
                        }
                    }

                    is ScreenData.NewExercise -> {
                        val screenData = currentScreen
                        val workouts by appViewModel.workoutsFlow.collectAsState()

                        if (screenData.exerciseDefinitionId == null && !screenData.skipLibrary) {
                            ExerciseLibraryPickerScreen(
                                definitions = appViewModel.workoutStore.exerciseDefinitions,
                                equipments = appViewModel.workoutStore.equipments +
                                    appViewModel.workoutStore.accessoryEquipments,
                                onSelect = { definition ->
                                    appViewModel.setScreenData(
                                        ScreenData.NewExercise(screenData.workoutId, definition.id)
                                    )
                                },
                                onCreate = {
                                    appViewModel.setScreenData(
                                        ScreenData.NewExercise(screenData.workoutId, skipLibrary = true)
                                    )
                                },
                                onCancel = { appViewModel.goBack() },
                            )
                            return@SaveableStateProvider
                        }

                        val selectedDefinition = screenData.exerciseDefinitionId?.let { definitionId ->
                            appViewModel.workoutStore.exerciseDefinitions.firstOrNull { it.id == definitionId }
                        }
                        val definitionTemplate = selectedDefinition?.let { definition ->
                            Exercise(
                                id = java.util.UUID.randomUUID(), enabled = true,
                                name = definition.name, notes = "", sets = emptyList(),
                                exerciseType = definition.exerciseType, minReps = 0, maxReps = 0,
                                lowerBoundMaxHRPercent = null, upperBoundMaxHRPercent = null,
                                equipmentId = definition.equipmentId,
                                bodyWeightPercentage = definition.bodyWeightPercentage,
                                muscleGroups = definition.muscleGroups,
                                secondaryMuscleGroups = definition.secondaryMuscleGroups,
                                requiredAccessoryEquipmentIds = definition.requiredAccessoryEquipmentIds,
                                exerciseCategory = definition.exerciseCategory,
                                movementRef = definition.movementRef,
                                exerciseDefinitionId = definition.id,
                                placementNotes = "",
                            )
                        }

                        var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!
                        var currentWorkout = selectedWorkout

                        while (!currentWorkout.isActive) {
                            val nextWorkout =
                                workouts.find { it.id == currentWorkout.nextVersionId }!!
                            currentWorkout = nextWorkout
                        }

                        selectedWorkout = currentWorkout
                        val recurringFamily = selectedWorkout.recurringSessionId?.let { sessionId ->
                            workouts.filter { it.isActive && it.recurringSessionId == sessionId }
                        }.orEmpty()

                        var isSaving by remember { mutableStateOf(false) }
                        ExerciseForm(
                            appViewModel,
                            onExerciseUpsert = { newExercise, recurringEdit ->
                                if (isSaving) return@ExerciseForm
                                isSaving = true
                                scope.launch {
                                    try {
                                        val definition = selectedDefinition ?: ExerciseDefinition(
                                            id = java.util.UUID.randomUUID(),
                                            exerciseFamilyId = null,
                                            name = newExercise.name,
                                            exerciseType = newExercise.exerciseType,
                                            equipmentId = newExercise.equipmentId,
                                            bodyWeightPercentage = newExercise.bodyWeightPercentage,
                                            muscleGroups = newExercise.muscleGroups,
                                            secondaryMuscleGroups = newExercise.secondaryMuscleGroups,
                                            requiredAccessoryEquipmentIds = newExercise.requiredAccessoryEquipmentIds,
                                            exerciseCategory = newExercise.exerciseCategory,
                                            movementRef = newExercise.movementRef,
                                        )
                                        val linkedExercise = newExercise.materializeDefinition(
                                            selectedDefinition ?: definition,
                                        )
                                        val safeExercise = sanitizeRecurringTrackMetadata(
                                            exercise = linkedExercise,
                                            originalExercise = null,
                                            isRecurringWorkout = selectedWorkout.recurringSessionId != null,
                                            family = recurringFamily,
                                        )
                                        val trackedExercise = try {
                                            applyRecurringExerciseEdit(safeExercise, recurringEdit, recurringFamily)
                                        } catch (_: IllegalArgumentException) {
                                            Toast.makeText(
                                                context,
                                                context.getString(R.string.main_weight_slot_incompatible),
                                                Toast.LENGTH_LONG,
                                            ).show()
                                            return@launch
                                        }
                                        val hasHistory = withContext(Dispatchers.IO) {
                                            workoutHistoryDao.workoutHistoryExistsByWorkoutId(
                                                selectedWorkout.id
                                            )
                                        }
                                        if (selectedDefinition == null) {
                                            appViewModel.addExerciseDefinition(definition)
                                        }
                                        val storedDefinition = appViewModel.workoutStore.exerciseDefinitions
                                            .firstOrNull { it.id == definition.id }
                                            ?: definition
                                        val resolvedTrackedExercise = trackedExercise.materializeDefinition(storedDefinition)
                                        appViewModel.addWorkoutComponentVersioned(
                                            selectedWorkout,
                                            resolvedTrackedExercise,
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
                            exercise = definitionTemplate,
                            isNewPrescription = true,
                            recurringWorkout = selectedWorkout.takeIf { it.recurringSessionId != null },
                            recurringFamily = recurringFamily,
                            isSaving = isSaving
                        )
                    }

                    is ScreenData.NewExerciseDefinition -> {
                        ExerciseDefinitionForm(
                            definition = null,
                            equipments = appViewModel.workoutStore.equipments,
                            accessories = appViewModel.workoutStore.accessoryEquipments,
                            isReferenced = false,
                            onSave = { definition ->
                                appViewModel.addExerciseDefinition(definition)
                                appViewModel.scheduleWorkoutSave(context)
                                appViewModel.goBack()
                            },
                            onCancel = { appViewModel.goBack() },
                            breadcrumbContent = {
                                NavigationBreadcrumbs(
                                    appViewModel = appViewModel,
                                    showOnDefinitionEditor = true,
                                )
                            },
                        )
                    }

                    is ScreenData.EditExerciseDefinition -> {
                        val definition = appViewModel.workoutStore.exerciseDefinitions
                            .firstOrNull { it.id == currentScreen.exerciseDefinitionId }
                        if (definition == null) {
                            LaunchedEffect(currentScreen.exerciseDefinitionId) {
                                appViewModel.goBack()
                            }
                        } else {
                            val isReferenced = appViewModel.workoutStore.allExercisePrescriptions()
                                .any { it.exerciseDefinitionId == definition.id }
                            ExerciseDefinitionForm(
                                definition = definition,
                                equipments = appViewModel.workoutStore.equipments,
                                accessories = appViewModel.workoutStore.accessoryEquipments,
                                isReferenced = isReferenced,
                                onSave = { updatedDefinition ->
                                    appViewModel.updateExerciseDefinition(updatedDefinition)
                                    appViewModel.scheduleWorkoutSave(context)
                                    appViewModel.goBack()
                                },
                                onCancel = { appViewModel.goBack() },
                                breadcrumbContent = {
                                    NavigationBreadcrumbs(
                                        appViewModel = appViewModel,
                                        showOnDefinitionEditor = true,
                                    )
                                },
                            )
                        }
                    }

                    is ScreenData.NewSuperset -> {
                        val screenData = currentScreen
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
                            viewModel = appViewModel,
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
                        val screenData = currentScreen
                        val workouts by appViewModel.workoutsFlow.collectAsState()

                        var selectedWorkout = workouts.find { it.id == screenData.workoutId }!!

                        var currentWorkout = selectedWorkout

                        while (!currentWorkout.isActive) {
                            val nextWorkout =
                                workouts.find { it.id == currentWorkout.nextVersionId }!!
                            currentWorkout = nextWorkout
                        }

                        selectedWorkout = currentWorkout
                        val recurringFamily = selectedWorkout.recurringSessionId?.let { sessionId ->
                            workouts.filter { it.isActive && it.recurringSessionId == sessionId }
                        }.orEmpty()

                        val selectedExercise = findWorkoutComponentByIdInWorkout(
                            selectedWorkout,
                            screenData.selectedExerciseId
                        ) as? Exercise

                        if (selectedExercise == null) {
                            LaunchedEffect(
                                screenData.workoutId,
                                screenData.selectedExerciseId
                            ) {
                                appViewModel.goBack()
                            }
                        } else {
                            var isSaving by remember { mutableStateOf(false) }
                            ExerciseForm(
                                appViewModel,
                                onExerciseUpsert = { updatedExercise, recurringEdit ->
                                    if (isSaving) return@ExerciseForm
                                    isSaving = true
                                    scope.launch {
                                        try {
                                            val hasHistory = withContext(Dispatchers.IO) {
                                                workoutHistoryDao.workoutHistoryExistsByWorkoutId(
                                                    selectedWorkout.id
                                                )
                                            }
                                            val sourceDefinitionId = selectedExercise.exerciseDefinitionId
                                            val resolution = sourceDefinitionId?.let { definitionId ->
                                                appViewModel.workoutStore.resolveExerciseVariation(
                                                    sourceDefinitionId = definitionId,
                                                    candidate = updatedExercise,
                                                )
                                            }
                                            val resolvedExercise = if (resolution != null) {
                                                val materialized = updatedExercise.materializeDefinition(
                                                    resolution.definition,
                                                )
                                                if (
                                                    hasHistory &&
                                                    resolution.definition.id != sourceDefinitionId
                                                ) {
                                                    materialized.duplicatePrescription()
                                                } else {
                                                    materialized
                                                }
                                            } else {
                                                updatedExercise
                                            }
                                            val safeExercise = sanitizeRecurringTrackMetadata(
                                                exercise = resolvedExercise,
                                                originalExercise = selectedExercise,
                                                isRecurringWorkout = selectedWorkout.recurringSessionId != null,
                                                family = recurringFamily,
                                            )
                                            val trackedExercise = try {
                                                applyRecurringExerciseEdit(safeExercise, recurringEdit, recurringFamily)
                                            } catch (_: IllegalArgumentException) {
                                                Toast.makeText(
                                                    context,
                                                    context.getString(R.string.main_weight_slot_incompatible),
                                                    Toast.LENGTH_LONG,
                                                ).show()
                                                return@launch
                                            }
                                            resolution?.let { appViewModel.updateWorkoutStore(it.workoutStore) }
                                            appViewModel.updateWorkoutComponentVersioned(
                                                selectedWorkout,
                                                selectedExercise,
                                                trackedExercise,
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
                                recurringWorkout = selectedWorkout.takeIf { it.recurringSessionId != null },
                                recurringFamily = recurringFamily,
                                isSaving = isSaving
                            )
                        }
                    }

                    is ScreenData.EditSuperset -> {
                        val screenData = currentScreen
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
                        ) as? Superset

                        if (selectedSuperset == null) {
                            LaunchedEffect(
                                screenData.workoutId,
                                screenData.selectedSupersetId
                            ) {
                                appViewModel.goBack()
                            }
                        } else {
                            var isSaving by remember { mutableStateOf(false) }
                            SupersetForm(
                                viewModel = appViewModel,
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
                                onExerciseSettingsClick = { exercise ->
                                    appViewModel.setScreenData(
                                        ScreenData.EditExercise(
                                            workoutId = selectedWorkout.id,
                                            selectedExerciseId = exercise.id
                                        )
                                    )
                                },
                                isSaving = isSaving
                            )
                        }
                    }

                    is ScreenData.NewSet -> {
                        val screenData = currentScreen
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
                        ) as? Exercise
                        if (parentExercise == null) {
                            LaunchedEffect(
                                screenData.workoutId,
                                screenData.parentExerciseId
                            ) {
                                appViewModel.goBack()
                            }
                        } else {
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
                    }

                    is ScreenData.NewRestSet -> {
                        val screenData = currentScreen
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
                        ) as? Exercise
                        if (parentExercise == null) {
                            LaunchedEffect(
                                screenData.workoutId,
                                screenData.parentExerciseId
                            ) {
                                appViewModel.goBack()
                            }
                        } else {
                            var isSaving by remember { mutableStateOf(false) }
                            RestSetForm(
                                appliesSameRestBetweenAllSets = true,
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
                    }

                    is ScreenData.EditRestSet -> {
                        val screenData = currentScreen
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
                        ) as? Exercise
                        if (parentExercise == null) {
                            LaunchedEffect(
                                screenData.workoutId,
                                screenData.parentExerciseId
                            ) {
                                appViewModel.goBack()
                            }
                        } else {
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
                    }

                    is ScreenData.NewRest -> {
                        val screenData = currentScreen
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
                            appliesSameRestBetweenAllExercises = true,
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
                        val screenData = currentScreen
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
                        val screenData = currentScreen
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
                        ) as? Exercise

                        if (parentExercise == null) {
                            LaunchedEffect(
                                screenData.workoutId,
                                screenData.exerciseId
                            ) {
                                appViewModel.goBack()
                            }
                        } else {
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
                    }

                    is ScreenData.InsertRestAfter -> {
                        val screenData = currentScreen
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
                        val screenData = currentScreen
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
                        ) as? Exercise
                        if (parentExercise == null) {
                            LaunchedEffect(
                                screenData.workoutId,
                                screenData.parentExerciseId
                            ) {
                                appViewModel.goBack()
                            }
                        } else {
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

                            EquipmentType.CARDIO_MACHINE -> CardioMachineForm(onUpsert = { new ->
                                appViewModel.updateEquipments(equipments + new)
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
                        val screenData = currentScreen
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

                            EquipmentType.CARDIO_MACHINE -> {
                                val selectedCardioMachine =
                                    equipments.find { it.id == screenData.equipmentId } as CardioMachine
                                CardioMachineForm(
                                    onUpsert = { updatedCardioMachine ->
                                        appViewModel.updateEquipments(
                                            equipments.map { equipment ->
                                                if (equipment.id == selectedCardioMachine.id) {
                                                    updatedCardioMachine
                                                } else {
                                                    equipment
                                                }
                                            }
                                        )
                                        appViewModel.goBack()
                                    },
                                    onCancel = { appViewModel.goBack() },
                                    cardioMachine = selectedCardioMachine,
                                )
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

            }
            SyncStatusBadge(
                visible = isSyncingToWatch && !isSyncing,
                modifier = Modifier
                    .align(Alignment.TopCenter)
                    .zIndex(2f),
            )
            }
        }
    }
}
