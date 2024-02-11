package com.gabstra.myworkoutassistant.screens

import android.annotation.SuppressLint
import android.util.Log
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowForward
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.composables.ExpandableCard
import com.gabstra.myworkoutassistant.composables.SetHistoriesRenderer
import com.gabstra.myworkoutassistant.formatSecondsToMinutesSeconds
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutManager
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import com.patrykandpatrick.vico.compose.axis.horizontal.rememberBottomAxis
import com.patrykandpatrick.vico.compose.axis.vertical.rememberStartAxis
import com.patrykandpatrick.vico.compose.chart.Chart
import com.patrykandpatrick.vico.compose.chart.column.columnChart
import com.patrykandpatrick.vico.compose.chart.line.lineChart
import com.patrykandpatrick.vico.core.axis.AxisPosition
import com.patrykandpatrick.vico.core.axis.formatter.AxisValueFormatter
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
    workoutHistoryDao: WorkoutHistoryDao,
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

    val horizontalAxisValueFormatter = AxisValueFormatter<AxisPosition.Horizontal.Bottom> { value, _ ->
        workoutHistories[value.toInt()].date.format(formatter)
    }

    val durationAxisValueFormatter = AxisValueFormatter<AxisPosition.Vertical.Start> { value, _ ->
        formatSecondsToMinutesSeconds(value.toInt())
    }

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
                }
                volumes.add(Pair(workoutHistories.indexOf(workoutHistory),volume))
                durations.add(Pair(workoutHistories.indexOf(workoutHistory),workoutHistory.duration.toFloat()))
            }

            Log.d("WorkoutHistoryScreen", "volumes: $volumes")
            volumeEntryModel = entryModelOf(*volumes.toTypedArray())
            durationEntryModel = entryModelOf(*durations.toTypedArray())
            selectedWorkoutHistory = workoutHistories.lastOrNull()
        }
    }

    LaunchedEffect(selectedWorkoutHistory) {
        if(selectedWorkoutHistory == null) return@LaunchedEffect

        withContext(Dispatchers.IO) {
            val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(selectedWorkoutHistory!!.id)
            setHistoriesByExerciseId = setHistories.groupBy { it.exerciseId }
        }
    }

    var selectedTabIndex by remember { mutableStateOf(0) }
    val tabTitles = listOf("Sets","Graphs")

    val graphsTabContent = @Composable {
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(10.dp),
        ){
            item {
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
                            bottomAxis = rememberBottomAxis(valueFormatter = horizontalAxisValueFormatter),
                        )
                    }
                }
            }
            item {
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
                            bottomAxis = rememberBottomAxis(valueFormatter = horizontalAxisValueFormatter),
                        )
                    }
                }
            }
        }




    }

    val setsTabContent = @Composable {
        Row(modifier = Modifier.padding(15.dp)) {
            if(selectedWorkoutHistory != workoutHistories.first()){
                IconButton(
                    onClick = {
                        val index = workoutHistories.indexOf(selectedWorkoutHistory)
                        selectedWorkoutHistory = workoutHistories[index-1]
                    }
                ) {
                    Icon(imageVector = Icons.Filled.ArrowBack, contentDescription = "Back")
                }
                Spacer(modifier = Modifier.width(10.dp))
            }
            Text(modifier = Modifier
                .fillMaxWidth(),
                text = selectedWorkoutHistory!!.date.format(formatter),
                textAlign = TextAlign.Center
            )
            if(selectedWorkoutHistory != workoutHistories.last()){
                Spacer(modifier = Modifier.width(10.dp))
                IconButton(
                    onClick = {
                        val index = workoutHistories.indexOf(selectedWorkoutHistory)
                        selectedWorkoutHistory = workoutHistories[index+1]
                    }
                ) {
                    Icon(imageVector = Icons.Filled.ArrowForward, contentDescription = "Forward")
                }
            }
        }

        Text(modifier = Modifier
            .fillMaxWidth(),
            text = "Duration: ${formatSecondsToMinutesSeconds(selectedWorkoutHistory!!.duration)} (mm:ss)",
            textAlign = TextAlign.Center
        )

        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(10.dp),
        ) {
            items(setHistoriesByExerciseId.keys.toList()) { key ->
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

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        modifier = Modifier.basicMarquee(),
                        text = "History: ${workout.name}"
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onGoBack) {
                        Icon(imageVector = Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                }
            )
        }
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(it),
            verticalArrangement = Arrangement.Top,
        ){
            if(workoutHistories.isEmpty() || selectedWorkoutHistory == null){
                Text(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(10.dp),
                    text = "No workout history found",
                    textAlign = TextAlign.Center
                )
                Spacer(modifier = Modifier.height(10.dp))
            }else{
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
                    0 -> setsTabContent()
                    1 -> graphsTabContent()
                }
            }
        }
    }
}

