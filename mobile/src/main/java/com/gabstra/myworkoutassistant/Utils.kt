package com.gabstra.myworkoutassistant

import android.annotation.SuppressLint
import android.content.ContentValues
import android.content.Context
import android.os.Environment
import android.provider.MediaStore
import android.widget.Toast
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.metadata.Device
import androidx.health.connect.client.records.metadata.Metadata
import androidx.health.connect.client.units.Energy
import androidx.health.connect.client.units.Mass
import com.gabstra.myworkoutassistant.shared.AppBackup
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.compressString
import com.gabstra.myworkoutassistant.shared.fromAppBackupToJSON
import com.gabstra.myworkoutassistant.shared.fromWorkoutStoreToJSON
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import com.gabstra.myworkoutassistant.ui.theme.DarkGray
import com.gabstra.myworkoutassistant.ui.theme.MediumLightGray
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.PutDataMapRequest
import kotlinx.coroutines.delay
import java.time.DayOfWeek
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.temporal.TemporalAdjusters
import java.util.UUID
import java.util.concurrent.CancellationException
import kotlin.math.max
import kotlin.math.min

fun sendWorkoutStore(dataClient: DataClient, workoutStore: WorkoutStore) {
    try {
        val jsonString = fromWorkoutStoreToJSON(workoutStore)
        val compressedData = compressString(jsonString)
        val request = PutDataMapRequest.create("/workoutStore").apply {
            dataMap.putByteArray("compressedJson",compressedData)
            dataMap.putString("timestamp",System.currentTimeMillis().toString())
        }.asPutDataRequest().setUrgent()

        dataClient.putDataItem(request)
    } catch (cancellationException: CancellationException) {
        cancellationException.printStackTrace()
    } catch (exception: Exception) {
        exception.printStackTrace()
    }
}

suspend fun sendAppBackup(dataClient: DataClient, appBackup: AppBackup) {
    try {
        val jsonString = fromAppBackupToJSON(appBackup)
        val chunkSize = 50000 // Adjust the chunk size as needed
        val compressedData = compressString(jsonString)
        val chunks = compressedData.asList().chunked(chunkSize)

        val transactionId = UUID.randomUUID().toString()

        val startRequest = PutDataMapRequest.create("/backupChunkPath").apply {
            dataMap.putBoolean("isStart", true)
            dataMap.putInt("chunksCount", chunks.size)
            dataMap.putString("timestamp", System.currentTimeMillis().toString())
            dataMap.putString("transactionId", transactionId)
        }.asPutDataRequest().setUrgent()

        dataClient.putDataItem(startRequest)

        delay(500)

        chunks.forEachIndexed { index, chunk ->
            val isLastChunk = index == chunks.size - 1

            val request = PutDataMapRequest.create("/backupChunkPath").apply {
                dataMap.putByteArray("chunk", chunk.toByteArray())
                if(isLastChunk) {
                    dataMap.putBoolean("isLastChunk", true)
                }
                dataMap.putString("timestamp", System.currentTimeMillis().toString())
                dataMap.putString("transactionId", transactionId)
            }.asPutDataRequest().setUrgent()

            dataClient.putDataItem(request)

            if (!isLastChunk) {
                delay(500)
            }
        }
    } catch (cancellationException: CancellationException) {
        cancellationException.printStackTrace()
    } catch (exception: Exception) {
        exception.printStackTrace()
    }
}

fun formatSecondsToMinutesSeconds(seconds: Int): String {
    val minutes = (seconds % 3600) / 60
    val remainingSeconds = seconds % 60
    return String.format("%02d:%02d", minutes, remainingSeconds)
}

fun formatMillisecondsToMinutesSeconds(milliseconds: Int): String {
    val seconds = milliseconds / 1000

    val minutes = (seconds % 3600) / 60
    val remainingSeconds = seconds % 60
    val remainingMilliseconds = milliseconds % 1000
    return String.format("%02d:%02d:%03d", minutes, remainingSeconds, remainingMilliseconds)
}

fun findWorkoutComponentByIdInWorkouts(workouts: List<Workout>, id: UUID): WorkoutComponent? {
    for(workout in workouts){
        for (workoutComponent in workout.workoutComponents) {
            if (workoutComponent.id == id) {
                return workoutComponent
            }

            if(workoutComponent is Superset){
                workoutComponent.exercises.forEach { exercise ->
                    if(exercise.id == id){
                        return exercise
                    }
                }
            }
        }
    }


    return null
}

fun findWorkoutComponentByIdInWorkout(workout: Workout, id: UUID): WorkoutComponent? {
    for (workoutComponent in workout.workoutComponents) {
        if (workoutComponent.id == id) {
            return workoutComponent
        }

        if(workoutComponent is Superset){
            workoutComponent.exercises.forEach { exercise ->
                if(exercise.id == id){
                    return exercise
                }
            }
        }
    }

    return null
}

fun writeJsonToDownloadsFolder(context: Context, fileName: String, fileContent: String) {
    val contentValues = ContentValues().apply {
        put(MediaStore.MediaColumns.DISPLAY_NAME, fileName)
        put(MediaStore.MediaColumns.MIME_TYPE, "application/json")
        put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
    }

    val resolver = context.contentResolver
    val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, contentValues)

    uri?.let {
        resolver.openOutputStream(it).use { outputStream ->
            outputStream?.write(fileContent.toByteArray())
        }
    } ?: run {
        Toast.makeText(context, "Failed to write to downloads folder", Toast.LENGTH_SHORT).show()
    }
}

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

