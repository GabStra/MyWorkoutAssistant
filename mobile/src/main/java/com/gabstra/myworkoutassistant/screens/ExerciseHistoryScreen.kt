package com.gabstra.myworkoutassistant.screens

import android.annotation.SuppressLint
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.composables.StandardChart
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.patrykandpatrick.vico.core.cartesian.data.CartesianChartModel
import com.patrykandpatrick.vico.core.cartesian.data.CartesianValueFormatter
import com.patrykandpatrick.vico.core.cartesian.data.LineCartesianLayerModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import java.time.format.DateTimeFormatter
import java.util.Locale

@SuppressLint("UnusedMaterial3ScaffoldPaddingParameter")
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun ExerciseHistoryScreen(
    appViewModel: AppViewModel,
    workout: Workout,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    exercise: Exercise,
    onGoBack: () -> Unit
) {
    var isLoading by remember { mutableStateOf(true) }

    var volumeEntryModel by remember { mutableStateOf<CartesianChartModel?>(null) }
    var durationEntryModel by remember { mutableStateOf<CartesianChartModel?>(null) }
    var volumeMarkerTarget by remember { mutableStateOf<Pair<Int, Float>?>(null) }
    var durationMarkerTarget by remember { mutableStateOf<Pair<Int, Float>?>(null) }

    var workoutHistories by remember { mutableStateOf(listOf<WorkoutHistory>()) }

    val currentLocale = Locale.getDefault()

    val dateFormatter = remember(currentLocale) {
        DateTimeFormatter.ofPattern("dd/MM/yy", currentLocale)
    }

    val timeFormatter = remember(currentLocale) {
        DateTimeFormatter.ofPattern("HH:mm:ss", currentLocale)
    }

    val durationAxisValueFormatter = CartesianValueFormatter { value, _, _ ->
        formatTime(value.toInt()/1000)
    }

    val horizontalAxisValueFormatter = CartesianValueFormatter { value, _, _ ->
        val currentWorkoutHistory = workoutHistories[value.toInt()]
        currentWorkoutHistory.date.format(dateFormatter)+" "+currentWorkoutHistory.time.format(timeFormatter)
    }

    LaunchedEffect(Unit) {
        withContext(Dispatchers.IO) {
            workoutHistories = workoutHistoryDao.getWorkoutsByWorkoutIdByDateAsc(workout.id)

            if (workoutHistories.isEmpty()) {
                delay(1000)
                isLoading = false
                return@withContext
            }

            val volumes = mutableListOf<Pair<Int, Float>>()
            val durations = mutableListOf<Pair<Int, Float>>()
            for (workoutHistory in workoutHistories) {
                val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryIdAndExerciseId(
                    workoutHistory.id,
                    exercise.id
                )
                var volume = 0f
                var duration = 0f
                for (setHistory in setHistories) {
                    if (setHistory.setData is WeightSetData) {
                        val setData = setHistory.setData as WeightSetData
                        volume += setData.actualReps * setData.actualWeight
                    }

                    if (setHistory.setData is BodyWeightSetData) {
                        val setData = setHistory.setData as BodyWeightSetData
                        volume += setData.actualReps
                    }

                    if (setHistory.setData is TimedDurationSetData) {
                        val setData = setHistory.setData as TimedDurationSetData
                        duration += setData.startTimer - setData.endTimer
                    }

                    if (setHistory.setData is EnduranceSetData) {
                        val setData = setHistory.setData as EnduranceSetData
                        duration += setData.endTimer
                    }
                }
                volumes.add(Pair(workoutHistories.indexOf(workoutHistory), volume))
                durations.add(Pair(workoutHistories.indexOf(workoutHistory), duration))
            }

            if (volumes.any { it.second != 0f }) {
                if (volumes.count() == 1) {
                    volumeMarkerTarget = volumes.last()
                } else if (volumes.count() > 1) {
                    volumeMarkerTarget = volumes.maxBy { it.second }
                }

                volumeEntryModel =
                    CartesianChartModel(LineCartesianLayerModel.build { series(*(volumes.map { it.second }).toTypedArray()) })
            }

            if (durations.any { it.second != 0f }) {
                if (durations.count() == 1) {
                    durationMarkerTarget = durations.last()
                } else if (volumes.count() > 1) {
                    durationMarkerTarget = durations.maxBy { it.second }
                }

                durationEntryModel =
                    CartesianChartModel(LineCartesianLayerModel.build { series(*(durations.map { it.second }).toTypedArray()) })
            }

            isLoading = false
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        modifier = Modifier.basicMarquee(iterations = Int.MAX_VALUE),
                        text = exercise.name
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onGoBack) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back"
                        )
                    }
                }
            )
        },
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(it),
            verticalArrangement = Arrangement.Top,
        ) {
            TabRow(
                selectedTabIndex = 1,
                indicator = { tabPositions ->
                    TabRowDefaults.Indicator(
                        Modifier.tabIndicatorOffset(tabPositions[1]),
                        color = Color.White, // Set the indicator color
                        height = 5.dp // Set the indicator thickness
                    )
                }
            ) {
                Tab(
                    selected = false,
                    onClick = {
                        appViewModel.setScreenData(
                            ScreenData.ExerciseDetail(
                                workout.id,
                                exercise.id
                            ), true
                        )
                    },
                    text = { Text("Overview") },
                    selectedContentColor = Color.White, // Color when tab is selected
                    unselectedContentColor = Color.LightGray // Color when tab is not selected
                )
                Tab(
                    selected = true,
                    onClick = { },
                    text = { Text("History") },
                    selectedContentColor = Color.White, // Color when tab is selected
                    unselectedContentColor = Color.LightGray // Color when tab is not selected
                )
            }

            if (isLoading || workoutHistories.isEmpty()) {
                Card(
                    modifier = Modifier
                        .padding(15.dp)
                ){
                    Text(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(20.dp),
                        text = if (isLoading) "Loading..." else "No history found",
                        textAlign = TextAlign.Center
                    )
                }
            } else {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(10.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    if (volumeEntryModel != null) {
                        StandardChart(
                            modifier = Modifier.padding(10.dp),
                            cartesianChartModel = volumeEntryModel!!,
                            title = "Cumulative Volume over time",
                            markerPosition = volumeMarkerTarget!!.first.toFloat(),
                            bottomAxisValueFormatter = horizontalAxisValueFormatter
                        )
                    }

                    if (durationEntryModel != null) {
                        StandardChart(
                            modifier = Modifier.padding(10.dp),
                            cartesianChartModel = durationEntryModel!!,
                            markerPosition = durationMarkerTarget!!.first.toFloat(),
                            title = "Cumulative Duration over time",
                            markerTextFormatter = { formatTime(it.toInt()/1000) },
                            startAxisValueFormatter = durationAxisValueFormatter,
                            bottomAxisValueFormatter = horizontalAxisValueFormatter
                        )
                    }
                }
            }
        }
    }
}