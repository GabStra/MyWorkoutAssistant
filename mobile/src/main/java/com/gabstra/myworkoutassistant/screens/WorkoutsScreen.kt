package com.gabstra.myworkoutassistant.screens

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.interaction.Interaction
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.BottomAppBar
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.TabRowDefaults
import androidx.compose.material3.TabRowDefaults.tabIndicatorOffset
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.HealthConnectClient
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.composables.DashedCard
import com.gabstra.myworkoutassistant.composables.ExpandableContainer
import com.gabstra.myworkoutassistant.composables.GenericButtonWithMenu
import com.gabstra.myworkoutassistant.composables.GenericSelectableList
import com.gabstra.myworkoutassistant.composables.HealthConnectHandler
import com.gabstra.myworkoutassistant.composables.MenuItem
import com.gabstra.myworkoutassistant.composables.ObjectiveProgressBar
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.composables.WorkoutsCalendar
import com.gabstra.myworkoutassistant.getEndOfWeek
import com.gabstra.myworkoutassistant.getStartOfWeek
import com.gabstra.myworkoutassistant.shared.MuscleGroup
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbells
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.equipments.toDisplayText
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.verticalColumnScrollbar
import com.gabstra.myworkoutassistant.workout.MuscleHeatMap
import com.gabstra.myworkoutassistant.workout.MuscleViewMode
import com.google.accompanist.permissions.ExperimentalPermissionsApi
import com.kizitonwose.calendar.compose.CalendarState
import com.kizitonwose.calendar.core.CalendarDay
import com.kizitonwose.calendar.core.DayPosition
import com.kizitonwose.calendar.core.yearMonth
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale
import java.util.UUID


@OptIn(ExperimentalPermissionsApi::class)
@Composable
fun Menu(
    onSyncClick: () -> Unit,
    onBackupClick: () -> Unit,
    onRestoreClick: () -> Unit,
    onOpenSettingsClick: () -> Unit,
    onClearUnfinishedWorkouts: () -> Unit,
    onClearAllHistories: () -> Unit,
    onSyncWithHealthConnectClick: () -> Unit,
    onExportWorkouts: () -> Unit,
    onClearAllExerciseInfo: () -> Unit,
    onViewErrorLogs: () -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }

    Box(
        modifier = Modifier.wrapContentSize(Alignment.TopEnd)
    ) {
        IconButton(onClick = { expanded = !expanded }) {
            Icon(
                imageVector = Icons.Default.MoreVert,
                contentDescription = "More"
            )
        }
        StyledCard {
            DropdownMenu(
                expanded = expanded,
                onDismissRequest = { expanded = false },
                modifier = Modifier.background(MaterialTheme.colorScheme.surface),
                border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant)
            ) {
                DropdownMenuItem(
                    text = { Text("Settings") },
                    onClick = {
                        onOpenSettingsClick()
                        expanded = false
                    }
                )
                DropdownMenuItem(
                    text = { Text("Sync with Watch") },
                    onClick = {
                        onSyncClick()
                        expanded = false
                    }
                )
                DropdownMenuItem(
                    text = { Text("Sync with Health Connect") },
                    onClick = {
                        onSyncWithHealthConnectClick()
                        expanded = false
                    }
                )
                DropdownMenuItem(
                    text = { Text("Export Workouts") },
                    onClick = {
                        onExportWorkouts()
                        expanded = false
                    }
                )
                DropdownMenuItem(
                    text = { Text("Save Backup") },
                    onClick = {
                        onBackupClick()
                        expanded = false
                    }
                )
                DropdownMenuItem(
                    text = { Text("Restore Backup") },
                    onClick = {
                        onRestoreClick()
                        expanded = false
                    }
                )
                DropdownMenuItem(
                    text = { Text("Clear all incomplete workouts") },
                    onClick = {
                        onClearUnfinishedWorkouts()
                        expanded = false
                    }
                )
                DropdownMenuItem(
                    text = { Text("Clear history") },
                    onClick = {
                        onClearAllHistories()
                        expanded = false
                    }
                )
                DropdownMenuItem(
                    text = { Text("Clear all exercise info") },
                    onClick = {
                        onClearAllExerciseInfo()
                        expanded = false
                    }
                )
                DropdownMenuItem(
                    text = { Text("View Error Logs") },
                    onClick = {
                        onViewErrorLogs()
                        expanded = false
                    }
                )
            }
        }
    }

}

/**
 * Aggregates all muscle groups from all workouts.
 * Includes muscle groups from exercises and exercises within Supersets.
 */
