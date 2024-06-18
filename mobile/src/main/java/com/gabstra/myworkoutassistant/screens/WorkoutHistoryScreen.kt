package com.gabstra.myworkoutassistant.screens

import android.annotation.SuppressLint
import android.text.Layout
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
import androidx.compose.ui.unit.sp
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
import com.gabstra.myworkoutassistant.shared.getHeartRateFromPercentage
import com.gabstra.myworkoutassistant.shared.getMaxHeartRate
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import com.patrykandpatrick.vico.compose.cartesian.CartesianChartHost
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberAxisLabelComponent
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberAxisTickComponent
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberBottomAxis
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberStartAxis
import com.patrykandpatrick.vico.compose.cartesian.decoration.rememberHorizontalLine
import com.patrykandpatrick.vico.compose.cartesian.fullWidth
import com.patrykandpatrick.vico.compose.cartesian.layer.rememberLineCartesianLayer
import com.patrykandpatrick.vico.compose.cartesian.rememberCartesianChart
import com.patrykandpatrick.vico.compose.cartesian.rememberVicoScrollState
import com.patrykandpatrick.vico.compose.cartesian.rememberVicoZoomState

import com.patrykandpatrick.vico.compose.common.component.rememberLineComponent
import com.patrykandpatrick.vico.compose.common.component.rememberShapeComponent

import com.patrykandpatrick.vico.compose.common.component.rememberTextComponent
import com.patrykandpatrick.vico.compose.common.of
import com.patrykandpatrick.vico.compose.common.shape.rounded
import com.patrykandpatrick.vico.core.cartesian.HorizontalLayout

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.format.DateTimeFormatter
import java.util.Locale
import java.util.UUID

