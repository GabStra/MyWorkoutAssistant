package com.gabstra.myworkoutassistant.screens

import android.util.Log
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size

import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.foundation.layout.wrapContentWidth
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowForward
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Star

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
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.composables.ExpandableCard
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.composables.GenericSelectableList
import com.gabstra.myworkoutassistant.composables.WorkoutRenderer
import com.gabstra.myworkoutassistant.composables.WorkoutsCalendar
import com.gabstra.myworkoutassistant.composables.rememberFirstCompletelyVisibleMonth
import com.gabstra.myworkoutassistant.optionalClip
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.google.accompanist.permissions.ExperimentalPermissionsApi
import com.kizitonwose.calendar.compose.CalendarLayoutInfo
import com.kizitonwose.calendar.compose.CalendarState
import com.kizitonwose.calendar.compose.HorizontalCalendar
import com.kizitonwose.calendar.compose.rememberCalendarState
import com.kizitonwose.calendar.core.CalendarDay
import com.kizitonwose.calendar.core.CalendarMonth
import com.kizitonwose.calendar.core.DayPosition
import com.kizitonwose.calendar.core.OutDateStyle
import com.kizitonwose.calendar.core.daysOfWeek
import com.kizitonwose.calendar.core.nextMonth
import com.kizitonwose.calendar.core.previousMonth

import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.launch
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.Month
import java.time.YearMonth
import java.time.format.DateTimeFormatter
import java.time.format.TextStyle
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
            onDismissRequest = { expanded = false }
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
fun WorkoutTitle(modifier: Modifier,workout: Workout){
    Row (
        horizontalArrangement = Arrangement.SpaceBetween,
        modifier = modifier.padding(15.dp)
    ){
        Text(
            modifier = Modifier.weight(1f),
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
    val workoutsFlow by appViewModel.workoutsFlow.collectAsState()
    val workouts = workoutsFlow.filter { it.enabled }

    var selectedWorkouts by remember { mutableStateOf(listOf<Workout>()) }
    var isSelectionModeActive by remember { mutableStateOf(false) }

    var groupedWorkouts by remember { mutableStateOf<Map<LocalDate, List<WorkoutHistory>>?>(null) }
    var workoutById by remember { mutableStateOf<Map<UUID, Workout>?>(null) }

    var selectedCalendarWorkouts by remember { mutableStateOf<List<Pair<WorkoutHistory,Workout>>?>(null) }

    LaunchedEffect(workouts){
        groupedWorkouts = workoutHistoryDao.getAllWorkoutHistories().groupBy { it.date }
        workoutById = workouts.associateBy { it.id }
    }

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

    fun onDayClicked(calendarState: CalendarState, day: CalendarDay){
        val workoutHistories = groupedWorkouts?.get(day.date)

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

    fun showStar(day: CalendarDay): Boolean {
        return groupedWorkouts?.get(day.date)?.isNotEmpty() ?: false
    }

    //add a menu in the floating action button
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
                    IconButton(onClick = {
                        val newWorkouts = workouts.filter { workout ->
                            selectedWorkouts.none { it === workout }
                        }
                        appViewModel.updateWorkouts(newWorkouts)
                        scope.launch {
                            for (workout in selectedWorkouts) {
                                val workoutHistories = workoutHistoryDao.getWorkoutsByWorkoutId(workout.id)
                                for(workoutHistory in workoutHistories) {
                                    setHistoryDao.deleteByWorkoutHistoryId(workoutHistory.id)
                                }
                                workoutHistoryDao.deleteAllByWorkoutId(workout.id)
                            }
                            groupedWorkouts = workoutHistoryDao.getAllWorkoutHistories().groupBy { it.date }
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
                                appViewModel.updateWorkout(workout,workout.copy(enabled = true))
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
                                appViewModel.updateWorkout(workout,workout.copy(enabled = false))
                            }
                            selectedWorkouts = emptyList()
                            isSelectionModeActive = false
                        }) {
                        Text("Disable")
                    }
                }
            )
        },
        floatingActionButton= {
            if(selectedWorkouts.isEmpty())
                FloatingActionButton(
                    onClick = {
                        appViewModel.setScreenData(ScreenData.NewWorkout());
                    }
                ) {
                    Icon(
                        imageVector = Icons.Default.Add,
                        contentDescription = null
                    )
                }
        }
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(it),
            verticalArrangement = Arrangement.Top,
        ){
            if(workouts.isEmpty()){
                Text(modifier = Modifier
                    .padding(10.dp)
                    .fillMaxSize(),text = "Add a new workout", textAlign = TextAlign.Center)
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
                        WorkoutsCalendar(
                            selectedDate = selectedDate,
                            onDayClicked = { calendarState, day ->
                                onDayClicked(calendarState,day)
                            },
                            showStar = { day -> showStar(day) }
                        )
                        if(selectedDate != null){
                            Column(modifier = Modifier.padding(8.dp)) {
                                Text(
                                    text = selectedDate!!.date.format(formatter),
                                    modifier = Modifier.fillMaxWidth().padding(vertical=10.dp),
                                    color = Color.Gray,
                                    textAlign = TextAlign.Center
                                )
                                if(selectedCalendarWorkouts.isNullOrEmpty()){
                                    Text(
                                        text = "No workouts on this day",
                                        modifier = Modifier.fillMaxWidth().padding(vertical=10.dp),
                                        textAlign = TextAlign.Center,
                                        style = MaterialTheme.typography.titleLarge,
                                        color = Color.Gray
                                    )
                                }else{
                                    LazyColumn{
                                        items(selectedCalendarWorkouts!!){ (workoutHistory,workout) ->
                                            Card(
                                                modifier = Modifier.padding(5.dp),
                                                onClick = {
                                                    appViewModel.setScreenData(ScreenData.WorkoutHistory(workout.id,workoutHistory.id))
                                                }
                                            ){
                                                WorkoutTitle(Modifier,workout)
                                            }
                                        }
                                    }
                                }
                            }
                        }

                    }
                    1 -> {
                        GenericSelectableList(
                            PaddingValues(0.dp,5.dp),
                            items = workouts,
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
                                appViewModel.updateWorkouts(newWorkouts)
                            },
                            itemContent = { it ->
                                ExpandableCard(
                                    isExpandable = it.workoutComponents.isNotEmpty(),
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .alpha(if (it.enabled) 1f else 0.4f),
                                    title = { modifier ->  WorkoutTitle(modifier,it) },
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
