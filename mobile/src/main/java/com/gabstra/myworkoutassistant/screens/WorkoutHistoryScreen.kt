package com.gabstra.myworkoutassistant.screens

import android.annotation.SuppressLint
import android.util.Log
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableDoubleStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.zIndex
import androidx.health.connect.client.HealthConnectClient
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.calculateKiloCaloriesBurned
import com.gabstra.myworkoutassistant.composables.AppDropdownMenu
import com.gabstra.myworkoutassistant.composables.AppDropdownMenuItem
import com.gabstra.myworkoutassistant.composables.ContentTitle
import com.gabstra.myworkoutassistant.composables.ExerciseHistoryRenderer
import com.gabstra.myworkoutassistant.composables.ExpandableContainer
import com.gabstra.myworkoutassistant.composables.HeartRateChartContent
import com.gabstra.myworkoutassistant.composables.HistoryGraphEmptyState
import com.gabstra.myworkoutassistant.composables.HistoryGraphTabColumn
import com.gabstra.myworkoutassistant.composables.HistorySetsTabColumn
import com.gabstra.myworkoutassistant.composables.PrimarySurface
import com.gabstra.myworkoutassistant.composables.RangeDropdown
import com.gabstra.myworkoutassistant.composables.ScrollableTextColumn
import com.gabstra.myworkoutassistant.composables.StandardChart
import com.gabstra.myworkoutassistant.composables.SupersetRenderer
import com.gabstra.myworkoutassistant.composables.SupersetSetHistoriesRenderer
import com.gabstra.myworkoutassistant.composables.TargetHrProgressSection
import com.gabstra.myworkoutassistant.composables.formatRestHistoryDisplayLine
import com.gabstra.myworkoutassistant.composables.historyExerciseNameTextStyle
import com.gabstra.myworkoutassistant.composables.rememberHistoryFilterRangeSelection
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.formatTimeHourMinutes
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.shared.FilterRange
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.RestHistoryDao
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import com.gabstra.myworkoutassistant.shared.WorkoutRecordDao
import com.gabstra.myworkoutassistant.shared.colorsByZone
import com.gabstra.myworkoutassistant.shared.filterBy
import com.gabstra.myworkoutassistant.shared.formatNumber
import com.gabstra.myworkoutassistant.shared.getHeartRateFromPercentage
import com.gabstra.myworkoutassistant.shared.getMaxHeartRate
import com.gabstra.myworkoutassistant.shared.getNewSetFromRestHistory
import com.gabstra.myworkoutassistant.shared.getNewSetFromSetHistory
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.utils.averageValidHeartRateOrNull
import com.gabstra.myworkoutassistant.shared.workout.history.SessionTimelineItem
import com.gabstra.myworkoutassistant.shared.workout.history.WorkoutHistoryLayoutItem
import com.gabstra.myworkoutassistant.shared.workout.history.buildWorkoutHistoryLayout
import com.gabstra.myworkoutassistant.shared.workout.history.mergeSessionTimeline
import com.gabstra.myworkoutassistant.shared.workout.model.WorkoutSessionStatus
import com.gabstra.myworkoutassistant.shared.workout.model.resolveWorkoutSessionStatus
import com.gabstra.myworkoutassistant.shared.workout.model.workoutSessionDisplayLabel
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.zoneRanges
import com.kevinnzou.compose.progressindicator.SimpleProgressIndicator
import com.patrykandpatrick.vico.compose.cartesian.data.CartesianChartModel
import com.patrykandpatrick.vico.compose.cartesian.data.CartesianValueFormatter
import com.patrykandpatrick.vico.compose.cartesian.data.LineCartesianLayerModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import java.time.Duration
import java.time.format.DateTimeFormatter
import java.util.Calendar
import java.util.Locale
import java.util.UUID
import kotlin.math.abs
import kotlin.math.roundToLong

private const val WORKOUT_HISTORY_SCREEN_LOG_TAG = "WorkoutHistoryScreen"

private data class HeartRateZoneSegment(
    val zoneIndex: Int,
    val xValues: List<Double>,
    val yValues: List<Double>,
)

private data class TargetHeartRateProgress(
    val counter: Int,
    val total: Int,
)

private fun roundXToSupportedPrecision(value: Double): Double {
    return (value * 10_000.0).roundToLong() / 10_000.0
}

private fun WorkoutHistoryLayoutItem.setsTabHistoryItemKey(): Any = when (this) {
    is WorkoutHistoryLayoutItem.ExerciseSection -> "exercise:$exerciseId"
    is WorkoutHistoryLayoutItem.SupersetSection -> "superset:$supersetId"
    is WorkoutHistoryLayoutItem.RestSection -> "rest:$restComponentId:${history.id}"
}

@Composable
private fun RestBetweenWorkoutComponentsBlock(
    history: RestHistory
) {
    PrimarySurface {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(10.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text(
                text = formatRestHistoryDisplayLine(history),
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurface
            )
        }
    }
}

private fun getHeartRateZoneGuideValues(
    userAge: Int,
    measuredMaxHeartRate: Int?,
    restingHeartRate: Int?,
): List<Double> {
    val zoneBounds = getHeartRateZoneBounds(
        userAge = userAge,
        measuredMaxHeartRate = measuredMaxHeartRate,
        restingHeartRate = restingHeartRate,
    )
    return (zoneBounds.drop(1).map { it.first.toDouble() } + getMaxHeartRate(userAge).toDouble())
        .distinct().sorted()
}