import com.patrykandpatrick.vico.core.cartesian.Zoom
import com.patrykandpatrick.vico.core.cartesian.axis.AxisItemPlacer
import com.patrykandpatrick.vico.core.cartesian.axis.AxisPosition
import com.patrykandpatrick.vico.core.cartesian.axis.BaseAxis
import com.patrykandpatrick.vico.core.cartesian.data.AxisValueOverrider
import com.patrykandpatrick.vico.core.cartesian.data.CartesianChartModel
import com.patrykandpatrick.vico.core.cartesian.data.CartesianValueFormatter
import com.patrykandpatrick.vico.core.cartesian.data.LineCartesianLayerModel
import com.patrykandpatrick.vico.core.common.Defaults
import com.patrykandpatrick.vico.core.common.Dimensions
import com.patrykandpatrick.vico.core.common.HorizontalPosition
import com.patrykandpatrick.vico.core.common.VerticalPosition
import com.patrykandpatrick.vico.core.common.shape.Shape
import kotlinx.coroutines.delay

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

    val userAge by appViewModel.userAge

    val exerciseById =  remember(workout) {
        WorkoutManager.getAllExercisesFromWorkout(workout).associateBy { it.id }
    }

    val formatter = remember(currentLocale) {
        DateTimeFormatter.ofPattern("dd/MM/yy", currentLocale)
    }

    var workoutHistories by remember { mutableStateOf(listOf<WorkoutHistory>()) }

    var selectedWorkoutHistory by remember { mutableStateOf<WorkoutHistory?>(null) }

    var setHistoriesByExerciseId by remember { mutableStateOf<Map<UUID, List<SetHistory>>>(emptyMap()) }

    var volumeEntryModel by remember { mutableStateOf<CartesianChartModel?>(null) }
    var durationEntryModel by remember { mutableStateOf<CartesianChartModel?>(null) }
    var heartRateEntryModel by remember { mutableStateOf<CartesianChartModel?>(null) }


    val horizontalAxisValueFormatter = CartesianValueFormatter { value, chartValues, _->
        workoutHistories[value.toInt()].date.format(formatter)
    }

    val secondsHorizontalAxisValueFormatter = CartesianValueFormatter { value, chartValues, _->
        formatTime(value.toInt())
    }

    val durationAxisValueFormatter = CartesianValueFormatter { value, chartValues, _->
        formatTime(value.toInt())
    }

    var isLoading by remember { mutableStateOf(true) }

    var selectedMode by remember { mutableIntStateOf(0) } // 0 for Graphs, 1 for Sets

    LaunchedEffect(workout) {
        withContext(Dispatchers.IO) {
            workoutHistories = workoutHistoryDao.getWorkoutsByWorkoutIdByDateAsc(workout.id)
            //stop if no workout histories
            if(workoutHistories.isEmpty()){
                delay(1000)
                isLoading = false
                return@withContext
            }

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
                volumeEntryModel = CartesianChartModel(LineCartesianLayerModel.build { series(*(volumes.map{ it.second }).toTypedArray()) })
            }

            durationEntryModel = CartesianChartModel(LineCartesianLayerModel.build { series(*(durations.map{ it.second }).toTypedArray()) })
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
            heartRateEntryModel = CartesianChartModel(LineCartesianLayerModel.build { series(selectedWorkoutHistory!!.heartBeatRecords) })
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
                    CartesianChartHost(
                        zoomState = rememberVicoZoomState(zoomEnabled = false),
                        chart = rememberCartesianChart(
                            rememberLineCartesianLayer(spacing = 75.dp),
                            startAxis = rememberStartAxis(),
                            bottomAxis = rememberBottomAxis(valueFormatter = horizontalAxisValueFormatter)),
                        model = volumeEntryModel!!,
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
                    CartesianChartHost(
                        zoomState = rememberVicoZoomState(zoomEnabled = false),
                        chart = rememberCartesianChart(
                            rememberLineCartesianLayer(spacing = 75.dp),
                            startAxis = rememberStartAxis(valueFormatter = durationAxisValueFormatter),
                            bottomAxis = rememberBottomAxis(valueFormatter = horizontalAxisValueFormatter),
                        ),
                        model=durationEntryModel!!,
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

                CartesianChartHost(
                    modifier = Modifier
                        .padding(10.dp),
                    zoomState = rememberVicoZoomState(initialZoom = Zoom.Content, zoomEnabled = false),
                    scrollState = rememberVicoScrollState(scrollEnabled = false),
                    chart = rememberCartesianChart(
                        rememberLineCartesianLayer(axisValueOverrider = AxisValueOverrider.fixed(null,null,50f,200f)),
                        decorations =
                        listOf(
                            rememberHorizontalLine(
                                y = { getHeartRateFromPercentage(0.5f,userAge).toFloat() },
                                line = rememberLineComponent(color = Color.hsl(208f, 0.61f, 0.76f,.5f), thickness = 2.dp),
                            ),
                            rememberHorizontalLine(
                                y = { getHeartRateFromPercentage(0.6f,userAge).toFloat() },
                                line = rememberLineComponent(color = Color.hsl(200f, 0.66f, 0.49f,.5f), thickness = 2.dp),
                            ),
                            rememberHorizontalLine(
                                y = { getHeartRateFromPercentage(0.7f,userAge).toFloat() },
                                line = rememberLineComponent(color = Color.hsl(113f, 0.79f, 0.34f,.5f),thickness = 2.dp),
                            ),
                            rememberHorizontalLine(
                                y = { getHeartRateFromPercentage(0.8f,userAge).toFloat() },
                                line = rememberLineComponent(color = Color.hsl(27f, 0.97f, 0.54f,.5f), thickness = 2.dp),
                            ),
                            rememberHorizontalLine(
                                y = { getHeartRateFromPercentage(0.9f,userAge).toFloat() },
                                line = rememberLineComponent(color = Color.hsl(9f, 0.88f, 0.45f,.5f), thickness = 2.dp),
                            ),
                            rememberHorizontalLine(
                                y = { getHeartRateFromPercentage(1f,userAge).toFloat() },
                                line = rememberLineComponent(color = Color.Black, thickness = 2.dp),
                            ),
                        ),

                    ),
                    model = heartRateEntryModel!!,
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
                        if (selectedMode == 0) Modifier.background(Color.White) else Modifier
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
                        if (selectedMode == 1) Modifier.background(Color.White) else Modifier
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