fun aggregateAllMuscleGroups(workouts: List<Workout>): Set<MuscleGroup> {
    val allMuscleGroups = mutableSetOf<MuscleGroup>()
    
    workouts.forEach { workout ->
        workout.workoutComponents.forEach { component ->
            when (component) {
                is Exercise -> {
                    component.muscleGroups?.let { muscleGroups ->
                        allMuscleGroups.addAll(muscleGroups)
                    }
                }
                is Superset -> {
                    component.exercises.forEach { exercise ->
                        exercise.muscleGroups?.let { muscleGroups ->
                            allMuscleGroups.addAll(muscleGroups)
                        }
                    }
                }
                else -> { /* Rest or other components don't have muscle groups */ }
            }
        }
    }
    
    return allMuscleGroups
}

@Composable
fun WorkoutTitle(
    modifier: Modifier,
    workout: Workout,
    content: @Composable () -> Unit = {},
    style: TextStyle = MaterialTheme.typography.bodyLarge
) {
    Row(
        horizontalArrangement = Arrangement.SpaceBetween,
        modifier = modifier,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            modifier = Modifier
                .weight(1f)
                .basicMarquee(iterations = Int.MAX_VALUE),
            text = workout.name,
            color = if (workout.enabled) MaterialTheme.colorScheme.onBackground else MaterialTheme.colorScheme.onSurfaceVariant,
            style = style,
        )
        content()
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WorkoutsScreen(
    appViewModel: AppViewModel,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    healthConnectClient: HealthConnectClient,
    onSyncClick: () -> Unit,
    onBackupClick: () -> Unit,
    onRestoreClick: () -> Unit,
    onOpenSettingsClick: () -> Unit,
    onClearUnfinishedWorkouts: () -> Unit,
    onClearAllHistories: () -> Unit,
    onSyncToHealthConnectClick: () -> Unit,
    onExportWorkouts: () -> Unit,
    onClearAllExerciseInfo: () -> Unit,
    onViewErrorLogs: () -> Unit,
    selectedTabIndex: Int
) {
    val updateMessage by appViewModel.updateNotificationFlow.collectAsState(initial = null)

    var isLoading by remember { mutableStateOf(true) }

    val workouts by appViewModel.workoutsFlow.collectAsState()

    val equipments by appViewModel.equipmentsFlow.collectAsState()

    val enabledWorkouts = workouts.filter { it.enabled }

    val activeAndEnabledWorkouts =
        workouts.filter { it.enabled && it.isActive }.sortedBy { it.order }

    val activeWorkouts = workouts.filter { it.isActive }.sortedBy { it.order }

    val timesCompletedInAWeekObjective =
        enabledWorkouts.filter { it.timesCompletedInAWeek != null && it.timesCompletedInAWeek != 0 }
            .associate { workout ->
                workout.id to (workout.timesCompletedInAWeek ?: 0)
            }

    val hasObjectives = timesCompletedInAWeekObjective.values.any { it > 0 }

    var selectedWorkouts by remember { mutableStateOf(listOf<Workout>()) }
    var isWorkoutSelectionModeActive by remember { mutableStateOf(false) }

    var selectedEquipments by remember { mutableStateOf(listOf<WeightLoadedEquipment>()) }
    var isEquipmentSelectionModeActive by remember { mutableStateOf(false) }

    var objectiveProgress by remember { mutableStateOf(0.0) }

    var selectedDay by remember {
        mutableStateOf<LocalDate>(LocalDate.now())
    }

    var groupedWorkoutsHistories by remember {
        mutableStateOf<Map<LocalDate, List<WorkoutHistory>>?>(
            null
        )
    }
    var workoutById by remember { mutableStateOf<Map<UUID, Workout>?>(null) }

    var weeklyWorkoutsByActualTarget by remember {
        mutableStateOf<Map<Workout, Pair<Int, Int>>?>(
            null
        )
    }

    var selectedCalendarWorkouts by remember {
        mutableStateOf<List<Pair<WorkoutHistory, Workout>>?>(
            null
        )
    }

    var isCardExpanded by remember {
        mutableStateOf(false)
    }

    val currentLocale = Locale.getDefault()

    val formatter = remember(currentLocale) {
        DateTimeFormatter.ofPattern("dd/MM/yy", currentLocale)
    }

    val scope = rememberCoroutineScope()

    val tabTitles = listOf("Status", "Workouts", "Equipments")

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
        if (enabledWorkouts.isEmpty()) return

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
        val eligibleById = enabledWorkouts
            .filter { it.timesCompletedInAWeek != null && it.timesCompletedInAWeek != 0 }
            .associateBy { it.id }

        val weeklyWorkouts = workoutHistoriesInAWeek
            .mapNotNull { eligibleById[it.workoutId] }
            .distinctBy { it.id }   // <<< FIX 1

        val uniqueGlobalIds = weeklyWorkouts.map { it.globalId }.toSet()

        val totalWeeklyWorkouts = weeklyWorkouts +
                activeAndEnabledWorkouts.filter {
                    it.globalId !in uniqueGlobalIds && it.timesCompletedInAWeek != null && it.timesCompletedInAWeek != 0
                }

        val workoutsByGlobalId = totalWeeklyWorkouts.groupBy { it.globalId }
        val actualCountsByWorkoutId = workoutHistoriesInAWeek.groupingBy { it.workoutId }.eachCount()

        data class Fam(val active: Workout, val countedActual: Int, val totalTarget: Int, val progress: Double)

        val families: List<Fam> = workoutsByGlobalId.map { (_, wsRaw) ->
            val ws = wsRaw.distinctBy { it.id } // <<< Safety de-dupe
            val targets = ws.associate { w -> w.id to (timesCompletedInAWeekObjective[w.id] ?: 0) }
            val actuals = ws.associate { w -> w.id to (actualCountsByWorkoutId[w.id] ?: 0) }

            val totalTarget = targets.values.sum()
            val allReached = ws.all { w -> (targets[w.id] ?: 0) <= 0 || (actuals[w.id] ?: 0) >= (targets[w.id] ?: 0) }

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

        objectiveProgress = if (families.isNotEmpty()) families.map { it.progress }.average() else 0.0
    }

    LaunchedEffect(enabledWorkouts, updateMessage) {
        isLoading = true
        groupedWorkoutsHistories =
            workoutHistoryDao.getAllWorkoutHistories().filter { workoutHistory ->
                enabledWorkouts.any { it.id == workoutHistory.workoutId }
            }.groupBy { it.date }
        workoutById = enabledWorkouts.associateBy { it.id }

        val workoutHistories = groupedWorkoutsHistories?.get(selectedDay)

        selectedCalendarWorkouts = try {
            workoutHistories?.map { workoutHistory ->
                Pair(workoutHistory, workoutById?.get(workoutHistory.workoutId)!!)
            } ?: emptyList()
        } catch (e: Exception) {
            emptyList()
        }

        calculateObjectiveProgress(LocalDate.now())
        delay(500)
        isLoading = false
    }

    LaunchedEffect(selectedDate) {
        if (selectedDate == null) return@LaunchedEffect

        isLoading = true
        calculateObjectiveProgress(selectedDate!!.date)
        delay(500)
        isLoading = false
    }

    fun onDayClicked(calendarState: CalendarState, day: CalendarDay) {
        scope.launch(Dispatchers.Main) {
            if (groupedWorkoutsHistories == null || workoutById == null) return@launch
            isLoading = true

            selectedDay = day.date
            val workoutHistories = groupedWorkoutsHistories?.get(selectedDay)

            selectedCalendarWorkouts = try {
                workoutHistories?.map { workoutHistory ->
                    Pair(workoutHistory, workoutById?.get(workoutHistory.workoutId)!!)
                } ?: emptyList()
            } catch (e: Exception) {
                emptyList()
            }

            if (day.position != DayPosition.MonthDate) {
                calendarState.scrollToMonth(selectedDay.yearMonth)
                selectedDate = day
                return@launch
            }


            selectedDate = day
        }
    }

    fun highlightDay(day: CalendarDay): Boolean {
        return groupedWorkoutsHistories?.get(day.date)?.isNotEmpty() ?: false
    }

    fun getHighlightColor(day: CalendarDay): Color {
        val workoutsDoneCount = groupedWorkoutsHistories?.get(day.date)?.size ?: 0

        return when {
            workoutsDoneCount <= 0 -> Color.Transparent
            workoutsDoneCount == 1 -> Color(0xFFff6700)
            workoutsDoneCount == 2 -> Color(0xFFff6700)
            workoutsDoneCount >= 3 -> Color(0xFFff6700)
            else -> Color.Transparent
        }
    }

    @Composable
    fun workoutsBottomBar(){
        if (selectedWorkouts.isNotEmpty()) {
            StyledCard{
                BottomAppBar(
                    contentPadding = PaddingValues(0.dp),
                    containerColor = Color.Transparent,
                    actions = {
                        Row(
                            modifier = Modifier.fillMaxSize(),
                            horizontalArrangement = Arrangement.SpaceEvenly,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            IconButton(
                                onClick = {
                                    val newWorkouts =
                                        activeAndEnabledWorkouts.filter { workout ->
                                            selectedWorkouts.none { it.id == workout.id }
                                        }

                                    val newWorkoutsWithUpdatedOrder =
                                        newWorkouts.mapIndexed { index, workout ->
                                            workout.copy(
                                                order = index
                                            )
                                        }

                                    appViewModel.updateWorkouts(newWorkoutsWithUpdatedOrder)
                                    scope.launch(Dispatchers.IO) {
                                        for (workout in selectedWorkouts) {
                                            val workoutHistories =
                                                workoutHistoryDao.getWorkoutsByWorkoutId(
                                                    workout.id
                                                )
                                            for (workoutHistory in workoutHistories) {
                                                setHistoryDao.deleteByWorkoutHistoryId(
                                                    workoutHistory.id
                                                )
                                            }
                                            workoutHistoryDao.deleteAllByWorkoutId(workout.id)
                                        }
                                        groupedWorkoutsHistories =
                                            workoutHistoryDao.getAllWorkoutHistories()
                                                .groupBy { it.date }
                                    }
                                    selectedWorkouts = emptyList()
                                    isWorkoutSelectionModeActive = false
                                }
                            ) {
                                Icon(
                                    imageVector = Icons.Default.Delete,
                                    contentDescription = "Delete",
                                    tint = MaterialTheme.colorScheme.onBackground
                                )
                            }
                            Button(
                                modifier = Modifier.padding(5.dp),
                                colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
                                onClick = {
                                    for (workout in selectedWorkouts) {
                                        appViewModel.updateWorkoutOld(
                                            workout,
                                            workout.copy(enabled = true)
                                        )
                                    }
                                    selectedWorkouts = emptyList()
                                    isWorkoutSelectionModeActive = false
                                }) {
                                Text("Enable")
                            }
                            Button(
                                colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
                                modifier = Modifier.padding(5.dp),
                                onClick = {
                                    for (workout in selectedWorkouts) {
                                        appViewModel.updateWorkoutOld(
                                            workout,
                                            workout.copy(enabled = false)
                                        )
                                    }
                                    selectedWorkouts = emptyList()
                                    isWorkoutSelectionModeActive = false
                                }) {
                                Text("Disable")
                            }

                        }
                    }
                )
            }
        }
    }

    @Composable
    fun equipmentsBottomBar(){
        if(selectedEquipments.isNotEmpty()){
            StyledCard {
                BottomAppBar(
                    contentPadding = PaddingValues(0.dp),
                    containerColor = Color.Transparent,
                    actions = {
                        Row(
                            modifier = Modifier.fillMaxSize(),
                            horizontalArrangement = Arrangement.SpaceEvenly,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            IconButton(onClick = {
                                val newEquipments = selectedEquipments.map { it ->
                                    when (it.type){
                                        EquipmentType.GENERIC -> throw NotImplementedError()
                                        EquipmentType.BARBELL -> Barbell(UUID.randomUUID(), it.name + " (Copy)", (it as Barbell).availablePlates, it.barLength,it.barWeight)
                                        EquipmentType.DUMBBELLS -> Dumbbells(UUID.randomUUID(), it.name + " (Copy)", (it as Dumbbells).availableDumbbells, it.extraWeights, it.maxExtraWeightsPerLoadingPoint)
                                        EquipmentType.DUMBBELL -> TODO()
                                        EquipmentType.PLATELOADEDCABLE -> TODO()
                                        EquipmentType.WEIGHTVEST -> TODO()
                                        EquipmentType.MACHINE -> TODO()
                                        EquipmentType.IRONNECK -> TODO()
                                    }
                                }

                                val newTotalEquipments = equipments + newEquipments

                                appViewModel.updateEquipments(newTotalEquipments)
                                isEquipmentSelectionModeActive = false
                            }) {
                                Icon(imageVector = Icons.Default.ContentCopy, contentDescription = "Copy",tint = MaterialTheme.colorScheme.onBackground)
                            }
                            IconButton(onClick = {
                                val newEquipments = equipments.filter { item ->
                                    selectedEquipments.none { it.id == item.id }
                                }
                                appViewModel.updateEquipments(newEquipments)
                                isEquipmentSelectionModeActive = false
                            }) {
                                Icon(imageVector = Icons.Default.Delete, contentDescription = "Delete",tint = MaterialTheme.colorScheme.onBackground)
                            }
                        }
                    }
                )
            }
        }
    }

    val pagerState = rememberPagerState(
        initialPage = selectedTabIndex,
        pageCount = {
            3
        }
    )

    LaunchedEffect(selectedTabIndex) {
        pagerState.scrollToPage(selectedTabIndex)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background, titleContentColor = MaterialTheme.colorScheme.onBackground),
                title = {
                    Text(
                        modifier = Modifier
                            .fillMaxWidth()
                            .basicMarquee(iterations = Int.MAX_VALUE),
                        text = "My Workout Assistant", textAlign = TextAlign.Center,
                    )
                },
                navigationIcon = {
                    IconButton(modifier = Modifier.alpha(0f), onClick = {}) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back"
                        )
                    }
                },
                actions = {
                    Menu(
                        onSyncClick = onSyncClick,
                        onOpenSettingsClick = onOpenSettingsClick,
                        onBackupClick = onBackupClick,
                        onRestoreClick = onRestoreClick,
                        onClearUnfinishedWorkouts = onClearUnfinishedWorkouts,
                        onClearAllHistories = onClearAllHistories,
                        onSyncWithHealthConnectClick = onSyncToHealthConnectClick,
                        onExportWorkouts = onExportWorkouts,
                        onClearAllExerciseInfo = onClearAllExerciseInfo,
                        onViewErrorLogs = onViewErrorLogs
                    )
                }
            )
        },
        bottomBar = {
            when(pagerState.currentPage){
                1 -> workoutsBottomBar()
                2 -> equipmentsBottomBar()
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
                        text = { Text(text = title) },
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
                                val scrollState = rememberScrollState()

                                Column(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(top = 10.dp)
                                        .verticalColumnScrollbar(scrollState)
                                        .verticalScroll(scrollState)
                                        .padding(horizontal = 15.dp),
                                    verticalArrangement = Arrangement.spacedBy(10.dp)
                                ) {
                                    StyledCard {
                                        WorkoutsCalendar(
                                            selectedDate = selectedDate,
                                            onDayClicked = { calendarState, day ->
                                                onDayClicked(calendarState, day)
                                            },
                                            shouldHighlight = { day -> highlightDay(day) },
                                            getHighlightColor = { day -> getHighlightColor(day) }
                                        )
                                    }
                                    if (isLoading) {
                                        Box(
                                            modifier = Modifier
                                                .fillMaxSize().padding(10.dp),
                                            contentAlignment = Alignment.Center
                                        ) {
                                            CircularProgressIndicator(
                                                modifier = Modifier.width(32.dp),
                                                color = MaterialTheme.colorScheme.primary,
                                                trackColor = MaterialTheme.colorScheme.background,
                                            )
                                        }
                                    } else {
                                        if (hasObjectives) {
                                            val currentDate = selectedDate.date

                                            val startWeekDate =  getStartOfWeek(currentDate)
                                            val startWeekMonth = startWeekDate.format(DateTimeFormatter.ofPattern("MMM"))
                                            val endWeekDate = getEndOfWeek(currentDate)
                                            val endWeekMonth = endWeekDate.format(DateTimeFormatter.ofPattern("MMM"))

                                            val dateText = if(startWeekMonth == endWeekMonth) {
                                                "${startWeekDate.dayOfMonth} - ${endWeekDate.dayOfMonth} $startWeekMonth"
                                            }else{
                                                "${startWeekDate.dayOfMonth} $startWeekMonth - ${endWeekDate.dayOfMonth} $endWeekMonth"
                                            }

                                            StyledCard {
                                                Column(
                                                    modifier = Modifier
                                                        .fillMaxWidth()
                                                        .padding(10.dp),
                                                    verticalArrangement = Arrangement.spacedBy(5.dp)
                                                ) {
                                                    Text(
                                                        modifier = Modifier.fillMaxWidth(),
                                                        text = "Weekly progress (${dateText}):",
                                                        style = MaterialTheme.typography.titleMedium,
                                                        textAlign = TextAlign.Center,
                                                        color = MaterialTheme.colorScheme.onBackground
                                                    )
                                                    ExpandableContainer(
                                                        isOpen = false,
                                                        isExpandable = if (weeklyWorkoutsByActualTarget == null) false else weeklyWorkoutsByActualTarget!!.isNotEmpty(),
                                                        title = { modifier ->
                                                            Row(
                                                                modifier = modifier
                                                                    .fillMaxWidth()
                                                                    .padding(10.dp),
                                                                horizontalArrangement = Arrangement.Center,
                                                                verticalAlignment = Alignment.CenterVertically
                                                            ) {
                                                                Text(
                                                                    text = "${(objectiveProgress * 100).toInt()}%",
                                                                    style = MaterialTheme.typography.titleMedium,
                                                                    textAlign = TextAlign.Center,
                                                                    color = MaterialTheme.colorScheme.onBackground,
                                                                )
                                                                Spacer(modifier = Modifier.width(10.dp))
                                                                ObjectiveProgressBar(
                                                                    Modifier.weight(1f),
                                                                    progress = objectiveProgress.toFloat()
                                                                )
                                                            }
                                                        }, content = {
                                                            Column(
                                                                modifier = Modifier
                                                                    .fillMaxWidth()
                                                                    .padding(10.dp),
                                                                verticalArrangement = Arrangement.spacedBy(
                                                                    10.dp
                                                                )
                                                            ) {
                                                                weeklyWorkoutsByActualTarget?.entries?.forEachIndexed { index, (workout, pair) ->
                                                                    Row(
                                                                        horizontalArrangement = Arrangement.SpaceBetween
                                                                    ) {
                                                                        Text(
                                                                            text = workout.name,
                                                                            modifier = Modifier.weight(
                                                                                1f
                                                                            ),
                                                                            color = MaterialTheme.colorScheme.onBackground,
                                                                            style = MaterialTheme.typography.bodyLarge,
                                                                        )
                                                                        Text(
                                                                            text = "${pair.first}/${pair.second}",
                                                                            color = MaterialTheme.colorScheme.onBackground,
                                                                            style = MaterialTheme.typography.bodyLarge,
                                                                        )
                                                                    }
                                                                }
                                                            }
                                                        })
                                                }
                                            }
                                        }
                                        StyledCard {
                                            Column(
                                                modifier = Modifier
                                                    .fillMaxWidth()
                                                    .padding(10.dp),
                                                verticalArrangement = Arrangement.spacedBy(10.dp)
                                            ) {
                                                val currentDate = selectedDate.date
                                                val currentMonth =
                                                    currentDate.format(DateTimeFormatter.ofPattern("MMM"))

                                                Text(
                                                    modifier = Modifier.fillMaxWidth(),
                                                    text = "Workout Histories (${currentDate.dayOfMonth} ${currentMonth}):",
                                                    style = MaterialTheme.typography.titleMedium,
                                                    textAlign = TextAlign.Center,
                                                    color = MaterialTheme.colorScheme.onBackground
                                                )

                                                if (selectedCalendarWorkouts.isNullOrEmpty()) {
                                                    Box(
                                                        modifier = Modifier
                                                            .fillMaxSize(),
                                                        contentAlignment = Alignment.Center
                                                    ) {
                                                        Text(
                                                            modifier = Modifier
                                                                .padding(15.dp),
                                                            text = "No workouts on this day",
                                                            textAlign = TextAlign.Center,
                                                            color = MaterialTheme.colorScheme.onBackground,
                                                        )
                                                    }
                                                } else {
                                                    val timeFormatter = remember(currentLocale) {
                                                        DateTimeFormatter.ofPattern(
                                                            "HH:mm",
                                                            currentLocale
                                                        )
                                                    }
                                                    selectedCalendarWorkouts!!
                                                        .groupBy { it.second.id } // Group by workout.id
                                                        .forEach { (workoutId, historyAndWorkoutList) ->
                                                            val moreThanOneWorkout = historyAndWorkoutList.size > 1

                                                            //create a composable that takes workout history and workout
                                                            @Composable
                                                            fun WorkoutHistoryCard(workoutHistory: WorkoutHistory, workout: Workout){
                                                                Row(
                                                                    verticalAlignment = Alignment.CenterVertically,
                                                                    horizontalArrangement = Arrangement.spacedBy(10.dp)
                                                                ) {
                                                                    IconButton(
                                                                        modifier= Modifier.clip(CircleShape).size(35.dp),
                                                                        onClick = {
                                                                            appViewModel.setScreenData(
                                                                                ScreenData.WorkoutHistory(
                                                                                    workout.id,
                                                                                    workoutHistory.id
                                                                                )
                                                                            )
                                                                        }) {
                                                                        Icon(

                                                                            imageVector = Icons.Filled.Search,
                                                                            contentDescription = "Details",
                                                                            tint = MaterialTheme.colorScheme.onBackground
                                                                        )
                                                                    }

                                                                    Text(
                                                                        modifier = Modifier
                                                                            .weight(1f)
                                                                            .basicMarquee(iterations = Int.MAX_VALUE),
                                                                        text = if(workoutHistory.isDone) workout.name else workout.name + " (Incomplete)",
                                                                        color = if (workout.enabled) MaterialTheme.colorScheme.onBackground else MaterialTheme.colorScheme.onSurfaceVariant,
                                                                        style = MaterialTheme.typography.bodyLarge,
                                                                    )

                                                                    if (workoutHistory.isDone) {
                                                                        Text(
                                                                            text = workoutHistory.time.format(
                                                                                timeFormatter
                                                                            ),
                                                                            textAlign = TextAlign.End,
                                                                            color = MaterialTheme.colorScheme.onBackground,
                                                                            style = MaterialTheme.typography.bodyLarge,
                                                                        )
                                                                    }
                                                                }
                                                            }

                                                            if(moreThanOneWorkout){
                                                                val workout = historyAndWorkoutList[0].second
                                                                ExpandableContainer(
                                                                    title = { modifier ->
                                                                        Row(
                                                                            modifier = modifier,
                                                                            verticalAlignment = Alignment.CenterVertically,
                                                                            horizontalArrangement = Arrangement.spacedBy(10.dp)
                                                                        ) {
                                                                            Box(
                                                                                modifier = Modifier
                                                                                    .clip(CircleShape)
                                                                                    .size(30.dp)
                                                                                    .background(MaterialTheme.colorScheme.primary),
                                                                                contentAlignment = Alignment.Center
                                                                            ){
                                                                                Text(
                                                                                    modifier = Modifier.fillMaxWidth(),
                                                                                    text =  historyAndWorkoutList.size.toString(),
                                                                                    color = MaterialTheme.colorScheme.background,
                                                                                    textAlign = TextAlign.Center,
                                                                                    style = MaterialTheme.typography.titleMedium
                                                                                )
                                                                            }

                                                                            Text(
                                                                                modifier = Modifier
                                                                                    .weight(1f)
                                                                                    .padding(start = 5.dp)
                                                                                    .basicMarquee(iterations = Int.MAX_VALUE),
                                                                                text = workout.name,
                                                                                color = if (workout.enabled) MaterialTheme.colorScheme.onBackground else MaterialTheme.colorScheme.onSurfaceVariant,
                                                                                style = MaterialTheme.typography.bodyLarge,
                                                                            )
                                                                        }
                                                                    },
                                                                    content = {
                                                                        DashedCard {
                                                                            Column(
                                                                                modifier = Modifier
                                                                                    .fillMaxWidth()
                                                                                    .padding(10.dp),
                                                                                verticalArrangement = Arrangement.spacedBy(
                                                                                    10.dp
                                                                                )
                                                                            ) {
                                                                                historyAndWorkoutList.forEach { (workoutHistory, workout) ->
                                                                                    WorkoutHistoryCard(
                                                                                        workoutHistory,
                                                                                        workout
                                                                                    )
                                                                                }
                                                                            }
                                                                        }
                                                                    }
                                                                )
                                                            }else{
                                                                val workoutHistory = historyAndWorkoutList[0].first
                                                                val workout = historyAndWorkoutList[0].second

                                                                WorkoutHistoryCard(workoutHistory,workout)
                                                            }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            1 -> {
                                val scrollState = rememberScrollState()
                                
                                // Aggregate all muscle groups from all workouts
                                val allMuscleGroups = remember(workouts) {
                                    aggregateAllMuscleGroups(workouts)
                                }
                                
                                // Determine view mode based on available muscle groups
                                val hasFrontMuscles = remember(allMuscleGroups) {
                                    allMuscleGroups.any { it.name.startsWith("FRONT_") }
                                }
                                val hasBackMuscles = remember(allMuscleGroups) {
                                    allMuscleGroups.any { it.name.startsWith("BACK_") }
                                }
                                val effectiveViewMode = remember(hasFrontMuscles, hasBackMuscles) {
                                    when {
                                        hasFrontMuscles && hasBackMuscles -> MuscleViewMode.BOTH
                                        hasFrontMuscles -> MuscleViewMode.FRONT_ONLY
                                        hasBackMuscles -> MuscleViewMode.BACK_ONLY
                                        else -> MuscleViewMode.BOTH
                                    }
                                }

                                Column(
                                    modifier = Modifier
                                        .fillMaxSize()
                                        .padding(top = 10.dp)
                                        .verticalColumnScrollbar(scrollState)
                                        .verticalScroll(scrollState)
                                        .padding(horizontal = 15.dp),
                                    verticalArrangement = Arrangement.spacedBy(5.dp)
                                ) {
                                    // Display all muscle groups
                                    StyledCard(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .padding(horizontal = 5.dp)
                                    ) {
                                        Column(
                                            modifier = Modifier.padding(vertical = 5.dp)
                                        ) {
                                            Text(
                                                modifier = Modifier.fillMaxWidth(),
                                                text = "All Muscle Groups",
                                                style = MaterialTheme.typography.titleMedium,
                                                textAlign = TextAlign.Center,
                                                color = MaterialTheme.colorScheme.onBackground
                                            )
                                            
                                            if (allMuscleGroups.isEmpty()) {
                                                Text(
                                                    text = "No muscle groups found in workouts",
                                                    style = MaterialTheme.typography.bodySmall,
                                                    color = MaterialTheme.colorScheme.onBackground,
                                                    textAlign = TextAlign.Center,
                                                    modifier = Modifier.fillMaxWidth()
                                                )
                                            } else {
                                                MuscleHeatMap(
                                                    modifier = Modifier
                                                        .fillMaxWidth()
                                                        .height(300.dp),
                                                    activeMuscles = allMuscleGroups,
                                                    viewMode = effectiveViewMode,
                                                    highlightColor = MaterialTheme.colorScheme.primary,
                                                    baseColor = MaterialTheme.colorScheme.surface,
                                                    outlineColor = MaterialTheme.colorScheme.surface
                                                )
                                            }
                                        }
                                    }
                                    
                                    if (activeAndEnabledWorkouts.isEmpty()) {
                                        Row(
                                            modifier = Modifier.fillMaxWidth().padding(5.dp),
                                            horizontalArrangement = Arrangement.Center,
                                            verticalAlignment = Alignment.CenterVertically
                                        ) {
                                            Button(
                                                colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
                                                onClick = {
                                                    appViewModel.setScreenData(ScreenData.NewWorkout());
                                                },
                                            ) {
                                                Text("Add Workout")
                                            }
                                        }
                                    } else {
                                        GenericSelectableList(
                                            PaddingValues(0.dp, 10.dp),
                                            items = activeWorkouts,
                                            selectedItems = selectedWorkouts,
                                            isWorkoutSelectionModeActive,
                                            onItemClick = {
                                                if (isCardExpanded) return@GenericSelectableList
                                                appViewModel.setScreenData(
                                                    ScreenData.WorkoutDetail(
                                                        it.id
                                                    )
                                                )
                                            },
                                            onEnableSelection = {
                                                isWorkoutSelectionModeActive = true
                                            },
                                            onDisableSelection = {
                                                isWorkoutSelectionModeActive = false
                                            },
                                            onSelectionChange = { newSelection ->
                                                selectedWorkouts = newSelection
                                            },
                                            onOrderChange = { newWorkouts ->
                                                val workoutsWithOrderUpdated =
                                                    newWorkouts.mapIndexed { index, workout ->
                                                        workout.copy(
                                                            order = index
                                                        )
                                                    }
                                                appViewModel.updateWorkouts(workoutsWithOrderUpdated)
                                            },
                                            itemContent = { it ->
                                                StyledCard {
                                                    WorkoutTitle(
                                                        Modifier.padding(15.dp),
                                                        it
                                                    )
                                                }
                                            },
                                            isDragDisabled = true
                                        )
                                        Row(
                                            modifier = Modifier.fillMaxWidth(),
                                            horizontalArrangement = Arrangement.Center, // Space items evenly, including space at the edges
                                            verticalAlignment = Alignment.CenterVertically // Center items vertically within the Row
                                        ) {
                                            Button(
                                                colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
                                                onClick = {
                                                    appViewModel.setScreenData(ScreenData.NewWorkout());
                                                },
                                            ) {
                                                Icon(
                                                    imageVector = Icons.Filled.Add,
                                                    contentDescription = "Add",
                                                    tint = MaterialTheme.colorScheme.background,
                                                )
                                            }
                                        }
                                    }

                                }
                            }

                            2 -> {
                                val scrollState = rememberScrollState()

                                Column(
                                    modifier = Modifier
                                        .fillMaxSize()
                                        .padding(top = 10.dp)
                                        .verticalColumnScrollbar(scrollState)
                                        .verticalScroll(scrollState)
                                        .padding(horizontal = 15.dp)
                                ) {
                                    if (equipments.isEmpty()) {
                                        Row(
                                            modifier = Modifier.fillMaxWidth().padding(5.dp),
                                            horizontalArrangement = Arrangement.Center, // Space items evenly, including space at the edges
                                            verticalAlignment = Alignment.CenterVertically // Center items vertically within the Row
                                        ) {
                                            GenericButtonWithMenu(
                                                menuItems = EquipmentType.entries.filter { it != EquipmentType.GENERIC }.map { equipmentType ->
                                                    MenuItem("Add ${equipmentType.toDisplayText()}") {
                                                        appViewModel.setScreenData(
                                                            ScreenData.NewEquipment(equipmentType)
                                                        )
                                                    }
                                                }.toList(),
                                                content = {
                                                    Text("Add Equipment")
                                                }
                                            )
                                        }
                                    } else {
                                        GenericSelectableList(
                                            PaddingValues(0.dp, 10.dp),
                                            items = equipments,
                                            selectedItems = selectedEquipments,
                                            isEquipmentSelectionModeActive,
                                            onItemClick = { equipment ->
                                                appViewModel.setScreenData(
                                                    ScreenData.EditEquipment(
                                                        equipment.id,
                                                        equipment.type
                                                    )
                                                )
                                            },
                                            onEnableSelection = {
                                                isEquipmentSelectionModeActive = true
                                            },
                                            onDisableSelection = {
                                                isEquipmentSelectionModeActive = false
                                            },
                                            onSelectionChange = { newSelection ->
                                                selectedEquipments = newSelection
                                            },
                                            onOrderChange = { },
                                            itemContent = { it ->
                                                StyledCard {
                                                    Text(
                                                        modifier = Modifier
                                                            .fillMaxSize()
                                                            .padding(15.dp)
                                                            .basicMarquee(iterations = Int.MAX_VALUE),
                                                        text = it.name,
                                                        color = Color.White.copy(alpha = .87f),
                                                        style = MaterialTheme.typography.bodyLarge,
                                                    )
                                                }
                                            },
                                            isDragDisabled = true
                                        )
                                        Row(
                                            modifier = Modifier.fillMaxWidth(),
                                            horizontalArrangement = Arrangement.Center, // Space items evenly, including space at the edges
                                            verticalAlignment = Alignment.CenterVertically // Center items vertically within the Row
                                        ) {
                                            GenericButtonWithMenu(
                                                menuItems = EquipmentType.entries.filter { it != EquipmentType.GENERIC }.map { equipmentType ->
                                                    MenuItem("Add ${equipmentType.toDisplayText()}") {
                                                        appViewModel.setScreenData(
                                                            ScreenData.NewEquipment(equipmentType)
                                                        )
                                                    }
                                                }.toList(),
                                                content = {
                                                    Icon(
                                                        imageVector = Icons.Filled.Add,
                                                        contentDescription = "Add",
                                                        tint = MaterialTheme.colorScheme.background,
                                                    )
                                                }
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


    }
}
