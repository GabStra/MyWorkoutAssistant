package com.gabstra.myworkoutassistant.screens

import android.annotation.SuppressLint
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.automirrored.filled.ShowChart
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowForward
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
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.composables.ExpandableContainer
import com.gabstra.myworkoutassistant.composables.SetHistoriesRenderer
import com.gabstra.myworkoutassistant.composables.StandardChart
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.getOneRepMax
import com.gabstra.myworkoutassistant.round
import com.gabstra.myworkoutassistant.shared.DarkGray
import com.gabstra.myworkoutassistant.shared.LightGray
import com.gabstra.myworkoutassistant.shared.MediumLightGray
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.formatNumber
import com.gabstra.myworkoutassistant.shared.getHeartRateFromPercentage
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.verticalColumnScrollbar
import com.kevinnzou.compose.progressindicator.SimpleProgressIndicator
import com.patrykandpatrick.vico.core.cartesian.data.CartesianChartModel
import com.patrykandpatrick.vico.core.cartesian.data.CartesianValueFormatter
import com.patrykandpatrick.vico.core.cartesian.data.LineCartesianLayerModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import java.time.Duration
import java.time.format.DateTimeFormatter
import java.util.Locale
import java.util.UUID

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
    var volumeMarkerTarget by remember { mutableStateOf<Pair<Int, Double>?>(null) }
    var durationMarkerTarget by remember { mutableStateOf<Pair<Int, Float>?>(null) }
    var oneRepMaxMarkerTarget by remember { mutableStateOf<Pair<Int, Double>?>(null) }
    var oneRepMaxEntryModel by remember { mutableStateOf<CartesianChartModel?>(null) }
    var workoutHistories by remember { mutableStateOf(listOf<WorkoutHistory>()) }

    var selectedMode by remember { mutableIntStateOf(0) }

    val userAge by appViewModel.userAge

    val currentLocale = Locale.getDefault()

    val volumeAxisValueFormatter = CartesianValueFormatter { _, value, _ ->
        formatNumber(value)
    }

    val dateFormatter = remember(currentLocale) {
        DateTimeFormatter.ofPattern("dd/MM/yy", currentLocale)
    }

    val timeFormatter = remember(currentLocale) {
        DateTimeFormatter.ofPattern("HH:mm:ss", currentLocale)
    }

    val durationAxisValueFormatter = CartesianValueFormatter { _, value, _ ->
        formatTime(value.toInt()/1000)
    }

    val horizontalAxisValueFormatter = CartesianValueFormatter { _, value, _ ->
        val currentWorkoutHistory = workoutHistories[value.toInt()]
        currentWorkoutHistory.date.format(dateFormatter)//+" "+currentWorkoutHistory.time.format(timeFormatter)
    }

    val workouts by appViewModel.workoutsFlow.collectAsState()

    val volumes = remember { mutableListOf<Pair<Int, Double>>() }
    val durations = remember { mutableListOf<Pair<Int, Float>>() }
    val oneRepMaxes = remember { mutableListOf<Pair<Int, Double>>() }


    var selectedWorkoutHistory by remember { mutableStateOf<WorkoutHistory?>(null) }
    var setHistoriesByWorkoutHistoryId by remember { mutableStateOf<Map<UUID, List<SetHistory>>>(emptyMap()) }

    LaunchedEffect(Unit) {
        withContext(Dispatchers.IO) {
            workoutHistories = workouts.flatMap { workout ->
                workoutHistoryDao.getWorkoutsByWorkoutId(workout.id)
            }.filter { it.isDone }.sortedBy { it.date }

            if (workoutHistories.isEmpty()) {
                delay(500)
                isLoading = false
                return@withContext
            }

            volumes.clear()
            durations.clear()
            oneRepMaxes.clear()
            val equipment = exercise?.equipmentId?.let { appViewModel.getEquipmentById(it) }

            val mutableMap = setHistoriesByWorkoutHistoryId.toMutableMap()

            for (workoutHistory in workoutHistories) {
                val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryIdAndExerciseId(
                    workoutHistory.id,
                    exercise.id
                )

                if (setHistories.isEmpty()) {
                    continue
                }

                var volume = 0.0
                var duration = 0f
                var oneRepMax = 0.0


                mutableMap.put(workoutHistory.id, setHistories)

                for (setHistory in setHistories) {


                    if (setHistory.setData is WeightSetData) {
                        val setData = setHistory.setData as WeightSetData
                        volume += setData.calculateVolume()
                        val currentOneRepMax = getOneRepMax(setData.getWeight(), setData.actualReps)
                        if(currentOneRepMax> oneRepMax){
                            oneRepMax = currentOneRepMax
                        }
                    }

                    if (setHistory.setData is BodyWeightSetData) {

                        val setData = setHistory.setData as BodyWeightSetData
                        volume += setData.calculateVolume()

                        val currentOneRepMax = getOneRepMax(setData.getWeight(), setData.actualReps)
                        if(currentOneRepMax> oneRepMax){
                            oneRepMax = currentOneRepMax
                        }
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

                oneRepMaxes.add(Pair(workoutHistories.indexOf(workoutHistory), oneRepMax.round(2)))
            }

            setHistoriesByWorkoutHistoryId = mutableMap

            selectedWorkoutHistory = workoutHistories.first { it.id == setHistoriesByWorkoutHistoryId.keys.last() }

            if (volumes.any { it.second != 0.0 }) {
                if (volumes.count() == 1) {
                    volumeMarkerTarget = volumes.last()
                } else if (volumes.count() > 1) {
                    volumeMarkerTarget = volumes.maxBy { it.second }
                }

                volumeEntryModel =
                    CartesianChartModel(LineCartesianLayerModel.build {
                        series(volumes.map { it.first },volumes.map { it.second })
                    })
            }

            if (durations.any { it.second != 0f }) {
                if (durations.count() == 1) {
                    durationMarkerTarget = durations.last()
                } else if (durations.count() > 1) {
                    durationMarkerTarget = durations.maxBy { it.second }
                }

                durationEntryModel =
                    CartesianChartModel(LineCartesianLayerModel.build {
                        series(durations.map { it.first },durations.map { it.second })
                    })
            }

            if (oneRepMaxes.any { it.second != 0.0 }) {
                if (oneRepMaxes.count() == 1) {
                    oneRepMaxMarkerTarget = oneRepMaxes.last()
                } else if (oneRepMaxes.count() > 1) {
                    oneRepMaxMarkerTarget = oneRepMaxes.maxBy { it.second }
                }

                oneRepMaxEntryModel =
                    CartesianChartModel(LineCartesianLayerModel.build {
                        series(oneRepMaxes.map { it.first },oneRepMaxes.map { it.second })
                    })
            }


            delay(500)
            isLoading = false
        }
    }

    val workoutSelector = @Composable {
        val selectableWorkoutHistories = remember(setHistoriesByWorkoutHistoryId,workoutHistories) {
            workoutHistories.filter{setHistoriesByWorkoutHistoryId.containsKey(it.id)}
        }

        Row(
            verticalAlignment = Alignment.CenterVertically
        ) {
            IconButton(
                modifier = Modifier.size(25.dp),
                onClick = {
                    val index = selectableWorkoutHistories.indexOf(selectedWorkoutHistory)
                    if (index > 0) {
                        selectedWorkoutHistory = selectableWorkoutHistories[index - 1]
                    }
                },
                enabled = selectedWorkoutHistory != selectableWorkoutHistories.first()
            ) {
                val isEnabled = selectedWorkoutHistory != selectableWorkoutHistories.first()
                val color =  if (isEnabled) LightGray else MediumLightGray

                Icon(imageVector = Icons.Filled.ArrowBack, contentDescription = "Previous",tint = color)
            }
            Spacer(modifier = Modifier.width(10.dp))
            Text(
                modifier = Modifier
                    .weight(1f),
                text = selectedWorkoutHistory!!.date.format(dateFormatter) + " "+ selectedWorkoutHistory!!.time.format(timeFormatter),
                textAlign = TextAlign.Center,
                color = LightGray,
                style = MaterialTheme.typography.titleMedium,
            )
            Spacer(modifier = Modifier.width(10.dp))
            IconButton(
                modifier = Modifier.size(25.dp),
                onClick = {
                    val index = selectableWorkoutHistories.indexOf(selectedWorkoutHistory)
                    if (index < selectableWorkoutHistories.size - 1) { // Check to avoid IndexOutOfBoundsException
                        selectedWorkoutHistory = selectableWorkoutHistories[index + 1]
                    }
                },
                enabled = selectedWorkoutHistory != selectableWorkoutHistories.last()
            ) {
                val isEnabled = selectedWorkoutHistory != selectableWorkoutHistories.last()
                val color =  if (isEnabled) LightGray else MediumLightGray

                Icon(imageVector = Icons.Filled.ArrowForward, contentDescription = "Next",tint = color)
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
                        tint = if (selectedMode == 0) DarkGray else MediumLightGray
                    )
                    Spacer(modifier = Modifier.width(5.dp))
                    Text("Graphs", color =  if (selectedMode == 0) DarkGray else MediumLightGray, style = MaterialTheme.typography.titleMedium,)
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
                        tint = if (selectedMode == 1) DarkGray else MediumLightGray
                    )
                    Spacer(modifier = Modifier.width(5.dp))
                    Text("Sets", color =  if (selectedMode == 1) DarkGray else MediumLightGray, style = MaterialTheme.typography.titleMedium,)
                }
            }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(containerColor = DarkGray, titleContentColor = LightGray),
                title = {
                    Text(
                        modifier = Modifier
                            .fillMaxWidth()
                            .basicMarquee(iterations = Int.MAX_VALUE),
                        textAlign = TextAlign.Center,
                        text = exercise.name,
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
                    IconButton(modifier = Modifier.alpha(0f), onClick = {}) {
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
                .background(DarkGray)
                .padding(it),
            verticalArrangement = Arrangement.Top,
        ) {
            TabRow(
                contentColor = DarkGray,
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
                    modifier = Modifier.background(DarkGray),
                    selected = false,
                    onClick = {
                        appViewModel.setScreenData(
                            ScreenData.ExerciseDetail(
                                workout.id,
                                exercise.id
                            ), true
                        )
                    },
                    text = {
                        Text(
                            text = "Overview"
                        )
                    },
                    selectedContentColor = MaterialTheme.colorScheme.primary,
                    unselectedContentColor = MediumLightGray,
                )
                Tab(
                    modifier = Modifier.background(DarkGray),
                    selected = true,
                    onClick = { },
                    text = {
                        Text(
                            text = "History"
                        )
                    },
                    selectedContentColor = MaterialTheme.colorScheme.primary,
                    unselectedContentColor = MediumLightGray,
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
                        trackColor = Color.DarkGray,
                    )
                }
            } else {
                if (workoutHistories.isEmpty()) {
                    Box(
                        modifier = Modifier
                            .fillMaxSize(),
                        contentAlignment = Alignment.Center
                    ) {
                        StyledCard(
                            modifier = Modifier
                                .padding(15.dp),
                            ) {
                            Text(
                                modifier = Modifier
                                    .padding(15.dp),
                                text = "No history found",
                                textAlign = TextAlign.Center,
                                color = DarkGray,
                            )
                        }
                    }
                }else{
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
                                .padding(top = 5.dp)
                                .verticalColumnScrollbar(scrollState)
                                .verticalScroll(scrollState)
                                .padding(horizontal = 15.dp),
                            verticalArrangement = Arrangement.spacedBy(10.dp)
                        ) {
                            when (updatedSelectedMode) {
                                0 -> {
                                    if (volumeEntryModel != null) {
                                        StandardChart(
                                            cartesianChartModel = volumeEntryModel!!,
                                            title = "Volume",
                                            markerTextFormatter = { formatNumber(it) },
                                            startAxisValueFormatter = volumeAxisValueFormatter,
                                            bottomAxisValueFormatter = horizontalAxisValueFormatter,
                                        )
                                    }

                                    if (oneRepMaxEntryModel != null) {
                                        StandardChart(
                                            cartesianChartModel = oneRepMaxEntryModel!!,
                                            title = "One Rep Max",
                                            startAxisValueFormatter = CartesianValueFormatter { _, value, _ ->
                                                value.round(2).toString()
                                            },
                                            bottomAxisValueFormatter = horizontalAxisValueFormatter,
                                        )
                                    }

                                    if (durationEntryModel != null) {
                                        StandardChart(
                                            cartesianChartModel = durationEntryModel!!,
                                            title = "Total duration over time",
                                            markerTextFormatter = {  value -> formatTime(value.toInt()/1000) },
                                            startAxisValueFormatter = durationAxisValueFormatter,
                                            bottomAxisValueFormatter = horizontalAxisValueFormatter,
                                        )
                                    }
                                }
                                1 -> {
                                    workoutSelector()
                                    StyledCard {
                                        Column {
                                            Text(
                                                modifier = Modifier
                                                    .fillMaxWidth()
                                                    .padding(vertical = 10.dp),
                                                text = "Exercise History",
                                                style = MaterialTheme.typography.titleMedium,
                                                textAlign = TextAlign.Center,
                                                color = LightGray,
                                            )
                                            Column(
                                                modifier = Modifier.padding(10.dp),
                                                verticalArrangement = Arrangement.spacedBy(10.dp)
                                            ) {
                                                val setHistories =
                                                    setHistoriesByWorkoutHistoryId[selectedWorkoutHistory!!.id]!!

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

                                                StyledCard {
                                                    ExpandableContainer(
                                                        isOpen = true,
                                                        isExpandable = false,
                                                        modifier = Modifier
                                                            .fillMaxWidth(),
                                                        title = { m ->
                                                            Row(
                                                                horizontalArrangement = Arrangement.SpaceBetween,
                                                                modifier = m,
                                                                verticalAlignment = Alignment.CenterVertically
                                                            ) {
                                                                Text(
                                                                    modifier = Modifier
                                                                        .padding(10.dp)
                                                                        .basicMarquee(iterations = Int.MAX_VALUE),
                                                                    text = exercise.name,
                                                                    style = MaterialTheme.typography.bodyLarge,
                                                                    color = LightGray,
                                                                )
                                                            }
                                                        },
                                                        content = {
                                                            if (hasTarget) {
                                                                Column {
                                                                    Column(
                                                                        modifier = Modifier
                                                                            .fillMaxWidth()
                                                                            .padding(10.dp)
                                                                    ) {
                                                                        var progress =
                                                                            targetCounter.toFloat() / targetTotal
                                                                        if (progress.isNaN()) {
                                                                            progress = 0f
                                                                        }

                                                                        Text(
                                                                            text = "Target HR",
                                                                            color = LightGray,
                                                                            style = MaterialTheme.typography.bodyMedium,
                                                                        )
                                                                        Spacer(Modifier.height(5.dp))
                                                                        Row(modifier = Modifier.fillMaxWidth()) {
                                                                            val lowHr =
                                                                                getHeartRateFromPercentage(
                                                                                    exercise.lowerBoundMaxHRPercent!!,
                                                                                    userAge
                                                                                )
                                                                            val highHr =
                                                                                getHeartRateFromPercentage(
                                                                                    exercise.upperBoundMaxHRPercent!!,
                                                                                    userAge
                                                                                )
                                                                            Text(
                                                                                "$lowHr - $highHr bpm",
                                                                                Modifier.weight(1f),
                                                                                color = LightGray,
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
                                                                                color = LightGray,
                                                                            )
                                                                        }
                                                                        Spacer(Modifier.height(5.dp))
                                                                        SimpleProgressIndicator(
                                                                            progress = progress,
                                                                            trackColor = MediumLightGray,
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
                                                                    SetHistoriesRenderer(setHistories = setHistories, appViewModel = appViewModel, workout = workout)
                                                                }
                                                            } else {
                                                                SetHistoriesRenderer(setHistories = setHistories, appViewModel = appViewModel, workout = workout)
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
                    }

                    if (!(workoutHistories.isEmpty() || selectedWorkoutHistory == null)) {
                        customBottomBar()
                    }
                }
            }
        }
    }
}