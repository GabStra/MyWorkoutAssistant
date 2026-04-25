package com.gabstra.myworkoutassistant.screens

import android.annotation.SuppressLint
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.ScaffoldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.zIndex
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.composables.EquipmentAccessoryMetadata
import com.gabstra.myworkoutassistant.composables.HistoryGraphEmptyState
import com.gabstra.myworkoutassistant.composables.HistoryGraphTabColumn
import com.gabstra.myworkoutassistant.composables.HistorySetsTabColumn
import com.gabstra.myworkoutassistant.composables.rememberHistoryFilterRangeSelection
import com.gabstra.myworkoutassistant.composables.PrimarySurface
import com.gabstra.myworkoutassistant.composables.RangeDropdown
import com.gabstra.myworkoutassistant.composables.SetHistoriesRenderer
import com.gabstra.myworkoutassistant.composables.TargetHrProgressSection
import com.gabstra.myworkoutassistant.composables.StandardChart
import com.gabstra.myworkoutassistant.composables.SupersetSetHistoriesRenderer
import com.gabstra.myworkoutassistant.shared.FilterRange
import com.gabstra.myworkoutassistant.shared.filterBy
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
import com.patrykandpatrick.vico.compose.cartesian.data.CartesianChartModel
import com.patrykandpatrick.vico.compose.cartesian.data.CartesianValueFormatter
import com.patrykandpatrick.vico.compose.cartesian.data.LineCartesianLayerModel
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
    workoutHistoryId: UUID? = null,
    selectedHistoryMode: Int = 0,
    historyFilterRange: FilterRange? = null,
    onHistoryFilterRangeChange: ((FilterRange) -> Unit)? = null,
    onGoBack: () -> Unit,
    onSelectedWorkoutHistoryIdChanged: (UUID?) -> Unit = {},
) {
    var isLoading by remember { mutableStateOf(true) }
    var isChartInteractionActive by remember { mutableStateOf(false) }

    var volumeEntryModel by remember { mutableStateOf<CartesianChartModel?>(null) }
    var durationEntryModel by remember { mutableStateOf<CartesianChartModel?>(null) }
    var volumeMarkerTarget by remember { mutableStateOf<Pair<Int, Double>?>(null) }
    var durationMarkerTarget by remember { mutableStateOf<Pair<Int, Float>?>(null) }
    var oneRepMaxMarkerTarget by remember { mutableStateOf<Pair<Int, Double>?>(null) }
    var oneRepMaxEntryModel by remember { mutableStateOf<CartesianChartModel?>(null) }
    var workoutHistories by remember { mutableStateOf(listOf<WorkoutHistory>()) }
    var chartWorkoutHistories by remember { mutableStateOf(listOf<WorkoutHistory>()) }
    var hasLoadedWorkoutHistories by remember { mutableStateOf(false) }

    val (selectedRange, onHistoryRangeSelected) = rememberHistoryFilterRangeSelection(
        historyFilterRange = historyFilterRange,
        onHistoryFilterRangeChange = onHistoryFilterRangeChange,
    )
    val historiesToShow = remember(workoutHistories, selectedRange) {
        workoutHistories.filterBy(selectedRange)
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
    val updateMessage by appViewModel.updateNotificationFlow.collectAsState(initial = null)

    val volumes = remember { mutableListOf<Pair<Int, Double>>() }
    val durations = remember { mutableListOf<Pair<Int, Float>>() }
    val oneRepMaxes = remember { mutableListOf<Pair<Int, Double>>() }

    var selectedWorkoutHistory by remember { mutableStateOf<WorkoutHistory?>(null) }
    var setHistoriesByWorkoutHistoryId by remember { mutableStateOf<Map<UUID, ExerciseHistoryDisplayData>>(emptyMap()) }

    fun resolveSelectedWorkoutHistory(
        requestedWorkoutHistoryId: UUID?,
        availableWorkoutHistories: List<WorkoutHistory>,
    ): WorkoutHistory? {
        return requestedWorkoutHistoryId
            ?.let { id -> availableWorkoutHistories.find { it.id == id } }
            ?: availableWorkoutHistories.lastOrNull()
    }

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

        selectedWorkoutHistory = resolveSelectedWorkoutHistory(
            requestedWorkoutHistoryId = workoutHistoryId,
            availableWorkoutHistories = pointsWorkoutHistories,
        )

        if (volumes.any { it.second != 0.0 }) {
            volumeEntryModel =
                CartesianChartModel(LineCartesianLayerModel.build {
                    series(volumes.map { it.first },volumes.map { it.second })
                })
        }

        if (durations.any { it.second != 0f }) {
            durationEntryModel =
                CartesianChartModel(LineCartesianLayerModel.build {
                    series(durations.map { it.first },durations.map { it.second })
                })
        }

        if (oneRepMaxes.any { it.second != 0.0 }) {
            oneRepMaxEntryModel =
                CartesianChartModel(LineCartesianLayerModel.build {
                    series(oneRepMaxes.map { it.first },oneRepMaxes.map { it.second })
                })
        }
    }

    LaunchedEffect(
        updateMessage,
        workout.id,
        exercise.id,
        workouts.map { it.id }.toSet()
    ) {
        isLoading = true
        val loadedWorkoutHistories = withContext(Dispatchers.IO) {
            workouts.flatMap { workout ->
                workoutHistoryDao.getWorkoutsByWorkoutId(workout.id)
            }.sortedWith(
                compareBy<WorkoutHistory>(
                    { it.date },
                    { it.time },
                    { it.version.toLong() }
                )
            )
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
            ensureMinimumLoadingDuration(loadingStartedAt, minimumDurationMillis = 450L)
            isLoading = false
            return@LaunchedEffect
        }
        setCharts(historiesToShow)
        ensureMinimumLoadingDuration(loadingStartedAt, minimumDurationMillis = 450L)
        isLoading = false
    }

    LaunchedEffect(workoutHistoryId, chartWorkoutHistories) {
        val resolvedWorkoutHistory = resolveSelectedWorkoutHistory(
            requestedWorkoutHistoryId = workoutHistoryId,
            availableWorkoutHistories = chartWorkoutHistories,
        )
        if (selectedWorkoutHistory?.id != resolvedWorkoutHistory?.id) {
            selectedWorkoutHistory = resolvedWorkoutHistory
        }
    }

    LaunchedEffect(
        hasLoadedWorkoutHistories,
        isLoading,
        selectedWorkoutHistory?.id,
        chartWorkoutHistories,
        workoutHistoryId,
    ) {
        if (!hasLoadedWorkoutHistories || isLoading) {
            return@LaunchedEffect
        }

        val selectedWorkoutHistoryId = selectedWorkoutHistory?.id
        if (selectedWorkoutHistoryId == null && chartWorkoutHistories.isNotEmpty()) {
            return@LaunchedEffect
        }

        if (selectedWorkoutHistoryId != workoutHistoryId) {
            onSelectedWorkoutHistoryIdChanged(selectedWorkoutHistoryId)
        }
    }

    LaunchedEffect(
        selectedWorkoutHistory?.id,
        chartWorkoutHistories,
        volumeEntryModel,
        durationEntryModel,
        oneRepMaxEntryModel,
        hasLoadedWorkoutHistories,
    ) {
        if (!hasLoadedWorkoutHistories) return@LaunchedEffect
        val history = selectedWorkoutHistory ?: run {
            volumeMarkerTarget = null
            durationMarkerTarget = null
            oneRepMaxMarkerTarget = null
            return@LaunchedEffect
        }
        val idx = chartWorkoutHistories.indexOfFirst { it.id == history.id }
        if (idx < 0) {
            volumeMarkerTarget = null
            durationMarkerTarget = null
            oneRepMaxMarkerTarget = null
            return@LaunchedEffect
        }
        volumeMarkerTarget = volumes.find { it.first == idx }
        durationMarkerTarget = durations.find { it.first == idx }
        oneRepMaxMarkerTarget = oneRepMaxes.find { it.first == idx }
    }

    val workoutSelector = @Composable {
        val selectableWorkoutHistories = remember(setHistoriesByWorkoutHistoryId, historiesToShow) {
            historiesToShow.filter { setHistoriesByWorkoutHistoryId.containsKey(it.id) }
        }

        val canGoBack = selectableWorkoutHistories.size > 1 &&
            selectedWorkoutHistory != selectableWorkoutHistories.first()
        val canGoForward = selectableWorkoutHistories.size > 1 &&
            selectedWorkoutHistory != selectableWorkoutHistories.last()
        
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
                                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                                contentDescription = "Previous"
                            )
                        }
                    }
                }
                Spacer(modifier = Modifier.width(10.dp))
                Text(
                    modifier = Modifier
                        .weight(1f),
                    text = selectedWorkoutHistory!!.date.format(dateFormatter) + " " +
                        selectedWorkoutHistory!!.time.format(timeFormatter),
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
                                imageVector = Icons.AutoMirrored.Filled.ArrowForward,
                                contentDescription = "Next"
                            )
                        }
                    }
                }
            }
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background),
        verticalArrangement = Arrangement.Top,
    ) {
        val isSetHistorySelectionPending =
            selectedHistoryMode.coerceIn(0, 1) == 1 &&
                    setHistoriesByWorkoutHistoryId.isNotEmpty() &&
                    selectedWorkoutHistory == null

        Column(
            modifier = Modifier
                .zIndex(1f)
                .fillMaxWidth(),
        ) {
            Spacer(modifier = Modifier.height(10.dp))
            RangeDropdown(selectedRange, onHistoryRangeSelected)
            Spacer(modifier = Modifier.height(12.dp))

            if (hasLoadedWorkoutHistories &&
                selectedWorkoutHistory != null &&
                setHistoriesByWorkoutHistoryId.isNotEmpty()
            ) {
                Column(modifier = Modifier.padding(horizontal = Spacing.md)) {
                    workoutSelector()
                }
                Spacer(modifier = Modifier.height(12.dp))
            }
        }

        when {
            isLoading || isSetHistorySelectionPending -> {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f),
                    contentAlignment = Alignment.Center,
                ) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(32.dp),
                        color = MaterialTheme.colorScheme.primary,
                        trackColor = MediumDarkGray,
                    )
                }
            }
            historiesToShow.isEmpty() -> {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f),
                    contentAlignment = Alignment.Center,
                ) {
                    PrimarySurface(modifier = Modifier.padding(15.dp)) {
                        Text(
                            modifier = Modifier.padding(15.dp),
                            text = "No history found",
                            textAlign = TextAlign.Center,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                    }
                }
            }
            else -> {
                val scrollState = rememberScrollState()
                when (selectedHistoryMode.coerceIn(0, 1)) {
                    0 -> {
                        HistoryGraphTabColumn(
                            scrollState = scrollState,
                            isScrollEnabled = !isChartInteractionActive,
                        ) {
                            if (setHistoriesByWorkoutHistoryId.isEmpty()) {
                                HistoryGraphEmptyState(text = "No history in selected range.")
                            }
                            if (volumeEntryModel != null) {
                                StandardChart(
                                    cartesianChartModel = volumeEntryModel!!,
                                    title = "Volume (kg)",
                                    markerTextFormatter = { formatNumber(it) },
                                    startAxisValueFormatter = volumeAxisValueFormatter,
                                    bottomAxisValueFormatter = horizontalAxisValueFormatter,
                                    xAxisTickValues = volumes.map { it.first.toDouble() },
                                    markerPosition = volumeMarkerTarget?.first?.toDouble(),
                                    onInteractionChange = { isChartInteractionActive = it },
                                )
                            }

                            if (oneRepMaxEntryModel != null) {
                                StandardChart(
                                    cartesianChartModel = oneRepMaxEntryModel!!,
                                    title = "Estimated 1RM / session (kg)",
                                    startAxisValueFormatter = CartesianValueFormatter { _, value, _ ->
                                        value.round(2).toString()
                                    },
                                    bottomAxisValueFormatter = horizontalAxisValueFormatter,
                                    xAxisTickValues = oneRepMaxes.map { it.first.toDouble() },
                                    markerPosition = oneRepMaxMarkerTarget?.first?.toDouble(),
                                    onInteractionChange = { isChartInteractionActive = it },
                                )
                            }

                            if (durationEntryModel != null) {
                                StandardChart(
                                    cartesianChartModel = durationEntryModel!!,
                                    title = "Total duration",
                                    markerTextFormatter = { value ->
                                        formatTime(value.toInt() / 1000)
                                    },
                                    startAxisValueFormatter = durationAxisValueFormatter,
                                    bottomAxisValueFormatter = horizontalAxisValueFormatter,
                                    xAxisTickValues = durations.map { it.first.toDouble() },
                                    markerPosition = durationMarkerTarget?.first?.toDouble(),
                                    onInteractionChange = { isChartInteractionActive = it },
                                )
                            }
                        }
                    }
                    1 -> {
                        if (setHistoriesByWorkoutHistoryId.isEmpty() || selectedWorkoutHistory == null) {
                            HistoryGraphEmptyState(text = "No history in selected range.")
                            return@Column
                        }

                        val lazyListState = rememberLazyListState()
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

                        HistorySetsTabColumn(
                            state = lazyListState,
                        ) {
                            if (hasTarget) {
                                item {
                                    PrimarySurface {
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
                                        TargetHrProgressSection(
                                            targetCounter = targetCounter,
                                            targetTotal = targetTotal,
                                            lowHrBpm = lowHr,
                                            highHrBpm = highHr,
                                        )
                                    }
                                }
                            }
                            item {
                                PrimarySurface {
                                    Column(
                                        modifier = Modifier.padding(vertical = Spacing.md),
                                        verticalArrangement = Arrangement.spacedBy(8.dp)
                                    ) {
                                        val historicalEquipmentName = setHistories.selectedExerciseSetHistories
                                            .firstOrNull()
                                            ?.equipmentNameSnapshot
                                        val historicalEquipmentId = setHistories.selectedExerciseSetHistories
                                            .firstOrNull()
                                            ?.equipmentIdSnapshot
                                        val equipmentName = when {
                                            !historicalEquipmentName.isNullOrBlank() -> historicalEquipmentName
                                            historicalEquipmentId != null -> appViewModel.getEquipmentById(historicalEquipmentId)?.name
                                            else -> exercise.equipmentId?.let { appViewModel.getEquipmentById(it)?.name }
                                        }
                                        val accessoryNames = (exercise.requiredAccessoryEquipmentIds ?: emptyList())
                                            .mapNotNull { id -> appViewModel.getAccessoryEquipmentById(id)?.name }
                                        EquipmentAccessoryMetadata(
                                            equipmentName = equipmentName,
                                            accessoryNames = accessoryNames,
                                        )
                                        if (setHistories.isSupersetSession) {
                                            SupersetSetHistoriesRenderer(
                                                setHistories = setHistories.renderSetHistories,
                                                workout = workout,
                                                getEquipmentById = { appViewModel.getEquipmentById(it) }
                                            )
                                        } else {
                                            SetHistoriesRenderer(
                                                setHistories = setHistories.renderSetHistories,
                                                appViewModel = appViewModel,
                                                workout = workout,
                                                showMetadata = false,
                                            )
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
