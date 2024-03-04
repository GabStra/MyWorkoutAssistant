package com.gabstra.myworkoutassistant.screens

import android.annotation.SuppressLint
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.automirrored.filled.ShowChart
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowForward
import androidx.compose.material3.Button
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
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.composables.ExpandableCard
import com.gabstra.myworkoutassistant.composables.SetHistoriesRenderer
import com.gabstra.myworkoutassistant.formatSecondsToMinutesSeconds
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutManager
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import com.gabstra.myworkoutassistant.ui.theme.MyWorkoutAssistantTheme
import com.patrykandpatrick.vico.compose.axis.horizontal.rememberBottomAxis
import com.patrykandpatrick.vico.compose.axis.vertical.rememberStartAxis
import com.patrykandpatrick.vico.compose.chart.Chart
import com.patrykandpatrick.vico.compose.chart.column.columnChart
import com.patrykandpatrick.vico.compose.chart.edges.rememberFadingEdges
import com.patrykandpatrick.vico.compose.chart.layout.fullWidth
import com.patrykandpatrick.vico.compose.chart.line.lineChart
import com.patrykandpatrick.vico.compose.chart.scroll.ChartScrollSpec
import com.patrykandpatrick.vico.core.axis.AxisPosition
import com.patrykandpatrick.vico.core.axis.formatter.AxisValueFormatter
import com.patrykandpatrick.vico.core.chart.edges.FadingEdges
import com.patrykandpatrick.vico.core.chart.layout.HorizontalLayout
import com.patrykandpatrick.vico.core.chart.scale.AutoScaleUp
import com.patrykandpatrick.vico.core.component.text.TextComponent
import com.patrykandpatrick.vico.core.entry.ChartEntryModel
import com.patrykandpatrick.vico.core.entry.entryModelOf
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.format.DateTimeFormatter
import java.util.Locale
import java.util.UUID