fun getEnabledStatusOfWorkoutComponent(workoutComponent: WorkoutComponent): Boolean {
    return when (workoutComponent) {
        is Exercise -> workoutComponent.enabled
        is Rest -> workoutComponent.enabled
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

    val exerciseSessionRecords = workoutHistories.map {
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

    val heartRateRecords = workoutHistories
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

    val totalCaloriesBurnedRecords = workoutHistories
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
                    clientRecordId =   workoutHistory.id.toString()
                )
            )
        }


    val weightRecord = androidx.health.connect.client.records.WeightRecord(
        time = Instant.now(),
        zoneOffset = ZoneOffset.systemDefault().rules.getOffset(Instant.now()),
        weight = Mass.kilograms(weightKg.toDouble()),
        metadata = Metadata.unknownRecordingMethod()
    )

    healthConnectClient.insertRecords(exerciseSessionRecords)
    healthConnectClient.insertRecords(heartRateRecords)
    healthConnectClient.insertRecords(totalCaloriesBurnedRecords)
    healthConnectClient.insertRecords(listOf(weightRecord))

    for (workoutHistory in workoutHistories) {
        workoutHistoryDao.updateHasBeenSentToHealth(workoutHistory.id, true)
    }
}

fun calculateVolume(weight: Double, reps: Int): Double {
    if(weight == 0.0) return reps.toDouble()
    return weight * reps
}

fun calculateOneRepMax(weight: Double, reps: Int): Double {
    return weight / (1.0278 - (0.0278 * reps))
}

fun Double.round(decimals: Int): Double {
    var multiplier = 1.0
    repeat(decimals) { multiplier *= 10 }
    return kotlin.math.round(this * multiplier) / multiplier
}


@Composable
fun Modifier.verticalColumnScrollbar(
    scrollState: ScrollState,
    width: Dp = 4.dp,
    showScrollBarTrack: Boolean = true,
    scrollBarTrackColor: Color = DarkGray,
    scrollBarColor: Color = MediumLightGray,
    scrollBarCornerRadius: Float = 4f,
    endPadding: Float = 12f,
    trackHeight: Dp? = null,
    startSizeRatio: Float = 0.75f,
    minThumbHeight: Float = 3f
): Modifier {
    val clampedStartSizeRatio = startSizeRatio.coerceIn(0.01f, 1.0f)

    val widthPx = with(LocalDensity.current) { width.toPx() }
    val trackHeightPx = with(LocalDensity.current) { trackHeight?.toPx() }

    return drawWithContent {
        drawContent()

        val viewportHeight = this.size.height
        val totalContentHeight = max(scrollState.maxValue.toFloat() + viewportHeight, viewportHeight)
        val scrollValue = scrollState.value.toFloat()

        val visibleRatio = viewportHeight / totalContentHeight

        if (visibleRatio >= 1f || viewportHeight <= 0f || totalContentHeight <= viewportHeight || scrollState.maxValue == 0) {
            return@drawWithContent
        }

        val defaultTrackHeight = viewportHeight * 0.95f
        val actualTrackHeight = trackHeightPx?.coerceAtMost(viewportHeight) ?: defaultTrackHeight
        if (actualTrackHeight <= 0f) return@drawWithContent

        val trackTopOffset = if (actualTrackHeight < viewportHeight) {
            (viewportHeight - actualTrackHeight) / 2f
        } else {
            0f
        }

        val trackStartX = this.size.width - widthPx - endPadding

        if (showScrollBarTrack) {
            drawRoundRect(
                cornerRadius = CornerRadius(scrollBarCornerRadius),
                color = scrollBarTrackColor,
                topLeft = Offset(trackStartX, trackTopOffset),
                size = Size(widthPx, actualTrackHeight),
            )
        }

        val scrollBarHeight = (visibleRatio * actualTrackHeight)
            .coerceAtLeast(minThumbHeight)
            .coerceAtMost(actualTrackHeight)


        val availableScrollSpace = scrollState.maxValue.toFloat()
        if (availableScrollSpace <= 0f) return@drawWithContent

        val availableTrackSpace = actualTrackHeight - scrollBarHeight
        if (availableTrackSpace <= 0f) {
            // Thumb fills the track, position is fixed. Draw and return or let calculation proceed.
        }

        val effectiveAvailableTrackSpace = min(availableTrackSpace, availableScrollSpace)
        val nonNegativeEffectiveTrackSpace = max(0f, effectiveAvailableTrackSpace)

        val scrollProgress = (scrollValue / availableScrollSpace).coerceIn(0f, 1f)

        val scrollBarOffsetWithinTrack = scrollProgress * nonNegativeEffectiveTrackSpace
        val scrollBarTop = trackTopOffset + scrollBarOffsetWithinTrack

        drawRoundRect(
            cornerRadius = CornerRadius(scrollBarCornerRadius),
            color = scrollBarColor,
            topLeft = Offset(trackStartX, scrollBarTop.coerceAtMost(trackTopOffset + availableTrackSpace)),
            size = Size(widthPx, scrollBarHeight)
        )
    }
}