private fun getHeartRateZoneBounds(
    userAge: Int,
    measuredMaxHeartRate: Int?,
    restingHeartRate: Int?,
): List<IntRange> {
    val zoneStarts = zoneRanges.map { (lowerBoundPercent, _) ->
        getHeartRateFromPercentage(
            lowerBoundPercent,
            userAge,
            measuredMaxHeartRate,
            restingHeartRate,
        )
    }
    val absoluteMax = getHeartRateFromPercentage(
        zoneRanges.last().second,
        userAge,
        measuredMaxHeartRate,
        restingHeartRate,
    )

    return zoneStarts.indices.map { zoneIndex ->
        val lowerBound = zoneStarts[zoneIndex]
        val upperBound = if (zoneIndex < zoneStarts.lastIndex) {
            zoneStarts[zoneIndex + 1] - 1
        } else {
            absoluteMax
        }
        lowerBound..maxOf(lowerBound, upperBound)
    }
}

private fun getZoneFromHeartRate(
    heartRate: Double,
    userAge: Int,
    measuredMaxHeartRate: Int?,
    restingHeartRate: Int?,
): Int {
    val zoneBounds = getHeartRateZoneBounds(userAge, measuredMaxHeartRate, restingHeartRate)
    for (zoneIndex in zoneBounds.indices.reversed()) {
        val zoneRange = zoneBounds[zoneIndex]
        if (heartRate in zoneRange.first.toDouble()..zoneRange.last.toDouble()) {
            return zoneIndex
        }
    }

    return when {
        heartRate < zoneBounds.first().first.toDouble() -> 0
        heartRate > zoneBounds.last().last.toDouble() -> zoneBounds.lastIndex
        else -> 0
    }
}

private fun buildHeartRateZoneSegments(
    values: List<Double>,
    thresholds: List<Double>,
    zoneFromValue: (Double) -> Int,
): List<HeartRateZoneSegment> {
    if (values.size < 2) return emptyList()

    val segments = mutableListOf<HeartRateZoneSegment>()
    var currentX = mutableListOf(0.0)
    var currentY = mutableListOf(values.first())
    var currentZone = zoneFromValue(values.first())

    fun closeCurrentSegment() {
        if (currentX.size >= 2 && currentY.size >= 2) {
            segments += HeartRateZoneSegment(
                zoneIndex = currentZone,
                xValues = currentX.toList(),
                yValues = currentY.toList(),
            )
        }
    }

    for (index in 0 until values.lastIndex) {
        val x1 = index.toDouble()
        val x2 = (index + 1).toDouble()
        val y1 = values[index]
        val y2 = values[index + 1]

        if (abs(y2 - y1) < 1e-9) {
            currentX.add(x2)
            currentY.add(y2)
            continue
        }

        val minY = minOf(y1, y2)
        val maxY = maxOf(y1, y2)
        val isAscending = y2 > y1
        val crossings = thresholds
            .filter { it > minY && it < maxY }
            .sortedBy { if (isAscending) it else -it }

        if (crossings.isEmpty()) {
            currentX.add(x2)
            currentY.add(y2)
            continue
        }

        for (threshold in crossings) {
            val t = (threshold - y1) / (y2 - y1)
            val crossingX = roundXToSupportedPrecision(x1 + (x2 - x1) * t)

            currentX.add(crossingX)
            currentY.add(threshold)
            closeCurrentSegment()

            val epsilon = if (isAscending) 1e-4 else -1e-4
            currentZone = zoneFromValue(threshold + epsilon)
            currentX = mutableListOf(crossingX)
            currentY = mutableListOf(threshold)
        }

        currentX.add(x2)
        currentY.add(y2)
    }

    closeCurrentSegment()
    return segments
}

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
                text = { Text("Delete selected history") },
                onClick = {
                    onDeleteHistory()
                    expanded = false
                }
            )
        }
    }
}

