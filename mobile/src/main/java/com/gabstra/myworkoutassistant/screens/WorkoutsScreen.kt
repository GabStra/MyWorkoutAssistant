package com.gabstra.myworkoutassistant.screens

import com.gabstra.myworkoutassistant.composables.BreadcrumbScaffold

import androidx.activity.compose.BackHandler
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.composables.AccessoriesBottomBar
import com.gabstra.myworkoutassistant.composables.EditPlanNameDialog
import com.gabstra.myworkoutassistant.composables.EquipmentsBottomBar
import com.gabstra.myworkoutassistant.composables.LoadingOverlay
import com.gabstra.myworkoutassistant.composables.rememberDebouncedSavingVisible
import com.gabstra.myworkoutassistant.composables.MoveWorkoutDialog
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
import com.gabstra.myworkoutassistant.healthconnect.external.ExternalHealthConnectSessionSyncService
import com.gabstra.myworkoutassistant.shared.DarkGray
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import com.gabstra.myworkoutassistant.shared.WeeklyProgressResolver
import com.gabstra.myworkoutassistant.shared.WeeklyProgressSnapshot
import com.gabstra.myworkoutassistant.shared.fromJSONToExerciseLibraryPackage
import com.gabstra.myworkoutassistant.shared.motion.restoreExerciseMovementBackups
import com.gabstra.myworkoutassistant.shared.motion.requireExerciseMovementPayloads
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
    workoutDataExportStatus: String = "Exporting workout data...",
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
    selectedTabIndex: Int
) {
    val animatedSyncProgress by animateFloatAsState(
        targetValue = syncProgress ?: 0f,
        animationSpec = tween(durationMillis = 400),
        label = "Wear-acknowledged sync progress"
    )
    val updateMessage by appViewModel.updateNotificationFlow.collectAsState(initial = null)
    val context = LocalContext.current
    val externalSessionDatabase = remember(context) {
        ExternalHealthConnectSessionDatabase.getDatabase(context)
    }
    val externalSessions by externalSessionDatabase
        .externalHealthConnectSessionDao()
        .observeAllSessions()
        .collectAsState(initial = emptyList())

    var isDaySelectionLoading by remember { mutableStateOf(false) }
    var hasInitializedSelectedDate by remember { mutableStateOf(false) }

    val workouts by appViewModel.workoutsFlow.collectAsState()
    val workoutStore by appViewModel.workoutStoreFlow.collectAsState()

    val equipments by appViewModel.equipmentsFlow.collectAsState()
    val accessories by appViewModel.accessoryEquipmentsFlow.collectAsState()

    // Group workouts by plan - keep reactive to workoutStore updates
    val allPlans by appViewModel.workoutPlansFlow.collectAsState()
    val weeklyProgressOverrides by appViewModel.weeklyProgressOverridesFlow.collectAsState()

    // Filter state - use ViewModel state to persist across navigation
    val selectedPlanFilter by appViewModel.effectiveSelectedWorkoutPlanIdFlow.collectAsState()

    // Filter workouts by selected plan
    val filteredWorkouts = remember(workouts, selectedPlanFilter) {
        val planId = selectedPlanFilter
        if (planId != null) {
            appViewModel.getWorkoutsByPlan(planId)
        } else {
            workouts.filter { it.workoutPlanId == null }
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

    fun selectWorkoutPlan(planId: UUID) {
        selectedWorkouts = emptyList()
        isWorkoutSelectionModeActive = false
        appViewModel.setSelectedWorkoutPlanId(planId)
    }

    LaunchedEffect(visibleActiveWorkouts.map { it.id }) {
        val visibleIds = visibleActiveWorkouts.mapTo(mutableSetOf()) { it.id }
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

    var showEditPlanNameDialog by remember { mutableStateOf(false) }
    var planToEdit by remember { mutableStateOf<WorkoutPlan?>(null) }
    var showMoveWorkoutDialog by remember { mutableStateOf(false) }
    var showCreateNewPlanDialog by remember { mutableStateOf(false) }

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
            externalSessions,
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
                    val dayExternalSessions = externalSessions
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

    val activityDates = remember(groupedWorkoutsHistories, externalSessions) {
        buildSet {
            groupedWorkoutsHistories?.keys?.forEach(::add)
            externalSessions.forEach { add(it.date) }
        }
    }

    val activityKindByDate = remember(groupedWorkoutsHistories, externalSessions, activityDates) {
        activityDates.associateWith { date ->
            val hasAppOwned = groupedWorkoutsHistories?.get(date)?.isNotEmpty() == true
            val hasExternal = externalSessions.any { it.date == date }
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

    val tabTitles = listOf("Status", "Workouts", "Exercise Library", "Alarms", "Gear")

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
                                    .basicMarquee(iterations = Int.MAX_VALUE),
                                text = "My Workout Assistant", textAlign = TextAlign.Center,
                            )
                        },
                        navigationIcon = {
                            IconButton(onClick = {
                                scope.launch {
                                    drawerState.apply {
                                        if (isClosed) open() else close()
                                    }
                                }
                            }) {
                                Icon(
                                    imageVector = Icons.Default.Menu,
                                    contentDescription = "Menu"
                                )
                            }
                        },
                        actions = {
                            IconButton(modifier = Modifier.alpha(0f), onClick = {}) {
                                Icon(
                                    imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                                    contentDescription = "Back"
                                )
                            }
                        }
                    )
                },
                bottomBar = {
                    when (selectedTabIndex) {
                        1 -> WorkoutsBottomBar(
                            selectedWorkouts = selectedWorkouts,
                            activeWorkouts = visibleActiveWorkouts,
                            appViewModel = appViewModel,
                            workoutHistoryDao = workoutHistoryDao,
                            setHistoryDao = setHistoryDao,
                            scope = scope,
                            context = context,
                            onSelectionChange = { selectedWorkouts = it },
                            onSelectionModeChange = { isWorkoutSelectionModeActive = it },
                            onShowMoveWorkoutDialogChange = { showMoveWorkoutDialog = it },
                            onUpdateWorkoutsEnabledState = { enabled ->
                                updateWorkoutsEnabledState(
                                    enabled
                                )
                            },
                            onGroupedWorkoutsHistoriesChange = { appViewModel.loadWorkoutHistories(workouts) },
                            onMoveWorkoutUp = { onMoveWorkoutUp() },
                            onMoveWorkoutDown = { onMoveWorkoutDown() },
                            isSelectionModeActive = isWorkoutSelectionModeActive
                        )

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
                                        Column(modifier = Modifier.fillMaxSize()) {
                                            WorkoutPlanFilterPicker(
                                                allPlans = allPlans,
                                                selectedPlanFilter = selectedPlanFilter,
                                                onPlanSelected = ::selectWorkoutPlan,
                                            )
                                            WorkoutsListTab(
                                                workouts = visibleActiveWorkouts,
                                                selectedWorkouts = selectedWorkouts,
                                                isSelectionModeActive = isWorkoutSelectionModeActive,
                                                appViewModel = appViewModel,
                                                hideDisabledWorkouts = hideDisabledWorkouts,
                                                disabledWorkoutCount = disabledActiveWorkoutCount,
                                                emptyMessage = if (
                                                    hideDisabledWorkouts &&
                                                    disabledActiveWorkoutCount > 0 &&
                                                    activeWorkouts.isNotEmpty()
                                                ) {
                                                    "No enabled workouts in this plan."
                                                } else {
                                                    "No workouts in this plan yet."
                                                },
                                                onHideDisabledWorkoutsChange = {
                                                    hideDisabledWorkouts = it
                                                },
                                                onWorkoutClick = { workout ->
                                                    appViewModel.setScreenData(
                                                        ScreenData.WorkoutDetail(workout.id)
                                                    )
                                                },
                                                onSelectionChange = { selectedWorkouts = it },
                                                onSelectionModeChange = {
                                                    isWorkoutSelectionModeActive = it
                                                },
                                                selectedPlanId = selectedPlanFilter
                                            )
                                        }
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
                                                                    exerciseDefinitions = importedLibrary.exerciseDefinitions,
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
                                                            "Imported $addedDefinitions exercise definition(s).",
                                                            Toast.LENGTH_LONG,
                                                        ).show()
                                                    }.onFailure { error ->
                                                        Toast.makeText(
                                                            context,
                                                            error.message ?: "Couldn't import that exercise library.",
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

        // Edit Plan Name Dialog
        EditPlanNameDialog(
            show = showEditPlanNameDialog,
            currentName = planToEdit?.name ?: "",
            onDismiss = {
                showEditPlanNameDialog = false
                planToEdit = null
            },
            onConfirm = { newName ->
                planToEdit?.let { plan ->
                    appViewModel.updateWorkoutPlanName(plan.id, newName)
                    appViewModel.scheduleWorkoutSave(context)
                }
                showEditPlanNameDialog = false
                planToEdit = null
            }
        )

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
            onDismiss = {
                showMoveWorkoutDialog = false
            },
            onMoveToPlan = { targetPlanId ->
                appViewModel.moveWorkoutsToPlan(
                    selectedWorkouts.map { it.id }.toSet(),
                    targetPlanId
                )
                appViewModel.scheduleWorkoutSave(context)
                showMoveWorkoutDialog = false
                selectedWorkouts = emptyList()
                isWorkoutSelectionModeActive = false
            },
            onCreateNewPlan = {
                showMoveWorkoutDialog = false
                showCreateNewPlanDialog = true
            }
        )

        // Create New Plan Dialog
        WorkoutPlanNameDialog(
            show = showCreateNewPlanDialog,
            confirmButtonText = "Create",
            onDismiss = {
                showCreateNewPlanDialog = false
            },
            onConfirm = { planName ->
                showCreateNewPlanDialog = false
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
                appViewModel.addWorkoutPlan(newPlan)

                // Move all selected workouts to the new plan
                appViewModel.moveWorkoutsToPlan(
                    selectedWorkouts.map { it.id }.toSet(),
                    newPlanId
                )

                appViewModel.scheduleWorkoutSave(context)

                selectedWorkouts = emptyList()
                isWorkoutSelectionModeActive = false
            }
        )

        LoadingOverlay(isVisible = rememberDebouncedSavingVisible(isSaving), text = "Saving...")
        LoadingOverlay(
            isVisible = isSyncing,
            text = when (syncPhase) {
                SyncPhase.CONNECTING -> "Connecting to watch..."
                SyncPhase.TRANSFERRING -> "Sending data to watch..."
                SyncPhase.PROCESSING -> "Watch is processing received data..."
                SyncPhase.COMPLETED -> "Sync complete"
                null -> "Preparing sync..."
            },
            useOpaqueBackground = true,
            progress = if (syncPhase == SyncPhase.TRANSFERRING) {
                syncProgress?.let { animatedSyncProgress }
            } else {
                null
            },
            onCancel = onCancelSync,
        )
        LoadingOverlay(
            isVisible = rememberMinimumLoadingVisibility(
                isLoading = isExportingWorkoutDataForLlm,
                minVisibleMs = 1_000L,
            ),
            text = workoutDataExportStatus,
            useOpaqueBackground = true
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun WorkoutPlanFilterPicker(
    allPlans: List<WorkoutPlan>,
    selectedPlanFilter: UUID?,
    onPlanSelected: (UUID) -> Unit
) {
    if (allPlans.size <= 1) {
        return
    }

    val planItems = remember(allPlans) {
        allPlans
            .distinctBy { it.id }
            .map { StandardFilterDropdownItem(value = it.id, label = it.name) }
    }
    val selectedPlanLabel = remember(planItems, selectedPlanFilter) {
        planItems
            .firstOrNull { it.value == selectedPlanFilter }
            ?.label
            ?: "Select workout plan"
    }

    StandardFilterDropdown(
        label = "Workout Plan:",
        selectedText = selectedPlanLabel,
        items = planItems,
        onItemSelected = onPlanSelected,
        selectedValue = selectedPlanFilter,
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 15.dp, vertical = 8.dp),
        isItemSelected = { it == selectedPlanFilter },
        marqueeSelectedText = false,
        marqueeItems = false,
        itemMaxLines = 3,
    )
}
