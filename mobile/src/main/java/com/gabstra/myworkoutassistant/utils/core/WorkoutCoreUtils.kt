package com.gabstra.myworkoutassistant

import android.annotation.SuppressLint
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import android.widget.Toast
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.RestingHeartRateRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.TotalCaloriesBurnedRecord
import androidx.health.connect.client.records.metadata.Device
import androidx.health.connect.client.records.metadata.Metadata
import androidx.health.connect.client.units.Energy
import com.gabstra.myworkoutassistant.composables.FilterRange
import com.gabstra.myworkoutassistant.shared.AppBackup
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseInfo
import com.gabstra.myworkoutassistant.shared.ExerciseInfoDao
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgression
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgressionDao
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.compressString
import com.gabstra.myworkoutassistant.shared.datalayer.DataLayerPaths
import com.gabstra.myworkoutassistant.shared.equipments.AccessoryEquipment
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.export.equipmentToJSON
import com.gabstra.myworkoutassistant.shared.export.extractEquipmentFromWorkoutPlan
import com.gabstra.myworkoutassistant.shared.export.ExerciseHistoryMarkdownResult
import com.gabstra.myworkoutassistant.shared.export.buildExerciseHistoryMarkdown
import com.gabstra.myworkoutassistant.shared.export.buildWorkoutPlanMarkdown
import com.gabstra.myworkoutassistant.shared.fromAppBackupToJSON
import com.gabstra.myworkoutassistant.shared.fromAppBackupToJSONPrettyPrint
import com.gabstra.myworkoutassistant.shared.fromJSONtoAppBackup
import com.gabstra.myworkoutassistant.shared.fromWorkoutStoreToJSON
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.utils.DoubleProgressionHelper
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.utils.Ternary
import com.gabstra.myworkoutassistant.shared.utils.compareSetListsUnordered
import com.gabstra.myworkoutassistant.shared.viewmodels.ProgressionState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import com.google.android.gms.tasks.Tasks
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.PutDataMapRequest
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.selects.select
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.coroutines.CancellationException
import java.text.SimpleDateFormat
import java.time.DayOfWeek
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.YearMonth
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.temporal.TemporalAdjusters
import java.util.Date
import java.util.Locale
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import kotlin.math.pow
import kotlin.math.roundToInt
import java.security.MessageDigest

fun Modifier.optionalClip(shape:RoundedCornerShape?): Modifier {
    return if (shape != null) {
        clip(shape)
    } else {
        this
    }
}

fun formatTime(seconds: Int): String {
    val hours = seconds / 3600
    val minutes = (seconds % 3600) / 60
    val remainingSeconds = seconds % 60
    return if (hours > 0) {
        String.format("%02d:%02d:%02d", hours, minutes, remainingSeconds)
    } else {
        String.format("%02d:%02d", minutes, remainingSeconds)
    }
}

fun formatTimeHourMinutes(seconds: Int): String {
    val hours = seconds / 3600
    val minutes = (seconds % 3600) / 60

    return String.format("%02d:%02d", hours, minutes)
}

fun getEnabledStatusOfWorkoutComponent(workoutComponent: WorkoutComponent): Boolean {
    return when (workoutComponent) {
        is Exercise -> workoutComponent.enabled
        is Rest -> workoutComponent.enabled
        is Superset -> workoutComponent.enabled
        else -> false // Default case if the component type is unknown
    }
}

fun getStartOfWeek(date: LocalDate): LocalDate {
    return date.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
}

fun getEndOfWeek(date: LocalDate): LocalDate {
    return date.with(TemporalAdjusters.nextOrSame(DayOfWeek.SUNDAY))
}

fun getOneRepMax(weight: Double, reps: Int): Double {
    return weight / (1.0278f - (0.0278f * reps))
}

fun calculateKiloCaloriesBurned(
    age: Int,
    weightKg: Double,
    averageHeartRate: Double,
    durationMinutes: Double,
    isMale: Boolean
): Double {
    if (age <= 0 || weightKg <= 0 || averageHeartRate <= 0 || durationMinutes <= 0) {
        return 0.0
    }

    val caloriesBurned = if (isMale) {
        (age * 0.2017) + (weightKg * 0.199) + (averageHeartRate * 0.6309) - 55.0969
    } else {
        (age * 0.074) - (weightKg * 0.05741) + (averageHeartRate * 0.4472) - 20.4022
    }

    return caloriesBurned * durationMinutes / 4.184
}

