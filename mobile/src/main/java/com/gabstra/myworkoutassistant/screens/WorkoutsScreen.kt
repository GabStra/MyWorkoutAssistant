package com.gabstra.myworkoutassistant.screens

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.interaction.Interaction
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
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
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.TabRowDefaults
import androidx.compose.material3.TabRowDefaults.tabIndicatorOffset
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
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.HealthConnectClient
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.composables.AccessoriesBottomBar
import com.gabstra.myworkoutassistant.composables.EditPlanNameDialog
import com.gabstra.myworkoutassistant.composables.EquipmentsBottomBar
import com.gabstra.myworkoutassistant.composables.HealthConnectHandler
import com.gabstra.myworkoutassistant.composables.LoadingOverlay
import com.gabstra.myworkoutassistant.composables.rememberDebouncedSavingVisible
import com.gabstra.myworkoutassistant.composables.MoveWorkoutDialog
import com.gabstra.myworkoutassistant.composables.StandardFilterDropdown
import com.gabstra.myworkoutassistant.composables.StandardFilterDropdownItem
import com.gabstra.myworkoutassistant.composables.WorkoutPlanNameDialog
import com.gabstra.myworkoutassistant.composables.WorkoutsBottomBar
import com.gabstra.myworkoutassistant.composables.WorkoutsMenu
import com.gabstra.myworkoutassistant.getEndOfWeek
import com.gabstra.myworkoutassistant.getStartOfWeek
import com.gabstra.myworkoutassistant.shared.DarkGray
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import com.gabstra.myworkoutassistant.shared.equipments.AccessoryEquipment
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.kizitonwose.calendar.compose.CalendarState
import com.kizitonwose.calendar.core.CalendarDay
import com.kizitonwose.calendar.core.DayPosition
import com.kizitonwose.calendar.core.yearMonth
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlin.math.abs
import java.time.LocalDate
import android.util.Log
import java.time.format.DateTimeFormatter
import java.util.Locale
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
    onSyncClick: () -> Unit,
    onBackupClick: () -> Unit,
    onRestoreClick: () -> Unit,
    onImportWorkoutsClick: () -> Unit,
    onOpenSettingsClick: () -> Unit,
    onClearUnfinishedWorkouts: () -> Unit,
    onClearAllHistories: () -> Unit,
    onSyncToHealthConnectClick: () -> Unit,
    onExportWorkouts: () -> Unit,
    onExportWorkoutPlan: () -> Unit,
    onExportEquipment: () -> Unit,
    onClearAllExerciseInfo: () -> Unit,
    onViewErrorLogs: () -> Unit,
    selectedTabIndex: Int
) {
    val updateMessage by appViewModel.updateNotificationFlow.collectAsState(initial = null)

    var isLoading by remember { mutableStateOf(true) }

    val workouts by appViewModel.workoutsFlow.collectAsState()

    val equipments by appViewModel.equipmentsFlow.collectAsState()
    val accessories by appViewModel.accessoryEquipmentsFlow.collectAsState()

    // Group workouts by plan - keep reactive to workoutStore updates
    val allPlans by appViewModel.workoutPlansFlow.collectAsState()

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

    var selectedEquipments by remember { mutableStateOf(listOf<WeightLoadedEquipment>()) }
    var isEquipmentSelectionModeActive by remember { mutableStateOf(false) }

    var selectedAccessories by remember { mutableStateOf(listOf<AccessoryEquipment>()) }
    var isAccessorySelectionModeActive by remember { mutableStateOf(false) }

    var showEditPlanNameDialog by remember { mutableStateOf(false) }
    var planToEdit by remember { mutableStateOf<WorkoutPlan?>(null) }
    var showMoveWorkoutDialog by remember { mutableStateOf(false) }
    var showCreateNewPlanDialog by remember { mutableStateOf(false) }

    var objectiveProgress by remember { mutableStateOf(0.0) }

    var selectedWeekAnchorDate by remember {
        mutableStateOf<LocalDate>(LocalDate.now())
    }

    val groupedWorkoutsHistories by appViewModel.groupedWorkoutHistories.collectAsState(initial = null)
    val workoutById by appViewModel.workoutByIdForHistories.collectAsState(initial = null)

    var weeklyWorkoutsByActualTarget by remember {
        mutableStateOf<Map<Workout, Pair<Int, Int>>?>(
            null
        )
    }

    val selectedWeekStart = remember(selectedWeekAnchorDate) { getStartOfWeek(selectedWeekAnchorDate) }
    val selectedWeekEnd = remember(selectedWeekAnchorDate) { getEndOfWeek(selectedWeekAnchorDate) }

    val selectedWeekWorkoutsByDate =
        remember(groupedWorkoutsHistories, selectedWeekStart, selectedWeekEnd, workoutById) {
            val byId = workoutById ?: return@remember null
            try {
                generateSequence(selectedWeekStart) { current ->
                    current.plusDays(1).takeIf { !it.isAfter(selectedWeekEnd) }
                }.mapNotNull { date ->
                    val dayWorkouts = groupedWorkoutsHistories?.get(date)
                        ?.map { history -> Pair(history, byId[history.workoutId]!!) }
                        .orEmpty()
                    if (dayWorkouts.isEmpty()) null else (date to dayWorkouts)
                }.toMap(LinkedHashMap())
            } catch (e: Exception) {
                emptyMap()
            }
        }

    var isCardExpanded by remember {
        mutableStateOf(false)
    }

    val currentLocale = Locale.getDefault()

    val formatter = remember(currentLocale) {
        DateTimeFormatter.ofPattern("dd/MM/yy", currentLocale)
    }

    val scope = rememberCoroutineScope()

    val drawerState = rememberDrawerState(initialValue = DrawerValue.Closed)

    BackHandler(enabled = drawerState.isOpen) {
        scope.launch {
            drawerState.close()
        }
    }

    val tabTitles = listOf("Status", "Workouts", "Gear", "Alarms")

    var selectedDate by remember {
        mutableStateOf<CalendarDay>(
            CalendarDay(
                LocalDate.now(),
                DayPosition.InDate
            )
        )
    }

    fun calculateObjectiveProgress(currentDate: LocalDate) {
        weeklyWorkoutsByActualTarget = null
        objectiveProgress = 0.0
        if (allEnabledWorkouts.isEmpty()) return

        val startOfWeek = getStartOfWeek(currentDate)
        val endOfWeek = getEndOfWeek(currentDate)

        // Inclusive date iteration without Int/Long range pitfalls
        val workoutHistoriesInAWeek =
            generateSequence(startOfWeek) { it.plusDays(1) }
                .takeWhile { !it.isAfter(endOfWeek) }
                .flatMap { d -> groupedWorkoutsHistories?.get(d)?.asSequence() ?: emptySequence() }
                .filter { it.isDone }
                .toList()

        // Fast lookup of eligible workouts and DE-DUPE by workout id
        val eligibleById = allEnabledWorkouts
            .filter { it.timesCompletedInAWeek != null && it.timesCompletedInAWeek != 0 }
            .associateBy { it.id }

        val weeklyWorkouts = workoutHistoriesInAWeek
            .mapNotNull { eligibleById[it.workoutId] }
            .distinctBy { it.id }   // <<< FIX 1

        val uniqueGlobalIds = weeklyWorkouts.map { it.globalId }.toSet()

        val totalWeeklyWorkouts = weeklyWorkouts +
                allActiveAndEnabledWorkouts.filter {
                    it.globalId !in uniqueGlobalIds && it.timesCompletedInAWeek != null && it.timesCompletedInAWeek != 0
                }

        val workoutsByGlobalId = totalWeeklyWorkouts.groupBy { it.globalId }
        val actualCountsByWorkoutId =
            workoutHistoriesInAWeek.groupingBy { it.workoutId }.eachCount()

        data class Fam(
            val active: Workout,
            val countedActual: Int,
            val totalTarget: Int,
            val progress: Double
        )

        val families: List<Fam> = workoutsByGlobalId.map { (_, wsRaw) ->
            val ws = wsRaw.distinctBy { it.id } // <<< Safety de-dupe
            val targets = ws.associate { w -> w.id to (timesCompletedInAWeekObjective[w.id] ?: 0) }
            val actuals = ws.associate { w -> w.id to (actualCountsByWorkoutId[w.id] ?: 0) }

            val totalTarget = targets.values.sum()
            val allReached = ws.all { w ->
                (targets[w.id] ?: 0) <= 0 || (actuals[w.id] ?: 0) >= (targets[w.id] ?: 0)
            }

            val countedActual = if (allReached) {
                actuals.values.sum()
            } else {
                ws.sumOf { w -> minOf(actuals[w.id] ?: 0, targets[w.id] ?: 0) }
            }

            val activeWorkout = ws.firstOrNull { it.isActive } ?: ws.first()
            val progress = if (totalTarget > 0) countedActual.toDouble() / totalTarget else 0.0
            Fam(activeWorkout, countedActual, totalTarget, progress)
        }

        // <<< FIX 2: add tiebreaker so different keys don't collide when 'order' is equal
        weeklyWorkoutsByActualTarget = families
            .associate { it.active to (it.countedActual to it.totalTarget) }
            .toSortedMap(compareBy<Workout> { it.order }.thenBy { it.id })

        objectiveProgress =
            if (families.isNotEmpty()) families.map { it.progress }.average() else 0.0
    }

    LaunchedEffect(allEnabledWorkouts.map { it.id }.toSet()) {
        // #region agent log
        Log.d(TAG, "LaunchedEffect H3 effect run enabledCount=${allEnabledWorkouts.size}")
        // #endregion
        if (allEnabledWorkouts.isNotEmpty()) {
            appViewModel.loadWorkoutHistories(allEnabledWorkouts)
        }
    }

    LaunchedEffect(updateMessage, allEnabledWorkouts.map { it.id }.toSet()) {
        if (updateMessage != null && allEnabledWorkouts.isNotEmpty()) {
            appViewModel.loadWorkoutHistories(allEnabledWorkouts)
        }
    }

    LaunchedEffect(groupedWorkoutsHistories) {
        // #region agent log
        Log.d(TAG, "observeGrouped H4 isNull=${groupedWorkoutsHistories == null} groupedSize=${groupedWorkoutsHistories?.size ?: -1}")
        // #endregion
        if (groupedWorkoutsHistories != null) {
            isLoading = false
            calculateObjectiveProgress(LocalDate.now())
        }
    }

    LaunchedEffect(selectedDate) {
        isLoading = true
        calculateObjectiveProgress(selectedDate.date)
        delay(500)
        isLoading = false
    }

    fun onDayClicked(calendarState: CalendarState, day: CalendarDay) {
        scope.launch(Dispatchers.Main) {
            if (groupedWorkoutsHistories == null || workoutById == null) return@launch
            val willChangeSelection = selectedDate != day || selectedWeekAnchorDate != day.date
            if (!willChangeSelection) return@launch

            isLoading = true
            selectedWeekAnchorDate = day.date
            if (day.position != DayPosition.MonthDate) {
                calendarState.scrollToMonth(day.date.yearMonth)
                selectedDate = day
                return@launch
            }
            selectedDate = day
        }
    }

    fun highlightDay(day: CalendarDay): Boolean {
        return groupedWorkoutsHistories?.get(day.date)?.isNotEmpty() ?: false
    }

    val context = androidx.compose.ui.platform.LocalContext.current
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

    fun onMoveWorkoutUp() {
        if (selectedWorkouts.size != 1) return
        val selected = selectedWorkouts.first()
        val index = activeWorkouts.indexOfFirst { it.id == selected.id }
        if (index <= 0 || index >= activeWorkouts.size) return
        val newList = activeWorkouts.toMutableList().apply {
            val prev = this[index - 1]
            this[index - 1] = this[index]
            this[index] = prev
        }
        appViewModel.reorderWorkoutsInPlan(selectedPlanFilter, newList)
        appViewModel.scheduleWorkoutSave(context)
    }

    fun onMoveWorkoutDown() {
        if (selectedWorkouts.size != 1) return
        val selected = selectedWorkouts.first()
        val index = activeWorkouts.indexOfFirst { it.id == selected.id }
        if (index < 0 || index >= activeWorkouts.size - 1) return
        val newList = activeWorkouts.toMutableList().apply {
            val next = this[index + 1]
            this[index + 1] = this[index]
            this[index] = next
        }
        appViewModel.reorderWorkoutsInPlan(selectedPlanFilter, newList)
        appViewModel.scheduleWorkoutSave(context)
    }

    val pagerState = rememberPagerState(
        initialPage = selectedTabIndex,
        pageCount = {
            4
        }
    )

    LaunchedEffect(selectedTabIndex) {
        if (selectedTabIndex == pagerState.currentPage) {
            return@LaunchedEffect
        }
        val pageDistance = abs(selectedTabIndex - pagerState.currentPage)
        if (pageDistance > 1) {
            pagerState.scrollToPage(selectedTabIndex)
        } else {
            pagerState.animateScrollToPage(selectedTabIndex)
        }
    }

    LaunchedEffect(pagerState.currentPage) {
        if (selectedTabIndex != pagerState.currentPage) {
            appViewModel.setHomeTab(pagerState.currentPage)
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
                        onSyncClick = onSyncClick,
                        onOpenSettingsClick = onOpenSettingsClick,
                        onBackupClick = onBackupClick,
                        onRestoreClick = onRestoreClick,
                        onImportWorkoutsClick = onImportWorkoutsClick,
                        onClearUnfinishedWorkouts = onClearUnfinishedWorkouts,
                        onClearAllHistories = onClearAllHistories,
                        onSyncWithHealthConnectClick = onSyncToHealthConnectClick,
                        onExportWorkouts = onExportWorkouts,
                        onExportWorkoutPlan = onExportWorkoutPlan,
                        onExportEquipment = onExportEquipment,
                        onClearAllExerciseInfo = onClearAllExerciseInfo,
                        onViewErrorLogs = onViewErrorLogs,
                        onMenuItemClick = {
                            scope.launch {
                                drawerState.close()
                            }
                        }
                    )
                }
            }
        ) {
            Scaffold(
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
                    when (pagerState.currentPage) {
                        1 -> WorkoutsBottomBar(
                            selectedWorkouts = selectedWorkouts,
                            activeWorkouts = activeWorkouts,
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
                            onGroupedWorkoutsHistoriesChange = { appViewModel.loadWorkoutHistories(allEnabledWorkouts) },
                            onMoveWorkoutUp = { onMoveWorkoutUp() },
                            onMoveWorkoutDown = { onMoveWorkoutDown() },
                            isSelectionModeActive = isWorkoutSelectionModeActive
                        )

                        2 -> {
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

                    TabRow(
                        contentColor = MaterialTheme.colorScheme.background,
                        selectedTabIndex = pagerState.currentPage,
                        indicator = { tabPositions ->
                            TabRowDefaults.Indicator(
                                Modifier.tabIndicatorOffset(tabPositions[pagerState.currentPage]),
                                color = MaterialTheme.colorScheme.primary, // Set the indicator color
                                height = 2.dp,
                            )
                        }
                    ) {
                        tabTitles.forEachIndexed { index, title ->
                            val isSelected = index == pagerState.currentPage
                            Tab(
                                modifier = Modifier.background(MaterialTheme.colorScheme.background),
                                selected = isSelected,
                                onClick = {
                                    appViewModel.setHomeTab(index)
                                },
                                text = {
                                    Text(
                                        text = title,
                                        style = MaterialTheme.typography.bodySmall
                                    )
                                },
                                selectedContentColor = MaterialTheme.colorScheme.primary,
                                unselectedContentColor = MaterialTheme.colorScheme.onBackground,
                                interactionSource = object : MutableInteractionSource {
                                    override val interactions: Flow<Interaction> = emptyFlow()
                                    override suspend fun emit(interaction: Interaction) {
                                        // Empty implementation
                                    }

                                    override fun tryEmit(interaction: Interaction): Boolean = true
                                }
                            )
                        }
                    }

                    HorizontalPager(
                        modifier = Modifier
                            .fillMaxSize()
                            .background(MaterialTheme.colorScheme.background),
                        state = pagerState,
                    ) { pageIndex ->
                        Column(
                            modifier = Modifier
                                .fillMaxSize()
                                .background(MaterialTheme.colorScheme.background),
                            horizontalAlignment = Alignment.CenterHorizontally
                        ) {
                            HealthConnectHandler(appViewModel, healthConnectClient)

                            AnimatedContent(
                                modifier = Modifier.background(MaterialTheme.colorScheme.background),
                                targetState = pageIndex,
                                transitionSpec = {
                                    fadeIn(animationSpec = tween(500)) togetherWith fadeOut(
                                        animationSpec = tween(
                                            500
                                        )
                                    )
                                }, label = ""
                            ) { updatedSelectedTab ->
                                when (updatedSelectedTab) {
                                    0 -> {
                                        WorkoutsStatusTab(
                                            isLoading = isLoading,
                                            hasObjectives = hasObjectives,
                                            selectedDate = selectedDate,
                                            selectedWeekStart = selectedWeekStart,
                                            selectedWeekEnd = selectedWeekEnd,
                                            selectedWeekWorkoutsByDate = selectedWeekWorkoutsByDate,
                                            weeklyWorkoutsByActualTarget = weeklyWorkoutsByActualTarget,
                                            objectiveProgress = objectiveProgress,
                                            appViewModel = appViewModel,
                                            onDayClicked = { calendarState, day ->
                                                onDayClicked(
                                                    calendarState,
                                                    day
                                                )
                                            },
                                            highlightDay = { day -> highlightDay(day) },
                                            groupedWorkoutsHistories = groupedWorkoutsHistories
                                        )
                                    }

                                    1 -> {
                                        Column(modifier = Modifier.fillMaxSize()) {
                                            WorkoutPlanFilterPicker(
                                                allPlans = allPlans,
                                                selectedPlanFilter = selectedPlanFilter,
                                                onPlanSelected = { planId ->
                                                    appViewModel.setSelectedWorkoutPlanId(planId)
                                                }
                                            )
                                            WorkoutsListTab(
                                                workouts = activeWorkouts,
                                                selectedWorkouts = selectedWorkouts,
                                                isSelectionModeActive = isWorkoutSelectionModeActive,
                                                appViewModel = appViewModel,
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

                                    2 -> {
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
                                                onPlanSelected = { planId ->
                                                    appViewModel.setSelectedWorkoutPlanId(planId)
                                                }
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
        LoadingOverlay(isVisible = isSyncing, text = "Syncing...")
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
            ?: planItems.firstOrNull()?.label
            ?: "Workout Plan"
    }

    StandardFilterDropdown(
        label = "Workout Plan:",
        selectedText = selectedPlanLabel,
        items = planItems,
        onItemSelected = onPlanSelected,
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 15.dp, vertical = 8.dp),
        isItemSelected = { it == selectedPlanFilter }
    )
}
