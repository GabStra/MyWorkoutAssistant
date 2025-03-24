package com.gabstra.myworkoutassistant.screens

import android.os.Build
import androidx.annotation.RequiresApi
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.indication
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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width

import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.verticalScroll

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.MoreVert

import androidx.compose.material3.BottomAppBar
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults

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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.HealthConnectClient
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.composables.ExpandableContainer
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.composables.DarkModeContainer
import com.gabstra.myworkoutassistant.composables.GenericButtonWithMenu
import com.gabstra.myworkoutassistant.composables.GenericSelectableList
import com.gabstra.myworkoutassistant.composables.HealthConnectHandler
import com.gabstra.myworkoutassistant.composables.MenuItem
import com.gabstra.myworkoutassistant.composables.ObjectiveProgressBar
import com.gabstra.myworkoutassistant.composables.WorkoutsCalendar
import com.gabstra.myworkoutassistant.getEndOfWeek
import com.gabstra.myworkoutassistant.getStartOfWeek
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbells
import com.gabstra.myworkoutassistant.shared.equipments.Equipment
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.google.accompanist.permissions.ExperimentalPermissionsApi
import com.kizitonwose.calendar.compose.weekcalendar.WeekCalendarState
import com.kizitonwose.calendar.core.WeekDay
import com.kizitonwose.calendar.core.WeekDayPosition
import kotlinx.coroutines.Dispatchers
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.CircularProgressIndicator
import com.kizitonwose.calendar.compose.CalendarState
import com.kizitonwose.calendar.core.CalendarDay
import com.kizitonwose.calendar.core.DayPosition
import com.kizitonwose.calendar.core.yearMonth
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.YearMonth
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit
import java.util.Locale
import java.util.UUID
import kotlinx.coroutines.delay

@OptIn(ExperimentalPermissionsApi::class)
@Composable
fun Menu(
    onSyncClick: () -> Unit,
    onBackupClick: () -> Unit,
    onRestoreClick: () -> Unit,
    onOpenSettingsClick: () -> Unit,
    onClearUnfinishedWorkouts: () -> Unit,
    onClearAllHistories: () -> Unit,
    onSyncToHealthConnectClick: () -> Unit
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
        DarkModeContainer(whiteOverlayAlpha = .1f, isRounded = false) {
            DropdownMenu(
                expanded = expanded,
                onDismissRequest = { expanded = false },
                modifier = Modifier.background(MaterialTheme.colorScheme.background)
            ) {
                DropdownMenuItem(
                    text = { Text("Sync with Watch") },
                    onClick = {
                        onSyncClick()
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
                    text = { Text("Settings") },
                    onClick = {
                        onOpenSettingsClick()
                        expanded = false
                    }
                )
                DropdownMenuItem(
                    text = { Text("Sync to Health Connect") },
                    onClick = {
                        onSyncToHealthConnectClick()
                        expanded = false
                    }
                )
                DropdownMenuItem(
                    text = { Text("Clear partial workouts") },
                    onClick = {
                        onClearUnfinishedWorkouts()
                        expanded = false
                    }
                )
                DropdownMenuItem(
                    text = { Text("Clear all histories") },
                    onClick = {
                        onClearAllHistories()
                        expanded = false
                    }
                )
            }
        }
    }

}