@SuppressLint("RestrictedApi")
suspend fun sendWorkoutsToHealthConnect(
    workouts: List<Workout>,
    healthConnectClient: HealthConnectClient,
    workoutHistoryDao: WorkoutHistoryDao,
    updateAll: Boolean = false,
    age: Int,
    weightKg: Double,
) {
    if (workouts.isEmpty()) return

    val requiredPermissions = setOf(
        HealthPermission.getReadPermission(ExerciseSessionRecord::class),
        HealthPermission.getWritePermission(ExerciseSessionRecord::class),
        HealthPermission.getReadPermission(HeartRateRecord::class),
        HealthPermission.getWritePermission(HeartRateRecord::class)
    )

    val grantedPermissions = healthConnectClient.permissionController.getGrantedPermissions()
    val missingPermissions = requiredPermissions - grantedPermissions

    if (missingPermissions.isNotEmpty()) {
        throw IllegalStateException("Missing required permissions: $missingPermissions")
    }

    val workoutsById = workouts.associateBy { it.id }

    val workoutHistories = if(updateAll){
        workoutHistoryDao.getAllWorkoutHistoriesByIsDone()
    }else {
        workoutHistoryDao.getWorkoutHistoriesByHasBeenSentToHealth(false)
    }.filter { workoutsById.containsKey(it.workoutId) }

    if (workoutHistories.isEmpty()) return

    // Process workout histories in batches of 5 to avoid exceeding Health Connect's 5MB chunk limit
    val batchSize = 5
    workoutHistories.chunked(batchSize).forEach { batch ->
        // Delete existing records for this batch
        healthConnectClient.deleteRecords(
            ExerciseSessionRecord::class,
            clientRecordIdsList = batch.map { it.id.toString() },
            recordIdsList = emptyList()
        )

        healthConnectClient.deleteRecords(
            HeartRateRecord::class,
            clientRecordIdsList = batch.map { it.id.toString() },
            recordIdsList = emptyList()
        )

        healthConnectClient.deleteRecords(
            TotalCaloriesBurnedRecord::class,
            clientRecordIdsList = batch.map { it.id.toString() },
            recordIdsList = emptyList()
        )

        // Create records for this batch
        val exerciseSessionRecords = batch.map {
            ExerciseSessionRecord(
                startTime = it.startTime.atZone(ZoneId.systemDefault()).toInstant(),
                startZoneOffset = ZoneOffset.systemDefault().rules.getOffset(Instant.now()),
                endTime = it.startTime.plusSeconds(it.duration.toLong())
                    .atZone(ZoneId.systemDefault()).toInstant(),

                endZoneOffset = ZoneOffset.systemDefault().rules.getOffset(Instant.now()),
                exerciseType = workoutsById[it.workoutId]!!.type,
                title = workoutsById[it.workoutId]!!.name,
                metadata = Metadata.activelyRecorded(
                    Device(type = Device.TYPE_WATCH),
                    clientRecordId = it.id.toString()
                ),
            )
        }

        val heartRateRecords = batch
            .filter { it.heartBeatRecords.isNotEmpty() }
            .mapNotNull { workoutHistory ->
                val startTime = workoutHistory.startTime.atZone(ZoneId.systemDefault()).toInstant()
                val endTime = workoutHistory.startTime.plusSeconds(workoutHistory.duration.toLong()).atZone(ZoneId.systemDefault()).toInstant()
                val zoneOffset = ZoneOffset.systemDefault().rules.getOffset(Instant.now())

                val samples = workoutHistory.heartBeatRecords.mapIndexedNotNull { index, bpm ->
                    val sampleTime = startTime.plus(Duration.ofMillis(index.toLong() * 1000))
                    if (sampleTime.isAfter(endTime) || bpm <= 0) {
                        null
                    } else {
                        HeartRateRecord.Sample(
                            time = sampleTime,
                            beatsPerMinute = bpm.toLong()
                        )
                    }
                }

                if(samples.isEmpty()) {
                    return@mapNotNull null
                }

                HeartRateRecord(
                    startTime = startTime,
                    endTime = endTime,
                    startZoneOffset = zoneOffset,
                    endZoneOffset = zoneOffset,
                    samples = samples,
                    metadata = Metadata.activelyRecorded(
                        Device(type = Device.TYPE_WATCH),
                        clientRecordId =   workoutHistory.id.toString()
                    )
                )
            }

        val totalCaloriesBurnedRecords = batch
            .filter { it.heartBeatRecords.isNotEmpty() }
            .mapNotNull { workoutHistory ->
                val avgHeartRate = workoutHistory.heartBeatRecords.average()

                val durationMinutes = workoutHistory.duration.toDouble() / 60
                val kiloCaloriesBurned = calculateKiloCaloriesBurned(
                    age = age,
                    weightKg = weightKg.toDouble(),
                    averageHeartRate = avgHeartRate,
                    durationMinutes = durationMinutes,
                    isMale = true
                )

                if(kiloCaloriesBurned <= 0) {
                    return@mapNotNull null
                }

                val startTime = workoutHistory.startTime.atZone(ZoneId.systemDefault()).toInstant()
                val endTime = workoutHistory.startTime.plusSeconds(workoutHistory.duration.toLong()).atZone(ZoneId.systemDefault()).toInstant()
                val zoneOffset = ZoneOffset.systemDefault().rules.getOffset(Instant.now())

                androidx.health.connect.client.records.TotalCaloriesBurnedRecord(
                    startTime= startTime,
                    startZoneOffset = zoneOffset,
                    endTime = endTime,
                    endZoneOffset = zoneOffset,
                    energy = Energy.kilocalories(kiloCaloriesBurned),
                    metadata =  Metadata.activelyRecorded(
                        Device(type = Device.TYPE_WATCH),
                        clientRecordId = workoutHistory.id.toString()
                    )
                )
            }

        // Insert records for this batch
        healthConnectClient.insertRecords(exerciseSessionRecords)
        healthConnectClient.insertRecords(heartRateRecords)
        healthConnectClient.insertRecords(totalCaloriesBurnedRecords)

        // Update hasBeenSentToHealth flag for this batch
        for (workoutHistory in batch) {
            workoutHistoryDao.updateHasBeenSentToHealth(workoutHistory.id, true)
        }
    }
}

