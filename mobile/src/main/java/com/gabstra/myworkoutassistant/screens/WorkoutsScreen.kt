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
import com.gabstra.myworkoutassistant.optionalClip
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


fun YearMonth.displayText(short: Boolean = false): String {
    return "${this.month.displayText(short = short)} ${this.year}"
}

fun Month.displayText(short: Boolean = true): String {
    val style = if (short) TextStyle.SHORT else TextStyle.FULL
    return getDisplayName(style, Locale.getDefault())
}

fun DayOfWeek.displayText(uppercase: Boolean = false): String {
    return getDisplayName(TextStyle.SHORT, Locale.getDefault()).let { value ->
        if (uppercase) value.uppercase(Locale.getDefault()) else value
    }
}

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

@Composable
fun MonthHeader(
    modifier: Modifier = Modifier,
    daysOfWeek: List<DayOfWeek> = emptyList(),
) {
    Row(modifier.fillMaxWidth()) {
        for (dayOfWeek in daysOfWeek) {
            Text(
                modifier = Modifier.weight(1f),
                textAlign = TextAlign.Center,
                fontSize = 12.sp,
                color = Color.White,
                text = dayOfWeek.displayText(),
                fontWeight = FontWeight.Light,
            )
        }
    }
}

@Composable
private fun Day(
    day: CalendarDay,
    isToday: Boolean = false,
    isSelected: Boolean = false,
    showStar: Boolean = false,
    onClick: (CalendarDay) -> Unit = {},
) {
    Box(
        modifier = Modifier
            .aspectRatio(1f) // This is important for square-sizing!
            .border(
                width = if (isSelected) 1.dp else 0.dp,
                color = if (isSelected) Color.White else Color.Transparent,
            )
            .padding(3.dp)
            // Disable clicks on inDates/outDates
            .clickable(
                enabled = day.position == DayPosition.MonthDate,
                onClick = { onClick(day) },
            ),
    ) {
        val textColor = if (isToday) Color.Black else when (day.position) {
            DayPosition.MonthDate -> Color.Unspecified
            DayPosition.InDate, DayPosition.OutDate -> Color.Gray
        }

        val shape = if(isToday) RoundedCornerShape(3.dp) else null

        Box(
            modifier = Modifier
                .align(Alignment.TopEnd)
                .optionalClip(shape)
                .size(20.dp)
                .background(if (isToday) Color.White else Color.Transparent),
            contentAlignment = Alignment.Center
        ){
            Text(
                modifier = Modifier
                    .background(if (isToday) Color.White else Color.Transparent),
                text = day.date.dayOfMonth.toString(),
                color = textColor,
                fontSize = 12.sp,
            )
        }


        //set the star yellow
        Icon(
            imageVector = Icons.Default.Star,
            contentDescription = "Star",
            modifier = Modifier
                .align(Alignment.BottomEnd)
                .padding(0.dp, 5.dp)
                .alpha(if (showStar) 1f else 0f)
                .size(15.dp),
            tint = Color.Yellow

        )
    }
}

private val CalendarLayoutInfo.completelyVisibleMonths: List<CalendarMonth>
    get() {
        val visibleItemsInfo = this.visibleMonthsInfo.toMutableList()
        return if (visibleItemsInfo.isEmpty()) {
            emptyList()
        } else {
            val lastItem = visibleItemsInfo.last()
            val viewportSize = this.viewportEndOffset + this.viewportStartOffset
            if (lastItem.offset + lastItem.size > viewportSize) {
                visibleItemsInfo.removeLast()
            }
            val firstItem = visibleItemsInfo.firstOrNull()
            if (firstItem != null && firstItem.offset < this.viewportStartOffset) {
                visibleItemsInfo.removeFirst()
            }
            visibleItemsInfo.map { it.month }
        }
    }

@Composable
fun rememberFirstCompletelyVisibleMonth(state: CalendarState): CalendarMonth {
    val visibleMonth = remember(state) { mutableStateOf(state.firstVisibleMonth) }
    // Only take non-null values as null will be produced when the
    // list is mid-scroll as no index will be completely visible.
    LaunchedEffect(state) {
        snapshotFlow { state.layoutInfo.completelyVisibleMonths.firstOrNull() }
            .filterNotNull()
            .collect { month -> visibleMonth.value = month }
    }
    return visibleMonth.value
}

