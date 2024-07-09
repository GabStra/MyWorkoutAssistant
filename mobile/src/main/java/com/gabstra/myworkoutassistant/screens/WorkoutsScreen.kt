package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
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

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.MoreVert

import androidx.compose.material3.BottomAppBar
import androidx.compose.material3.Button
import androidx.compose.material3.Card

import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.composables.ExpandableCard
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.composables.GenericSelectableList
import com.gabstra.myworkoutassistant.composables.ObjectiveProgressBar
import com.gabstra.myworkoutassistant.composables.WorkoutRenderer
import com.gabstra.myworkoutassistant.composables.WorkoutsCalendar
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.google.accompanist.permissions.ExperimentalPermissionsApi
import com.kizitonwose.calendar.compose.CalendarState
import com.kizitonwose.calendar.core.CalendarDay
import com.kizitonwose.calendar.core.DayPosition
import com.kizitonwose.calendar.core.nextMonth
import com.kizitonwose.calendar.core.previousMonth
import kotlinx.coroutines.Dispatchers

import kotlinx.coroutines.launch
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit
import java.time.temporal.TemporalAdjusters
import java.util.Locale
import java.util.UUID

@OptIn(ExperimentalPermissionsApi::class)
@Composable
fun Menu(
    onSyncClick: () -> Unit,
    onBackupClick: () -> Unit,
    onRestoreClick: () -> Unit,
    onOpenSettingsClick: () -> Unit,
    onClearAllHistories: () -> Unit,
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

        DropdownMenu(
            expanded = expanded,
            onDismissRequest = { expanded = false },
            modifier = Modifier
                .background(Color.Black)
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
                text = { Text("Clear all histories") },
                onClick = {
                    onClearAllHistories()
                    expanded = false
                }
            )
        }
    }
}