@SuppressLint("UnusedMaterial3ScaffoldPaddingParameter")
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun WorkoutHistoryScreen(
    appViewModel: AppViewModel,
    workoutHistoryDao: WorkoutHistoryDao,
    workoutHistoryId: Int? = null,
    setHistoryDao: SetHistoryDao,
    workout : Workout,
    onGoBack : () -> Unit
){
    val currentLocale = Locale.getDefault()

    val exerciseById =  remember(workout) {
        WorkoutManager.getAllExercisesFromWorkout(workout).associateBy { it.id }
    }

    val formatter = remember(currentLocale) {
        DateTimeFormatter.ofPattern("dd/MM/yy", currentLocale)
    }

    var workoutHistories by remember { mutableStateOf(listOf<WorkoutHistory>()) }

    var selectedWorkoutHistory by remember { mutableStateOf<WorkoutHistory?>(null) }

    var setHistoriesByExerciseId by remember { mutableStateOf<Map<UUID, List<SetHistory>>>(emptyMap()) }

    var volumeEntryModel by remember { mutableStateOf<ChartEntryModel?>(null) }
    var durationEntryModel by remember { mutableStateOf<ChartEntryModel?>(null) }
    var heartRateEntryModel by remember { mutableStateOf<ChartEntryModel?>(null) }


    val horizontalAxisValueFormatter = AxisValueFormatter<AxisPosition.Horizontal.Bottom> { value, _ ->
        workoutHistories[value.toInt()].date.format(formatter)
    }

    val secondsHorizontalAxisValueFormatter = AxisValueFormatter<AxisPosition.Horizontal.Bottom> { value, _ ->
        formatTime(value.toInt())
    }

    val durationAxisValueFormatter = AxisValueFormatter<AxisPosition.Vertical.Start> { value, _ ->
        formatTime(value.toInt())
    }

    var isLoading by remember { mutableStateOf(true) }

    var selectedMode by remember { mutableIntStateOf(0) } // 0 for Graphs, 1 for Sets

    LaunchedEffect(workout) {
        withContext(Dispatchers.IO) {
            workoutHistories = workoutHistoryDao.getWorkoutsByWorkoutIdByDateAsc(workout.id)

            val volumes = mutableListOf<Pair<Int,Float>>()
            val durations = mutableListOf<Pair<Int,Float>>()
            for(workoutHistory in workoutHistories){
                val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)

                var volume = 0f
                for(setHistory in setHistories){
                    if(setHistory.setData is WeightSetData){
                        val setData = setHistory.setData as WeightSetData
                        volume += setData.actualReps * setData.actualWeight
                    }

                    if(setHistory.setData is BodyWeightSetData){
                        val setData = setHistory.setData as BodyWeightSetData
                        volume += setData.actualReps
                    }
                }
                volumes.add(Pair(workoutHistories.indexOf(workoutHistory),volume))
                durations.add(Pair(workoutHistories.indexOf(workoutHistory),workoutHistory.duration.toFloat()))
            }

            //check if volumes are not all 0
            if(volumes.any { it.second != 0f }) {
                volumeEntryModel = entryModelOf(*volumes.toTypedArray())
            }

            durationEntryModel = entryModelOf(*durations.toTypedArray())
            selectedWorkoutHistory = if(workoutHistoryId!=null) workoutHistories.find { it.id == workoutHistoryId} else workoutHistories.lastOrNull()

            if(workoutHistoryId !=null && selectedWorkoutHistory != null){
                selectedMode = 1
            }

            isLoading = false
        }
    }

    LaunchedEffect(selectedWorkoutHistory) {
        if(selectedWorkoutHistory == null) return@LaunchedEffect

        heartRateEntryModel = null
        if(selectedWorkoutHistory!!.heartBeatRecords.isNotEmpty() && selectedWorkoutHistory!!.heartBeatRecords.any { it != 0 }){
            val indexedHeartBeatRecords = selectedWorkoutHistory!!.heartBeatRecords.mapIndexed { index, value ->
                (index+1)/2 to value
            }
            heartRateEntryModel = entryModelOf(*indexedHeartBeatRecords.toTypedArray())
        }

        withContext(Dispatchers.IO) {
            val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(selectedWorkoutHistory!!.id)
            setHistoriesByExerciseId = setHistories.groupBy { it.exerciseId }
        }
    }

    val graphsTabContent = @Composable {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(10.dp),
        ){
            if(volumeEntryModel != null){
                Column(Modifier.padding(10.dp)){
                    Text(modifier = Modifier
                        .fillMaxWidth(),
                        text = "Volume over time",
                        textAlign = TextAlign.Center
                    )
                    Chart(
                        modifier = Modifier.padding(10.dp),
                        chart = columnChart(),
                        model = volumeEntryModel!!,
                        startAxis = rememberStartAxis(),
                        bottomAxis = rememberBottomAxis(valueFormatter = horizontalAxisValueFormatter, labelRotationDegrees = -45f),
                    )
                }
            }
            if(durationEntryModel != null){
                Column(Modifier.padding(10.dp)){
                    Text(modifier = Modifier
                        .fillMaxWidth(),
                        text = "Workout duration over time",
                        textAlign = TextAlign.Center
                    )
                    Chart(
                        modifier = Modifier.padding(10.dp),
                        chart = lineChart(),
                        model = durationEntryModel!!,
                        startAxis = rememberStartAxis(valueFormatter = durationAxisValueFormatter),
                        bottomAxis = rememberBottomAxis(valueFormatter = horizontalAxisValueFormatter, labelRotationDegrees = -45f),
                    )
                }
            }
        }
    }

    val workoutSelector = @Composable {
        Row(modifier = Modifier.padding(15.dp,0.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            IconButton(
                onClick = {
                    val index = workoutHistories.indexOf(selectedWorkoutHistory)
                    if (index > 0) { // Check to avoid IndexOutOfBoundsException
                        selectedWorkoutHistory = workoutHistories[index - 1]
                    }
                },
                enabled = selectedWorkoutHistory != workoutHistories.first()
            ) {
                Icon(imageVector = Icons.Filled.ArrowBack, contentDescription = "Previous")
            }
            Spacer(modifier = Modifier.width(10.dp))
            Text(modifier = Modifier
                .weight(1f),
                text = selectedWorkoutHistory!!.date.format(formatter),
                textAlign = TextAlign.Center
            )
            Spacer(modifier = Modifier.width(10.dp))
            IconButton(
                onClick = {
                    val index = workoutHistories.indexOf(selectedWorkoutHistory)
                    if (index < workoutHistories.size - 1) { // Check to avoid IndexOutOfBoundsException
                        selectedWorkoutHistory = workoutHistories[index + 1]
                    }
                },
                enabled = selectedWorkoutHistory != workoutHistories.last()
            ) {
                Icon(imageVector = Icons.Filled.ArrowForward, contentDescription = "Next")
            }
        }
    }

    val setsTabContent = @Composable {


        if(heartRateEntryModel != null){
            Column(Modifier.padding(10.dp)){
                Text(modifier = Modifier
                    .fillMaxWidth(),
                    text = "HR over workout duration (1/2 sec intervals)",
                    textAlign = TextAlign.Center
                )
                Chart(
                    modifier = Modifier.padding(10.dp),
                    chart = lineChart(),
                    model = heartRateEntryModel!!,
                    startAxis = rememberStartAxis(),
                    bottomAxis = rememberBottomAxis(valueFormatter= secondsHorizontalAxisValueFormatter),
                    isZoomEnabled = false,
                    getXStep = { heartRateEntryModel!!.entries[0].size.toFloat()/2 },
                )
            }
        }

        Text(modifier = Modifier
            .fillMaxWidth(),
            text = "Duration: ${formatTime(selectedWorkoutHistory!!.duration)}",
            textAlign = TextAlign.Center
        )

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(10.dp)
        ) {
            setHistoriesByExerciseId.keys.toList().forEach(){ key ->
                ExpandableCard(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(5.dp),
                    isOpen = true,
                    title = { modifier -> WorkoutComponentTitle(modifier,exerciseById[key] as WorkoutComponent) },
                    content = {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 10.dp, vertical = 10.dp)
                                .clip(RoundedCornerShape(5.dp))
                                .background(Color.Black),
                            horizontalAlignment = Alignment.CenterHorizontally
                        ){
                            SetHistoriesRenderer(setHistoriesByExerciseId[key]!!)
                        }
                    },
                    onOpen = { },
                    onClose = {}
                )
            }
        }
    }

    val customBottomBar = @Composable {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp), // Fill the width of the container
            horizontalArrangement = Arrangement.SpaceAround, // Space items evenly, including space at the edges
            verticalAlignment = Alignment.CenterVertically // Center items vertically within the Row
        ) {
            Box(
                modifier = Modifier
                    .clip(RoundedCornerShape(10.dp)) // Apply rounded corners to the Box
                    .then(
                        if (selectedMode == 0) Modifier.background(MaterialTheme.colorScheme.primary) else Modifier
                    ) // Apply background color only if enabled
                    .clickable { selectedMode = 0 }
                    .padding(8.dp),
                contentAlignment = Alignment.Center
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.AutoMirrored.Filled.ShowChart, contentDescription = "Graphs", tint = if (selectedMode != 0) Color.White else Color.Black)
                    Spacer(modifier = Modifier.width(5.dp))
                    Text("Graphs", color = if (selectedMode != 0) Color.White else Color.Black)
                }
            }

            Box(
                modifier = Modifier
                    .clip(RoundedCornerShape(10.dp)) // Apply rounded corners to the Box
                    .then(
                        if (selectedMode == 1) Modifier.background(MaterialTheme.colorScheme.primary) else Modifier
                    ) // Apply background color only if enabled
                    .clickable { selectedMode = 1 }
                    .padding(8.dp),
                contentAlignment = Alignment.Center
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.AutoMirrored.Filled.List, contentDescription = "Sets", tint = if (selectedMode != 1) Color.White else Color.Black)
                    Spacer(modifier = Modifier.width(5.dp))
                    Text("Sets", color = if (selectedMode != 1) Color.White else Color.Black)
                }
            }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        modifier = Modifier.basicMarquee(),
                        text = workout.name
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onGoBack) {
                        Icon(imageVector = Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                }
            )
        },
        bottomBar = {
            if(!(workoutHistories.isEmpty() || selectedWorkoutHistory == null)){
                customBottomBar()
            }
        }
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(it),
            verticalArrangement = Arrangement.Top,
        ){
            TabRow(
                selectedTabIndex = 1,
                indicator = {
                    tabPositions ->
                    TabRowDefaults.Indicator(
                        Modifier.tabIndicatorOffset(tabPositions[1]),
                        color = Color.White, // Set the indicator color
                        height = 5.dp // Set the indicator thickness
                    )
                }
            ) {
                Tab(
                    selected = false,
                    onClick = { appViewModel.setScreenData(ScreenData.WorkoutDetail(workout.id),true) },
                    text = { Text("Overview") },
                    selectedContentColor = Color.White, // Color when tab is selected
                    unselectedContentColor = Color.LightGray // Color when tab is not selected
                )
                Tab(
                    selected = true,
                    onClick = { },
                    text = { Text("History")  },
                    selectedContentColor = Color.White, // Color when tab is selected
                    unselectedContentColor = Color.LightGray // Color when tab is not selected
                )
            }

            if(workoutHistories.isEmpty() || selectedWorkoutHistory == null){
                Text(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(20.dp),
                    text = if(isLoading) "Loading..." else "No workout history found",
                    textAlign = TextAlign.Center
                )
                Spacer(modifier = Modifier.height(10.dp))
            }else{
                LazyColumn(){
                    when(selectedMode){
                        0 -> item{graphsTabContent()}
                        1 -> {
                            item {workoutSelector()}
                            item{setsTabContent()}
                        }
                    }
                }
            }
        }
    }
}