@SuppressLint("RestrictedApi")
suspend fun deleteWorkoutHistoriesFromHealthConnect(
    workoutHistories: List<WorkoutHistory>,
    healthConnectClient: HealthConnectClient
) {
    if (workoutHistories.isEmpty()) return

    val requiredPermissions = setOf(
        HealthPermission.getReadPermission(ExerciseSessionRecord::class),
        HealthPermission.getWritePermission(ExerciseSessionRecord::class),
        HealthPermission.getReadPermission(HeartRateRecord::class),
        HealthPermission.getWritePermission(HeartRateRecord::class)
    )

    val grantedPermissions = healthConnectClient.permissionController.getGrantedPermissions()
    val missingPermissions = requiredPermissions - grantedPermissions

    if (missingPermissions.isNotEmpty()) {
        throw IllegalStateException("Missing required permissions: $missingPermissions")
    }

    healthConnectClient.deleteRecords(
        ExerciseSessionRecord::class,
        clientRecordIdsList = workoutHistories.map { it.id.toString() },
        recordIdsList = emptyList()
    )

    healthConnectClient.deleteRecords(
        HeartRateRecord::class,
        clientRecordIdsList = workoutHistories.map { it.id.toString() },
        recordIdsList = emptyList()
    )

    healthConnectClient.deleteRecords(
        TotalCaloriesBurnedRecord::class,
        clientRecordIdsList = workoutHistories.map { it.id.toString() },
        recordIdsList = emptyList()
    )
}

