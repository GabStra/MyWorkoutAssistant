package com.gabstra.myworkoutassistant.screens

import com.gabstra.myworkoutassistant.composables.BreadcrumbScaffold
import com.gabstra.myworkoutassistant.utils.sync.WatchConnectionMonitor

import androidx.activity.compose.BackHandler
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.platform.testTag
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import android.app.Activity
import android.content.Context
import android.content.Intent
import com.gabstra.myworkoutassistant.MainActivity
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material.icons.filled.Watch
import androidx.compose.material3.TopAppBar
import androidx.compose.material.icons.filled.Watch
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.lifecycle.viewModelScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.composables.AccessoriesBottomBar
import com.gabstra.myworkoutassistant.composables.EquipmentsBottomBar
import com.gabstra.myworkoutassistant.composables.LoadingOverlay
import com.gabstra.myworkoutassistant.composables.rememberDebouncedSavingVisible
import com.gabstra.myworkoutassistant.composables.MoveWorkoutDialog
import com.gabstra.myworkoutassistant.composables.RecurringSessionDialog
import com.gabstra.myworkoutassistant.composables.StandardFilterDropdown
import com.gabstra.myworkoutassistant.composables.StandardFilterDropdownItem
import com.gabstra.myworkoutassistant.composables.WorkoutPlanNameDialog
import com.gabstra.myworkoutassistant.composables.WorkoutsBottomBar
import com.gabstra.myworkoutassistant.composables.WorkoutsMenu
import com.gabstra.myworkoutassistant.composables.SwipeableTabs
import com.gabstra.myworkoutassistant.composables.rememberMinimumLoadingVisibility
import com.gabstra.myworkoutassistant.getEndOfWeek
import com.gabstra.myworkoutassistant.getStartOfWeek
import com.gabstra.myworkoutassistant.healthconnect.external.ExternalHealthConnectSessionDatabase
import com.gabstra.myworkoutassistant.healthconnect.external.ExternalHealthConnectSessionEntity
import com.gabstra.myworkoutassistant.healthconnect.external.ExternalHealthConnectSessionSyncService
import com.gabstra.myworkoutassistant.shared.DarkGray
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutManager
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import com.gabstra.myworkoutassistant.shared.RecurringWorkoutAuthoring
import com.gabstra.myworkoutassistant.shared.WeeklyProgressResolver
import com.gabstra.myworkoutassistant.shared.WeeklyProgressSnapshot
import com.gabstra.myworkoutassistant.shared.validateWorkoutStoreForRuntimeUse
import com.gabstra.myworkoutassistant.shared.fromJSONToExerciseLibraryPackage
import com.gabstra.myworkoutassistant.shared.normalizedForImport
import com.gabstra.myworkoutassistant.shared.motion.restoreExerciseMovementBackups
import com.gabstra.myworkoutassistant.shared.motion.requireExerciseMovementPayloads
import com.gabstra.myworkoutassistant.shared.profile.Profiles
import com.gabstra.myworkoutassistant.shared.datalayer.SyncPhase
import com.gabstra.myworkoutassistant.shared.equipments.AccessoryEquipment
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.export.WorkoutDataExportRange
import com.kizitonwose.calendar.compose.CalendarState
import com.kizitonwose.calendar.core.CalendarDay
import com.kizitonwose.calendar.core.DayPosition
import com.kizitonwose.calendar.core.yearMonth
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDate
import android.util.Log
import android.widget.Toast
import java.util.UUID

