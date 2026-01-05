package com.gabstra.myworkoutassistant.screens

import android.annotation.SuppressLint
import android.util.Log
import android.widget.Toast
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.Interaction
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.automirrored.filled.ShowChart
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowForward
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.CircularProgressIndicator
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
import androidx.compose.runtime.mutableDoubleStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.HealthConnectClient
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.calculateKiloCaloriesBurned
import com.gabstra.myworkoutassistant.composables.AppDropdownMenu
import com.gabstra.myworkoutassistant.composables.AppDropdownMenuItem
import com.gabstra.myworkoutassistant.composables.ExpandableContainer
import com.gabstra.myworkoutassistant.composables.ExerciseRenderer
import com.gabstra.myworkoutassistant.composables.FilterRange
import com.gabstra.myworkoutassistant.composables.HeartRateChart
import com.gabstra.myworkoutassistant.composables.RangeDropdown
import com.gabstra.myworkoutassistant.composables.StandardChart
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.deleteWorkoutHistoriesFromHealthConnect
import com.gabstra.myworkoutassistant.filterBy
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.formatTimeHourMinutes
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutRecordDao
import com.gabstra.myworkoutassistant.shared.colorsByZone
import com.gabstra.myworkoutassistant.shared.formatNumber
import com.gabstra.myworkoutassistant.shared.getHeartRateFromPercentage
import com.gabstra.myworkoutassistant.shared.getMaxHearthRatePercentage
import com.gabstra.myworkoutassistant.shared.getNewSetFromSetHistory
import com.gabstra.myworkoutassistant.shared.mapPercentageToZone
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.zoneRanges
import com.gabstra.myworkoutassistant.verticalColumnScrollbar
import com.kevinnzou.compose.progressindicator.SimpleProgressIndicator
import com.patrykandpatrick.vico.core.cartesian.data.CartesianChartModel
import com.patrykandpatrick.vico.core.cartesian.data.CartesianValueFormatter
import com.patrykandpatrick.vico.core.cartesian.data.LineCartesianLayerModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.Duration
import java.time.format.DateTimeFormatter
import java.util.Calendar
import java.util.Locale
import java.util.UUID

@Composable
fun Menu(
    modifier: Modifier,
    onDeleteHistory: () -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }

    Box(
        modifier = modifier.wrapContentSize(Alignment.TopEnd)
    ) {
        IconButton(onClick = { expanded = !expanded }) {
            Icon(
                imageVector = Icons.Default.MoreVert,
                contentDescription = "More"
            )
        }

        AppDropdownMenu(
            expanded = expanded,
            onDismissRequest = { expanded = false }
        ) {
            AppDropdownMenuItem(
                text = { Text("Delete Selected History") },
                onClick = {
                    onDeleteHistory()
                    expanded = false
                }
            )
        }
    }
}