suspend fun getHistoricalRestingHeartRateFromHealthConnect(
    healthConnectClient: HealthConnectClient,
    lookbackDays: Long = 14
): Int? {
    val heartRatePermission = HealthPermission.getReadPermission(HeartRateRecord::class)
    val restingPermission = HealthPermission.getReadPermission(RestingHeartRateRecord::class)
    val sleepPermission = HealthPermission.getReadPermission(SleepSessionRecord::class)

    val grantedPermissions = healthConnectClient.permissionController.getGrantedPermissions()
    val canReadHeartRate = grantedPermissions.contains(heartRatePermission)
    val canReadResting = grantedPermissions.contains(restingPermission)
    val canReadSleep = grantedPermissions.contains(sleepPermission)

    if (!canReadHeartRate && !canReadResting) {
        return null
    }

    val endTime = Instant.now()
    val startTime = endTime.minus(Duration.ofDays(lookbackDays))
    val zoneId = ZoneId.systemDefault()
    val targetCoverageDays = lookbackDays.coerceAtLeast(1).toDouble()
    val estimates = mutableListOf<WeightedEstimate>()

    if (canReadResting) {
        val restingValues = mutableListOf<Double>()
        val restingDays = mutableSetOf<LocalDate>()
        var restingPageToken: String? = null
        do {
            val response = healthConnectClient.readRecords(
                ReadRecordsRequest(
                    recordType = RestingHeartRateRecord::class,
                    timeRangeFilter = TimeRangeFilter.between(startTime, endTime),
                    pageToken = restingPageToken
                )
            )
            response.records
                .asSequence()
                .onEach { restingDays.add(it.time.atZone(zoneId).toLocalDate()) }
                .map { it.beatsPerMinute.toDouble() }
                .filter { it > 0.0 }
                .forEach { restingValues.add(it) }
            restingPageToken = response.pageToken
        } while (restingPageToken != null)

        if (restingValues.isNotEmpty()) {
            val value = medianValue(restingValues)
            val dayCoverageFactor = (restingDays.size / targetCoverageDays).coerceIn(0.25, 1.0)
            val sampleFactor = (restingValues.size / 20.0).coerceIn(0.4, 1.0)
            estimates.add(
                WeightedEstimate(
                    value = value,
                    weight = 0.5 * dayCoverageFactor * sampleFactor
                )
            )
        }
    }

    if (canReadHeartRate) {
        val allSamples = mutableListOf<HeartRateRecord.Sample>()
        var hrPageToken: String? = null
        do {
            val response = healthConnectClient.readRecords(
                ReadRecordsRequest(
                    recordType = HeartRateRecord::class,
                    timeRangeFilter = TimeRangeFilter.between(startTime, endTime),
                    pageToken = hrPageToken
                )
            )

            response.records.forEach { record ->
                record.samples
                    .asSequence()
                    .filter { it.beatsPerMinute > 0 }
                    .forEach { allSamples.add(it) }
            }
            hrPageToken = response.pageToken
        } while (hrPageToken != null)

        if (allSamples.isNotEmpty()) {
            val sortedSamples = allSamples.sortedBy { it.time }

            if (canReadSleep) {
                val sleepSessions = mutableListOf<SleepSessionRecord>()
                var sleepPageToken: String? = null
                do {
                    val response = healthConnectClient.readRecords(
                        ReadRecordsRequest(
                            recordType = SleepSessionRecord::class,
                            timeRangeFilter = TimeRangeFilter.between(startTime, endTime),
                            pageToken = sleepPageToken
                        )
                    )
                    sleepSessions.addAll(response.records)
                    sleepPageToken = response.pageToken
                } while (sleepPageToken != null)

                val nightlyValues = sleepSessions.mapNotNull { session ->
                    val sessionBpms = sortedSamples
                        .asSequence()
                        .filter { it.time >= session.startTime && it.time <= session.endTime }
                        .map { it.beatsPerMinute.toDouble() }
                        .toList()
                    if (sessionBpms.isEmpty()) {
                        null
                    } else {
                        percentile(sessionBpms, 5.0)
                    }
                }

                if (nightlyValues.isNotEmpty()) {
                    val value = medianValue(nightlyValues)
                    val sleepCoverageFactor = (nightlyValues.size / targetCoverageDays).coerceIn(0.25, 1.0)
                    estimates.add(
                        WeightedEstimate(
                            value = value,
                            weight = 0.3 * sleepCoverageFactor
                        )
                    )
                }
            }

            // Fallback signal: estimate only from overnight low-variance samples to avoid workout-only skew.
            val filtered = sortedSamples.filterIndexed { index, sample ->
                if (sample.beatsPerMinute !in 30..120) {
                    return@filterIndexed false
                }
                if (index == 0) {
                    return@filterIndexed true
                }
                val previous = sortedSamples[index - 1]
                val seconds = Duration.between(previous.time, sample.time).seconds
                if (seconds <= 0 || seconds > 15) {
                    return@filterIndexed true
                }
                val delta = kotlin.math.abs(sample.beatsPerMinute - previous.beatsPerMinute)
                delta <= 3
            }

            val overnightByDay = filtered
                .asSequence()
                .filter {
                    val localTime = it.time.atZone(zoneId).toLocalTime()
                    localTime.hour in 0..5
                }
                .groupBy { it.time.atZone(zoneId).toLocalDate() }
            val dailyLowValues = overnightByDay.values.mapNotNull { daySamples ->
                val bpms = daySamples.map { it.beatsPerMinute.toDouble() }
                if (bpms.isEmpty()) null else percentile(bpms, 5.0)
            }

            val daysWithCoverage = overnightByDay.values.count { it.size >= 10 }
            if (daysWithCoverage >= 3 && dailyLowValues.isNotEmpty()) {
                val value = medianValue(dailyLowValues)
                val overnightCoverageFactor = (daysWithCoverage / targetCoverageDays).coerceIn(0.25, 1.0)
                estimates.add(
                    WeightedEstimate(
                        value = value,
                        weight = 0.2 * overnightCoverageFactor
                    )
                )
            }
        }
    }

    if (estimates.isEmpty()) {
        return null
    }

    val sourceMedian = medianValue(estimates.map { it.value })
    val inliers = estimates.filter { kotlin.math.abs(it.value - sourceMedian) <= 15.0 }
    val selectedEstimates = if (inliers.isNotEmpty()) inliers else estimates

    return weightedMedianValue(selectedEstimates).roundToInt().coerceIn(30, 120)
}