@Composable
fun SimpleCalendarTitle(
    modifier: Modifier,
    currentMonth: YearMonth,
    goToPrevious: () -> Unit,
    goToNext: () -> Unit,
) {
    Row(
        modifier = modifier.height(40.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconButton(
            onClick = goToPrevious,
        ) {
            Icon(imageVector = Icons.Filled.ArrowBack, contentDescription = "Back")
        }

        Text(
            modifier = Modifier
                .weight(1f),
            text = currentMonth.displayText(),
            fontSize = 22.sp,
            textAlign = TextAlign.Center,
            fontWeight = FontWeight.Medium,
        )

        IconButton(
            onClick = goToNext,
        ) {
            Icon(imageVector = Icons.Filled.ArrowForward, contentDescription = "Back")
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WorkoutsScreen(
    appViewModel: AppViewModel,
    workoutHistoryDao: WorkoutHistoryDao,
    onSyncClick: () -> Unit,
    onBackupClick: () -> Unit,
    onRestoreClick: () -> Unit,
    onOpenSettingsClick: () -> Unit,
    onClearAllHistories: () -> Unit,
) {
    val workouts by appViewModel.workoutsFlow.collectAsState()
    var selectedWorkouts by remember { mutableStateOf(listOf<Workout>()) }
    var isSelectionModeActive by remember { mutableStateOf(false) }

    var groupedWorkouts by remember { mutableStateOf<Map<LocalDate, List<WorkoutHistory>>?>(null) }

    var selectedCalendarWorkouts by remember { mutableStateOf<List<Pair<WorkoutHistory,Workout>>?>(null) }

    LaunchedEffect(workouts){
        groupedWorkouts = workoutHistoryDao.getAllWorkoutHistories().groupBy { it.date }
    }

    var isCardExpanded by remember {
        mutableStateOf(false)
    }

    val currentLocale = Locale.getDefault()

    val formatter = remember(currentLocale) {
        DateTimeFormatter.ofPattern("dd/MM/yy", currentLocale)
    }

    val scope = rememberCoroutineScope()

    var selectedTabIndex by remember { mutableIntStateOf(0) }
    val tabTitles = listOf("Status","Workouts")

    val currentDay = remember { LocalDate.now() }
    val currentMonth = remember { YearMonth.now() }
    val startMonth = remember { currentMonth.minusMonths(500) }
    val endMonth = remember { currentMonth.plusMonths(500) }
    var selectedDate by remember { mutableStateOf<CalendarDay?>(null) }
    val daysOfWeek = remember { daysOfWeek() }

    val calendarState = rememberCalendarState(
        startMonth = startMonth,
        endMonth = endMonth,
        firstVisibleMonth = currentMonth,
        firstDayOfWeek = daysOfWeek.first(),
        outDateStyle = OutDateStyle.EndOfGrid,
    )
    val visibleMonth = rememberFirstCompletelyVisibleMonth(calendarState)
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
                                workoutHistoryDao.deleteAllByWorkoutId(workout.id)
                            }
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
        if(workouts.isEmpty()){
            Text(modifier = Modifier
                .padding(it)
                .fillMaxSize(),text = "Add a new workout", textAlign = TextAlign.Center)
        }else{
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(it),
                verticalArrangement = Arrangement.Top,
            ){
                TabRow(selectedTabIndex = selectedTabIndex) {
                    tabTitles.forEachIndexed { index, title ->
                        Tab(
                            selected = index == selectedTabIndex,
                            onClick = { selectedTabIndex = index },
                            text = { Text(title) }
                        )
                    }
                }

                when (selectedTabIndex) {
                    0 -> {
                        SimpleCalendarTitle(
                            modifier = Modifier
                                .padding(horizontal = 8.dp, vertical = 12.dp),
                            currentMonth = visibleMonth.yearMonth,
                            goToPrevious = {
                                scope.launch {
                                    calendarState.animateScrollToMonth(calendarState.firstVisibleMonth.yearMonth.previousMonth)
                                }
                            },
                            goToNext = {
                                scope.launch {
                                    calendarState.animateScrollToMonth(calendarState.firstVisibleMonth.yearMonth.nextMonth)
                                }
                            },
                        )
                        HorizontalCalendar(
                            modifier = Modifier.wrapContentWidth(),
                            state = calendarState,
                            calendarScrollPaged= false,
                            userScrollEnabled = false,
                            dayContent = { day ->
                                val workoutHistories = groupedWorkouts?.get(day.date)

                                val hasWorkouts = workoutHistories.let { histories ->
                                    !histories.isNullOrEmpty()
                                }

                                Day(
                                    isToday = day.date == currentDay,
                                    day = day,
                                    isSelected = selectedDate == day,
                                    showStar = hasWorkouts,

                                ) { clicked ->
                                    Log.d("WorkoutsScreen", "Selected date: ${clicked.date.format(formatter)}")
                                    Log.d("WorkoutsScreen","hasWorkouts: $hasWorkouts")
                                    Log.d("WorkoutsScreen","workoutHistories: $workoutHistories")


                                    if (workoutHistories != null) {
                                        try {
                                            selectedCalendarWorkouts = workoutHistories.map { workoutHistory ->
                                                Pair(workoutHistory,workouts.first { workout -> workout.id == workoutHistory.workoutId })
                                            }
                                        }catch (e:Exception){
                                            selectedCalendarWorkouts = null
                                            Log.e("WorkoutsScreen",e.message.toString())
                                        }

                                    }else{
                                        selectedCalendarWorkouts =  emptyList()
                                    }
                                    Log.d("WorkoutsScreen","selectedCalendarWorkouts: $selectedCalendarWorkouts")
                                    selectedDate = clicked
                                }
                            },
                            monthHeader = {
                                MonthHeader(
                                    modifier = Modifier.padding(vertical = 8.dp),
                                    daysOfWeek = daysOfWeek,
                                )
                            },
                        )
                        if(selectedDate != null){
                            Column(modifier = Modifier.padding(8.dp)) {
                                Text(
                                    text = selectedDate!!.date.format(formatter),
                                    modifier = Modifier.padding(8.dp),
                                    color = Color.Gray
                                )
                                if(selectedCalendarWorkouts.isNullOrEmpty()){
                                    Text(
                                        text = "No workouts for this day",
                                        modifier = Modifier.padding(8.dp),
                                        textAlign = TextAlign.Center,
                                        style = MaterialTheme.typography.headlineSmall,
                                        color = Color.Gray
                                    )
                                }else{
                                    LazyColumn(modifier = Modifier.padding(horizontal = 8.dp)){
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
                            isDragDisabled = isCardExpanded
                        )
                    }
                }
            }
        }
    }
}
