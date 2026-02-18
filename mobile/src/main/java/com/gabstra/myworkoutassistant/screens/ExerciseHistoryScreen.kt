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
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.automirrored.filled.ShowChart
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowForward
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
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
import com.gabstra.myworkoutassistant.composables.FilterRange
import com.gabstra.myworkoutassistant.composables.PrimarySurface
import com.gabstra.myworkoutassistant.composables.RangeDropdown
import com.gabstra.myworkoutassistant.composables.SetHistoriesRenderer
import com.gabstra.myworkoutassistant.composables.StandardChart
import com.gabstra.myworkoutassistant.composables.SupersetSetHistoriesRenderer
import com.gabstra.myworkoutassistant.filterBy
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.round
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.OneRM.calculateOneRepMax
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
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
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

private data class ExerciseHistoryDisplayData(
    val selectedExerciseSetHistories: List<SetHistory>,
    val renderSetHistories: List<SetHistory>,
    val isSupersetSession: Boolean
)

@SuppressLint("UnusedMaterial3ScaffoldPaddingParameter")
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun ExerciseHistoryScreen(
    appViewModel: AppViewModel,
    workout: Workout,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    exercise: Exercise,
    initialSelectedTabIndex: Int = 0,
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
    var chartWorkoutHistories by remember { mutableStateOf(listOf<WorkoutHistory>()) }
    var hasLoadedWorkoutHistories by remember { mutableStateOf(false) }

    var selectedRange by remember { mutableStateOf(FilterRange.ALL) }
    val historiesToShow = remember(workoutHistories, selectedRange) {
        workoutHistories.filterBy(selectedRange)
    }

    var selectedMode by remember(initialSelectedTabIndex) {
        mutableIntStateOf(initialSelectedTabIndex.coerceIn(0, 1))
    }

    val userAge by appViewModel.userAge
    val measuredMaxHeartRate = appViewModel.workoutStore.measuredMaxHeartRate
    val restingHeartRate = appViewModel.workoutStore.restingHeartRate

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

    val horizontalAxisValueFormatter = remember(chartWorkoutHistories) {
        CartesianValueFormatter { _, value, _->
            if(value.toInt() < 0 || value.toInt() >= chartWorkoutHistories.size) return@CartesianValueFormatter "-"
            val currentWorkoutHistory = chartWorkoutHistories[value.toInt()]
            currentWorkoutHistory.date.format(dateFormatter)
        }
    }

    val workouts by appViewModel.workoutsFlow.collectAsState()

    val volumes = remember { mutableListOf<Pair<Int, Double>>() }
    val durations = remember { mutableListOf<Pair<Int, Float>>() }
    val oneRepMaxes = remember { mutableListOf<Pair<Int, Double>>() }

    var selectedWorkoutHistory by remember { mutableStateOf<WorkoutHistory?>(null) }
    var setHistoriesByWorkoutHistoryId by remember { mutableStateOf<Map<UUID, ExerciseHistoryDisplayData>>(emptyMap()) }

    suspend fun ensureMinimumLoadingDuration(
        startedAtMillis: Long,
        minimumDurationMillis: Long = 1_000L,
    ) {
        val elapsed = System.currentTimeMillis() - startedAtMillis
        val remaining = minimumDurationMillis - elapsed
        if (remaining > 0) {
            delay(remaining)
        }
    }

    suspend fun setCharts(workoutHistories: List<WorkoutHistory>){
        volumes.clear()
        durations.clear()
        oneRepMaxes.clear()

        volumeEntryModel = null
        durationEntryModel = null
        oneRepMaxEntryModel = null
        volumeMarkerTarget = null
        durationMarkerTarget = null
        oneRepMaxMarkerTarget = null
        selectedWorkoutHistory = null
        setHistoriesByWorkoutHistoryId = emptyMap()
        chartWorkoutHistories = emptyList()

        if(workoutHistories.isEmpty()) return

        val mutableMap = mutableMapOf<UUID, ExerciseHistoryDisplayData>()
        val pointsWorkoutHistories = mutableListOf<WorkoutHistory>()
        val supersetByExerciseId = workout.workoutComponents
            .filterIsInstance<Superset>()
            .flatMap { superset -> superset.exercises.map { it.id to superset.id } }
            .toMap()

        for (workoutHistory in workoutHistories) {
            val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryIdAndExerciseIdOrdered(
                workoutHistory.id,
                exercise.id
            )

            if (setHistories.isEmpty()) {
                continue
            }

            var volume = 0.0
            var duration = 0f

            val oneRepMax = setHistories.maxOf {
                when (it.setData) {
                    is BodyWeightSetData -> {
                        val setData = it.setData as BodyWeightSetData
                        calculateOneRepMax(setData.getWeight(), setData.actualReps)
                    }

                    is WeightSetData ->{
                        val setData = it.setData as WeightSetData
                        calculateOneRepMax(setData.getWeight(), setData.actualReps)
                    }
                    else -> 0.0
                }
            }

            val selectedSupersetId = setHistories.firstNotNullOfOrNull { it.supersetId }
                ?: supersetByExerciseId[exercise.id]
            val supersetSetHistories = if (selectedSupersetId != null) {
                setHistoryDao.getSetHistoriesByWorkoutHistoryIdAndSupersetIdOrdered(
                    workoutHistory.id,
                    selectedSupersetId
                )
            } else {
                emptyList()
            }
            mutableMap[workoutHistory.id] = ExerciseHistoryDisplayData(
                selectedExerciseSetHistories = setHistories,
                renderSetHistories = if (supersetSetHistories.isNotEmpty()) supersetSetHistories else setHistories,
                isSupersetSession = supersetSetHistories.isNotEmpty()
            )
            pointsWorkoutHistories.add(workoutHistory)
            val pointIndex = pointsWorkoutHistories.lastIndex

            for (setHistory in setHistories) {
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

            volumes.add(Pair(pointIndex, volume))
            durations.add(Pair(pointIndex, duration))

            oneRepMaxes.add(Pair(pointIndex, oneRepMax.round(2)))
        }

        setHistoriesByWorkoutHistoryId = mutableMap
        chartWorkoutHistories = pointsWorkoutHistories

        if(setHistoriesByWorkoutHistoryId.isEmpty()) return

        selectedWorkoutHistory = chartWorkoutHistories.lastOrNull()

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
            } /*else if (durations.count() > 1) {
                durationMarkerTarget = durations.maxBy { it.second }
            }*/

            durationEntryModel =
                CartesianChartModel(LineCartesianLayerModel.build {
                    series(durations.map { it.first },durations.map { it.second })
                })
        }

        if (oneRepMaxes.any { it.second != 0.0 }) {
            if (oneRepMaxes.count() == 1) {
                oneRepMaxMarkerTarget = oneRepMaxes.last()
            } /*else if (oneRepMaxes.count() > 1) {
                oneRepMaxMarkerTarget = oneRepMaxes.maxBy { it.second }
            }*/

            oneRepMaxEntryModel =
                CartesianChartModel(LineCartesianLayerModel.build {
                    series(oneRepMaxes.map { it.first },oneRepMaxes.map { it.second })
                })
        }
    }

    LaunchedEffect(Unit) {
        isLoading = true
        val loadedWorkoutHistories = withContext(Dispatchers.IO) {
            workouts.flatMap { workout ->
                workoutHistoryDao.getWorkoutsByWorkoutId(workout.id)
            }.filter { it.isDone }.sortedBy { it.date }
        }
        workoutHistories = loadedWorkoutHistories
        hasLoadedWorkoutHistories = true
    }

    LaunchedEffect(historiesToShow, hasLoadedWorkoutHistories) {
        if (!hasLoadedWorkoutHistories) {
            return@LaunchedEffect
        }
        val loadingStartedAt = System.currentTimeMillis()
        isLoading = true
        if (historiesToShow.isEmpty()) {
            volumeEntryModel = null
            durationEntryModel = null
            oneRepMaxEntryModel = null
            volumeMarkerTarget = null
            durationMarkerTarget = null
            oneRepMaxMarkerTarget = null
            selectedWorkoutHistory = null
            setHistoriesByWorkoutHistoryId = emptyMap()
            chartWorkoutHistories = emptyList()
            ensureMinimumLoadingDuration(loadingStartedAt)
            isLoading = false
            return@LaunchedEffect
        }
        setCharts(historiesToShow)
        ensureMinimumLoadingDuration(loadingStartedAt)
        isLoading = false
    }

    val workoutSelector = @Composable {
        val selectableWorkoutHistories = remember(setHistoriesByWorkoutHistoryId,historiesToShow) {
            historiesToShow.filter{setHistoriesByWorkoutHistoryId.containsKey(it.id)}
        }

        val canGoBack = selectedWorkoutHistory != selectableWorkoutHistories.first()
        val canGoForward = selectedWorkoutHistory != selectableWorkoutHistories.last()
        
        val navIconColors = IconButtonDefaults.iconButtonColors(
            contentColor = MaterialTheme.colorScheme.onBackground,
            disabledContentColor = DisabledContentGray
        )
        
        PrimarySurface(
            modifier = Modifier.fillMaxWidth()
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 10.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Box(
                    modifier = Modifier.size(25.dp),
                    contentAlignment = Alignment.Center
                ) {
                    if (canGoBack) {
                        IconButton(
                            modifier = Modifier.size(25.dp),
                            onClick = {
                                val index = selectableWorkoutHistories.indexOf(selectedWorkoutHistory)
                                if (index > 0) {
                                    selectedWorkoutHistory = selectableWorkoutHistories[index - 1]
                                }
                            },
                            colors = navIconColors
                        ) {
                            Icon(
                                imageVector = Icons.Filled.ArrowBack,
                                contentDescription = "Previous"
                            )
                        }
                    }
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
                Box(
                    modifier = Modifier.size(25.dp),
                    contentAlignment = Alignment.Center
                ) {
                    if (canGoForward) {
                        IconButton(
                            modifier = Modifier.size(25.dp),
                            onClick = {
                                val index = selectableWorkoutHistories.indexOf(selectedWorkoutHistory)
                                if (index < selectableWorkoutHistories.size - 1) { // Check to avoid IndexOutOfBoundsException
                                    selectedWorkoutHistory = selectableWorkoutHistories[index + 1]
                                }
                            },
                            colors = navIconColors
                        ) {
                            Icon(
                                imageVector = Icons.Filled.ArrowForward,
                                contentDescription = "Next"
                            )
                        }
                    }
                }
            }
        }
    }

    val customBottomBar = @Composable {
        Column {
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(20.dp), // Fill the width of the container
                horizontalArrangement = Arrangement.SpaceAround, // Space items evenly, including space at the edges
                verticalAlignment = Alignment.CenterVertically // Center items vertically within the Row
            ) {
            Box(
                modifier = Modifier
                    .clip(MaterialTheme.shapes.medium)
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
                    .clip(MaterialTheme.shapes.medium)
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
                },
                actions = {
                    // Invisible icon to balance the title correctly
                    IconButton(modifier = Modifier.alpha(0f), onClick = { /* No-op */ }) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = null
                        )
                    }
                }
            )
        },
    ) { paddingValues ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .background(MaterialTheme.colorScheme.background)
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
                    unselectedContentColor = MaterialTheme.colorScheme.onBackground,
                )
                Tab(
                    modifier = Modifier.background(MaterialTheme.colorScheme.background),
                    selected = true,
                    onClick = { },
                    text = {
                        Text(
                            text = "History"
                        )
                    },
                    selectedContentColor = MaterialTheme.colorScheme.primary,
                    unselectedContentColor = MaterialTheme.colorScheme.onBackground,
                )
            }

            if(isLoading){
                if (selectedMode == 0) {
                    Column(
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(top = 10.dp)
                            .padding(bottom = 10.dp)
                            .padding(horizontal = 15.dp),
                        verticalArrangement = Arrangement.Top
                    ) {
                        RangeDropdown(selectedRange) { selectedRange = it }
                        Box(
                            modifier = Modifier
                                .fillMaxSize(),
                            contentAlignment = Alignment.Center
                        ) {
                            CircularProgressIndicator(
                                modifier = Modifier.width(32.dp),
                                color = MaterialTheme.colorScheme.primary,
                                trackColor = MediumDarkGray,
                            )
                        }
                    }
                } else {
                    Box(
                        modifier = Modifier
                            .fillMaxSize(),
                        contentAlignment = Alignment.Center
                    ){
                        CircularProgressIndicator(
                            modifier = Modifier.width(32.dp),
                            color = MaterialTheme.colorScheme.primary,
                            trackColor = MediumDarkGray,
                        )
                    }
                }
            } else {
                if (historiesToShow.isEmpty()) {
                    Box(
                        modifier = Modifier
                            .fillMaxSize(),
                        contentAlignment = Alignment.Center
                    ) {
                        PrimarySurface(
                            modifier = Modifier
                                .padding(15.dp),
                            ) {
                            Text(
                                modifier = Modifier
                                    .padding(15.dp),
                                text = "No history found",
                                textAlign = TextAlign.Center,
                                color = MaterialTheme.colorScheme.onSurface,
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
                                .padding(top = 10.dp)
                                .padding(bottom = 10.dp)
                                .verticalColumnScrollbar(scrollState)
                                .verticalScroll(scrollState)
                                .padding(horizontal = 15.dp),
                            verticalArrangement = Arrangement.spacedBy(10.dp)
                        ) {
                            when (updatedSelectedMode) {
                                0 -> {
                                    val selectedHistoryMarkerPosition = selectedWorkoutHistory
                                        ?.let { workoutHistory ->
                                            chartWorkoutHistories.indexOfFirst { it.id == workoutHistory.id }
                                        }
                                        ?.takeIf { it >= 0 }
                                        ?.toDouble()

                                    RangeDropdown(selectedRange) { selectedRange = it }

                                    if (setHistoriesByWorkoutHistoryId.isEmpty()) {
                                        PrimarySurface(
                                            modifier = Modifier.fillMaxWidth()
                                        ) {
                                            Text(
                                                modifier = Modifier
                                                    .fillMaxWidth()
                                                    .padding(15.dp),
                                                text = "No history found for this range",
                                                textAlign = TextAlign.Center,
                                                color = MaterialTheme.colorScheme.onSurface.copy(alpha = .87f),
                                            )
                                        }
                                    }
                                    if (volumeEntryModel != null) {
                                        StandardChart(
                                            cartesianChartModel = volumeEntryModel!!,
                                            title = "Volume (KG)",
                                            markerTextFormatter = { formatNumber(it) },
                                            startAxisValueFormatter = volumeAxisValueFormatter,
                                            bottomAxisValueFormatter = horizontalAxisValueFormatter,
                                            xAxisTickValues = volumes.map { it.first.toDouble() },
                                            markerPosition = selectedHistoryMarkerPosition
                                                ?: volumeMarkerTarget?.first?.toDouble()
                                        )
                                    }

                                    if (oneRepMaxEntryModel != null) {
                                        StandardChart(
                                            cartesianChartModel = oneRepMaxEntryModel!!,
                                            title = "Estimated 1RM/Session (KG)",
                                            startAxisValueFormatter = CartesianValueFormatter { _, value, _ ->
                                                value.round(2).toString()
                                            },
                                            bottomAxisValueFormatter = horizontalAxisValueFormatter,
                                            xAxisTickValues = oneRepMaxes.map { it.first.toDouble() },
                                            markerPosition = selectedHistoryMarkerPosition
                                                ?: oneRepMaxMarkerTarget?.first?.toDouble()
                                        )
                                    }

                                    if (durationEntryModel != null) {
                                        StandardChart(
                                            cartesianChartModel = durationEntryModel!!,
                                            title = "Total duration",
                                            markerTextFormatter = {  value -> formatTime(value.toInt()/1000) },
                                            startAxisValueFormatter = durationAxisValueFormatter,
                                            bottomAxisValueFormatter = horizontalAxisValueFormatter,
                                            xAxisTickValues = durations.map { it.first.toDouble() },
                                            markerPosition = selectedHistoryMarkerPosition
                                                ?: durationMarkerTarget?.first?.toDouble()
                                        )
                                    }
                                }
                                1 -> {
                                    if (setHistoriesByWorkoutHistoryId.isEmpty() || selectedWorkoutHistory == null) {
                                        PrimarySurface(
                                            modifier = Modifier.fillMaxWidth()
                                        ) {
                                            Text(
                                                modifier = Modifier
                                                    .fillMaxWidth()
                                                    .padding(15.dp),
                                                text = "No history found for this range",
                                                textAlign = TextAlign.Center,
                                                color = MaterialTheme.colorScheme.onSurface.copy(alpha = .87f),
                                            )
                                        }
                                        return@AnimatedContent
                                    }
                                    workoutSelector()
                                    val setHistories =
                                        setHistoriesByWorkoutHistoryId[selectedWorkoutHistory!!.id]!!

                                    val hasTarget =
                                        exercise.lowerBoundMaxHRPercent != null && exercise.upperBoundMaxHRPercent != null

                                    val (targetCounter, targetTotal) = remember(
                                        hasTarget,
                                        setHistories.selectedExerciseSetHistories,
                                        selectedWorkoutHistory?.id,
                                        selectedWorkoutHistory?.heartBeatRecords,
                                        exercise.lowerBoundMaxHRPercent,
                                        exercise.upperBoundMaxHRPercent,
                                        userAge,
                                        measuredMaxHeartRate,
                                        restingHeartRate
                                    ) {
                                        if (!hasTarget) {
                                            0 to 0
                                        } else {
                                            var counter = 0
                                            var total = 0
                                            setHistories.selectedExerciseSetHistories
                                                .filter { it.setData !is RestSetData && it.startTime != null && it.endTime != null }
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
                                                        userAge,
                                                        measuredMaxHeartRate,
                                                        restingHeartRate
                                                    )
                                                    val highHr = getHeartRateFromPercentage(
                                                        exercise.upperBoundMaxHRPercent!!,
                                                        userAge,
                                                        measuredMaxHeartRate,
                                                        restingHeartRate
                                                    )

                                                    val hrEntriesCount =
                                                        selectedWorkoutHistory!!.heartBeatRecords.filterIndexed { index, value ->
                                                            index >= hrTimeOffset && index <= hrTimeOffset + setDuration && value >= lowHr && value <= highHr
                                                        }.size

                                                    counter += hrEntriesCount
                                                    total += setDuration.toInt()
                                                }
                                            counter to total
                                        }
                                    }

                                    PrimarySurface {
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
                                                        color = MaterialTheme.colorScheme.onBackground,
                                                        style = MaterialTheme.typography.bodyMedium,
                                                    )
                                                    Spacer(Modifier.height(5.dp))
                                                    Row(modifier = Modifier.fillMaxWidth()) {
                                                        val lowHr =
                                                            getHeartRateFromPercentage(
                                                                exercise.lowerBoundMaxHRPercent!!,
                                                                userAge,
                                                                measuredMaxHeartRate,
                                                                restingHeartRate
                                                            )
                                                        val highHr =
                                                            getHeartRateFromPercentage(
                                                                exercise.upperBoundMaxHRPercent!!,
                                                                userAge,
                                                                measuredMaxHeartRate,
                                                                restingHeartRate
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
                                                        trackColor = MediumDarkGray,
                                                        modifier = Modifier
                                                            .fillMaxWidth()
                                                            .height(16.dp)
                                                            .clip(MaterialTheme.shapes.large),
                                                        progressBarColor = Color.hsl(
                                                            113f,
                                                            0.79f,
                                                            0.34f
                                                        ),
                                                    )
                                                }
                                                if (setHistories.isSupersetSession) {
                                                    SupersetSetHistoriesRenderer(
                                                        modifier = Modifier.padding(horizontal = 5.dp, vertical = 5.dp),
                                                        setHistories = setHistories.renderSetHistories,
                                                        workout = workout
                                                    )
                                                } else {
                                                    SetHistoriesRenderer(
                                                        modifier = Modifier.padding(horizontal = 5.dp, vertical = 5.dp),
                                                        setHistories = setHistories.renderSetHistories,
                                                        appViewModel = appViewModel,
                                                        workout = workout
                                                    )
                                                }
                                            }
                                        } else {
                                            if (setHistories.isSupersetSession) {
                                                SupersetSetHistoriesRenderer(
                                                    modifier = Modifier.padding(horizontal = 5.dp, vertical = 5.dp),
                                                    setHistories = setHistories.renderSetHistories,
                                                    workout = workout
                                                )
                                            } else {
                                                SetHistoriesRenderer(
                                                    modifier = Modifier.padding(horizontal = 5.dp, vertical = 5.dp),
                                                    setHistories = setHistories.renderSetHistories,
                                                    appViewModel = appViewModel,
                                                    workout = workout
                                                )
                                            }
                                        }
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
    }
}