private const val TAG = "WorkoutHistDebug"

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WorkoutsScreen(
    appViewModel: AppViewModel,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    workoutScheduleDao: com.gabstra.myworkoutassistant.shared.WorkoutScheduleDao,
    healthConnectClient: HealthConnectClient,
    isSyncing: Boolean = false,
    syncPhase: SyncPhase? = null,
    syncProgress: Float? = null,
    isExportingWorkoutDataForLlm: Boolean = false,
    workoutDataExportStatus: String = "",
    onSyncClick: () -> Unit,
    onCancelSync: () -> Unit,
    onBackupClick: () -> Unit,
    onRestoreClick: () -> Unit,
    onImportWorkoutsClick: () -> Unit,
    onOpenSettingsClick: () -> Unit,
    onClearAllHistories: () -> Unit,
    onSyncToHealthConnectClick: () -> Unit,
    onExportWorkouts: () -> Unit,
    onExportWorkoutPlan: () -> Unit,
    onExportWorkoutDataForLlm: (WorkoutDataExportRange) -> Unit,
    onExportEquipment: () -> Unit,
    onClearAllExerciseInfo: () -> Unit,
    onViewErrorLogs: () -> Unit,
    onViewSensorSessions: () -> Unit,
    selectedTabIndex: Int,
    focusedRecurringSessionId: UUID? = null,
) {
    val animatedSyncProgress by animateFloatAsState(
        targetValue = syncProgress ?: 0f,
        animationSpec = tween(durationMillis = 100),
        label = "Wear-acknowledged sync progress"
    )
    val watchReachable by WatchConnectionMonitor.watchReachable.collectAsState()
    val updateMessage by appViewModel.updateNotificationFlow.collectAsState(initial = null)
    val context = LocalContext.current
    // Profile names come from a disk-backed index; resolve them once per screen entry and
    // only when the install actually has several profiles.
    val profilesForSwitcher = remember(context) {
        Profiles.profiles(context).takeIf { it.size > 1 }.orEmpty()
    }
    val activeProfileId = remember(context) { Profiles.activeProfileId(context) }
    val activeProfileName = remember(context) {
        profilesForSwitcher.firstOrNull { it.id == activeProfileId }?.name
    }
    var profileMenuExpanded by remember { mutableStateOf(false) }
    val workoutInProgress = remember(context) {
        context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
            .getBoolean("isWorkoutInProgress", false)
    }
    val externalSessionDatabase = remember(context) {
        ExternalHealthConnectSessionDatabase.getDatabase(context)
    }
    val externalSessions by externalSessionDatabase
        .externalHealthConnectSessionDao()
        .observeAllSessions()
        .collectAsState(initial = emptyList())

    // Health Connect sessions belong to the profile that owns Health Connect; other profiles
    // must not see them in the calendar.
    val showsExternalSessions = remember(context) { Profiles.isHealthConnectProfile(context) }
    val visibleExternalSessions =
        if (showsExternalSessions) externalSessions else emptyList<ExternalHealthConnectSessionEntity>()

    var isDaySelectionLoading by remember { mutableStateOf(false) }
    var hasInitializedSelectedDate by remember { mutableStateOf(false) }

    val workouts by appViewModel.workoutsFlow.collectAsState()
    val workoutStore by appViewModel.workoutStoreFlow.collectAsState()
    val focusedSessionWorkout = remember(workouts, focusedRecurringSessionId) {
        focusedRecurringSessionId?.let { sessionId ->
            workouts.firstOrNull { it.isActive && it.recurringSessionId == sessionId }
        }
    }

    val equipments by appViewModel.equipmentsFlow.collectAsState()
    val accessories by appViewModel.accessoryEquipmentsFlow.collectAsState()

    // Group workouts by plan - keep reactive to workoutStore updates
    val allPlans by appViewModel.workoutPlansFlow.collectAsState()
    val weeklyProgressOverrides by appViewModel.weeklyProgressOverridesFlow.collectAsState()

    // Filter state - use ViewModel state to persist across navigation
    val selectedPlanFilter by appViewModel.effectiveSelectedWorkoutPlanIdFlow.collectAsState()

    // Filter workouts by selected plan
    // getWorkoutsByPlan(null) also depends on which plan IDs currently exist, because orphaned
    // plan IDs are shown in the "No plan" bucket.
    val filteredWorkouts = remember(
        workouts,
        allPlans,
        selectedPlanFilter,
        focusedRecurringSessionId,
    ) {
        if (focusedRecurringSessionId != null) {
            workouts.filter { it.isActive && it.recurringSessionId == focusedRecurringSessionId }
        } else {
            appViewModel.getWorkoutsByPlan(selectedPlanFilter)
        }
    }

    val enabledWorkouts = remember(filteredWorkouts) {
        filteredWorkouts.filter { it.enabled }
    }

    val activeAndEnabledWorkouts = remember(filteredWorkouts) {
        filteredWorkouts.filter { it.enabled && it.isActive }.sortedBy { it.order }
    }

    // Status tab always uses all workouts across plans.
    val allEnabledWorkouts = remember(workouts) {
        workouts.filter { it.enabled }
    }

    val allActiveAndEnabledWorkouts = remember(workouts) {
        workouts.filter { it.enabled && it.isActive }.sortedBy { it.order }
    }

    val activeWorkouts = remember(filteredWorkouts) {
        filteredWorkouts.filter { it.isActive }.sortedBy { it.order }
    }

    var hideDisabledWorkouts by rememberSaveable { mutableStateOf(true) }
    val visibleActiveWorkouts = remember(
        activeWorkouts,
        activeAndEnabledWorkouts,
        hideDisabledWorkouts
    ) {
        if (hideDisabledWorkouts) activeAndEnabledWorkouts else activeWorkouts
    }
    val disabledActiveWorkoutCount = remember(activeWorkouts) {
        activeWorkouts.count { !it.enabled }
    }

    val workoutsByPlan = remember(activeWorkouts, allPlans, selectedPlanFilter) {
        val grouped = mutableMapOf<WorkoutPlan?, MutableList<Workout>>()

        // If a plan is selected, only show that plan's workouts
        if (selectedPlanFilter != null) {
            val selectedPlan = allPlans.find { it.id == selectedPlanFilter }
            if (selectedPlan != null) {
                grouped[selectedPlan] =
                    activeWorkouts.filter { it.workoutPlanId == selectedPlanFilter }.toMutableList()
            }
        } else {
            // Initialize with all plans
            allPlans.forEach { plan ->
                grouped[plan] = mutableListOf()
            }
            // Add unassigned group
            grouped[null] = mutableListOf()

            // Group workouts
            activeWorkouts.forEach { workout ->
                val plan = workout.workoutPlanId?.let { planId ->
                    allPlans.find { it.id == planId }
                }
                grouped[plan]?.add(workout)
            }
        }

        // Sort workouts within each plan by order
        grouped.values.forEach { workoutList ->
            workoutList.sortBy { it.order }
        }

        // Return sorted by plan order, with unassigned at the end
        grouped.toList().sortedBy { (plan, _) ->
            plan?.order ?: Int.MAX_VALUE
        }
    }

    val timesCompletedInAWeekObjective =
        allEnabledWorkouts.filter { it.timesCompletedInAWeek != null && it.timesCompletedInAWeek != 0 }
            .associate { workout ->
                workout.id to (workout.timesCompletedInAWeek ?: 0)
            }

    val hasObjectives = timesCompletedInAWeekObjective.values.any { it > 0 }

    var selectedWorkouts by remember { mutableStateOf(listOf<Workout>()) }
    var isWorkoutSelectionModeActive by remember { mutableStateOf(false) }
    var recurringFamilyToManage by remember { mutableStateOf<List<Workout>?>(null) }
    val selectedRecurringSessionId = selectedWorkouts.firstOrNull()?.recurringSessionId
        ?.takeIf { sessionId -> selectedWorkouts.all { it.recurringSessionId == sessionId } }

    fun selectWorkoutPlan(planId: UUID?) {
        selectedWorkouts = emptyList()
        isWorkoutSelectionModeActive = false
        appViewModel.setSelectedWorkoutPlanId(planId)
    }

    val selectionVisibleIds = remember(visibleActiveWorkouts, activeWorkouts, focusedRecurringSessionId) {
        if (focusedRecurringSessionId != null) {
            activeWorkouts.asSequence()
                .filter { it.recurringSessionId == focusedRecurringSessionId }
                .map { it.id }
                .toSet()
        } else {
            visibleActiveWorkouts.asSequence().flatMap { visible ->
                if (visible.recurringSessionId == null) {
                    sequenceOf(visible.id)
                } else {
                    activeWorkouts.asSequence()
                        .filter { it.recurringSessionId == visible.recurringSessionId }
                        .map { it.id }
                }
            }.toSet()
        }
    }

    LaunchedEffect(selectionVisibleIds) {
        val visibleIds = selectionVisibleIds
        val visibleSelection = selectedWorkouts.filter { it.id in visibleIds }
        if (visibleSelection.size != selectedWorkouts.size) {
            selectedWorkouts = visibleSelection
            if (visibleSelection.isEmpty()) {
                isWorkoutSelectionModeActive = false
            }
        }
    }

    var selectedEquipments by remember { mutableStateOf(listOf<WeightLoadedEquipment>()) }
    var isEquipmentSelectionModeActive by remember { mutableStateOf(false) }

    var selectedAccessories by remember { mutableStateOf(listOf<AccessoryEquipment>()) }
    var isAccessorySelectionModeActive by remember { mutableStateOf(false) }

    var showMoveWorkoutDialog by remember { mutableStateOf(false) }
    var moveWorkoutError by remember { mutableStateOf<String?>(null) }
    var showCreateNewPlanDialog by remember { mutableStateOf(false) }
    var createPlanError by remember { mutableStateOf<String?>(null) }
    val planSaveError = stringResource(R.string.loc_plan_error_save)
    val movePlanUnavailableError = stringResource(R.string.loc_workout_plan_move_unavailable)

    var selectedWeekAnchorDate by remember {
        mutableStateOf<LocalDate>(LocalDate.now())
    }

    val groupedWorkoutsHistories by appViewModel.groupedWorkoutHistories.collectAsState(initial = null)
    val workoutHistorySessionStatuses by appViewModel.workoutHistorySessionStatuses.collectAsState(
        initial = null
    )
    val workoutById by appViewModel.workoutByIdForHistories.collectAsState(initial = null)
    val isHistoryStateReady =
        groupedWorkoutsHistories != null &&
            workoutHistorySessionStatuses != null &&
            workoutById != null
    val isLoading = !isHistoryStateReady || isDaySelectionLoading

    val selectedWeekStart = remember(selectedWeekAnchorDate) { getStartOfWeek(selectedWeekAnchorDate) }
    val selectedWeekEnd = remember(selectedWeekAnchorDate) { getEndOfWeek(selectedWeekAnchorDate) }

    fun computeWeekObjectiveSnapshot(weekStart: LocalDate): WeeklyProgressSnapshot {
        if (allEnabledWorkouts.isEmpty()) {
            return WeeklyProgressSnapshot()
        }

        val endOfWeek = getEndOfWeek(weekStart)
        val workoutHistoriesInWeek = generateSequence(weekStart) { current ->
            current.plusDays(1).takeIf { !it.isAfter(endOfWeek) }
        }
            .flatMap { date ->
                groupedWorkoutsHistories?.get(date)?.asSequence() ?: emptySequence()
            }
            .toList()

        return WeeklyProgressResolver.resolveForWeek(
            workouts = workouts,
            workoutHistoriesInWeek = workoutHistoriesInWeek,
            weekStart = weekStart,
            weekEnd = endOfWeek,
            weeklyProgressOverrides = weeklyProgressOverrides
        )
    }

    val selectedWeekSnapshot = remember(
        groupedWorkoutsHistories,
        workouts,
        weeklyProgressOverrides,
        selectedWeekStart
    ) {
        computeWeekObjectiveSnapshot(selectedWeekStart)
    }

    val selectedWeekSessionsByDate =
        remember(
            groupedWorkoutsHistories,
            visibleExternalSessions,
            selectedWeekStart,
            selectedWeekEnd,
            workoutById,
            selectedWeekSnapshot.excludedWorkoutGlobalIds
        ) {
            val byId = workoutById ?: return@remember null
            try {
                generateSequence(selectedWeekStart) { current ->
                    current.plusDays(1).takeIf { !it.isAfter(selectedWeekEnd) }
                }.mapNotNull { date ->
                    val dayWorkouts = groupedWorkoutsHistories?.get(date)
                        ?.mapNotNull { history ->
                            byId[history.workoutId]?.let { workout ->
                                AppWorkoutStatusSessionEntry(
                                    WeeklyStatusWorkoutHistory(
                                        workoutHistory = history,
                                        workout = workout,
                                        isExcludedFromWeeklyProgress =
                                            history.globalId in selectedWeekSnapshot.excludedWorkoutGlobalIds
                                    )
                                )
                            }
                        }
                        .orEmpty()
                    val dayExternalSessions = visibleExternalSessions
                        .filter { it.date == date }
                        .map(::ExternalWorkoutStatusSessionEntry)
                    val daySessions = deduplicateWorkoutStatusSessions(dayWorkouts + dayExternalSessions)
                        .sortedBy { it.startedAt }
                    if (daySessions.isEmpty()) null else (date to daySessions)
                }.toMap(LinkedHashMap())
            } catch (e: Exception) {
                emptyMap()
            }
        }

    val activityDates = remember(groupedWorkoutsHistories, visibleExternalSessions) {
        buildSet {
            groupedWorkoutsHistories?.keys?.forEach(::add)
            visibleExternalSessions.forEach { add(it.date) }
        }
    }

    val activityKindByDate = remember(groupedWorkoutsHistories, visibleExternalSessions, activityDates) {
        activityDates.associateWith { date ->
            val hasAppOwned = groupedWorkoutsHistories?.get(date)?.isNotEmpty() == true
            val hasExternal = visibleExternalSessions.any { it.date == date }
            when {
                !hasAppOwned && hasExternal -> WorkoutCalendarActivityKind.EXTERNAL_ONLY
                hasAppOwned || hasExternal -> WorkoutCalendarActivityKind.APP_OR_MIXED
                else -> WorkoutCalendarActivityKind.NONE
            }
        }
    }

    val scope = rememberCoroutineScope()

    val drawerState = rememberDrawerState(initialValue = DrawerValue.Closed)

    BackHandler(enabled = drawerState.isOpen) {
        scope.launch {
            drawerState.close()
        }
    }

    val tabTitles = listOf(
        stringResource(R.string.loc_scr_tab_status),
        stringResource(R.string.loc_scr_tab_workouts),
        stringResource(R.string.loc_scr_tab_exercise_library),
        stringResource(R.string.loc_scr_tab_alarms),
        stringResource(R.string.loc_scr_tab_gear),
    )

    var selectedDate by remember {
        mutableStateOf<CalendarDay>(
            CalendarDay(
                LocalDate.now(),
                DayPosition.InDate
            )
        )
    }

    val completedWeekStarts = remember(
        groupedWorkoutsHistories,
        allEnabledWorkouts,
        workouts,
        selectedWeekStart,
        weeklyProgressOverrides
    ) {
        if (!hasObjectives) {
            emptySet()
        } else {
            val candidateWeekStarts = buildSet {
                groupedWorkoutsHistories?.keys?.forEach { add(getStartOfWeek(it)) }
                add(getStartOfWeek(LocalDate.now()))
                add(selectedWeekStart)
            }

            candidateWeekStarts.filterTo(mutableSetOf()) { weekStart ->
                computeWeekObjectiveSnapshot(weekStart).objectiveProgress >= 1.0
            }
        }
    }

    LaunchedEffect(
        appViewModel.checkedHealthPermission,
        appViewModel.hasHealthPermissions,
        workouts.map { it.id }.toSet(),
    ) {
        if (!appViewModel.checkedHealthPermission || !appViewModel.hasHealthPermissions) {
            return@LaunchedEffect
        }
        val requiredReadPermissions = setOf(
            HealthPermission.getReadPermission(ExerciseSessionRecord::class),
            HealthPermission.getReadPermission(HeartRateRecord::class),
        )
        val grantedPermissions = runCatching {
            healthConnectClient.permissionController.getGrantedPermissions()
        }.getOrElse {
            appViewModel.setHealthPermissions(false)
            return@LaunchedEffect
        }
        if (!grantedPermissions.containsAll(requiredReadPermissions)) {
            appViewModel.setHealthPermissions(false)
            return@LaunchedEffect
        }
        // A profile that does not own Health Connect has nothing to show, so skip importing too.
        if (!showsExternalSessions) return@LaunchedEffect
        try {
            withContext(Dispatchers.IO) {
                ExternalHealthConnectSessionSyncService(
                    context = context,
                    healthConnectClient = healthConnectClient,
                    externalDatabase = externalSessionDatabase,
                    appDatabase = AppDatabase.getDatabase(context),
                ).refreshRecentSessions()
            }
        } catch (error: SecurityException) {
            appViewModel.setHealthPermissions(false)
            Log.w(TAG, "Health Connect permissions changed during session refresh", error)
        }
    }

    LaunchedEffect(workouts.map { it.id }.toSet()) {
        // #region agent log
        Log.d(TAG, "LaunchedEffect H3 effect run workoutCount=${workouts.size}")
        // #endregion
        appViewModel.loadWorkoutHistories(workouts)
    }

    LaunchedEffect(updateMessage, workouts.map { it.id }.toSet()) {
        if (updateMessage != null) {
            appViewModel.loadWorkoutHistories(workouts)
        }
    }

    LaunchedEffect(selectedDate, isHistoryStateReady) {
        if (!isHistoryStateReady) {
            isDaySelectionLoading = false
            return@LaunchedEffect
        }
        if (!hasInitializedSelectedDate) {
            hasInitializedSelectedDate = true
            return@LaunchedEffect
        }
        isDaySelectionLoading = true
        delay(500)
        isDaySelectionLoading = false
    }

    fun onDayClicked(calendarState: CalendarState, day: CalendarDay) {
        scope.launch(Dispatchers.Main) {
            if (!isHistoryStateReady) return@launch
            // Do nothing when clicking a day within the already selected week
            if (!day.date.isBefore(selectedWeekStart) && !day.date.isAfter(selectedWeekEnd)) {
                return@launch
            }
            val willChangeSelection = selectedDate != day || selectedWeekAnchorDate != day.date
            if (!willChangeSelection) return@launch

            isDaySelectionLoading = true
            selectedWeekAnchorDate = day.date
            if (day.position != DayPosition.MonthDate) {
                calendarState.scrollToMonth(day.date.yearMonth)
                selectedDate = day
                return@launch
            }
            selectedDate = day
        }
    }

    fun activityKindForDay(day: CalendarDay): WorkoutCalendarActivityKind {
        return activityKindByDate[day.date] ?: WorkoutCalendarActivityKind.NONE
    }
    var isSaving by remember { mutableStateOf(false) }

    fun commitRecurringWorkoutChanges(
        replacements: List<Pair<Workout, Workout>> = emptyList(),
        addedWorkout: Workout? = null,
    ) {
        if (isSaving) return
        isSaving = true
        appViewModel.viewModelScope.launch {
            try {
                val versionsWithHistory = withContext(Dispatchers.IO) {
                    replacements.associate { (original, _) ->
                        original.id to WorkoutManager.workoutVersionIds(original, appViewModel.workouts)
                            .any { versionId -> workoutHistoryDao.workoutHistoryExistsByWorkoutId(versionId) }
                    }
                }
                var candidateWorkouts = appViewModel.workouts
                replacements.forEach { (original, updated) ->
                    candidateWorkouts = if (versionsWithHistory[original.id] == true) {
                        WorkoutManager.updateWorkout(candidateWorkouts, original, updated)
                    } else {
                        WorkoutManager.updateWorkoutOld(candidateWorkouts, original, updated)
                    }
                }
                if (addedWorkout != null) candidateWorkouts = candidateWorkouts + addedWorkout
                val candidateStore = appViewModel.workoutStore.copy(workouts = candidateWorkouts)
                validateWorkoutStoreForRuntimeUse(candidateStore)
                withContext(Dispatchers.Main) {
                    appViewModel.updateWorkoutStore(candidateStore)
                    appViewModel.scheduleWorkoutSave(context)
                    addedWorkout?.let { appViewModel.setScreenData(ScreenData.WorkoutDetail(it.id)) }
                }
            } catch (exception: Exception) {
                Log.e("RecurringWorkoutSave", "Could not save recurring workout changes.", exception)
                withContext(Dispatchers.Main) {
                    Toast.makeText(
                        context,
                        recurringAuthoringErrorMessage(
                            context,
                            exception,
                            R.string.loc_scr_save_recurring_error,
                        ),
                        Toast.LENGTH_LONG,
                    ).show()
                }
            } finally {
                isSaving = false
            }
        }
    }

    fun renameRecurringSession(family: List<Workout>, newName: String) {
        runCatching { RecurringWorkoutAuthoring.renameFamily(family, newName) }
            .onSuccess { replacements ->
                commitRecurringWorkoutChanges(family.zip(replacements))
            }
            .onFailure { exception ->
                Toast.makeText(
                    context,
                    recurringAuthoringErrorMessage(context, exception, R.string.loc_scr_save_recurring_error),
                    Toast.LENGTH_LONG,
                ).show()
            }
    }

    fun updateRecurringPrescriptionLabel(workout: Workout, family: List<Workout>, label: String?) {
        runCatching { RecurringWorkoutAuthoring.updatePrescriptionLabel(workout, label, family) }
            .onSuccess { updated -> commitRecurringWorkoutChanges(listOf(workout to updated)) }
            .onFailure { exception ->
                Toast.makeText(
                    context,
                    recurringAuthoringErrorMessage(context, exception, R.string.loc_scr_save_recurring_error),
                    Toast.LENGTH_LONG,
                ).show()
            }
    }

    fun reorderRecurringSession(family: List<Workout>, orderedWorkoutIds: List<UUID>) {
        runCatching {
            RecurringWorkoutAuthoring.reorderFamily(family, orderedWorkoutIds)
        }.onSuccess { reordered ->
            val reorderedById = reordered.associateBy { it.id }
            val replacements = family.mapNotNull { original ->
                reorderedById[original.id]?.takeIf { it.prescriptionOrdinal != original.prescriptionOrdinal }
                    ?.let { original to it }
            }
            if (replacements.isNotEmpty()) commitRecurringWorkoutChanges(replacements)
        }.onFailure { exception ->
            Toast.makeText(
                context,
                recurringAuthoringErrorMessage(
                    context,
                    exception,
                    R.string.loc_scr_reorder_prescriptions_error,
                ),
                Toast.LENGTH_LONG,
            ).show()
        }
    }

    fun attachRecurringWorkout(workout: Workout, family: List<Workout>) {
        runCatching { RecurringWorkoutAuthoring.attach(workout, family) }
            .onSuccess { updated -> commitRecurringWorkoutChanges(listOf(workout to updated)) }
            .onFailure { exception ->
                Toast.makeText(
                    context,
                    recurringAuthoringErrorMessage(context, exception, R.string.loc_scr_save_recurring_error),
                    Toast.LENGTH_LONG,
                ).show()
            }
    }

    fun detachRecurringWorkout(workout: Workout) {
        val updated = RecurringWorkoutAuthoring.detach(workout)
        commitRecurringWorkoutChanges(listOf(workout to updated))
    }

    fun addNextRecurringPrescription(source: Workout, family: List<Workout>) {
        runCatching { RecurringWorkoutAuthoring.cloneNext(source, family, label = null) }
            .onSuccess { clone -> commitRecurringWorkoutChanges(addedWorkout = clone) }
            .onFailure { exception ->
                Toast.makeText(
                    context,
                    recurringAuthoringErrorMessage(context, exception, R.string.loc_scr_save_recurring_error),
                    Toast.LENGTH_LONG,
                ).show()
            }
    }

    fun updateWorkoutsEnabledState(enabled: Boolean) {
        val workoutsToUpdate = selectedWorkouts.toList()
        if (workoutsToUpdate.isEmpty()) return
        if (isSaving) return
        isSaving = true
        scope.launch {
            try {
                val historyById = withContext(Dispatchers.IO) {
                    workoutsToUpdate.associate {
                        it.id to workoutHistoryDao.workoutHistoryExistsByWorkoutId(
                            it.id
                        )
                    }
                }
                withContext(Dispatchers.Main) {
                    workoutsToUpdate.forEach { workout ->
                        val hasHistory = historyById[workout.id] ?: false
                        appViewModel.updateWorkoutVersioned(
                            workout,
                            workout.copy(enabled = enabled),
                            hasHistory
                        )
                    }
                    selectedWorkouts = emptyList()
                    isWorkoutSelectionModeActive = false
                }
                appViewModel.scheduleWorkoutSave(context)
            } finally {
                isSaving = false
            }
        }
    }

    fun activeWorkoutOrderWithVisibleOrder(
        visibleOrderedWorkouts: List<Workout>,
        allActiveWorkouts: List<Workout>
    ): List<Workout> {
        val visibleIds = visibleOrderedWorkouts.mapTo(mutableSetOf()) { it.id }
        var visibleIndex = 0
        return allActiveWorkouts.map { workout ->
            if (workout.id in visibleIds) {
                visibleOrderedWorkouts[visibleIndex++]
            } else {
                workout
            }
        }
    }

    fun onMoveWorkoutUp() {
        if (selectedWorkouts.size != 1) return
        val selected = selectedWorkouts.first()
        if (focusedRecurringSessionId != null) {
            val family = activeWorkouts
                .filter { it.recurringSessionId == focusedRecurringSessionId }
                .sortedBy { it.prescriptionOrdinal ?: Int.MAX_VALUE }
            val index = family.indexOfFirst { it.id == selected.id }
            if (index <= 0) return
            val reordered = family.toMutableList().apply {
                val previous = this[index - 1]
                this[index - 1] = this[index]
                this[index] = previous
            }
            reorderRecurringSession(family, reordered.map { it.id })
            return
        }
        val index = visibleActiveWorkouts.indexOfFirst { it.id == selected.id }
        if (index <= 0 || index >= visibleActiveWorkouts.size) return
        val newVisibleList = visibleActiveWorkouts.toMutableList().apply {
            val prev = this[index - 1]
            this[index - 1] = this[index]
            this[index] = prev
        }
        appViewModel.reorderWorkoutsInPlan(
            selectedPlanFilter,
            activeWorkoutOrderWithVisibleOrder(newVisibleList, activeWorkouts)
        )
        appViewModel.scheduleWorkoutSave(context)
    }

    fun onMoveWorkoutDown() {
        if (selectedWorkouts.size != 1) return
        val selected = selectedWorkouts.first()
        if (focusedRecurringSessionId != null) {
            val family = activeWorkouts
                .filter { it.recurringSessionId == focusedRecurringSessionId }
                .sortedBy { it.prescriptionOrdinal ?: Int.MAX_VALUE }
            val index = family.indexOfFirst { it.id == selected.id }
            if (index < 0 || index >= family.lastIndex) return
            val reordered = family.toMutableList().apply {
                val next = this[index + 1]
                this[index + 1] = this[index]
                this[index] = next
            }
            reorderRecurringSession(family, reordered.map { it.id })
            return
        }
        val index = visibleActiveWorkouts.indexOfFirst { it.id == selected.id }
        if (index < 0 || index >= visibleActiveWorkouts.size - 1) return
        val newVisibleList = visibleActiveWorkouts.toMutableList().apply {
            val next = this[index + 1]
            this[index + 1] = this[index]
            this[index] = next
        }
        appViewModel.reorderWorkoutsInPlan(
            selectedPlanFilter,
            activeWorkoutOrderWithVisibleOrder(newVisibleList, activeWorkouts)
        )
        appViewModel.scheduleWorkoutSave(context)
    }

    @Composable
    fun workoutsListContent(showPlanPicker: Boolean) {
        val sessionWorkouts = if (focusedRecurringSessionId == null) {
            visibleActiveWorkouts
        } else {
            activeWorkouts.filter { it.recurringSessionId == focusedRecurringSessionId }
        }
        Column(modifier = Modifier.fillMaxSize()) {
            if (showPlanPicker) {
                WorkoutPlanFilterPicker(
                    allPlans = allPlans,
                    selectedPlanFilter = selectedPlanFilter,
                    onPlanSelected = ::selectWorkoutPlan,
                )
            }
            WorkoutsListTab(
                workouts = sessionWorkouts,
                selectedWorkouts = selectedWorkouts,
                isSelectionModeActive = isWorkoutSelectionModeActive,
                appViewModel = appViewModel,
                hideDisabledWorkouts = if (focusedRecurringSessionId == null) hideDisabledWorkouts else false,
                disabledWorkoutCount = if (focusedRecurringSessionId == null) disabledActiveWorkoutCount else 0,
                emptyMessage = when {
                    focusedRecurringSessionId == null &&
                        hideDisabledWorkouts &&
                        disabledActiveWorkoutCount > 0 &&
                        activeWorkouts.isNotEmpty() ->
                        if (selectedPlanFilter == null) {
                            stringResource(R.string.loc_workout_plan_filter_no_enabled_workouts)
                        } else {
                            stringResource(R.string.loc_scr_no_enabled_workouts_plan)
                        }

                    else ->
                        if (selectedPlanFilter == null) {
                            stringResource(R.string.loc_workout_plan_filter_no_workouts)
                        } else {
                            stringResource(R.string.loc_scr_no_workouts_plan)
                        }
                },
                onHideDisabledWorkoutsChange = { hideDisabledWorkouts = it },
                onReorderRecurring = ::reorderRecurringSession,
                onAddNextPrescription = ::addNextRecurringPrescription,
                workoutHistories = groupedWorkoutsHistories?.values?.flatten(),
                suggestionEnabledByPlan = allPlans.associate { it.id to it.suggestNextPrescription },
                onWorkoutClick = { workout ->
                    appViewModel.setScreenData(ScreenData.WorkoutDetail(workout.id))
                },
                onSelectionChange = { selectedWorkouts = it },
                onSelectionModeChange = { isWorkoutSelectionModeActive = it },
                selectedPlanId = selectedPlanFilter,
                focusedRecurringSessionId = focusedRecurringSessionId,
                onOpenRecurringSession = { sessionId ->
                    appViewModel.setScreenData(ScreenData.SessionPrescriptions(sessionId))
                },
            )
        }
    }

    Box(modifier = Modifier.fillMaxSize()) {
        ModalNavigationDrawer(
            drawerState = drawerState,
            drawerContent = {
                ModalDrawerSheet(
                    drawerContainerColor = DarkGray
                ) {
                    WorkoutsMenu(
                        isDrawerOpen = drawerState.isOpen,
                        onSyncClick = onSyncClick,
                        onOpenSettingsClick = onOpenSettingsClick,
                        onOpenPlansClick = { appViewModel.setScreenData(ScreenData.Plans()) },
                        onBackupClick = onBackupClick,
                        onRestoreClick = onRestoreClick,
                        onImportWorkoutsClick = onImportWorkoutsClick,
                        onClearAllHistories = onClearAllHistories,
                        onSyncWithHealthConnectClick = onSyncToHealthConnectClick,
                        onExportWorkouts = onExportWorkouts,
                        onExportWorkoutPlan = onExportWorkoutPlan,
                        onExportWorkoutDataForLlm = onExportWorkoutDataForLlm,
                        onExportEquipment = onExportEquipment,
                        onClearAllExerciseInfo = onClearAllExerciseInfo,
                        onViewErrorLogs = onViewErrorLogs,
                        onViewSensorSessions = onViewSensorSessions,
                        onMenuItemClick = { action ->
                            scope.launch {
                                drawerState.close()
                                action()
                            }
                        }
                    )
                }
            }
        ) {
            BreadcrumbScaffold(
                showTopBarDivider = false,
                topBar = {
                    TopAppBar(
                        colors = TopAppBarDefaults.topAppBarColors(
                            containerColor = MaterialTheme.colorScheme.background,
                            titleContentColor = MaterialTheme.colorScheme.onBackground,
                            navigationIconContentColor = MaterialTheme.colorScheme.onBackground,
                            actionIconContentColor = MaterialTheme.colorScheme.onBackground
                        ),
                        title = {
                            Text(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clipToBounds(),
                                text = focusedSessionWorkout?.name
                                    ?: if (focusedRecurringSessionId != null) {
                                        stringResource(R.string.loc_scr_prescriptions)
                                    } else {
                                        stringResource(R.string.app_name)
                                    },
                                textAlign = TextAlign.Center,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        },
                        navigationIcon = {
                            if (focusedRecurringSessionId != null) {
                                IconButton(
                                    modifier = Modifier.testTag("session_back_to_workouts"),
                                    onClick = {
                                        if (!appViewModel.goBack()) {
                                            appViewModel.setScreenData(ScreenData.Workouts(1))
                                        }
                                    },
                                ) {
                                    Icon(
                                        imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                                        contentDescription = stringResource(R.string.loc_scr_back_to_workouts_cd),
                                    )
                                }
                            } else {
                                IconButton(onClick = {
                                    scope.launch {
                                        drawerState.apply {
                                            if (isClosed) open() else close()
                                        }
                                    }
                                }) {
                                    Icon(
                                        imageVector = Icons.Default.Menu,
                                        contentDescription = stringResource(R.string.loc_menu)
                                    )
                                }
                            }
                        },
                        actions = {
                            activeProfileName?.let { profileName ->
                                // Every tab shows per-profile data, so the active profile is
                                // named here and can be switched without leaving the screen.
                                Box {
                                    val switchProfileDescription =
                                        stringResource(R.string.loc_scr_switch_profile_cd, profileName)
                                    Row(
                                        modifier = Modifier
                                            .padding(end = Spacing.xs)
                                            .clip(RoundedCornerShape(percent = 50))
                                            .background(MaterialTheme.colorScheme.surfaceVariant)
                                            .clickable { profileMenuExpanded = true }
                                            .padding(start = Spacing.sm, end = 4.dp, top = 4.dp, bottom = 4.dp)
                                            .semantics { contentDescription = switchProfileDescription },
                                        verticalAlignment = Alignment.CenterVertically
                                    ) {
                                        Text(
                                            text = profileName,
                                            style = MaterialTheme.typography.labelMedium,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                            maxLines = 1,
                                            overflow = TextOverflow.Ellipsis,
                                            modifier = Modifier.weight(1f, fill = false)
                                        )
                                        // Explicit affordance: without it the chip reads as a label.
                                        Icon(
                                            imageVector = Icons.Filled.ArrowDropDown,
                                            contentDescription = null,
                                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                            modifier = Modifier.size(18.dp)
                                        )
                                    }
                                    DropdownMenu(
                                        expanded = profileMenuExpanded,
                                        onDismissRequest = { profileMenuExpanded = false }
                                    ) {
                                        // Hoisted: the item's onClick is not a composable context.
                                        val switchBlockedMessage = stringResource(
                                            R.string.profile_switch_blocked_workout_in_progress
                                        )
                                        profilesForSwitcher.forEach { profile ->
                                            DropdownMenuItem(
                                                text = {
                                                    Text(
                                                        text = profile.name,
                                                        color = if (profile.id == activeProfileId) {
                                                            MaterialTheme.colorScheme.primary
                                                        } else {
                                                            MaterialTheme.colorScheme.onSurface
                                                        }
                                                    )
                                                },
                                                onClick = {
                                                    profileMenuExpanded = false
                                                    if (profile.id == activeProfileId) return@DropdownMenuItem
                                                    if (workoutInProgress) {
                                                        Toast.makeText(
                                                            context,
                                                            switchBlockedMessage,
                                                            Toast.LENGTH_LONG
                                                        ).show()
                                                        return@DropdownMenuItem
                                                    }
                                                    Profiles.setActiveProfile(context, profile.id)
                                                    restartApp(context)
                                                }
                                            )
                                        }
                                    }
                                }
                            }
                            if (watchReachable) {
                                // Visible only while the watch is detected; tapping
                                // starts the same manual sync as the settings entry.
                                IconButton(onClick = onSyncClick) {
                                    Icon(
                                        imageVector = Icons.Filled.Watch,
                                        contentDescription = stringResource(R.string.loc_sync_with_watch)
                                    )
                                }
                            } else {
                                // Invisible placeholder keeps the title centered.
                                IconButton(modifier = Modifier.alpha(0f), onClick = {}) {
                                    Icon(
                                        imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                                        contentDescription = stringResource(R.string.common_back)
                                    )
                                }
                            }
                        }
                    )
                },
                bottomBar = {
                    if (focusedRecurringSessionId != null || selectedTabIndex == 1) {
                        WorkoutsBottomBar(
                            selectedWorkouts = selectedWorkouts,
                            activeWorkouts = if (focusedRecurringSessionId != null) {
                                activeWorkouts.sortedBy { it.prescriptionOrdinal ?: Int.MAX_VALUE }
                            } else visibleActiveWorkouts,
                            appViewModel = appViewModel,
                            workoutHistoryDao = workoutHistoryDao,
                            setHistoryDao = setHistoryDao,
                            scope = scope,
                            context = context,
                            onSelectionChange = { selectedWorkouts = it },
                            onSelectionModeChange = { isWorkoutSelectionModeActive = it },
                            onShowMoveWorkoutDialogChange = {
                                moveWorkoutError = null
                                showMoveWorkoutDialog = it
                            },
                            onUpdateWorkoutsEnabledState = { enabled ->
                                updateWorkoutsEnabledState(
                                    enabled
                                )
                            },
                            onGroupedWorkoutsHistoriesChange = { appViewModel.loadWorkoutHistories(workouts) },
                            onMoveWorkoutUp = { onMoveWorkoutUp() },
                            onMoveWorkoutDown = { onMoveWorkoutDown() },
                            isSelectionModeActive = isWorkoutSelectionModeActive,
                            canManageRecurringSession = selectedRecurringSessionId != null,
                            onManageRecurringSession = {
                                selectedRecurringSessionId?.let { sessionId ->
                                    workouts.filter { it.isActive && it.recurringSessionId == sessionId }
                                        .sortedBy { it.prescriptionOrdinal }
                                        .takeIf { it.isNotEmpty() }
                                        ?.let { recurringFamilyToManage = it }
                                }
                                selectedWorkouts = emptyList()
                                isWorkoutSelectionModeActive = false
                            },
                        )
                    } else if (focusedRecurringSessionId == null) when (selectedTabIndex) {
                        4 -> {
                            EquipmentsBottomBar(
                                selectedEquipments = selectedEquipments,
                                equipments = equipments,
                                appViewModel = appViewModel,
                                context = context,
                                onSelectionChange = { selectedEquipments = it },
                                onSelectionModeChange = { isEquipmentSelectionModeActive = it },
                                isSelectionModeActive = isEquipmentSelectionModeActive
                            )
                            AccessoriesBottomBar(
                                selectedAccessories = selectedAccessories,
                                accessories = accessories,
                                appViewModel = appViewModel,
                                context = context,
                                onSelectionChange = { selectedAccessories = it },
                                onSelectionModeChange = { isAccessorySelectionModeActive = it },
                                isSelectionModeActive = isAccessorySelectionModeActive
                            )
                        }
                    }
                },
            ) { paddingValues ->

                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .background(MaterialTheme.colorScheme.background)
                        .padding(paddingValues),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {

                    if (focusedRecurringSessionId != null) {
                        workoutsListContent(showPlanPicker = false)
                    } else {
                    SwipeableTabs(
                        tabTitles = tabTitles,
                        selectedTabIndex = selectedTabIndex,
                        onTabSelected = { appViewModel.setHomeTab(it) },
                        containerColor = MaterialTheme.colorScheme.background,
                        contentColor = MaterialTheme.colorScheme.onBackground,
                        selectedContentColor = MaterialTheme.colorScheme.primary,
                        unselectedContentColor = MaterialTheme.colorScheme.onBackground,
                        compactNavigation = true,
                        modifier = Modifier
                            .fillMaxSize()
                            .background(MaterialTheme.colorScheme.background),
                    ) { pageIndex ->
                        Column(
                            modifier = Modifier
                                .fillMaxSize()
                                .background(MaterialTheme.colorScheme.background),
                            horizontalAlignment = Alignment.CenterHorizontally
                        ) {
                            when (pageIndex) {
                                    0 -> {
                                        WorkoutsStatusTab(
                                            isLoading = isLoading,
                                            hasObjectives = hasObjectives,
                                            selectedDate = selectedDate,
                                            selectedWeekStart = selectedWeekStart,
                                            selectedWeekEnd = selectedWeekEnd,
                                            completedWeekStarts = completedWeekStarts,
                                            selectedWeekSessionsByDate = selectedWeekSessionsByDate,
                                            weeklyProgressSnapshot = selectedWeekSnapshot,
                                            appViewModel = appViewModel,
                                            onDayClicked = { calendarState, day ->
                                                onDayClicked(
                                                    calendarState,
                                                    day
                                                )
                                            },
                                            activityKindForDay = { day -> activityKindForDay(day) },
                                            onSaveWeeklyProgressSelection = { includedWorkoutGlobalIds ->
                                                appViewModel.setWeeklyProgressOverride(
                                                    weekStart = selectedWeekStart,
                                                    includedWorkoutGlobalIds = includedWorkoutGlobalIds
                                                )
                                                appViewModel.scheduleWorkoutSave(context)
                                            },
                                            onClearWeeklyProgressSelection = {
                                                appViewModel.clearWeeklyProgressOverride(selectedWeekStart)
                                                appViewModel.scheduleWorkoutSave(context)
                                            },
                                            activityDates = activityDates,
                                            workoutHistorySessionStatuses = workoutHistorySessionStatuses
                                        )
                                    }

                                    1 -> {
                                        workoutsListContent(showPlanPicker = true)
                                    }

                                    4 -> {
                                        WorkoutsGearTab(
                                            equipments = equipments,
                                            accessories = accessories,
                                            selectedEquipments = selectedEquipments,
                                            selectedAccessories = selectedAccessories,
                                            isEquipmentSelectionModeActive = isEquipmentSelectionModeActive,
                                            isAccessorySelectionModeActive = isAccessorySelectionModeActive,
                                            appViewModel = appViewModel,
                                            onEquipmentSelectionChange = {
                                                selectedEquipments = it
                                            },
                                            onAccessorySelectionChange = {
                                                selectedAccessories = it
                                            },
                                            onEquipmentSelectionModeChange = {
                                                isEquipmentSelectionModeActive = it
                                            },
                                            onAccessorySelectionModeChange = {
                                                isAccessorySelectionModeActive = it
                                            }
                                        )
                                    }

                                    3 -> {
                                        Column(modifier = Modifier.fillMaxSize()) {
                                            WorkoutPlanFilterPicker(
                                                allPlans = allPlans,
                                                selectedPlanFilter = selectedPlanFilter,
                                                onPlanSelected = ::selectWorkoutPlan,
                                            )
                                            WorkoutsAlarmsTab(
                                                workouts = filteredWorkouts,
                                                enabledWorkouts = enabledWorkouts,
                                                workoutScheduleDao = workoutScheduleDao,
                                                scope = scope,
                                                onSyncClick = onSyncClick,
                                                updateMessage = updateMessage
                                            )
                                        }
                                    }

                                    2 -> {
                                        ExerciseLibraryScreen(
                                            definitions = workoutStore.exerciseDefinitions,
                                            workouts = workouts,
                                            plans = allPlans,
                                            equipmentNamesById = equipments.associate { it.id to it.name },
                                            accessoryNamesById = accessories.associate { it.id to it.name },
                                            onAdd = {
                                                appViewModel.setScreenData(ScreenData.NewExerciseDefinition())
                                            },
                                            onImport = { content ->
                                                scope.launch {
                                                    runCatching {
                                                        val importedLibrary = fromJSONToExerciseLibraryPackage(content)
                                                        withContext(Dispatchers.IO) {
                                                            restoreExerciseMovementBackups(
                                                                context,
                                                                importedLibrary.exerciseMovements,
                                                            )
                                                            requireExerciseMovementPayloads(
                                                                context,
                                                                workoutStore.copy(
                                                                    // Validate exactly what the import will commit.
                                                                    exerciseDefinitions =
                                                                        importedLibrary.exerciseDefinitions.normalizedForImport(),
                                                                    workouts = emptyList(),
                                                                ),
                                                            )
                                                        }
                                                        val addedDefinitions = appViewModel
                                                            .importExerciseLibrary(importedLibrary)
                                                        appViewModel.scheduleWorkoutSave(context)
                                                        addedDefinitions
                                                    }.onSuccess { addedDefinitions ->
                                                        Toast.makeText(
                                                            context,
                                                            context.getString(R.string.loc_scr_imported_definitions, addedDefinitions),
                                                            Toast.LENGTH_LONG,
                                                        ).show()
                                                    }.onFailure { error ->
                                                        Toast.makeText(
                                                            context,
                                                            error.message ?: context.getString(R.string.loc_scr_import_library_error),
                                                            Toast.LENGTH_LONG,
                                                        ).show()
                                                    }
                                                }
                                            },
                                            onEdit = { definition ->
                                                appViewModel.setScreenData(
                                                    ScreenData.EditExerciseDefinition(definition.id)
                                                )
                                            },
                                            onDelete = { definition ->
                                                appViewModel.deleteExerciseDefinition(definition.id)
                                                appViewModel.scheduleWorkoutSave(context)
                                            },
                                            onOpenPlan = { planId ->
                                                appViewModel.openWorkoutPlanFromBreadcrumb(planId)
                                            },
                                            onOpenWorkout = { workoutId ->
                                                appViewModel.setScreenData(
                                                    ScreenData.WorkoutDetail(workoutId)
                                                )
                                            },
                                        )
                                    }
                            }
                        }
                    }
                    }
                }
            }
        }

        recurringFamilyToManage?.let { family ->
            val attachableWorkouts = workouts.filter { candidate ->
                candidate.isActive && candidate.recurringSessionId == null &&
                    candidate.workoutPlanId == family.firstOrNull()?.workoutPlanId
            }
            RecurringSessionDialog(
                family = family,
                attachableWorkouts = attachableWorkouts,
                onRename = { name -> renameRecurringSession(family, name); recurringFamilyToManage = null },
                onUpdatePrescriptionLabel = { workout, label ->
                    updateRecurringPrescriptionLabel(workout, family, label)
                    recurringFamilyToManage = null
                },
                onAttach = { workout -> attachRecurringWorkout(workout, family); recurringFamilyToManage = null },
                onDetach = { workout -> detachRecurringWorkout(workout); recurringFamilyToManage = null },
                onDismiss = { recurringFamilyToManage = null },
            )
        }

        // Move Workout Dialog
        val currentPlanId = if (
            selectedWorkouts.isNotEmpty() &&
            selectedWorkouts.all { it.workoutPlanId == selectedWorkouts.first().workoutPlanId }
        ) {
            selectedWorkouts.first().workoutPlanId
        } else {
            null
        }
        MoveWorkoutDialog(
            show = showMoveWorkoutDialog,
            workoutName = selectedWorkouts.firstOrNull()?.name ?: "",
            workoutCount = selectedWorkouts.size,
            availablePlans = appViewModel.getSelectableWorkoutPlans(currentPlanId),
            errorMessage = moveWorkoutError,
            onDismiss = {
                showMoveWorkoutDialog = false
                moveWorkoutError = null
            },
            onMoveToPlan = { targetPlanId ->
                val moved = appViewModel.moveWorkoutsToPlan(
                    selectedWorkouts.map { it.id }.toSet(),
                    targetPlanId
                )
                if (moved) {
                    appViewModel.scheduleWorkoutSave(context)
                    showMoveWorkoutDialog = false
                    moveWorkoutError = null
                    selectedWorkouts = emptyList()
                    isWorkoutSelectionModeActive = false
                } else {
                    // Keep the dialog and the selection so the user can choose another target.
                    moveWorkoutError = movePlanUnavailableError
                }
            },
            onCreateNewPlan = {
                showMoveWorkoutDialog = false
                moveWorkoutError = null
                createPlanError = null
                showCreateNewPlanDialog = true
            }
        )

        // Create New Plan Dialog
        WorkoutPlanNameDialog(
            show = showCreateNewPlanDialog,
            confirmButtonText = stringResource(R.string.loc_scr_create),
            errorMessage = createPlanError,
            onDismiss = {
                showCreateNewPlanDialog = false
                createPlanError = null
            },
            onConfirm = { planName ->
                val newPlanId = java.util.UUID.randomUUID()
                val nextOrder =
                    (appViewModel.getAllWorkoutPlans().maxOfOrNull { it.order } ?: -1) + 1
                val newPlan = WorkoutPlan(
                    id = newPlanId,
                    name = planName,
                    workoutIds = selectedWorkouts.map { it.id },
                    order = nextOrder
                )

                // Add the new plan
                if (!appViewModel.addWorkoutPlan(newPlan)) {
                    createPlanError = planSaveError
                } else {
                    // Move all selected workouts to the new plan
                    appViewModel.moveWorkoutsToPlan(
                        selectedWorkouts.map { it.id }.toSet(),
                        newPlanId
                    )

                    appViewModel.scheduleWorkoutSave(context)

                    selectedWorkouts = emptyList()
                    isWorkoutSelectionModeActive = false
                    showCreateNewPlanDialog = false
                    createPlanError = null
                }
            }
        )

        LoadingOverlay(isVisible = rememberDebouncedSavingVisible(isSaving), text = stringResource(R.string.common_saving))
        // Manual sync mirrors the watch's own sync screen: full-screen stage-based
        // loader, determinate only while chunks transfer, check mark when done.
        LoadingOverlay(
            isVisible = isSyncing,
            text = when (syncPhase) {
                SyncPhase.CONNECTING -> stringResource(R.string.loc_scr_sync_connecting)
                SyncPhase.TRANSFERRING -> stringResource(R.string.loc_scr_sync_transferring)
                SyncPhase.PROCESSING -> stringResource(R.string.loc_scr_sync_processing)
                SyncPhase.COMPLETED -> stringResource(R.string.loc_scr_sync_complete)
                null -> stringResource(R.string.loc_scr_sync_connecting)
            },
            useOpaqueBackground = true,
            progress = animatedSyncProgress.takeIf { syncPhase == SyncPhase.TRANSFERRING },
            completed = syncPhase == SyncPhase.COMPLETED,
            onCancel = if (syncPhase == SyncPhase.COMPLETED) null else onCancelSync,
        )
        LoadingOverlay(
            isVisible = rememberMinimumLoadingVisibility(
                isLoading = isExportingWorkoutDataForLlm,
                minVisibleMs = 1_000L,
            ),
            text = workoutDataExportStatus.ifBlank {
                stringResource(R.string.main_exporting_workout_data)
            },
            useOpaqueBackground = true
        )
    }
}

/**
 * Builds the plan filter choices as named plans followed by a filter-only "No plan" option.
 * The null choice only filters to workouts that are not attached to a named plan; it never
 * creates a plan or changes workout membership.
 */
internal fun workoutPlanFilterItems(
    plans: List<WorkoutPlan>,
    noPlanLabel: String,
): List<StandardFilterDropdownItem<UUID?>> =
    plans
        .distinctBy { it.id }
        .map { plan -> StandardFilterDropdownItem<UUID?>(value = plan.id, label = plan.name) } +
        StandardFilterDropdownItem<UUID?>(value = null, label = noPlanLabel)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun WorkoutPlanFilterPicker(
    allPlans: List<WorkoutPlan>,
    selectedPlanFilter: UUID?,
    onPlanSelected: (UUID?) -> Unit,
) {
    if (allPlans.isEmpty()) {
        return
    }

    val noPlanLabel = stringResource(R.string.loc_workout_plan_filter_no_plan)
    val planItems = remember(allPlans, noPlanLabel) {
        workoutPlanFilterItems(allPlans, noPlanLabel)
    }
    val selectedPlanLabel = remember(planItems, selectedPlanFilter, noPlanLabel) {
        planItems
            .firstOrNull { it.value == selectedPlanFilter }
            ?.label
            ?: noPlanLabel
    }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 15.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        StandardFilterDropdown(
            label = stringResource(R.string.loc_scr_workout_plan_label),
            selectedText = selectedPlanLabel,
            items = planItems,
            onItemSelected = onPlanSelected,
            selectedValue = selectedPlanFilter,
            modifier = Modifier.weight(1f),
            isItemSelected = { it == selectedPlanFilter },
            marqueeSelectedText = false,
            marqueeItems = false,
            itemMaxLines = 3,
        )
    }
}

/** The profile's data roots all change, so every cached screen state must be rebuilt. */
private fun restartApp(context: Context) {
    val intent = Intent(context, MainActivity::class.java)
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
    (context as? Activity)?.finish()
    context.startActivity(intent)
}