@SuppressLint("UnusedMaterial3ScaffoldPaddingParameter")
@OptIn(
    ExperimentalMaterial3Api::class,
    ExperimentalFoundationApi::class
)
@Composable
fun WorkoutHistoryScreen(
    appViewModel: AppViewModel,
    healthConnectClient: HealthConnectClient,
    workoutHistoryDao: WorkoutHistoryDao,
    workoutRecordDao: WorkoutRecordDao,
    workoutHistoryId: UUID? = null,
    setHistoryDao: SetHistoryDao,
    restHistoryDao: RestHistoryDao,
    workout: Workout,
    selectedHistoryMode: Int = 0,
    historyFilterRange: FilterRange? = null,
    onHistoryFilterRangeChange: ((FilterRange) -> Unit)? = null,
    onGoBack: () -> Unit,
    onSelectedWorkoutHistoryIdChanged: (UUID?) -> Unit = {},
) {

    val context = LocalContext.current
    var isChartInteractionActive by remember { mutableStateOf(false) }

    val currentLocale = Locale.getDefault()
    val scope = rememberCoroutineScope()
    val userAge by appViewModel.userAge
    val measuredMaxHeartRate = appViewModel.workoutStore.measuredMaxHeartRate
    val restingHeartRate = appViewModel.workoutStore.restingHeartRate

    val dateFormatter = remember(currentLocale) {
        DateTimeFormatter.ofPattern("dd/MM/yy", currentLocale)
    }

    val timeFormatter = remember(currentLocale) {
        DateTimeFormatter.ofPattern("HH:mm", currentLocale)
    }

    val (selectedRange, onHistoryRangeSelected) = rememberHistoryFilterRangeSelection(
        historyFilterRange = historyFilterRange,
        onHistoryFilterRangeChange = onHistoryFilterRangeChange,
    )

    var workoutHistories by remember { mutableStateOf(listOf<WorkoutHistory>()) }
    var workoutSessionStatuses by remember { mutableStateOf<Map<UUID, WorkoutSessionStatus>>(emptyMap()) }
    var workoutRecordsByHistoryId by remember { mutableStateOf<Map<UUID, WorkoutRecord>>(emptyMap()) }
    var hasLoadedWorkoutHistories by remember { mutableStateOf(false) }

    val historiesToShow = remember(workoutHistories, selectedRange) {
        workoutHistories.filterBy(selectedRange)
    }

    var selectedWorkoutHistory by remember { mutableStateOf<WorkoutHistory?>(null) }

    var setHistoriesByExerciseId by remember { mutableStateOf<Map<UUID, List<SetHistory>>>(emptyMap()) }

    var sessionRestHistories by remember { mutableStateOf<List<RestHistory>>(emptyList()) }

    var volumeEntryModel by remember { mutableStateOf<CartesianChartModel?>(null) }
    var durationEntryModel by remember { mutableStateOf<CartesianChartModel?>(null) }
    var workoutDurationEntryModel by remember { mutableStateOf<CartesianChartModel?>(null) }
    var heartRateEntryModel by remember { mutableStateOf<CartesianChartModel?>(null) }

    var volumeMarkerTarget by remember { mutableStateOf<Pair<Int, Double>?>(null) }
    var durationMarkerTarget by remember { mutableStateOf<Pair<Int, Float>?>(null) }
    var workoutDurationMarkerTarget by remember { mutableStateOf<Pair<Int, Float>?>(null) }
    var heartBeatMarkerTarget by remember { mutableStateOf<Pair<Int, Int>?>(null) }
    var zoneCounter by remember { mutableStateOf<Map<Int, Int>?>(null) }
    var heartRateMinY by remember { mutableStateOf<Double?>(null) }

    val horizontalAxisValueFormatter = remember(historiesToShow) {
        CartesianValueFormatter { _, value, _ ->
            if (value.toInt() < 0 || value.toInt() >= historiesToShow.size) return@CartesianValueFormatter "-"
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

    val workoutDurationAxisValueFormatter = CartesianValueFormatter { _, value, _ ->
        formatTimeHourMinutes(value.toInt())
    }

    var isLoading by remember { mutableStateOf(true) }

    val workouts by appViewModel.workoutsFlow.collectAsState()
    val updateMessage by appViewModel.updateNotificationFlow.collectAsState(initial = null)
    val selectedWorkout = workouts.find { it.id == workout.id }!!
    val supersetsById = remember(selectedWorkout) {
        selectedWorkout.workoutComponents.filterIsInstance<Superset>().associateBy { it.id }
    }

    val exerciseById = remember(workouts) {
        workouts.flatMap { workout ->
            workout.workoutComponents.filterIsInstance<Exercise>() +
                    workout.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }
        }.associateBy { it.id }
    }

    val workoutVersions = workouts.filter { it.globalId == selectedWorkout.globalId }
    val heartRateZoneBounds = remember(userAge, measuredMaxHeartRate, restingHeartRate) {
        getHeartRateZoneBounds(
            userAge = userAge,
            measuredMaxHeartRate = measuredMaxHeartRate,
            restingHeartRate = restingHeartRate,
        )
    }

    var kiloCaloriesBurned by remember { mutableDoubleStateOf(0.0) }

    val volumes = remember { mutableListOf<Pair<Int, Double>>() }
    val durations = remember { mutableListOf<Pair<Int, Float>>() }
    val workoutDurations = remember { mutableListOf<Pair<Int, Float>>() }

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

    suspend fun setCharts(workoutHistories: List<WorkoutHistory>) {
        volumes.clear()
        durations.clear()
        workoutDurations.clear()

        volumeMarkerTarget = null
        durationMarkerTarget = null
        workoutDurationMarkerTarget = null

        if (workoutHistories.isEmpty()) return

        for (workoutHistory in workoutHistories) {
            val setHistories =
                setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)

            val validSetHistories = setHistories.filter { it.exerciseId != null }

            var volume = 0.0
            var duration = 0f

            for (setHistory in validSetHistories) {
                if (!exerciseById.containsKey(setHistory.exerciseId!!)) {
                    continue
                }

                val selectedExercise = exerciseById[setHistory.exerciseId!!]!!
                val equipment =
                    selectedExercise.equipmentId?.let { appViewModel.getEquipmentById(it) }

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

        if (volumes.any { it.second != 0.0 }) {
            volumeEntryModel =
                CartesianChartModel(LineCartesianLayerModel.build {
                    series(volumes.map { it.first }, volumes.map { it.second })
                })
        }

        if (durations.any { it.second != 0f }) {
            durationEntryModel =
                CartesianChartModel(LineCartesianLayerModel.build {
                    series(durations.map { it.first }, durations.map { it.second })
                })
        }

        workoutDurationEntryModel =
            CartesianChartModel(LineCartesianLayerModel.build { series(*(workoutDurations.map { it.second }).toTypedArray()) })
    }

    LaunchedEffect(workout, updateMessage) {
        isLoading = true
        hasLoadedWorkoutHistories = false
        withContext(Dispatchers.IO) {
            val recordsByHistoryId = workoutRecordDao.getAll()
                .associateBy { workoutRecord -> workoutRecord.workoutHistoryId }
            val workoutHistoryIdsWithSets = setHistoryDao.getAllSetHistories()
                .mapNotNull { it.workoutHistoryId }
                .toSet()

            workoutRecordsByHistoryId = recordsByHistoryId
            workoutHistories = workoutVersions.flatMap { workoutVersion ->
                workoutHistoryDao.getWorkoutsByWorkoutId(workoutVersion.id)
            }.filter { history ->
                workoutHistoryIdsWithSets.contains(history.id) || recordsByHistoryId.containsKey(history.id)
            }
                .sortedWith(
                    compareBy<WorkoutHistory>(
                        { it.date },
                        { it.time },
                        { it.version.toLong() }
                    )
                )

            workoutSessionStatuses = workoutHistories.mapNotNull { history ->
                runCatching {
                    history.id to resolveWorkoutSessionStatus(
                        workoutHistory = history,
                        workoutRecord = recordsByHistoryId[history.id]
                    )
                }.onFailure { e ->
                    Log.e(
                        WORKOUT_HISTORY_SCREEN_LOG_TAG,
                        "Invalid session state for history ${history.id}",
                        e
                    )
                }.getOrNull()
            }.toMap()

            if (workoutHistories.isEmpty()) {
                selectedWorkoutHistory = null
                delay(500)
                hasLoadedWorkoutHistories = true
                isLoading = false
                return@withContext
            }

            selectedWorkoutHistory =
                workoutHistoryId?.let { id -> workoutHistories.find { it.id == id } }
                    ?: workoutHistories.lastOrNull()

            delay(500)
            hasLoadedWorkoutHistories = true
            if (selectedWorkoutHistory == null) {
                isLoading = false
            }
        }
    }

    LaunchedEffect(workoutHistoryId, workoutHistories, hasLoadedWorkoutHistories) {
        if (!hasLoadedWorkoutHistories || workoutHistories.isEmpty()) return@LaunchedEffect
        val resolved = workoutHistoryId?.let { id -> workoutHistories.find { it.id == id } }
            ?: workoutHistories.lastOrNull()
        if (selectedWorkoutHistory?.id != resolved?.id) {
            selectedWorkoutHistory = resolved
        }
    }

    LaunchedEffect(selectedWorkoutHistory) {
        onSelectedWorkoutHistoryIdChanged(selectedWorkoutHistory?.id)
        if (selectedWorkoutHistory == null) return@LaunchedEffect

        isLoading = true

        zoneCounter = null
        heartRateEntryModel = null
        heartRateMinY = null

        withContext(Dispatchers.IO) {

            if (selectedWorkoutHistory!!.heartBeatRecords.isNotEmpty() && selectedWorkoutHistory!!.heartBeatRecords.any { it != 0 }) {
                val validHeartBeatRecords =
                    selectedWorkoutHistory!!.heartBeatRecords.filter { it != 0 }
                val minHeartBeat = validHeartBeatRecords.minOrNull()
                heartRateMinY = minHeartBeat?.toDouble()

                validHeartBeatRecords.maxOrNull()?.let { maxHeartBeat ->
                    // Create a pair of the index of the max heartbeat and the value itself
                    heartBeatMarkerTarget = Pair(
                        selectedWorkoutHistory!!.heartBeatRecords.indexOf(maxHeartBeat),
                        maxHeartBeat
                    )
                }

                zoneCounter = mapOf(0 to 0, 1 to 0, 2 to 0, 3 to 0, 4 to 0, 5 to 0)

                for (heartBeat in validHeartBeatRecords) {
                    val zone = getZoneFromHeartRate(
                        heartRate = heartBeat.toDouble(),
                        userAge = userAge,
                        measuredMaxHeartRate = measuredMaxHeartRate,
                        restingHeartRate = restingHeartRate,
                    )
                    zoneCounter = zoneCounter!!.plus(zone to zoneCounter!![zone]!!.plus(1))
                }

                val heartRateSeries = selectedWorkoutHistory!!.heartBeatRecords.map {
                    if (it == 0 && minHeartBeat != null) {
                        minHeartBeat.toDouble()
                    } else {
                        it.toDouble()
                    }
                }

                heartRateEntryModel = CartesianChartModel(
                    LineCartesianLayerModel.build {
                        series(heartRateSeries)
                    }
                )
            }

            val setHistories =
                setHistoryDao.getSetHistoriesByWorkoutHistoryIdOrdered(selectedWorkoutHistory!!.id)
            sessionRestHistories = restHistoryDao.getByWorkoutHistoryIdOrdered(selectedWorkoutHistory!!.id)
            val sectionMap = linkedMapOf<UUID, List<SetHistory>>()
            val consumedHistoryIds = mutableSetOf<UUID>()

            for (superset in selectedWorkout.workoutComponents.filterIsInstance<Superset>()) {
                val supersetSetHistories = setHistories
                    .filter { it.supersetId == superset.id }
                    .sortedWith(
                        compareBy<SetHistory>(
                            { it.executionSequence == null },
                            { it.executionSequence ?: UInt.MAX_VALUE },
                            { it.startTime },
                            { it.order }
                        )
                    )
                if (supersetSetHistories.isNotEmpty()) {
                    sectionMap[superset.id] = supersetSetHistories
                    consumedHistoryIds.addAll(supersetSetHistories.map { it.id })
                }
            }

            val remainingByExerciseId = setHistories
                .filter { it.exerciseId != null && it.id !in consumedHistoryIds }
                .groupBy { it.exerciseId!! }
            sectionMap.putAll(remainingByExerciseId)
            setHistoriesByExerciseId = sectionMap

            val avgHeartRate =
                selectedWorkoutHistory!!.heartBeatRecords.averageValidHeartRateOrNull() ?: 0.0

            val currentYear = Calendar.getInstance().get(Calendar.YEAR)
            val age = currentYear - appViewModel.workoutStore.birthDateYear
            val weightForKcal = setHistories
                .mapNotNull { it.setData as? BodyWeightSetData }
                .firstOrNull()
                ?.let { bw ->
                    val pct = bw.bodyWeightPercentageSnapshot
                    if (pct != null && pct > 0) bw.relativeBodyWeightInKg / (pct / 100) else null
                }
                ?: appViewModel.workoutStore.weightKg
            val durationMinutes = selectedWorkoutHistory!!.duration.toDouble() / 60
            kiloCaloriesBurned = calculateKiloCaloriesBurned(
                age = age,
                weightKg = weightForKcal,
                averageHeartRate = avgHeartRate,
                durationMinutes = durationMinutes,
                isMale = true
            )

            delay(500)
            isLoading = false
        }
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
            workoutDurationEntryModel = null
            volumeMarkerTarget = null
            durationMarkerTarget = null
            workoutDurationMarkerTarget = null
            ensureMinimumLoadingDuration(loadingStartedAt, minimumDurationMillis = 450L)
            isLoading = false
            return@LaunchedEffect
        }
        setCharts(historiesToShow)
        ensureMinimumLoadingDuration(loadingStartedAt, minimumDurationMillis = 450L)
        isLoading = false
    }

    LaunchedEffect(
        selectedWorkoutHistory?.id,
        historiesToShow,
        volumeEntryModel,
        durationEntryModel,
        workoutDurationEntryModel,
        hasLoadedWorkoutHistories,
    ) {
        if (!hasLoadedWorkoutHistories) return@LaunchedEffect
        val history = selectedWorkoutHistory ?: run {
            volumeMarkerTarget = null
            durationMarkerTarget = null
            workoutDurationMarkerTarget = null
            return@LaunchedEffect
        }
        val idx = historiesToShow.indexOfFirst { it.id == history.id }
        if (idx < 0) {
            volumeMarkerTarget = null
            durationMarkerTarget = null
            workoutDurationMarkerTarget = null
            return@LaunchedEffect
        }
        volumeMarkerTarget = volumes.find { it.first == idx }
        durationMarkerTarget = durations.find { it.first == idx }
        workoutDurationMarkerTarget = workoutDurations.find { it.first == idx }
    }

    val scrollState = rememberScrollState()
    val setHistoryLazyListState = rememberLazyListState()

    val graphsTabContent: @Composable ColumnScope.() -> Unit = {
        HistoryGraphTabColumn(
            scrollState = scrollState,
            isScrollEnabled = !isChartInteractionActive,
        ) {
            if (historiesToShow.isEmpty()) {
                HistoryGraphEmptyState(text = "No history in this date range.")
            }

            if (volumeEntryModel != null) {
                StandardChart(
                    isZoomEnabled = true,
                    modifier = Modifier,
                    cartesianChartModel = volumeEntryModel!!,
                    title = "Total volume (kg)",
                    markerTextFormatter = { formatNumber(it) },
                    startAxisValueFormatter = volumeAxisValueFormatter,
                    bottomAxisValueFormatter = horizontalAxisValueFormatter,
                    xAxisTickValues = volumes.map { it.first.toDouble() },
                    markerPosition = volumeMarkerTarget?.first?.toDouble(),
                    onInteractionChange = { isChartInteractionActive = it },
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
                    xAxisTickValues = durations.map { it.first.toDouble() },
                    markerPosition = durationMarkerTarget?.first?.toDouble(),
                    onInteractionChange = { isChartInteractionActive = it },
                )
            }
            if (workoutDurationEntryModel != null) {
                StandardChart(
                    isZoomEnabled = true,
                    modifier = Modifier,
                    cartesianChartModel = workoutDurationEntryModel!!,
                    title = "Workout duration",
                    markerTextFormatter = { formatTimeHourMinutes(it.toInt()) },
                    startAxisValueFormatter = workoutDurationAxisValueFormatter,
                    bottomAxisValueFormatter = horizontalAxisValueFormatter,
                    xAxisTickValues = workoutDurations.map { it.first.toDouble() },
                    markerPosition = workoutDurationMarkerTarget?.first?.toDouble(),
                    onInteractionChange = { isChartInteractionActive = it },
                )
            }
        }
    }

    val workoutSelector = @Composable {
        val selectableWorkoutHistories = historiesToShow
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
                                val index =
                                    selectableWorkoutHistories.indexOf(selectedWorkoutHistory)
                                if (index > 0) { // Check to avoid IndexOutOfBoundsException
                                    isLoading = true
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
                Column(
                    modifier = Modifier
                        .weight(1f),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(2.dp)
                ) {
                    Text(
                        text = selectedWorkoutHistory!!.date.format(dateFormatter) + " " + selectedWorkoutHistory!!.time.format(
                            timeFormatter
                        ),
                        textAlign = TextAlign.Center,
                        color = MaterialTheme.colorScheme.onBackground,
                        style = MaterialTheme.typography.titleMedium,
                    )
                    workoutSessionDisplayLabel(
                        workoutSessionStatuses[selectedWorkoutHistory!!.id]
                    )?.let { statusLabel ->
                        Text(
                            text = statusLabel,
                            textAlign = TextAlign.Center,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            style = MaterialTheme.typography.labelMedium,
                        )
                    }
                }
                Spacer(modifier = Modifier.width(10.dp))
                Box(
                    modifier = Modifier.size(25.dp),
                    contentAlignment = Alignment.Center
                ) {
                    if (canGoForward) {
                        IconButton(
                            modifier = Modifier.size(25.dp),
                            onClick = {
                                val index =
                                    selectableWorkoutHistories.indexOf(selectedWorkoutHistory)
                                if (index < selectableWorkoutHistories.size - 1) { // Check to avoid IndexOutOfBoundsException
                                    isLoading = true
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

    val setsTabContent: @Composable ColumnScope.() -> Unit = {
        val selectedWorkoutRecord = remember(
            selectedWorkoutHistory?.id,
            workoutRecordsByHistoryId
        ) {
            selectedWorkoutHistory?.id?.let { historyId ->
                workoutRecordsByHistoryId[historyId]
            }
        }
        val selectedWorkoutSessionStatus = remember(
            selectedWorkoutHistory?.id,
            workoutSessionStatuses
        ) {
            selectedWorkoutHistory?.id?.let { historyId ->
                workoutSessionStatuses[historyId]
            }
        }
        val activeExerciseId = remember(
            selectedWorkoutRecord,
            selectedWorkoutSessionStatus
        ) {
            when (selectedWorkoutSessionStatus) {
                WorkoutSessionStatus.IN_PROGRESS_ON_PHONE,
                WorkoutSessionStatus.IN_PROGRESS_ON_WEAR,
                WorkoutSessionStatus.STOPPED_ON_WEAR,
                WorkoutSessionStatus.STALE_ON_WEAR -> selectedWorkoutRecord?.exerciseId

                else -> null
            }
        }
        val historyLayout = remember(
            selectedWorkout,
            setHistoriesByExerciseId,
            sessionRestHistories,
            activeExerciseId
        ) {
            buildWorkoutHistoryLayout(
                selectedWorkout,
                setHistoriesByExerciseId,
                sessionRestHistories,
                activeExerciseId = activeExerciseId
            )
        }
        val exerciseSectionIds = remember(historyLayout) {
            historyLayout.mapNotNull { layoutItem ->
                (layoutItem as? WorkoutHistoryLayoutItem.ExerciseSection)?.exerciseId
            }.toSet()
        }
        val restHistoriesByExerciseId = remember(sessionRestHistories) {
            sessionRestHistories
                .filter { it.exerciseId != null }
                .groupBy { it.exerciseId!! }
        }
        val supersetExerciseIdsBySupersetId = remember(selectedWorkout) {
            supersetsById.mapValues { (_, superset) ->
                superset.exercises.map { it.id }.toSet()
            }
        }
        val restHistoriesBySupersetId = remember(
            sessionRestHistories,
            supersetExerciseIdsBySupersetId
        ) {
            supersetExerciseIdsBySupersetId.mapValues { (_, exerciseIds) ->
                sessionRestHistories.filter { restHistory ->
                    restHistory.exerciseId != null && restHistory.exerciseId in exerciseIds
                }
            }
        }
        val exerciseTimelineById = remember(
            exerciseSectionIds,
            setHistoriesByExerciseId,
            restHistoriesByExerciseId
        ) {
            exerciseSectionIds.associateWith { exerciseId ->
                mergeSessionTimeline(
                    setHistoriesByExerciseId[exerciseId].orEmpty(),
                    restHistoriesByExerciseId[exerciseId].orEmpty()
                )
            }
        }
        val orderedSetsByExerciseId = remember(exerciseTimelineById) {
            exerciseTimelineById.mapValues { (_, timeline) ->
                timeline.map { item ->
                    when (item) {
                        is SessionTimelineItem.SetStep -> getNewSetFromSetHistory(item.history)
                        is SessionTimelineItem.RestStep -> getNewSetFromRestHistory(item.history)
                    }
                }
            }
        }
        val setHistoriesForRendererByExerciseId = remember(exerciseTimelineById) {
            exerciseTimelineById.mapValues { (_, timeline) ->
                timeline.mapNotNull { item ->
                    (item as? SessionTimelineItem.SetStep)?.history
                }
            }
        }
        val targetProgressByExerciseId = remember(
            setHistoriesForRendererByExerciseId,
            selectedWorkoutHistory?.id,
            selectedWorkoutHistory?.heartBeatRecords,
            exerciseById,
            userAge,
            measuredMaxHeartRate,
            restingHeartRate
        ) {
            val history = selectedWorkoutHistory ?: return@remember emptyMap()
            setHistoriesForRendererByExerciseId.mapValues { (exerciseId, histories) ->
                val exercise = exerciseById[exerciseId]
                val hasTarget =
                    exercise?.lowerBoundMaxHRPercent != null && exercise.upperBoundMaxHRPercent != null
                if (!hasTarget) {
                    TargetHeartRateProgress(counter = 0, total = 0)
                } else {
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
                    var counter = 0
                    var total = 0
                    histories
                        .filter { it.setData !is RestSetData && it.startTime != null && it.endTime != null }
                        .forEach { setHistory ->
                            val hrTimeOffset = Duration.between(
                                history.startTime,
                                setHistory.startTime,
                            ).seconds.toInt().coerceAtLeast(0)
                            val setDuration = Duration.between(
                                setHistory.startTime,
                                setHistory.endTime
                            ).seconds.toInt().coerceAtLeast(0)
                            val endOffset = (hrTimeOffset + setDuration)
                                .coerceAtMost(history.heartBeatRecords.lastIndex)
                            if (hrTimeOffset <= endOffset) {
                                counter += history.heartBeatRecords
                                    .subList(hrTimeOffset, endOffset + 1)
                                    .count { it in lowHr..highHr }
                            }
                            total += setDuration
                        }
                    TargetHeartRateProgress(counter = counter, total = total)
                }
            }
        }

        HistorySetsTabColumn(
            state = setHistoryLazyListState,
        ) {
            if (heartRateEntryModel != null && selectedWorkoutHistory != null && selectedWorkoutHistory!!.heartBeatRecords.isNotEmpty()) {
                item {
                    PrimarySurface {
                        ExpandableContainer(
                            isOpen = true,
                            modifier = Modifier.fillMaxWidth(),
                            isExpandable = zoneCounter != null,
                            title = {
                                Text(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(10.dp),
                                    text = "Heart rate during workout",
                                    color = MaterialTheme.colorScheme.onBackground,
                                    style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.SemiBold),
                                )
                            },
                        subContent = {
                            HeartRateChartContent(
                                modifier = Modifier.fillMaxWidth(),
                                cartesianChartModel = heartRateEntryModel!!,
                                userAge = userAge,
                                measuredMaxHeartRate = measuredMaxHeartRate,
                                restingHeartRate = restingHeartRate,
                                minYBpm = heartRateMinY,
                                zoneGuideValuesBpm = getHeartRateZoneGuideValues(
                                    userAge = userAge,
                                    measuredMaxHeartRate = measuredMaxHeartRate,
                                    restingHeartRate = restingHeartRate,
                                ),
                                onInteractionChange = { isChartInteractionActive = it },
                            )

                            Spacer(modifier = Modifier.height(10.dp))

                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(horizontal = 10.dp)
                                    .padding(bottom = 10.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.SpaceBetween
                            ) {
                                val minHeartRate =
                                    selectedWorkoutHistory!!.heartBeatRecords.filter { it != 0 }
                                        .min()
                                val maxHeartRate = selectedWorkoutHistory!!.heartBeatRecords.max()

                                Text(
                                    text = "Duration: ${formatTime(selectedWorkoutHistory!!.duration)}",
                                    modifier = Modifier.weight(2f),
                                    color = MaterialTheme.colorScheme.onBackground,
                                    style = MaterialTheme.typography.bodyMedium,
                                )
                                Column(modifier = Modifier.weight(1f)) {
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
                                    if (kiloCaloriesBurned != 0.0 && !kiloCaloriesBurned.isNaN()) {
                                        Row(
                                            modifier = Modifier.fillMaxWidth(),
                                            horizontalArrangement = Arrangement.SpaceBetween
                                        ) {
                                            Text(
                                                text = "Calories:",
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
                                verticalArrangement = Arrangement.spacedBy(Spacing.md)
                            ) {
                                zoneCounter!!
                                    .toList()
                                    .asReversed()
                                    .forEach { (zone, count) ->
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
                                                val zoneRange = heartRateZoneBounds[zone]
                                                Text(
                                                    text = if (zone == 0) {
                                                        "< ${heartRateZoneBounds[1].first} bpm"
                                                    } else {
                                                        "${zoneRange.first} - ${zoneRange.last} bpm"
                                                    },
                                                    modifier = Modifier.weight(1f),
                                                    color = MaterialTheme.colorScheme.onBackground,
                                                    style = MaterialTheme.typography.bodySmall,
                                                )
                                                Spacer(Modifier.weight(1f))
                                                Text(
                                                    text = "${(progress * 100).toInt()}% ${
                                                        formatTime(
                                                            count
                                                        )
                                                    }",
                                                    modifier = Modifier.weight(1f),
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
                                                progressBarColor = colorsByZone[zone],
                                            )
                                        }
                                    }
                            }
                        }
                    )
                }
            }
            }
            item {
                ContentTitle(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 10.dp),
                    text = "Exercise and superset history",
                )
            }
            items(
                items = historyLayout,
                key = { it.setsTabHistoryItemKey() },
            ) { layoutItem ->
                when (layoutItem) {
                    is WorkoutHistoryLayoutItem.SupersetSection -> {
                        val key = layoutItem.supersetId
                        val setHistories = setHistoriesByExerciseId[key].orEmpty()
                        val superset = supersetsById[key] ?: return@items
                        val supersetExerciseIds = supersetExerciseIdsBySupersetId[key].orEmpty()
                        val restsForSuperset = restHistoriesBySupersetId[key].orEmpty()
                        val isActiveSupersetWithoutHistory =
                            setHistories.isEmpty() &&
                                    activeExerciseId != null &&
                                    supersetExerciseIds.contains(activeExerciseId)
                        if (isActiveSupersetWithoutHistory) {
                            SupersetRenderer(
                                superset = superset,
                                showRest = true,
                                appViewModel = appViewModel,
                                initiallyExpanded = true,
                                onExerciseClick = { exerciseId ->
                                    appViewModel.setScreenData(
                                        ScreenData.ExerciseHistory(
                                            selectedWorkoutHistory?.workoutId ?: workout.id,
                                            exerciseId,
                                            1,
                                            workoutHistoryId = selectedWorkoutHistory?.id,
                                        )
                                    )
                                }
                            )
                        } else {
                            PrimarySurface {
                                Column(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(10.dp),
                                    verticalArrangement = Arrangement.spacedBy(8.dp)
                                ) {
                                    Text(
                                        text = "Superset: ${superset.exercises.joinToString(" ↔ ") { it.name }}",
                                        style = historyExerciseNameTextStyle(),
                                        color = MaterialTheme.colorScheme.onSurface
                                    )
                                    SupersetSetHistoriesRenderer(
                                        setHistories = setHistories,
                                        restHistories = restsForSuperset,
                                        workout = selectedWorkout,
                                        getEquipmentById = { appViewModel.getEquipmentById(it) }
                                    )
                                }
                            }
                        }
                    }

                    is WorkoutHistoryLayoutItem.ExerciseSection -> {
                        val key = layoutItem.exerciseId
                        val exercise = exerciseById[key] ?: return@items

                        val restsForExercise = restHistoriesByExerciseId[key].orEmpty()
                        val setHistoriesForRenderer = setHistoriesForRendererByExerciseId[key].orEmpty()
                        val orderedSets = orderedSetsByExerciseId[key].orEmpty()

                        val hasTarget =
                            exercise.lowerBoundMaxHRPercent != null && exercise.upperBoundMaxHRPercent != null
                        val targetProgress = targetProgressByExerciseId[key]
                            ?: TargetHeartRateProgress(counter = 0, total = 0)

                        val exerciseWithHistorySets = exercise.copy(
                            sets = orderedSets,
                            requiredAccessoryEquipmentIds = exercise.requiredAccessoryEquipmentIds
                                ?: emptyList()
                        )

                        PrimarySurface {
                            if (hasTarget) {
                                Column {
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
                                        targetCounter = targetProgress.counter,
                                        targetTotal = targetProgress.total,
                                        lowHrBpm = lowHr,
                                        highHrBpm = highHr,
                                    )
                                    ExerciseHistoryRenderer(
                                        exercise = exerciseWithHistorySets,
                                        showRest = true,
                                        appViewModel = appViewModel,
                                        setHistories = setHistoriesForRenderer,
                                        intraExerciseRestHistories = restsForExercise,
                                        customTitle = { m ->
                                            Row(
                                                horizontalArrangement = Arrangement.SpaceBetween,
                                                modifier = m,
                                                verticalAlignment = Alignment.CenterVertically
                                            ) {
                                                if (exerciseById.containsKey(key)) {
                                                    IconButton(
                                                        onClick = {
                                                            appViewModel.setScreenData(
                                                                ScreenData.ExerciseHistory(
                                                                    selectedWorkoutHistory?.workoutId
                                                                        ?: workout.id,
                                                                    exercise.id,
                                                                    1,
                                                                    workoutHistoryId = selectedWorkoutHistory?.id,
                                                                )
                                                            )
                                                        }) {
                                                        Icon(
                                                            imageVector = Icons.Filled.Info,
                                                            contentDescription = "View details",
                                                            tint = MaterialTheme.colorScheme.onBackground
                                                        )
                                                    }
                                                }
                                                ScrollableTextColumn(
                                                    text = exercise.name,
                                                    modifier = Modifier.weight(1f),
                                                    maxLines = 2,
                                                    style = historyExerciseNameTextStyle(),
                                                    color = if (exercise.enabled) MaterialTheme.colorScheme.onBackground else DisabledContentGray,
                                                )
                                            }
                                        }
                                    )
                                }
                            } else {
                                ExerciseHistoryRenderer(
                                    exercise = exerciseWithHistorySets,
                                    showRest = true,
                                    appViewModel = appViewModel,
                                    setHistories = setHistoriesForRenderer,
                                    intraExerciseRestHistories = restsForExercise,
                                    customTitle = { m ->
                                        Row(
                                            horizontalArrangement = Arrangement.SpaceBetween,
                                            modifier = m,
                                            verticalAlignment = Alignment.CenterVertically
                                        ) {
                                            if (exerciseById.containsKey(key)) {
                                                IconButton(
                                                    onClick = {
                                                        appViewModel.setScreenData(
                                                            ScreenData.ExerciseHistory(
                                                                selectedWorkoutHistory?.workoutId
                                                                    ?: workout.id,
                                                                exercise.id,
                                                                1,
                                                                workoutHistoryId = selectedWorkoutHistory?.id,
                                                            )
                                                        )
                                                    }) {
                                                    Icon(
                                                        imageVector = Icons.Filled.Info,
                                                        contentDescription = "View details",
                                                        tint = MaterialTheme.colorScheme.onBackground
                                                    )
                                                }
                                            }
                                            ScrollableTextColumn(
                                                text = exercise.name,
                                                modifier = Modifier.weight(1f),
                                                maxLines = 2,
                                                style = historyExerciseNameTextStyle(),
                                                color = if (exercise.enabled) MaterialTheme.colorScheme.onBackground else DisabledContentGray,
                                            )
                                        }
                                    }
                                )
                            }
                        }
                    }
                    is WorkoutHistoryLayoutItem.RestSection -> {
                        RestBetweenWorkoutComponentsBlock(
                            history = layoutItem.history,
                        )
                    }
                }
            }
        }
    }

    Column(
        modifier = Modifier.fillMaxSize(),
        verticalArrangement = Arrangement.Top,
    ) {
        Column(
            modifier = Modifier
                .zIndex(1f)
                .fillMaxWidth(),
        ) {
            Spacer(modifier = Modifier.height(10.dp))
            RangeDropdown(selectedRange, onHistoryRangeSelected)
            Spacer(modifier = Modifier.height(12.dp))

            if (hasLoadedWorkoutHistories && selectedWorkoutHistory != null) {
                Column(modifier = Modifier.padding(horizontal = Spacing.md)) {
                    workoutSelector()
                }
                Spacer(modifier = Modifier.height(12.dp))
            }
        }

        when {
            !hasLoadedWorkoutHistories -> {
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
            isLoading -> {
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
            selectedWorkoutHistory == null -> {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f),
                    contentAlignment = Alignment.Center,
                ) {
                    PrimarySurface(modifier = Modifier.padding(15.dp)) {
                        Text(
                            modifier = Modifier.padding(15.dp),
                            text = "No workout history yet.",
                            textAlign = TextAlign.Center,
                            color = MaterialTheme.colorScheme.onSurface.copy(alpha = .87f),
                        )
                    }
                }
            }
            else -> {
                when (selectedHistoryMode.coerceIn(0, 1)) {
                    0 -> {
                        graphsTabContent()
                    }
                    1 -> {
                        setsTabContent()
                    }
                }
            }
        }
    }
}
