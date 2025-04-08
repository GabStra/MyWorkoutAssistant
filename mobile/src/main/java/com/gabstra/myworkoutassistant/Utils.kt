package com.gabstra.myworkoutassistant

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
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
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
import com.gabstra.myworkoutassistant.ui.theme.MediumGray
import com.gabstra.myworkoutassistant.ui.theme.VeryLightGray
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

    val exerciseSessionRecords = workoutHistories
        .map {
        ExerciseSessionRecord(
            startTime = it.startTime.atZone(ZoneId.systemDefault()).toInstant(),
            endTime = it.startTime.plusSeconds(it.duration.toLong())
                .atZone(ZoneId.systemDefault()).toInstant(),
            startZoneOffset = ZoneOffset.systemDefault().rules.getOffset(Instant.now()),
            endZoneOffset = ZoneOffset.systemDefault().rules.getOffset(Instant.now()),
            title = workoutsById[it.workoutId]!!.name,
            exerciseType = workoutsById[it.workoutId]!!.type,
            metadata = androidx.health.connect.client.records.metadata.Metadata(
                clientRecordId = it.id.toString()
            )
        )
    }

    val heartRateRecords = workoutHistories
        .filter { it.heartBeatRecords.isNotEmpty() }
        .map { workoutHistory ->
            val startTime = workoutHistory.startTime.atZone(ZoneId.systemDefault()).toInstant()
            val endTime = workoutHistory.startTime.plusSeconds(workoutHistory.duration.toLong()).atZone(ZoneId.systemDefault()).toInstant()
            val zoneOffset = ZoneOffset.systemDefault().rules.getOffset(Instant.now())

            HeartRateRecord(
                startTime = startTime,
                endTime = endTime,
                startZoneOffset = zoneOffset,
                endZoneOffset = zoneOffset,
                samples = workoutHistory.heartBeatRecords.mapIndexedNotNull { index, bpm ->
                    val sampleTime = startTime.plus(Duration.ofMillis(index.toLong() * 1000))
                    if (sampleTime.isAfter(endTime) || bpm <= 0) {
                        null
                    } else {
                        HeartRateRecord.Sample(
                            time = sampleTime,
                            beatsPerMinute = bpm.toLong()
                        )
                    }
                },
                metadata = androidx.health.connect.client.records.metadata.Metadata(
                    clientRecordId = workoutHistory.id.toString()
                )
            )
        }

    val totalCaloriesBurnedRecords = workoutHistories
        .filter { it.heartBeatRecords.isNotEmpty() }
        .map { workoutHistory ->
            val avgHeartRate = workoutHistory.heartBeatRecords.average()

            val durationMinutes = workoutHistory.duration.toDouble() / 60
            val kiloCaloriesBurned = calculateKiloCaloriesBurned(
                age = age,
                weightKg = weightKg.toDouble(),
                averageHeartRate = avgHeartRate,
                durationMinutes = durationMinutes,
                isMale = true
            )

            val startTime = workoutHistory.startTime.atZone(ZoneId.systemDefault()).toInstant()
            val endTime = workoutHistory.startTime.plusSeconds(workoutHistory.duration.toLong()).atZone(ZoneId.systemDefault()).toInstant()
            val zoneOffset = ZoneOffset.systemDefault().rules.getOffset(Instant.now())

            androidx.health.connect.client.records.TotalCaloriesBurnedRecord(
                startTime= startTime,
                startZoneOffset = zoneOffset,
                endTime = endTime,
                endZoneOffset = zoneOffset,
                energy = Energy.kilocalories(kiloCaloriesBurned),
                metadata = Metadata(
                    clientRecordId = workoutHistory.id.toString()
                )
            )
        }


    val weightRecord = androidx.health.connect.client.records.WeightRecord(
        time = Instant.now(),
        zoneOffset = ZoneOffset.systemDefault().rules.getOffset(Instant.now()),
        weight = Mass.kilograms(weightKg.toDouble())
    )

    healthConnectClient.insertRecords(exerciseSessionRecords + heartRateRecords + totalCaloriesBurnedRecords + weightRecord)

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
    scrollBarTrackColor: Color = MediumGray,
    scrollBarColor: Color = VeryLightGray,
    scrollBarCornerRadius: Float = 4f,
    endPadding: Float = 12f,
    /**
     * Optional explicit height for the scrollbar track.
     * If null (default), the track height will be 2/3 of the viewport height and centered vertically.
     * If provided, the track will use this height. If this provided height is less
     * than the viewport height, it will also be centered vertically.
     */
    trackHeight: Dp? = null
): Modifier {
    return drawWithContent {
        // Draw the column's content
        drawContent()

        // Dimensions and calculations
        val viewportHeight = this.size.height
        val totalContentHeight = scrollState.maxValue.toFloat() + viewportHeight
        val scrollValue = scrollState.value.toFloat()

        // Compute visibility ratio (how much of the total content is visible)
        // Avoid division by zero if totalContentHeight is equal to viewportHeight (or less, though unlikely)
        val visibleRatio = if (totalContentHeight > viewportHeight) {
            viewportHeight / totalContentHeight
        } else {
            1f
        }

        if (visibleRatio >= 1f) {
            return@drawWithContent
        }

        // Calculate actual track height: Use provided height or default to 2/3 of viewport
        val defaultTrackHeight = viewportHeight * 0.95f //(2f / 3f)
        val actualTrackHeight = trackHeight?.toPx() ?: defaultTrackHeight

        // Calculate track position (center it if its height is less than the viewport height)
        val trackTopOffset = if (actualTrackHeight < viewportHeight) {
            (viewportHeight - actualTrackHeight) / 2f
        } else {
            0f // If track is as tall or taller than viewport, start at the top
        }

        // Draw the track (optional)
        if (showScrollBarTrack) {
            drawRoundRect(
                cornerRadius = CornerRadius(scrollBarCornerRadius),
                color = scrollBarTrackColor,
                topLeft = Offset(this.size.width - endPadding, trackTopOffset),
                size = Size(width.toPx(), actualTrackHeight),
            )
        }

        // Calculate scrollbar height (proportional to visible content ratio within the track height)
        // Ensure scrollbar height is at least a minimum size (e.g., width*2) for visibility? - Optional enhancement
        val scrollBarHeight = (visibleRatio * actualTrackHeight).coerceAtLeast(width.toPx() * 2) // Ensure minimum height


        // Calculate scrollbar position within the track
        val availableTrackSpace = actualTrackHeight - scrollBarHeight
        val scrollProgress = if (scrollState.maxValue > 0) {
            scrollValue / scrollState.maxValue.toFloat()
        } else {
            0f
        }
        // Ensure scroll progress is clamped between 0 and 1
        val clampedScrollProgress = scrollProgress.coerceIn(0f, 1f)

        val scrollBarOffsetWithinTrack = clampedScrollProgress * availableTrackSpace
        val scrollBarStartOffset = trackTopOffset + scrollBarOffsetWithinTrack

        // Draw the scrollbar thumb
        drawRoundRect(
            cornerRadius = CornerRadius(scrollBarCornerRadius),
            color = scrollBarColor,
            topLeft = Offset(this.size.width - endPadding, scrollBarStartOffset),
            // Ensure the drawn size doesn't exceed the track boundaries if calculations are slightly off
            size = Size(width.toPx(), scrollBarHeight.coerceAtMost(actualTrackHeight))
        )
    }
}