@Composable
fun WorkoutTitle(modifier: Modifier, workout: Workout, isDone: Boolean){
    Row (
        horizontalArrangement = Arrangement.SpaceBetween,
        modifier = modifier.padding(15.dp)
    ){
        if (!isDone) {
            Icon(
                imageVector = Icons.Default.Close,
                contentDescription = "Incomplete",
                modifier = Modifier.align(Alignment.CenterVertically)
            )
            Spacer(modifier = Modifier.width(8.dp))
        }
        Text(
            modifier = Modifier.weight(1f).basicMarquee(iterations = Int.MAX_VALUE),
            text = workout.name
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WorkoutsScreen(
    appViewModel: AppViewModel,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    onSyncClick: () -> Unit,
    onBackupClick: () -> Unit,
    onRestoreClick: () -> Unit,
    onOpenSettingsClick: () -> Unit,
    onClearAllHistories: () -> Unit,
    selectedTabIndex : Int
) {
    val workouts by appViewModel.workoutsFlow.collectAsState()
    val enabledWorkouts = workouts.filter { it.enabled }

    val activeAndEnabledWorkouts = workouts.filter { it.enabled && it.isActive }.sortedBy { it.order }

    val activeWorkouts = workouts.filter { it.isActive }.sortedBy { it.order }

    val timesCompletedInAWeekObjective = enabledWorkouts.filter { it.timesCompletedInAWeek != null }.associate { workout ->
        workout.id to (workout.timesCompletedInAWeek ?: 0)
    }

    val hasObjectives = timesCompletedInAWeekObjective.values.any { it > 0 }

    var selectedWorkouts by remember { mutableStateOf(listOf<Workout>()) }
    var isSelectionModeActive by remember { mutableStateOf(false) }

    var objectiveProgress by remember { mutableStateOf(0.0) }

    var groupedWorkoutsHistories by remember { mutableStateOf<Map<LocalDate, List<WorkoutHistory>>?>(null) }
    var workoutById by remember { mutableStateOf<Map<UUID, Workout>?>(null) }

    var weeklyWorkoutsByActualTarget by remember { mutableStateOf<Map<Workout, Pair<Int,Int>>?>(null) }

    var selectedCalendarWorkouts by remember { mutableStateOf<List<Pair<WorkoutHistory,Workout>>?>(null) }

    var isCardExpanded by remember {
        mutableStateOf(false)
    }

    val currentLocale = Locale.getDefault()

    val formatter = remember(currentLocale) {
        DateTimeFormatter.ofPattern("dd/MM/yy", currentLocale)
    }

    val scope = rememberCoroutineScope()

    val tabTitles = listOf("Status","Workouts")

    var selectedDate by remember { mutableStateOf<CalendarDay?>(null) }

    fun getStartOfWeek(date: LocalDate): LocalDate {
        return date.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
    }

    fun getEndOfWeek(date: LocalDate): LocalDate {
        return date.with(TemporalAdjusters.nextOrSame(DayOfWeek.SUNDAY))
    }

    fun calculateObjectiveProgress(currentDate: LocalDate){
        if(enabledWorkouts.isEmpty()) return
        if(groupedWorkoutsHistories == null || workoutById == null) return

        val startOfWeek = getStartOfWeek(currentDate)
        val endOfWeek = getEndOfWeek(currentDate)

        // Collect workouts for each day in the week range
        var workoutHistoriesInAWeek = (0..ChronoUnit.DAYS.between(startOfWeek, endOfWeek)).flatMap { offset ->
            val date = startOfWeek.plusDays(offset)
            groupedWorkoutsHistories?.get(date) ?: emptyList()  // Default to empty list if no workouts for the day
        }

        workoutHistoriesInAWeek = workoutHistoriesInAWeek.filter{ it.isDone }

        if(workoutHistoriesInAWeek.isEmpty()) return

        val weeklyWorkouts = workoutHistoriesInAWeek
            .mapNotNull { workoutHistory ->
            enabledWorkouts.firstOrNull { it.id == workoutHistory.workoutId }
        }

        val uniqueGlobalIds = weeklyWorkouts.map { it.globalId }.distinct()

        val totalWeeklyWorkouts = weeklyWorkouts +
                activeAndEnabledWorkouts.filter { !uniqueGlobalIds.contains(it.globalId) && timesCompletedInAWeekObjective.contains(it.id) }

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
            if(activeWorkout == null) activeWorkout = workouts.first()
            activeWorkout to Pair(actual,averageTarget)
        }.toMap().toSortedMap(compareBy { it.order})


        // Calculate average objective progress
        objectiveProgress = progressList.average()
    }

    LaunchedEffect(enabledWorkouts){
        groupedWorkoutsHistories = workoutHistoryDao.getAllWorkoutHistories().filter { workoutHistory ->
            enabledWorkouts.any { it.id == workoutHistory.workoutId }
        }.groupBy { it.date }
        workoutById = enabledWorkouts.associateBy { it.id }
        calculateObjectiveProgress(LocalDate.now())
    }

    LaunchedEffect(selectedDate) {
        if(selectedDate == null) return@LaunchedEffect

        calculateObjectiveProgress(selectedDate!!.date)
    }

    fun onDayClicked(calendarState: CalendarState, day: CalendarDay){
        if(groupedWorkoutsHistories == null || workoutById == null) return
        val workoutHistories = groupedWorkoutsHistories?.get(day.date)

        selectedCalendarWorkouts = try {
            workoutHistories?.map { workoutHistory ->
                Pair(workoutHistory,workoutById?.get(workoutHistory.workoutId)!!)
            } ?: emptyList()
        }catch (e:Exception){
            emptyList()
        }

        if(day.position == DayPosition.InDate){
            scope.launch {
                calendarState.animateScrollToMonth(calendarState.firstVisibleMonth.yearMonth.previousMonth)
                selectedDate = day
            }
            return
        }

        if(day.position == DayPosition.OutDate){
            scope.launch {
                calendarState.animateScrollToMonth(calendarState.firstVisibleMonth.yearMonth.nextMonth)
                selectedDate = day
            }
            return
        }

        selectedDate = day
    }

    fun highlightDay(day: CalendarDay): Boolean {
        return groupedWorkoutsHistories?.get(day.date)?.isNotEmpty() ?: false
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("My Workout Assistant") },
                actions = {
                    Menu(
                        onSyncClick = onSyncClick,
                        onOpenSettingsClick = onOpenSettingsClick,
                        onBackupClick = onBackupClick,
                        onRestoreClick = onRestoreClick,
                        onClearAllHistories = onClearAllHistories
                    )
                }
            )
        },
        bottomBar = {
            if(selectedWorkouts.isNotEmpty()) BottomAppBar(
                actions =  {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceEvenly
                    ) {
                        IconButton(onClick = {
                            val newWorkouts = activeAndEnabledWorkouts.filter { workout ->
                                selectedWorkouts.none { it === workout }
                            }

                            val newWorkoutsWithUpdatedOrder =
                                newWorkouts.mapIndexed { index, workout -> workout.copy(order = index) }

                            appViewModel.updateWorkouts(newWorkoutsWithUpdatedOrder)
                            scope.launch(Dispatchers.IO) {
                                for (workout in selectedWorkouts) {
                                    val workoutHistories =
                                        workoutHistoryDao.getWorkoutsByWorkoutId(workout.id)
                                    for (workoutHistory in workoutHistories) {
                                        setHistoryDao.deleteByWorkoutHistoryId(workoutHistory.id)
                                    }
                                    workoutHistoryDao.deleteAllByWorkoutId(workout.id)
                                }
                                groupedWorkoutsHistories = workoutHistoryDao.getAllWorkoutHistories().groupBy { it.date }
                            }
                            selectedWorkouts = emptyList()
                            isSelectionModeActive = false
                        }) {
                            Icon(imageVector = Icons.Default.Delete, contentDescription = "Delete")
                        }
                        Button(
                            modifier = Modifier.padding(5.dp),
                            onClick = {
                                for (workout in selectedWorkouts) {
                                    appViewModel.updateWorkout(
                                        workout,
                                        workout.copy(enabled = true)
                                    )
                                }
                                selectedWorkouts = emptyList()
                                isSelectionModeActive = false
                            }) {
                            Text("Enable")
                        }
                        Button(
                            modifier = Modifier.padding(5.dp),
                            onClick = {
                                for (workout in selectedWorkouts) {
                                    appViewModel.updateWorkout(
                                        workout,
                                        workout.copy(enabled = false)
                                    )
                                }
                                selectedWorkouts = emptyList()
                                isSelectionModeActive = false
                            }) {
                            Text("Disable")
                        }
                    }
                }
            )
        },
        floatingActionButton= {
            if(selectedWorkouts.isEmpty())
                FloatingActionButton(
                    containerColor = MaterialTheme.colorScheme.primary,
                    onClick = {
                        appViewModel.setScreenData(ScreenData.NewWorkout());
                    }
                ) {
                    Icon(
                        imageVector = Icons.Default.Add,
                        contentDescription = null,
                    )
                }
        }
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(it),
            horizontalAlignment = Alignment.CenterHorizontally
        ){
            if(activeAndEnabledWorkouts.isEmpty()){
                Card(
                    modifier = Modifier
                        .padding(15.dp)
                ){
                    Text(
                        text = "Add a new workout",
                        textAlign = TextAlign.Center,
                        color = Color.White,
                        modifier = Modifier
                            .padding(15.dp)
                    )
                }
            }else{
                TabRow(
                    selectedTabIndex = selectedTabIndex,
                    indicator = {
                            tabPositions ->
                        TabRowDefaults.Indicator(
                            Modifier.tabIndicatorOffset(tabPositions[selectedTabIndex]),
                            color = Color.White, // Set the indicator color
                            height = 2.dp // Set the indicator thickness
                        )
                    }
                ) {
                    tabTitles.forEachIndexed { index, title ->
                        Tab(
                            selected = index == selectedTabIndex,
                            onClick = { appViewModel.updateScreenData(ScreenData.Workouts(index)) },
                            text = { Text(title) },
                            selectedContentColor = Color.White, // Color when tab is selected
                            unselectedContentColor = Color.LightGray // Color when tab is not selected
                        )
                    }
                }

                when (selectedTabIndex) {
                    0 -> {
                        LazyColumn(){
                            item{ if(hasObjectives){
                                val currentDate = selectedDate?.date ?: LocalDate.now()

                                val currentMonth = currentDate.format(DateTimeFormatter.ofPattern("MMM"))

                                ExpandableCard(
                                    isExpandable = weeklyWorkoutsByActualTarget != null && weeklyWorkoutsByActualTarget!!.isNotEmpty(),
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(15.dp),
                                    title = { modifier ->
                                        Text(
                                            text = "Weekly progress (${getStartOfWeek(currentDate).dayOfMonth} - ${getEndOfWeek(currentDate).dayOfMonth} $currentMonth): ${(objectiveProgress * 100).toInt()}%",
                                            style = MaterialTheme.typography.titleSmall,
                                            color = Color.White,
                                            modifier = modifier
                                                .fillMaxWidth()
                                                .padding(start= 15.dp)
                                        )
                                    },
                                    subContent = {
                                        ObjectiveProgressBar(progress = objectiveProgress.toFloat())
                                    },
                                    content = {
                                        Column(
                                            modifier = Modifier.padding(10.dp),
                                            verticalArrangement = Arrangement.spacedBy(5.dp)
                                        ){
                                            weeklyWorkoutsByActualTarget?.forEach { (workout, pair) ->
                                                Row(
                                                    modifier = Modifier.padding(5.dp),
                                                    horizontalArrangement = Arrangement.SpaceBetween
                                                ){
                                                    Text(
                                                        text = workout.name,
                                                        modifier = Modifier.weight(1f),
                                                        color = Color.White
                                                    )
                                                    Text(
                                                        text = "${pair.first}/${pair.second}",
                                                        color = Color.White
                                                    )
                                                }
                                            }
                                        }
                                    },
                                    onOpen = { isCardExpanded = true },
                                    onClose = { isCardExpanded = false }
                                )
                            }}
                            item{
                                WorkoutsCalendar(
                                    selectedDate = selectedDate,
                                    onDayClicked = { calendarState, day ->
                                        onDayClicked(calendarState,day)
                                    },
                                    shouldHighlight = { day -> highlightDay(day) }
                                )
                            }
                            item{if(selectedDate != null){
                                Column(modifier = Modifier.padding(8.dp)) {
                                    Text(
                                        text = selectedDate!!.date.format(formatter),
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .padding(vertical = 10.dp),
                                        color = Color.Gray,
                                        textAlign = TextAlign.Center
                                    )
                                    if(selectedCalendarWorkouts.isNullOrEmpty()){
                                        Text(
                                            text = "No workouts on this day",
                                            modifier = Modifier
                                                .fillMaxWidth()
                                                .padding(vertical = 10.dp),
                                            textAlign = TextAlign.Center,
                                            style = MaterialTheme.typography.titleLarge,
                                            color = Color.Gray
                                        )
                                    }else{
                                        Column{
                                            selectedCalendarWorkouts!!.forEach { (workoutHistory, workout) ->
                                                Card(
                                                    modifier = Modifier.padding(5.dp),
                                                    onClick = {
                                                        appViewModel.setScreenData(ScreenData.WorkoutHistory(workout.id,workoutHistory.id))
                                                    }
                                                ){
                                                    WorkoutTitle(Modifier,workout,workoutHistory.isDone)
                                                }
                                            }
                                        }
                                    }
                                }
                            }}
                        }
                    }
                    1 -> {
                        GenericSelectableList(
                            PaddingValues(0.dp,5.dp),
                            items = activeWorkouts,
                            selectedItems= selectedWorkouts,
                            isSelectionModeActive,
                            onItemClick = {
                                if(isCardExpanded) return@GenericSelectableList
                                appViewModel.setScreenData(ScreenData.WorkoutDetail(it.id))
                            },
                            onEnableSelection = { isSelectionModeActive = true },
                            onDisableSelection = { isSelectionModeActive = false },
                            onSelectionChange = { newSelection -> selectedWorkouts = newSelection} ,
                            onOrderChange = { newWorkouts->
                                val workoutsWithOrderUpdated = newWorkouts.mapIndexed { index, workout -> workout.copy(order = index) }
                                appViewModel.updateWorkouts(workoutsWithOrderUpdated)
                            },
                            itemContent = { it ->
                                ExpandableCard(
                                    isExpandable = it.workoutComponents.isNotEmpty(),
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .alpha(if (it.enabled) 1f else 0.4f),
                                    title = { modifier ->  WorkoutTitle(modifier,it,true) },
                                    content = { WorkoutRenderer(it) },
                                    onOpen = { isCardExpanded = true },
                                    onClose = { isCardExpanded = false }
                                )
                            },
                            isDragDisabled = true
                        )
                    }
                }
            }
        }
    }
}