@Composable
fun WorkoutTitle(
    modifier: Modifier,
    workout: Workout,
    isDone: Boolean,
    content: @Composable () -> Unit = {},
    enabled: Boolean = true,
    style: TextStyle = MaterialTheme.typography.bodyMedium
) {
    Row(
        horizontalArrangement = Arrangement.SpaceBetween,
        modifier = modifier,
        verticalAlignment = Alignment.CenterVertically
    ) {
        if (!isDone) {
            Icon(
                imageVector = Icons.Default.Close,
                contentDescription = "Incomplete",
            )
            Spacer(modifier = Modifier.width(8.dp))
        }
        Text(
            modifier = Modifier
                .weight(1f)
                .basicMarquee(iterations = Int.MAX_VALUE),
            text = workout.name,
            color = Color.White.copy(alpha = if (enabled) .87f else .3f),
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

    var selectedEquipments by remember { mutableStateOf(listOf<Equipment>()) }
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

        // Collect workouts for each day in the week range
        var workoutHistoriesInAWeek =
            (0..ChronoUnit.DAYS.between(startOfWeek, endOfWeek)).flatMap { offset ->
                val date = startOfWeek.plusDays(offset)
                groupedWorkoutsHistories?.get(date)
                    ?: emptyList()  // Default to empty list if no workouts for the day
            }

        workoutHistoriesInAWeek = workoutHistoriesInAWeek.filter { it.isDone }

        val weeklyWorkouts = if (workoutHistoriesInAWeek.isEmpty()) emptyList() else workoutHistoriesInAWeek.mapNotNull { workoutHistory ->
            enabledWorkouts.find { it.id == workoutHistory.workoutId && it.timesCompletedInAWeek != null && it.timesCompletedInAWeek != 0 }
        }

        val uniqueGlobalIds = weeklyWorkouts.map { it.globalId }.distinct()

        val totalWeeklyWorkouts = weeklyWorkouts +
                activeAndEnabledWorkouts.filter {
                    !uniqueGlobalIds.contains(it.globalId) && it.timesCompletedInAWeek != null && it.timesCompletedInAWeek != 0
                }

        val workoutsByGlobalId = totalWeeklyWorkouts.groupBy { it.globalId }
        val workoutCountsByGlobalId = weeklyWorkouts.groupingBy { it.globalId }.eachCount()

        // Calculate progress list
        val progressList = workoutsByGlobalId.map { (globalId, workouts) ->
            val totalTarget = workouts.sumOf { timesCompletedInAWeekObjective[it.id] ?: 0 }
            val averageTarget = totalTarget / workouts.size
            val actual = workoutCountsByGlobalId[globalId] ?: 0
            if (averageTarget > 0) (actual.toDouble() / averageTarget) else 0.0
        }

        weeklyWorkoutsByActualTarget = workoutsByGlobalId.map { (globalId, workouts) ->
            val totalTarget = workouts.sumOf { timesCompletedInAWeekObjective[it.id] ?: 0 }
            val averageTarget = totalTarget / workouts.size
            val actual = workoutCountsByGlobalId[globalId] ?: 0

            //get the active workout in workouts
            var activeWorkout = workouts.firstOrNull { it.isActive }
            if (activeWorkout == null) activeWorkout = workouts.first()
            activeWorkout to Pair(actual, averageTarget)
        }.toMap().toSortedMap(compareBy { it.order })


        // Calculate average objective progress
        objectiveProgress = progressList.average()
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
        if (groupedWorkoutsHistories == null || workoutById == null) return
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
            scope.launch {
                calendarState.scrollToMonth(selectedDay.yearMonth)
                selectedDate = day
            }
            return
        }

        selectedDate = day
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
            DarkModeContainer(whiteOverlayAlpha = .1f, isRounded = false) {
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
                                            selectedWorkouts.none { it === workout }
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
                                    tint = Color.White.copy(alpha = .87f)
                                )
                            }
                            Button(
                                modifier = Modifier.padding(5.dp),
                                colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
                                onClick = {
                                    for (workout in selectedWorkouts) {
                                        appViewModel.updateWorkout(
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
                                        appViewModel.updateWorkout(
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
            DarkModeContainer(whiteOverlayAlpha = .1f, isRounded = false) {
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
                                    when (it) {
                                        is Barbell -> Barbell(UUID.randomUUID(), it.name + " (Copy)", it.availablePlates, it.barLength,it.barWeight, it.additionalPlates, it.maxAdditionalItems, it.volumeMultiplier)
                                        is Dumbbells -> Dumbbells(UUID.randomUUID(), it.name + " (Copy)", it.availableDumbbells, it.additionalPlates, it.maxAdditionalItems, it.volumeMultiplier)
                                        else -> throw IllegalArgumentException("Unknown equipment type")
                                    }
                                }

                                val newTotalEquipments = equipments + newEquipments

                                appViewModel.updateEquipments(newTotalEquipments)
                                isEquipmentSelectionModeActive = false
                            }) {
                                Icon(imageVector = Icons.Default.ContentCopy, contentDescription = "Copy",tint = Color.White.copy(alpha = .87f))
                            }
                            IconButton(onClick = {
                                val newEquipments = equipments.filter { item ->
                                    selectedEquipments.none { it === item }
                                }
                                appViewModel.updateEquipments(newEquipments)
                                isEquipmentSelectionModeActive = false
                            }) {
                                Icon(imageVector = Icons.Default.Delete, contentDescription = "Delete",tint = Color.White.copy(alpha = .87f))
                            }
                        }
                    }
                )
            }
        }
    }

    Scaffold(
        topBar = {
            DarkModeContainer(whiteOverlayAlpha = .1f, isRounded = false) {
                TopAppBar(
                    colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent),
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
                            onSyncToHealthConnectClick = onSyncToHealthConnectClick
                        )
                    }
                )
            }
        },
        bottomBar = {
            when(selectedTabIndex){
                1 -> workoutsBottomBar()
                2 -> equipmentsBottomBar()
            }
        },
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(it),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {

            TabRow(
                selectedTabIndex = selectedTabIndex,
                indicator = { tabPositions ->
                    TabRowDefaults.Indicator(
                        Modifier.tabIndicatorOffset(tabPositions[selectedTabIndex]),
                        color = MaterialTheme.colorScheme.primary, // Set the indicator color
                        height = 2.dp // Set the indicator thickness
                    )
                }
            ) {
                tabTitles.forEachIndexed { index, title ->
                    val isSelected = index == selectedTabIndex
                    Tab(
                        selected = isSelected,
                        onClick = { appViewModel.setHomeTab(index) },
                        text = { Text(text = title) },
                        selectedContentColor = MaterialTheme.colorScheme.primary,
                        unselectedContentColor = Color.White.copy(alpha = .3f),
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

                HealthConnectHandler(appViewModel, healthConnectClient)

                AnimatedContent(
                    targetState = selectedTabIndex,
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
                            Column(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(horizontal = 15.dp).verticalScroll(rememberScrollState())
                            ) {
                                WorkoutsCalendar(
                                    selectedDate = selectedDate,
                                    onDayClicked = { calendarState, day ->
                                        onDayClicked(calendarState, day)
                                    },
                                    shouldHighlight = { day -> highlightDay(day) },
                                    getHighlightColor = { day -> getHighlightColor(day) }
                                )
                                if (isLoading) {
                                    Box(
                                        modifier = Modifier
                                            .fillMaxSize().padding(10.dp),
                                        contentAlignment = Alignment.Center
                                    ) {
                                        CircularProgressIndicator(
                                            modifier = Modifier.width(32.dp),
                                            color = MaterialTheme.colorScheme.primary,
                                            trackColor = Color.DarkGray,
                                        )
                                    }
                                } else {
                                    if (hasObjectives) {
                                        val currentDate = selectedDate.date
                                        val currentMonth =
                                            currentDate.format(DateTimeFormatter.ofPattern("MMM"))

                                        Column(
                                            modifier = Modifier
                                                .fillMaxWidth()
                                                .padding(vertical = 10.dp),
                                            verticalArrangement = Arrangement.spacedBy(5.dp)
                                        ) {
                                            Text(
                                                modifier = Modifier.fillMaxWidth(),
                                                text = "Weekly progress (${
                                                    getStartOfWeek(
                                                        currentDate
                                                    ).dayOfMonth
                                                } - ${getEndOfWeek(currentDate).dayOfMonth} $currentMonth):",
                                                style = MaterialTheme.typography.titleMedium,
                                                textAlign = TextAlign.Center,
                                                color = Color.White.copy(alpha = .87f)
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
                                                            color = Color.White.copy(alpha = .87f),
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
                                                                    modifier = Modifier.weight(1f),
                                                                    color = Color.White.copy(alpha = .87f),
                                                                    style = MaterialTheme.typography.bodyMedium,
                                                                )
                                                                Text(
                                                                    text = "${pair.first}/${pair.second}",
                                                                    color = Color.White.copy(alpha = .87f),
                                                                    style = MaterialTheme.typography.bodyMedium,
                                                                )
                                                            }
                                                        }
                                                    }
                                                })
                                        }

                                    }
                                    Column(
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
                                            color = Color.White.copy(alpha = .87f)
                                        )

                                        if (selectedCalendarWorkouts.isNullOrEmpty()) {
                                            Box(
                                                modifier = Modifier
                                                    .fillMaxSize(),
                                                contentAlignment = Alignment.Center
                                            ) {
                                                DarkModeContainer(
                                                    modifier = Modifier
                                                        .padding(5.dp),
                                                    whiteOverlayAlpha = .1f
                                                ) {
                                                    Text(
                                                        modifier = Modifier
                                                            .padding(15.dp),
                                                        text = "No workouts on this day",
                                                        textAlign = TextAlign.Center,
                                                        color = Color.White.copy(alpha = .87f),
                                                    )
                                                }
                                            }
                                        } else {
                                            selectedCalendarWorkouts!!.forEach { (workoutHistory, workout) ->
                                                DarkModeContainer(whiteOverlayAlpha = .1f) {
                                                    WorkoutTitle(
                                                        Modifier
                                                            .padding(15.dp)
                                                            .clickable {
                                                                appViewModel.setScreenData(
                                                                    ScreenData.WorkoutHistory(
                                                                        workout.id,
                                                                        workoutHistory.id
                                                                    )
                                                                )
                                                            },
                                                        workout,
                                                        workoutHistory.isDone,
                                                        style = MaterialTheme.typography.bodyLarge
                                                    )
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        1 -> {
                            Column(
                                modifier = Modifier.fillMaxSize().padding(5.dp).verticalScroll(rememberScrollState())
                            ) {
                                if (activeAndEnabledWorkouts.isEmpty()) {
                                    Text(
                                        text = "Add a new workout",
                                        textAlign = TextAlign.Center,
                                        color = Color.White.copy(alpha = .87f),
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .padding(15.dp),
                                        style = MaterialTheme.typography.titleMedium
                                    )
                                } else {
                                    GenericSelectableList(
                                        PaddingValues(5.dp, 10.dp),
                                        items = activeWorkouts,
                                        selectedItems = selectedWorkouts,
                                        isWorkoutSelectionModeActive,
                                        onItemClick = {
                                            if (isCardExpanded) return@GenericSelectableList
                                            appViewModel.setScreenData(ScreenData.WorkoutDetail(it.id))
                                        },
                                        onEnableSelection = { isWorkoutSelectionModeActive = true },
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
                                            DarkModeContainer(whiteOverlayAlpha = .1f) {
                                                WorkoutTitle(
                                                    Modifier.padding(15.dp),
                                                    it,
                                                    true,
                                                    enabled = it.enabled
                                                )
                                            }
                                        },
                                        isDragDisabled = true
                                    )

                                }
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
                                            contentDescription = "Add"
                                        )
                                    }
                                }
                            }
                        }

                        2 -> {
                            Column(
                                modifier = Modifier.fillMaxSize().padding(5.dp).verticalScroll(rememberScrollState())
                            ) {
                                if (equipments.isEmpty()) {
                                    Text(
                                        text = "Add new equipment",
                                        textAlign = TextAlign.Center,
                                        color = Color.White.copy(alpha = .87f),
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .padding(15.dp),
                                        style = MaterialTheme.typography.titleMedium
                                    )
                                } else {
                                    GenericSelectableList(
                                        PaddingValues(5.dp, 10.dp),
                                        items = equipments,
                                        selectedItems = selectedEquipments,
                                        isEquipmentSelectionModeActive,
                                        onItemClick = { equipment ->
                                            val equipmentType = when (equipment) {
                                                is Barbell -> EquipmentType.BARBELL
                                                is Dumbbells -> EquipmentType.DUMBBELLS
                                                else -> throw IllegalArgumentException("Unknown equipment type")
                                            }

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
                                            DarkModeContainer(whiteOverlayAlpha = .1f) {
                                                Text(
                                                    modifier = Modifier
                                                        .fillMaxSize()
                                                        .padding(15.dp)
                                                        .basicMarquee(iterations = Int.MAX_VALUE),
                                                    text = it.name,
                                                    color = Color.White.copy(alpha = .87f),
                                                    style = MaterialTheme.typography.bodyMedium,
                                                )
                                            }
                                        },
                                        isDragDisabled = true
                                    )
                                }
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.Center, // Space items evenly, including space at the edges
                                    verticalAlignment = Alignment.CenterVertically // Center items vertically within the Row
                                ) {
                                    GenericButtonWithMenu(
                                        menuItems = listOf(
                                            MenuItem("Add Barbell") {
                                                appViewModel.setScreenData(
                                                    ScreenData.NewEquipment(
                                                        EquipmentType.BARBELL
                                                    )
                                                );
                                            },
                                            MenuItem("Add Dumbbells") {
                                                appViewModel.setScreenData(
                                                    ScreenData.NewEquipment(
                                                        EquipmentType.DUMBBELLS
                                                    )
                                                );
                                            }

                                        ),
                                        content = {
                                            Icon(
                                                imageVector = Icons.Filled.Add,
                                                contentDescription = "Add"
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
