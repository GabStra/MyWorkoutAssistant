package com.gabstra.myworkoutassistant

import android.content.ContentValues
import android.content.Context
import android.health.connect.datatypes.TotalCaloriesBurnedRecord
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import android.widget.Toast
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
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
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
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
        val chunkSize = 1000 // Adjust the chunk size as needed
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

fun getOneRepMax(weight: Float, reps: Int): Float {
    return weight / (1.0278f - (0.0278f * reps))
}

fun calculateCaloriesBurned(
    age: Int,
    weightKg: Double,
    averageHeartRate: Double,
    durationMinutes: Double,
    isMale: Boolean
): Double {
    if (age <= 0 || weightKg <= 0 || averageHeartRate <= 0 || durationMinutes <= 0) {
        throw IllegalArgumentException("All input values must be positive")
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
    weightKg: Float
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

    val workoutHistories = if(updateAll){
        workoutHistoryDao.getAllWorkoutHistoriesByIsDone()
    }else {
        workoutHistoryDao.getWorkoutHistoriesByHasBeenSentToHealth(false)
    }

    if (workoutHistories.isEmpty()) return

    val workoutsById = workouts.associateBy { it.id }

    val exerciseSessionRecords = workoutHistories.filter { workoutsById.containsKey(it.workoutId) }.map {
        ExerciseSessionRecord(
            startTime = it.startTime.atZone(ZoneId.systemDefault()).toInstant(),
            endTime = it.startTime.plusSeconds(it.duration.toLong())
                .atZone(ZoneId.systemDefault()).toInstant(),
            startZoneOffset = ZoneOffset.systemDefault().rules.getOffset(Instant.now()),
            endZoneOffset = ZoneOffset.systemDefault().rules.getOffset(Instant.now()),
            title = workoutsById[it.workoutId]!!.name,
            exerciseType = workoutsById[it.workoutId]!!.type,
            metadata = androidx.health.connect.client.records.metadata.Metadata(
                clientRecordId = it.workoutId.toString()
            )
        )
    }

    val heartRateRecords = workoutHistories
        .filter { it.heartBeatRecords.isNotEmpty() }
        .map { workout ->
            val startTime = workout.startTime.atZone(ZoneId.systemDefault()).toInstant()
            val endTime = workout.startTime.plusSeconds(workout.duration.toLong()).atZone(ZoneId.systemDefault()).toInstant()
            val zoneOffset = ZoneOffset.systemDefault().rules.getOffset(Instant.now())

            HeartRateRecord(
                startTime = startTime,
                endTime = endTime,
                startZoneOffset = zoneOffset,
                endZoneOffset = zoneOffset,
                samples = workout.heartBeatRecords.mapIndexedNotNull { index, bpm ->
                    val sampleTime = startTime.plus(Duration.ofMillis(index.toLong() * 500))
                    if (sampleTime.isAfter(endTime)) {
                        null
                    } else {
                        HeartRateRecord.Sample(
                            time = sampleTime,
                            beatsPerMinute = bpm.toLong()
                        )
                    }
                },
                metadata = androidx.health.connect.client.records.metadata.Metadata(
                    clientRecordId = workout.workoutId.toString()
                )
            )
        }

    val totalCaloriesBurnedRecords = workoutHistories
    .filter { it.heartBeatRecords.isNotEmpty() }
        .map { workout ->
            val avgHeartRate = workout.heartBeatRecords.average()

            val durationMinutes = workout.duration.toDouble() / 60
            val caloriesBurned = calculateCaloriesBurned(
                age = age,
                weightKg = weightKg.toDouble(),
                averageHeartRate = avgHeartRate,
                durationMinutes = durationMinutes,
                isMale = true
            )

            val startTime = workout.startTime.atZone(ZoneId.systemDefault()).toInstant()
            val endTime = workout.startTime.plusSeconds(workout.duration.toLong()).atZone(ZoneId.systemDefault()).toInstant()
            val zoneOffset = ZoneOffset.systemDefault().rules.getOffset(Instant.now())

            androidx.health.connect.client.records.TotalCaloriesBurnedRecord(
                startTime= startTime,
                startZoneOffset = zoneOffset,
                endTime = endTime,
                endZoneOffset = zoneOffset,
                energy = Energy.calories(caloriesBurned),
                metadata = Metadata(
                    clientRecordId = workout.workoutId.toString()
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

fun calculateVolume(weight: Float, reps: Int): Float {
    if(weight == 0f) return reps.toFloat()
    return weight * reps
}