@SuppressLint("UnusedMaterial3ScaffoldPaddingParameter")
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun WorkoutHistoryScreen(
    appViewModel: AppViewModel,
    healthConnectClient: HealthConnectClient,
    workoutHistoryDao: WorkoutHistoryDao,
    workoutRecordDao: WorkoutRecordDao,
    workoutHistoryId: UUID? = null,
    setHistoryDao: SetHistoryDao,
    workout: Workout,
    onGoBack: () -> Unit
) {

    val context = LocalContext.current

    val currentLocale = Locale.getDefault()
    val scope = rememberCoroutineScope()
    val userAge by appViewModel.userAge

    val dateFormatter = remember(currentLocale) {
        DateTimeFormatter.ofPattern("dd/MM/yy", currentLocale)
    }

    val timeFormatter = remember(currentLocale) {
        DateTimeFormatter.ofPattern("HH:mm", currentLocale)
    }

    var selectedRange by remember { mutableStateOf(FilterRange.LAST_30_DAYS) }

    var workoutHistories by remember { mutableStateOf(listOf<WorkoutHistory>()) }

    val historiesToShow = remember(workoutHistories, selectedRange) {
        workoutHistories.filterBy(selectedRange)
    }

    var selectedWorkoutHistory by remember { mutableStateOf<WorkoutHistory?>(null) }

    var setHistoriesByExerciseId by remember { mutableStateOf<Map<UUID, List<SetHistory>>>(emptyMap()) }

    var volumeEntryModel by remember { mutableStateOf<CartesianChartModel?>(null) }
    var durationEntryModel by remember { mutableStateOf<CartesianChartModel?>(null) }
    var workoutDurationEntryModel by remember { mutableStateOf<CartesianChartModel?>(null) }
    var heartRateEntryModel by remember { mutableStateOf<CartesianChartModel?>(null) }

    var volumeMarkerTarget by remember { mutableStateOf<Pair<Int, Double>?>(null) }
    var durationMarkerTarget by remember { mutableStateOf<Pair<Int, Float>?>(null) }
    var workoutDurationMarkerTarget by remember { mutableStateOf<Pair<Int, Float>?>(null) }
    var heartBeatMarkerTarget by remember { mutableStateOf<Pair<Int, Int>?>(null) }
    var zoneCounter by remember { mutableStateOf<Map<Int, Int>?>(null) }

    val horizontalAxisValueFormatter = remember(historiesToShow) {
        CartesianValueFormatter { _, value, _->
            if(value.toInt() < 0 || value.toInt() >= historiesToShow.size) return@CartesianValueFormatter "-"
            val currentWorkoutHistory = historiesToShow[value.toInt()]
            currentWorkoutHistory.date.format(dateFormatter)
        }
    }

    val volumeAxisValueFormatter = CartesianValueFormatter { _, value, _ ->
        formatNumber(value)
    }

    val durationAxisValueFormatter = CartesianValueFormatter { _, value, _ ->
        formatTime(value.toInt() / 1000)
    }

    val workoutDurationAxisValueFormatter = CartesianValueFormatter { _, value, _->
        formatTimeHourMinutes(value.toInt())
    }

    var isLoading by remember { mutableStateOf(true) }

    var selectedMode by remember { mutableIntStateOf(0) } // 0 for Graphs, 1 for Sets

    val workouts by appViewModel.workoutsFlow.collectAsState()
    val selectedWorkout = workouts.find { it.id == workout.id }!!

    val exerciseById = remember(workouts) {
        workouts.flatMap { workout ->
            workout.workoutComponents.filterIsInstance<Exercise>() +
                    workout.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }
        }.associateBy { it.id }
    }

    val workoutVersions = workouts.filter { it.globalId == selectedWorkout.globalId }

    var kiloCaloriesBurned by remember { mutableDoubleStateOf(0.0) }

    val volumes = remember { mutableListOf<Pair<Int, Double>>() }
    val durations = remember { mutableListOf<Pair<Int, Float>>() }
    val workoutDurations = remember { mutableListOf<Pair<Int, Float>>() }

    suspend fun setCharts(workoutHistories: List<WorkoutHistory>){
        volumes.clear()
        durations.clear()
        workoutDurations.clear()

        volumeMarkerTarget = null
        durationMarkerTarget = null
        workoutDurationMarkerTarget = null

        if(workoutHistories.isEmpty()) return

        for (workoutHistory in workoutHistories) {
            val setHistories =
                setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)

            val validSetHistories = setHistories.filter { it.exerciseId != null }

            var volume = 0.0
            var duration = 0f

            for (setHistory in validSetHistories) {
                if(!exerciseById.containsKey( setHistory.exerciseId!!)) {
                    continue
                }

                val selectedExercise = exerciseById[setHistory.exerciseId!!]!!
                val equipment = selectedExercise.equipmentId?.let { appViewModel.getEquipmentById(it) }

                if (setHistory.setData is WeightSetData) {
                    val setData = setHistory.setData as WeightSetData
                    volume += setData.calculateVolume()
                }

                if (setHistory.setData is BodyWeightSetData) {
                    val setData = setHistory.setData as BodyWeightSetData
                    volume += setData.calculateVolume()
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
            workoutDurations.add(
                Pair(
                    workoutHistories.indexOf(workoutHistory),
                    workoutHistory.duration.toFloat()
                )
            )
        }

        //check if volumes are not all 0
        if (volumes.any { it.second != 0.0 }) {
            if (volumes.count() == 1) {
                volumeMarkerTarget = volumes.last()
            } /*else if (volumes.count() > 1) {
                volumeMarkerTarget = volumes.maxBy { it.second }
            }*/

            volumeEntryModel =
                CartesianChartModel(LineCartesianLayerModel.build {
                    series(volumes.map { it.first },volumes.map { it.second })
                })
        }

        if (durations.any { it.second != 0f }) {
            if (durations.count() == 1) {
                durationMarkerTarget = durations.last()
            } /*else if (volumes.count() > 1) {
                durationMarkerTarget = durations.maxBy { it.second }
            }*/

            durationEntryModel =
                CartesianChartModel(LineCartesianLayerModel.build {
                    series(durations.map { it.first },durations.map { it.second })
                })
        }

        if (workoutDurations.count() == 1) {
            workoutDurationMarkerTarget = workoutDurations.last()
        } /*else if (workoutDurations.count() > 1) {
            workoutDurationMarkerTarget = workoutDurations.maxBy { it.second }
        }*/


        workoutDurationEntryModel =
            CartesianChartModel(LineCartesianLayerModel.build { series(*(workoutDurations.map { it.second }).toTypedArray()) })
    }

    LaunchedEffect(workout) {
        isLoading = true
        withContext(Dispatchers.IO) {

            workoutHistories = workoutVersions.flatMap { workoutVersion ->
                workoutHistoryDao.getWorkoutsByWorkoutId(workoutVersion.id)
            }.sortedBy { it.date }

            if (workoutHistoryId == null) {
                workoutHistories = workoutHistories.filter { it.isDone }
            }

            if (workoutHistories.isEmpty()) {
                delay(500)
                isLoading = false
                return@withContext
            }

            selectedWorkoutHistory =
                if (workoutHistoryId != null) workoutHistories.find { it.id == workoutHistoryId } else workoutHistories.lastOrNull()

            if (workoutHistoryId != null && selectedWorkoutHistory != null) {
                selectedMode = 1
            }

            delay(500)
            if (selectedWorkoutHistory == null) {
                isLoading = false
            }
        }
    }

    LaunchedEffect(selectedWorkoutHistory) {
        if (selectedWorkoutHistory == null) return@LaunchedEffect

        isLoading = true

        zoneCounter = null
        heartRateEntryModel = null

        withContext(Dispatchers.IO) {

            if (selectedWorkoutHistory!!.heartBeatRecords.isNotEmpty() && selectedWorkoutHistory!!.heartBeatRecords.any { it != 0 }) {

                selectedWorkoutHistory!!.heartBeatRecords.maxOrNull()?.let { maxHeartBeat ->
                    // Create a pair of the index of the max heartbeat and the value itself
                    heartBeatMarkerTarget = Pair(
                        selectedWorkoutHistory!!.heartBeatRecords.indexOf(maxHeartBeat),
                        maxHeartBeat
                    )
                }

                zoneCounter = mapOf(5 to 0, 4 to 0, 3 to 0, 2 to 0, 1 to 0)

                for (heartBeat in selectedWorkoutHistory!!.heartBeatRecords) {
                    val percentage = getMaxHearthRatePercentage(heartBeat, userAge)
                    val zone = mapPercentageToZone(percentage)
                    if (zone == 0) continue
                    zoneCounter = zoneCounter!!.plus(zone to zoneCounter!![zone]!!.plus(1))
                }

                heartRateEntryModel =
                    CartesianChartModel(LineCartesianLayerModel.build {
                        series(
                            selectedWorkoutHistory!!.heartBeatRecords.map { getMaxHearthRatePercentage(it, userAge) }
                        )
                    })
            }

            val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(selectedWorkoutHistory!!.id)
            setHistoriesByExerciseId = setHistories
                .filter { it.exerciseId != null }
                .groupBy { it.exerciseId!! }



            val avgHeartRate = selectedWorkoutHistory!!.heartBeatRecords.average()

            val currentYear = Calendar.getInstance().get(Calendar.YEAR)
            val age =  currentYear - appViewModel.workoutStore.birthDateYear
            val weight = appViewModel.workoutStore.weightKg
            val durationMinutes = selectedWorkoutHistory!!.duration.toDouble() / 60
            kiloCaloriesBurned = calculateKiloCaloriesBurned(
                age = age,
                weightKg = weight.toDouble(),
                averageHeartRate = avgHeartRate,
                durationMinutes = durationMinutes,
                isMale = true
            )

            delay(500)
            isLoading = false
        }
    }

    LaunchedEffect(historiesToShow) {
        if (historiesToShow.isEmpty()) return@LaunchedEffect
        setCharts(historiesToShow)
    }

    val graphsTabContent = @Composable {
        Column(
            modifier = Modifier
                .fillMaxSize(),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            RangeDropdown(selectedRange) { selectedRange = it }

            if (volumeEntryModel != null) {
                StandardChart(
                    isZoomEnabled = true,
                    modifier = Modifier,
                    cartesianChartModel = volumeEntryModel!!,
                    title = "Total volume (KG)",
                    markerTextFormatter = { formatNumber(it) },
                    startAxisValueFormatter = volumeAxisValueFormatter,
                    bottomAxisValueFormatter = horizontalAxisValueFormatter,
                    markerPosition = volumeMarkerTarget?.first?.toDouble()
                )
            }
            if (durationEntryModel != null) {
                StandardChart(
                    modifier = Modifier,
                    cartesianChartModel = durationEntryModel!!,
                    title = "Total duration",
                    markerTextFormatter = { formatTime(it.toInt() / 1000) },
                    startAxisValueFormatter = durationAxisValueFormatter,
                    bottomAxisValueFormatter = horizontalAxisValueFormatter,
                    markerPosition = durationMarkerTarget?.first?.toDouble()
                )
            }
            if (workoutDurationEntryModel != null) {
                StandardChart(
                    isZoomEnabled = true,
                    modifier = Modifier,
                    cartesianChartModel = workoutDurationEntryModel!!,
                    title = "Workout duration (hh:mm)",
                    markerTextFormatter = { formatTimeHourMinutes(it.toInt()) },
                    startAxisValueFormatter = workoutDurationAxisValueFormatter,
                    bottomAxisValueFormatter = horizontalAxisValueFormatter,
                    markerPosition = workoutDurationMarkerTarget?.first?.toDouble()
                )
            }
        }
    }

    val workoutSelector = @Composable {
        Row(
            verticalAlignment = Alignment.CenterVertically
        ) {
            IconButton(
                modifier = Modifier.size(25.dp),
                onClick = {
                    val index = workoutHistories.indexOf(selectedWorkoutHistory)
                    if (index > 0) { // Check to avoid IndexOutOfBoundsException
                        isLoading = true
                        selectedWorkoutHistory = workoutHistories[index - 1]
                    }
                },
                enabled = selectedWorkoutHistory != workoutHistories.first()
            ) {
                val color = MaterialTheme.colorScheme.onBackground

                Icon(imageVector = Icons.Filled.ArrowBack, contentDescription = "Previous",tint = color)
            }
            Spacer(modifier = Modifier.width(10.dp))
            Text(
                modifier = Modifier
                    .weight(1f),
                text = selectedWorkoutHistory!!.date.format(dateFormatter) + " "+ selectedWorkoutHistory!!.time.format(timeFormatter),
                textAlign = TextAlign.Center,
                color = MaterialTheme.colorScheme.onBackground,
                style = MaterialTheme.typography.titleMedium,
            )
            Spacer(modifier = Modifier.width(10.dp))
            IconButton(
                modifier = Modifier.size(25.dp),
                onClick = {
                    val index = workoutHistories.indexOf(selectedWorkoutHistory)
                    if (index < workoutHistories.size - 1) { // Check to avoid IndexOutOfBoundsException
                        isLoading = true
                        selectedWorkoutHistory = workoutHistories[index + 1]
                    }
                },
                enabled = selectedWorkoutHistory != workoutHistories.last()
            ) {
                val color = MaterialTheme.colorScheme.onBackground

                Icon(imageVector = Icons.Filled.ArrowForward, contentDescription = "Next",tint = color)
            }
        }
    }

    val setsTabContent = @Composable {
        Column(
            modifier = Modifier.padding(top=10.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            workoutSelector()

            if (heartRateEntryModel != null && selectedWorkoutHistory != null && selectedWorkoutHistory!!.heartBeatRecords.isNotEmpty()) {
                HeartRateChart(
                    modifier = Modifier.fillMaxWidth(),
                    cartesianChartModel = heartRateEntryModel!!,
                    title = "Heart Rate during Workout",
                    userAge = userAge,
                )

                StyledCard {
                    ExpandableContainer(
                        isOpen = false,
                        modifier = Modifier.fillMaxWidth(),
                        isExpandable =  zoneCounter != null,
                        title = { modifier ->
                            Row(
                                modifier = modifier.padding(10.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.SpaceBetween
                            ) {
                                val minHeartRate =
                                    selectedWorkoutHistory!!.heartBeatRecords.filter { it != 0 }
                                        .min()
                                val maxHeartRate = selectedWorkoutHistory!!.heartBeatRecords.max()

                                Text(
                                    text = "Duration: ${formatTime(selectedWorkoutHistory!!.duration)}",
                                    Modifier.weight(2f),
                                    color = MaterialTheme.colorScheme.onBackground,
                                    style = MaterialTheme.typography.bodyMedium,
                                )
                                Column(modifier = Modifier.weight(1f),) {
                                    Row(
                                        modifier = Modifier.fillMaxWidth(),
                                        horizontalArrangement = Arrangement.SpaceBetween
                                    ) {
                                        Text(
                                            text = "Min:",
                                            style = MaterialTheme.typography.bodySmall,
                                            color = MaterialTheme.colorScheme.onBackground,
                                        )
                                        Text(
                                            text = "$minHeartRate bpm",
                                            style = MaterialTheme.typography.bodySmall,
                                            color = MaterialTheme.colorScheme.onBackground,
                                            textAlign = TextAlign.End
                                        )
                                    }
                                    Row(
                                        modifier = Modifier.fillMaxWidth(),
                                        horizontalArrangement = Arrangement.SpaceBetween
                                    ) {
                                        Text(
                                            text = "Max:",
                                            style = MaterialTheme.typography.bodySmall,
                                            color = MaterialTheme.colorScheme.onBackground,
                                        )
                                        Text(
                                            text = "$maxHeartRate bpm",
                                            style = MaterialTheme.typography.bodySmall,
                                            color = MaterialTheme.colorScheme.onBackground,
                                            textAlign = TextAlign.End
                                        )
                                    }
                                    if (kiloCaloriesBurned != 0.0 || !kiloCaloriesBurned.isNaN()) {
                                        Row(
                                            modifier = Modifier.fillMaxWidth(),
                                            horizontalArrangement = Arrangement.SpaceBetween
                                        ) {
                                            Text(
                                                text = "kcal:",
                                                style = MaterialTheme.typography.bodySmall,
                                                color = MaterialTheme.colorScheme.onBackground,
                                            )
                                            Text(
                                                text = "${kiloCaloriesBurned.toInt()}",
                                                style = MaterialTheme.typography.bodySmall,
                                                color = MaterialTheme.colorScheme.onBackground,
                                                textAlign = TextAlign.End
                                            )
                                        }
                                    }
                                }
                            }
                        },
                        content = {
                            Column(
                                modifier = Modifier.padding(10.dp),
                                verticalArrangement = Arrangement.spacedBy(10.dp)
                            ) {
                                //Invert the order of the zones
                                zoneCounter!!.forEach { (zone, count) ->
                                    Column(modifier = Modifier.fillMaxWidth()) {
                                        val total = zoneCounter!!.values.sum()
                                        var progress = count.toFloat() / total
                                        if (progress.isNaN()) {
                                            progress = 0f
                                        }
                                        Text(
                                            text = "Zone $zone",
                                            color = MaterialTheme.colorScheme.onBackground,
                                            style = MaterialTheme.typography.bodyMedium,
                                        )
                                        Spacer(Modifier.height(5.dp))
                                        Row(modifier = Modifier.fillMaxWidth()) {
                                            val (lowerBound, upperBound) = zoneRanges[zone]
                                            val lowHr =
                                                getHeartRateFromPercentage(lowerBound, userAge)
                                            val highHr =
                                                getHeartRateFromPercentage(upperBound, userAge)
                                            Text(
                                                "$lowHr - $highHr bpm",
                                                Modifier.weight(1f),
                                                color = MaterialTheme.colorScheme.onBackground,
                                                style = MaterialTheme.typography.bodySmall,
                                            )
                                            Spacer(Modifier.weight(1f))
                                            Text(
                                                text = "${(progress * 100).toInt()}% ${
                                                    formatTime(count)
                                                }",
                                                Modifier.weight(1f),
                                                style = MaterialTheme.typography.bodySmall,
                                                textAlign = TextAlign.End,
                                                color = MaterialTheme.colorScheme.onBackground,
                                            )
                                        }
                                        Spacer(Modifier.height(5.dp))
                                        SimpleProgressIndicator(
                                            progress = progress,
                                            trackColor = MaterialTheme.colorScheme.surfaceVariant,
                                            modifier = Modifier
                                                .fillMaxWidth()
                                                .height(16.dp)
                                                .clip(RoundedCornerShape(16.dp)),
                                            progressBarColor = colorsByZone[zone],
                                        )
                                    }
                                }
                            }
                        })
                }


            }
            Column {
                Text(
                    modifier = Modifier.fillMaxWidth().padding(vertical= 10.dp),
                    text = "Exercise Histories",
                    style = MaterialTheme.typography.titleMedium,
                    textAlign = TextAlign.Center,
                    color = MaterialTheme.colorScheme.onBackground,
                )
                Column(
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    setHistoriesByExerciseId.keys.toList()
                        .forEach() { key ->
                            val exercise = exerciseById[key]!!
                            val setHistories = setHistoriesByExerciseId[key]!!

                            val hasTarget =
                                exercise.lowerBoundMaxHRPercent != null && exercise.upperBoundMaxHRPercent != null

                            var targetCounter = 0
                            var targetTotal = 0

                            LaunchedEffect(hasTarget) {
                                if (hasTarget) {
                                    targetCounter = 0

                                    setHistories.filter { it.setData !is RestSetData && it.startTime != null && it.endTime != null }
                                        .forEach { setHistory ->
                                            val hrTimeOffset = Duration.between(
                                                selectedWorkoutHistory!!.startTime,
                                                setHistory.startTime,
                                            ).seconds
                                            val setDuration = Duration.between(
                                                setHistory.startTime,
                                                setHistory.endTime
                                            ).seconds

                                            val lowHr = getHeartRateFromPercentage(
                                                exercise.lowerBoundMaxHRPercent!!,
                                                userAge
                                            )
                                            val highHr = getHeartRateFromPercentage(
                                                exercise.upperBoundMaxHRPercent!!,
                                                userAge
                                            )

                                            val hrEntriesCount =
                                                selectedWorkoutHistory!!.heartBeatRecords.filterIndexed { index, value ->
                                                    index >= hrTimeOffset && index <= hrTimeOffset + setDuration && value >= lowHr && value <= highHr
                                                }.size

                                            targetCounter += hrEntriesCount
                                            targetTotal += setDuration.toInt()
                                        }
                                }
                            }

                            // Convert SetHistory to Set objects, sorted by order
                            val sets = setHistories
                                .sortedBy { it.order }
                                .map { getNewSetFromSetHistory(it) }
                            
                            // Create an exercise with the historical sets
                            val exerciseWithHistorySets = exercise.copy(sets = sets)
                            
                            StyledCard {
                                if (hasTarget) {
                                    Column {
                                                Column(
                                                    modifier = Modifier.fillMaxWidth()
                                                        .padding(10.dp)
                                                ) {
                                                    var progress =
                                                        targetCounter.toFloat() / targetTotal
                                                    if (progress.isNaN()) {
                                                        progress = 0f
                                                    }

                                                    Text(
                                                        text = "Target HR",
                                                        color = MaterialTheme.colorScheme.onBackground,
                                                        style = MaterialTheme.typography.bodyMedium,
                                                    )
                                                    Spacer(Modifier.height(5.dp))
                                                    Row(modifier = Modifier.fillMaxWidth()) {
                                                        val lowHr = getHeartRateFromPercentage(
                                                            exercise.lowerBoundMaxHRPercent!!,
                                                            userAge
                                                        )
                                                        val highHr = getHeartRateFromPercentage(
                                                            exercise.upperBoundMaxHRPercent!!,
                                                            userAge
                                                        )
                                                        Text(
                                                            "$lowHr - $highHr bpm",
                                                            Modifier.weight(1f),
                                                            color = MaterialTheme.colorScheme.onBackground,
                                                            style = MaterialTheme.typography.bodySmall,
                                                        )
                                                        Spacer(Modifier.weight(1f))
                                                        Text(
                                                            text = "${(progress * 100).toInt()}% ${
                                                                formatTime(
                                                                    targetCounter
                                                                )
                                                            }",
                                                            Modifier.weight(1f),
                                                            style = MaterialTheme.typography.bodySmall,
                                                            textAlign = TextAlign.End,
                                                            color = MaterialTheme.colorScheme.onBackground,
                                                        )
                                                    }
                                                    Spacer(Modifier.height(5.dp))
                                                    SimpleProgressIndicator(
                                                        progress = progress,
                                                        trackColor = MaterialTheme.colorScheme.onSurfaceVariant,
                                                        modifier = Modifier
                                                            .fillMaxWidth()
                                                            .height(16.dp)
                                                            .clip(RoundedCornerShape(16.dp)),
                                                        progressBarColor = Color.hsl(
                                                            113f,
                                                            0.79f,
                                                            0.34f
                                                        ),
                                                    )
                                                }
                                                ExerciseRenderer(
                                                    exercise = exerciseWithHistorySets,
                                                    showRest = true,
                                                    appViewModel = appViewModel,
                                                    customTitle = { m ->
                                                        Row(
                                                            horizontalArrangement = Arrangement.SpaceBetween,
                                                            modifier = m,
                                                            verticalAlignment = Alignment.CenterVertically
                                                        ) {
                                                            if(exerciseById.containsKey(key)){
                                                                IconButton(
                                                                    onClick = {
                                                                        appViewModel.setScreenData(
                                                                            ScreenData.ExerciseHistory(
                                                                                workout.id,
                                                                                exercise.id
                                                                            )
                                                                        )
                                                                    }) {
                                                                    Icon(
                                                                        imageVector = Icons.Filled.Search,
                                                                        contentDescription = "Details",
                                                                        tint = MaterialTheme.colorScheme.onBackground
                                                                    )
                                                                }
                                                            }
                                                            Text(
                                                                modifier = Modifier
                                                                    .weight(1f)
                                                                    .basicMarquee(iterations = Int.MAX_VALUE),
                                                                text = exercise.name,
                                                                style = MaterialTheme.typography.bodyLarge,
                                                                color = if (exercise.enabled) MaterialTheme.colorScheme.onBackground else MaterialTheme.colorScheme.onSurfaceVariant,
                                                            )
                                                        }
                                                    }
                                                )
                                            }
                                } else {
                                    ExerciseRenderer(
                                        exercise = exerciseWithHistorySets,
                                        showRest = true,
                                        appViewModel = appViewModel,
                                        customTitle = { m ->
                                            Row(
                                                horizontalArrangement = Arrangement.SpaceBetween,
                                                modifier = m,
                                                verticalAlignment = Alignment.CenterVertically
                                            ) {
                                                if(exerciseById.containsKey(key)){
                                                    IconButton(
                                                        onClick = {
                                                            appViewModel.setScreenData(
                                                                ScreenData.ExerciseHistory(
                                                                    workout.id,
                                                                    exercise.id
                                                                )
                                                            )
                                                        }) {
                                                        Icon(
                                                            imageVector = Icons.Filled.Search,
                                                            contentDescription = "Details",
                                                            tint = MaterialTheme.colorScheme.onBackground
                                                        )
                                                    }
                                                }
                                                Text(
                                                    modifier = Modifier
                                                        .weight(1f)
                                                        .basicMarquee(iterations = Int.MAX_VALUE),
                                                    text = exercise.name,
                                                    style = MaterialTheme.typography.bodyLarge,
                                                    color = if (exercise.enabled) MaterialTheme.colorScheme.onBackground else MaterialTheme.colorScheme.onSurfaceVariant,
                                                )
                                            }
                                        }
                                    )
                                }
                            }
                        }
                }
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
                    Icon(
                        Icons.AutoMirrored.Filled.ShowChart,
                        contentDescription = "Graphs",
                        tint = if (selectedMode == 0) {
                            MaterialTheme.colorScheme.background
                        } else {
                            MaterialTheme.colorScheme.onBackground
                        }
                    )
                    Spacer(modifier = Modifier.width(5.dp))
                    Text("Graphs", color =  if (selectedMode == 0) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onBackground, style = MaterialTheme.typography.titleMedium,)
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
                    Icon(
                        Icons.AutoMirrored.Filled.List,
                        contentDescription = "Sets",
                        tint = if (selectedMode == 1) {
                            MaterialTheme.colorScheme.background
                        } else {
                            MaterialTheme.colorScheme.onBackground
                        }
                    )
                    Spacer(modifier = Modifier.width(5.dp))
                    Text("Sets", color =  if (selectedMode == 1) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onBackground, style = MaterialTheme.typography.titleMedium,)
                }
            }
        }
    }

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
                        textAlign = TextAlign.Center,
                        text = workout.name
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onGoBack) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back"
                        )
                    }
                },
                actions = {
                    val modifier = if(selectedWorkoutHistory == null || workoutHistories.isEmpty() || selectedMode == 0) Modifier.alpha(0f) else Modifier
                    Menu(
                        modifier = modifier,
                        onDeleteHistory = {
                            scope.launch {
                                val index = workoutHistories.indexOf(selectedWorkoutHistory)
                                try {
                                    deleteWorkoutHistoriesFromHealthConnect(listOf(selectedWorkoutHistory) as List<WorkoutHistory>,healthConnectClient)
                                }catch (e: Exception) {
                                    Log.e("MainActivity", "Error deleting workout histories from HealthConnect", e)
                                    Toast.makeText(context, "Failed to delete workout histories from HealthConnect", Toast.LENGTH_SHORT).show()
                                }

                                workoutHistoryDao.deleteById(selectedWorkoutHistory!!.id)
                                workoutRecordDao.deleteByWorkoutHistoryId(selectedWorkoutHistory!!.id)

                                if (workoutHistories.size > 1) {
                                    selectedWorkoutHistory = if (index == workoutHistories.size - 1) {
                                        workoutHistories[index - 1]
                                    }else {
                                        workoutHistories[index + 1]
                                    }
                                }

                                workoutHistories = workoutHistories.toMutableList().apply { removeAt(index) }

                                setCharts(workoutHistories)

                                Toast.makeText(context, "History Deleted", Toast.LENGTH_SHORT).show()
                                if(workoutHistories.isEmpty()) {
                                    onGoBack()
                                }
                            }
                        }
                    )
                }
            )
        },
    ) { paddingValues ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues),
            verticalArrangement = Arrangement.Top,
        ) {
            TabRow(
                contentColor = MaterialTheme.colorScheme.background,
                selectedTabIndex = 1,
                indicator = { tabPositions ->
                    TabRowDefaults.Indicator(
                        Modifier.tabIndicatorOffset(tabPositions[1]),
                        color = MaterialTheme.colorScheme.primary, // Set the indicator color
                        height = 2.dp // Set the indicator thickness
                    )
                }
            ) {
                Tab(
                    modifier = Modifier.background(MaterialTheme.colorScheme.background),
                    selected = false,
                    onClick = {
                        appViewModel.setScreenData(
                            ScreenData.WorkoutDetail(workout.id),
                            true
                        )
                    },
                    text = { Text(text = "Overview") },
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
                Tab(
                    modifier = Modifier.background(MaterialTheme.colorScheme.background),
                    selected = true,
                    onClick = { },
                    text = { Text(text = "History") },
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

            if(isLoading){
                Box(
                    modifier = Modifier
                        .fillMaxSize(),
                    contentAlignment = Alignment.Center
                ){
                    CircularProgressIndicator(
                        modifier = Modifier.width(32.dp),
                        color = MaterialTheme.colorScheme.primary,
                        trackColor = MaterialTheme.colorScheme.scrim,
                    )
                }
            } else {
                if (historiesToShow.isEmpty()) {
                    Box(
                        modifier = Modifier
                            .fillMaxSize(),
                        contentAlignment = Alignment.Center
                    ){
                        StyledCard(
                            modifier = Modifier
                                .padding(15.dp),
                            
                        ) {
                            Text(
                                modifier = Modifier
                                    .padding(15.dp),
                                text = "No history found",
                                textAlign = TextAlign.Center,
                                color = MaterialTheme.colorScheme.onSurface.copy(alpha = .87f),
                            )
                        }
                    }
                } else {
                    AnimatedContent(
                        modifier = Modifier.weight(1f),
                        targetState = selectedMode,
                        transitionSpec = {
                            fadeIn(animationSpec = tween(500)) togetherWith fadeOut(animationSpec = tween(500))
                        }, label = ""
                    ) { updatedSelectedMode ->
                        val scrollState = rememberScrollState()

                        Column(
                            modifier = Modifier
                                .fillMaxSize()
                                .padding(top = 10.dp)
                                .verticalColumnScrollbar(scrollState)
                                .verticalScroll(scrollState)
                                .padding(horizontal = 15.dp),
                            verticalArrangement = Arrangement.spacedBy(10.dp)
                        ) {
                            when (updatedSelectedMode) {
                                0 -> graphsTabContent()
                                1 -> setsTabContent()
                            }
                        }
                    }
                }
            }
            if (!(historiesToShow.isEmpty() || selectedWorkoutHistory == null)) {
                customBottomBar()
            }
        }
    }
}