private data class WeightedEstimate(
    val value: Double,
    val weight: Double
)

private fun weightedMedianValue(estimates: List<WeightedEstimate>): Double {
    if (estimates.isEmpty()) {
        return 0.0
    }

    val positiveWeightEstimates = estimates.filter { it.weight > 0.0 }
    if (positiveWeightEstimates.isEmpty()) {
        return medianValue(estimates.map { it.value })
    }

    val sorted = positiveWeightEstimates.sortedBy { it.value }
    val totalWeight = sorted.sumOf { it.weight }
    val halfWeight = totalWeight / 2.0
    var cumulative = 0.0

    sorted.forEach { estimate ->
        cumulative += estimate.weight
        if (cumulative >= halfWeight) {
            return estimate.value
        }
    }

    return sorted.last().value
}

private fun percentile(values: List<Double>, p: Double): Double {
    if (values.isEmpty()) {
        return 0.0
    }
    val sorted = values.sorted()
    if (sorted.size == 1) {
        return sorted.first()
    }
    val clampedP = p.coerceIn(0.0, 100.0)
    val rank = (clampedP / 100.0) * (sorted.size - 1)
    val lowIndex = kotlin.math.floor(rank).toInt()
    val highIndex = kotlin.math.ceil(rank).toInt()
    if (lowIndex == highIndex) {
        return sorted[lowIndex]
    }
    val fraction = rank - lowIndex
    return sorted[lowIndex] + (sorted[highIndex] - sorted[lowIndex]) * fraction
}

private fun medianValue(values: List<Double>): Double {
    if (values.isEmpty()) {
        return 0.0
    }
    val sorted = values.sorted()
    val n = sorted.size
    return if (n % 2 == 1) {
        sorted[n / 2]
    } else {
        (sorted[n / 2 - 1] + sorted[n / 2]) / 2.0
    }
}

fun calculateVolume(weight: Double, reps: Int): Double {
    if(weight == 0.0) return reps.toDouble()
    return weight * reps
}

fun calculateOneRepMax(weight: Double, reps: Int): Double =
    weight * reps.toDouble().pow(0.10)

fun Double.round(decimals: Int): Double {
    var multiplier = 1.0
    repeat(decimals) { multiplier *= 10 }
    return kotlin.math.round(this * multiplier) / multiplier
}

fun Float.round(decimals: Int): Float {
    var multiplier = 1.0f
    repeat(decimals) { multiplier *= 10 }
    return kotlin.math.round(this * multiplier) / multiplier
}

