package com.gabstra.myworkoutassistant

import android.annotation.SuppressLint
import android.content.ContentValues
import android.content.Context
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import android.widget.Toast
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberUpdatedState
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
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.TotalCaloriesBurnedRecord
import androidx.health.connect.client.records.metadata.Device
import androidx.health.connect.client.records.metadata.Metadata
import androidx.health.connect.client.units.Energy
import com.gabstra.myworkoutassistant.composables.FilterRange
import com.gabstra.myworkoutassistant.shared.AppBackup
import com.gabstra.myworkoutassistant.shared.AppDatabase
import androidx.compose.material3.MaterialTheme
import com.gabstra.myworkoutassistant.shared.ErrorLog
import com.gabstra.myworkoutassistant.shared.ExerciseInfo
import com.gabstra.myworkoutassistant.shared.ExerciseInfoDao
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgression
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgressionDao
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.compressString
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.export.ExerciseHistoryMarkdownResult
import com.gabstra.myworkoutassistant.shared.export.buildExerciseHistoryMarkdown
import com.gabstra.myworkoutassistant.shared.export.buildWorkoutPlanMarkdown
import com.gabstra.myworkoutassistant.shared.fromAppBackupToJSON
import com.gabstra.myworkoutassistant.shared.fromAppBackupToJSONPrettyPrint
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
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.PutDataMapRequest
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
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
import java.util.concurrent.CancellationException
import kotlin.math.pow

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
            if (workoutComponent.id == id) {
                return workoutComponent
            }

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
        android.os.Handler(android.os.Looper.getMainLooper()).post {
            Toast.makeText(context, "Failed to write to downloads folder", Toast.LENGTH_SHORT).show()
        }
    }
}

/**
 * Saves workout store to both internal storage and backup file.
 * This is a convenience function that combines both save operations.
 */
suspend fun saveWorkoutStoreWithBackup(
    context: Context,
    workoutStore: WorkoutStore,
    workoutStoreRepository: WorkoutStoreRepository,
    db: AppDatabase
) {
    withContext(Dispatchers.IO) {
        workoutStoreRepository.saveWorkoutStore(workoutStore)
        saveWorkoutStoreToDownloads(context, workoutStore, db)
    }
}

/**
 * Saves workout store with backup, automatically creating database and repository instances.
 * Use this in composables where you only have access to context.
 */
suspend fun saveWorkoutStoreWithBackupFromContext(
    context: Context,
    workoutStore: WorkoutStore
) {
    withContext(Dispatchers.IO) {
        val db = AppDatabase.getDatabase(context)
        val workoutStoreRepository = WorkoutStoreRepository(context.filesDir)
        workoutStoreRepository.saveWorkoutStore(workoutStore)
        saveWorkoutStoreToDownloads(context, workoutStore, db)
    }
}

suspend fun saveWorkoutStoreToDownloads(context: Context, workoutStore: WorkoutStore, db: AppDatabase) {
    withContext(Dispatchers.IO) {
        try {
            val fileName = "workout_store.json"
            val resolver = context.contentResolver

            // Get all DAOs
            val workoutHistoryDao = db.workoutHistoryDao()
            val setHistoryDao = db.setHistoryDao()
            val exerciseInfoDao = db.exerciseInfoDao()
            val workoutScheduleDao = db.workoutScheduleDao()
            val workoutRecordDao = db.workoutRecordDao()
            val exerciseSessionProgressionDao = db.exerciseSessionProgressionDao()
            val errorLogDao = db.errorLogDao()

            // Get all workout histories
            val workoutHistories = workoutHistoryDao.getAllWorkoutHistories()

            // Filter workouts: only active ones or ones with histories
            val allowedWorkouts = workoutStore.workouts.filter { workout ->
                workout.isActive || (!workout.isActive && workoutHistories.any { it.workoutId == workout.id })
            }

            // Filter workout histories by allowed workouts only (original backup logic - no exercise-based filtering)
            val validWorkoutHistories = workoutHistories.filter { workoutHistory ->
                allowedWorkouts.any { workout -> workout.id == workoutHistory.workoutId }
            }

            // Filter set histories to match valid workout histories
            val setHistories = setHistoryDao.getAllSetHistories().filter { setHistory ->
                validWorkoutHistories.any { it.id == setHistory.workoutHistoryId }
            }

            // Get all exercise infos, workout schedules, workout records
            val exerciseInfos = exerciseInfoDao.getAllExerciseInfos()
            val workoutSchedules = workoutScheduleDao.getAllSchedules()
            val workoutRecords = workoutRecordDao.getAll()

            // Filter exercise session progressions to match valid workout histories
            val exerciseSessionProgressions = exerciseSessionProgressionDao.getAllExerciseSessionProgressions().filter { progression ->
                validWorkoutHistories.any { it.id == progression.workoutHistoryId }
            }

            // Get all error logs
            val errorLogs = errorLogDao.getAllErrorLogs().first()

            // Create AppBackup with the same structure as original manual backup
            val appBackup = AppBackup(
                workoutStore.copy(workouts = allowedWorkouts),
                validWorkoutHistories,
                setHistories,
                exerciseInfos,
                workoutSchedules,
                workoutRecords,
                exerciseSessionProgressions,
                errorLogs.takeIf { it.isNotEmpty() }
            )

            val jsonString = fromAppBackupToJSONPrettyPrint(appBackup)

            // Query for existing file with the same name in downloads folder
            val projection = arrayOf(MediaStore.Downloads._ID)
            var deletedCount = 0
            
            // First, try to find and delete existing file(s) with the same name
            // Try with RELATIVE_PATH filter first
            val selectionWithPath = "${MediaStore.MediaColumns.DISPLAY_NAME} = ? AND ${MediaStore.MediaColumns.RELATIVE_PATH} = ?"
            val selectionArgsWithPath = arrayOf(fileName, Environment.DIRECTORY_DOWNLOADS)
            
            resolver.query(
                MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                projection,
                selectionWithPath,
                selectionArgsWithPath,
                null
            )?.use { cursor ->
                // Delete existing file(s) with the same name
                while (cursor.moveToNext()) {
                    val idIndex = cursor.getColumnIndexOrThrow(MediaStore.Downloads._ID)
                    val id = cursor.getLong(idIndex)
                    val deleteUri = android.content.ContentUris.withAppendedId(
                        MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                        id
                    )
                    val deleteResult = resolver.delete(deleteUri, null, null)
                    if (deleteResult > 0) {
                        deletedCount++
                    } else {
                        Log.w("Utils", "Failed to delete existing file with ID: $id")
                    }
                }
            }

            // Fallback: if no files found with path filter, try without path filter
            // (in case MediaStore stored the path differently)
            if (deletedCount == 0) {
                val selectionByName = "${MediaStore.MediaColumns.DISPLAY_NAME} = ?"
                val selectionArgsByName = arrayOf(fileName)
                
                resolver.query(
                    MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                    projection,
                    selectionByName,
                    selectionArgsByName,
                    null
                )?.use { cursor ->
                    while (cursor.moveToNext()) {
                        val idIndex = cursor.getColumnIndexOrThrow(MediaStore.Downloads._ID)
                        val id = cursor.getLong(idIndex)
                        val deleteUri = android.content.ContentUris.withAppendedId(
                            MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                            id
                        )
                        val deleteResult = resolver.delete(deleteUri, null, null)
                        if (deleteResult > 0) {
                            deletedCount++
                        } else {
                            Log.w("Utils", "Failed to delete existing file with ID: $id (fallback query)")
                        }
                    }
                }
            }

            if (deletedCount > 0) {
                Log.d("Utils", "Deleted $deletedCount existing backup file(s) before creating new one")
                // Small delay to ensure MediaStore processes the deletion
                delay(100)
            }

            // Insert or overwrite the file
            val contentValues = ContentValues().apply {
                put(MediaStore.MediaColumns.DISPLAY_NAME, fileName)
                put(MediaStore.MediaColumns.MIME_TYPE, "application/json")
                put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
            }

            val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, contentValues)
            if (uri != null) {
                try {
                    resolver.openOutputStream(uri)?.use { outputStream ->
                        outputStream.write(jsonString.toByteArray())
                        outputStream.flush()
                    } ?: run {
                        Log.e("Utils", "Failed to open output stream for new backup file")
                    }
                } catch (e: Exception) {
                    Log.e("Utils", "Error writing to backup file", e)
                    // Try to clean up the failed insert
                    try {
                        resolver.delete(uri, null, null)
                    } catch (deleteException: Exception) {
                        Log.e("Utils", "Error cleaning up failed file insert", deleteException)
                    }
                }
            } else {
                Log.e("Utils", "Failed to create backup file - insert returned null URI")
            }
        } catch (e: Exception) {
            Log.e("Utils", "Error saving workout store to Downloads folder", e)
        }
    }
}

suspend fun writeMarkdownToDownloadsFolder(context: Context, fileName: String, fileContent: String) {
    val contentValues = ContentValues().apply {
        put(MediaStore.MediaColumns.DISPLAY_NAME, fileName)
        put(MediaStore.MediaColumns.MIME_TYPE, "text/markdown")
        put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
    }

    val resolver = context.contentResolver
    val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, contentValues)

    uri?.let {
        resolver.openOutputStream(it).use { outputStream ->
            outputStream?.write(fileContent.toByteArray())
        }
        withContext(Dispatchers.Main) {
            Toast.makeText(context, "Export saved to downloads folder", Toast.LENGTH_SHORT).show()
        }
    } ?: run {
        withContext(Dispatchers.Main) {
            Toast.makeText(context, "Failed to write to downloads folder", Toast.LENGTH_SHORT).show()
        }
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

fun formatTimeHourMinutes(seconds: Int): String {
    val hours = seconds / 3600
    val minutes = (seconds % 3600) / 60

    return String.format("%02d:%02d", hours, minutes)
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

// Default height for the content fade gradient
private val DEFAULT_CONTENT_FADE_HEIGHT = 10.dp

@Composable
fun Modifier.verticalColumnScrollbar(
    scrollState: ScrollState,
    width: Dp = 4.dp,
    showScrollBarTrack: Boolean = true,
    scrollBarTrackColor: Color? = null,
    scrollBarColor: Color? = null,
    scrollBarCornerRadius: Float = 4f,
    endPadding: Float = 12f,
    trackHeight: Dp? = null,
    maxThumbHeightFraction: Float = 0.75f,      // Maximum thumb height as fraction of track height (0.0..1.0)
    // Content fade effect parameters
    enableTopFade: Boolean = false,
    enableBottomFade: Boolean = false,
    contentFadeHeight: Dp = DEFAULT_CONTENT_FADE_HEIGHT,
    contentFadeColor: Color? = null
): Modifier {
    val defaultTrackColor = scrollBarTrackColor ?: MaterialTheme.colorScheme.scrim
    val defaultScrollBarColor = scrollBarColor ?: MaterialTheme.colorScheme.onSurfaceVariant
    val defaultFadeColor = contentFadeColor ?: MaterialTheme.colorScheme.scrim
    // Remember updated state for all parameters accessed within draw lambda
    val rememberedShowTrack by rememberUpdatedState(showScrollBarTrack)
    val rememberedTrackColor by rememberUpdatedState(defaultTrackColor)
    val rememberedScrollBarColor by rememberUpdatedState(defaultScrollBarColor)
    val rememberedWidth by rememberUpdatedState(width)
    val rememberedCornerRadius by rememberUpdatedState(scrollBarCornerRadius)
    val rememberedEndPadding by rememberUpdatedState(endPadding)
    val rememberedTrackHeight by rememberUpdatedState(trackHeight)
    val rememberedEnableTopFade by rememberUpdatedState(enableTopFade)
    val rememberedEnableBottomFade by rememberUpdatedState(enableBottomFade)
    val rememberedContentFadeHeight by rememberUpdatedState(contentFadeHeight)
    val rememberedContentFadeColor by rememberUpdatedState(defaultFadeColor)
    val rememberedMaxThumbHeightFraction by rememberUpdatedState(maxThumbHeightFraction)

    return this.drawWithContent {
        // --- Draw the actual content first ---
        drawContent()

        // --- Content Fade Logic ---
        val fadeHeightPx = rememberedContentFadeHeight.toPx()
        val componentWidth = size.width
        val componentHeight = size.height
        val currentScrollValue = scrollState.value.toFloat()
        val maxScrollValue = scrollState.maxValue.toFloat()

        // Only proceed with fade drawing if fade height is positive
        if (fadeHeightPx > 0f) {

            // --- Top Fade Calculation ---
            if (rememberedEnableTopFade) {
                // Calculate alpha based on proximity to the top edge (within fadeHeightPx)
                // Alpha is 0.0 when scrollValue is 0, 1.0 when scrollValue >= fadeHeightPx
                val topAlpha = (currentScrollValue / fadeHeightPx).coerceIn(0f, 1f)

                // Only draw if alpha is > 0 (i.e., not exactly at the top)
                if (topAlpha > 0f) {
                    val topFadeBrush = Brush.verticalGradient(
                        colors = listOf(rememberedContentFadeColor, Color.Transparent),
                        startY = 0f,
                        endY = fadeHeightPx.coerceAtMost(componentHeight)
                    )
                    drawRect(
                        brush = topFadeBrush,
                        alpha = topAlpha,
                        topLeft = Offset.Zero,
                        size = Size(componentWidth, fadeHeightPx.coerceAtMost(componentHeight))
                    )
                }
            }

            // --- Bottom Fade Calculation ---
            if (rememberedEnableBottomFade && maxScrollValue > 0) { // Also check if scrolling is possible at all
                // Calculate distance from the bottom edge
                val distanceToBottom = maxScrollValue - currentScrollValue

                // Calculate alpha based on proximity to the bottom edge (within fadeHeightPx)
                // Alpha is 0.0 when distance is 0 (at bottom), 1.0 when distance >= fadeHeightPx
                val bottomAlpha = (distanceToBottom / fadeHeightPx).coerceIn(0f, 1f)

                // Only draw if alpha is > 0 (i.e., not exactly at the bottom)
                if (bottomAlpha > 0f) {
                    val bottomFadeBrush = Brush.verticalGradient(
                        colors = listOf(Color.Transparent, rememberedContentFadeColor),
                        startY = (componentHeight - fadeHeightPx).coerceAtLeast(0f),
                        endY = componentHeight
                    )
                    drawRect(
                        brush = bottomFadeBrush,
                        alpha = bottomAlpha,
                        topLeft = Offset(0f, (componentHeight - fadeHeightPx).coerceAtLeast(0f)),
                        size = Size(componentWidth, fadeHeightPx.coerceAtMost(componentHeight))
                    )
                }
            }
        }


        // --- Scrollbar Logic (remains the same, drawn on top) ---
        val viewportHeight = componentHeight
        val totalContentHeight = (maxScrollValue + viewportHeight).coerceAtLeast(viewportHeight)
        val scrollValue = currentScrollValue // Use already fetched value
        val visibleRatio = (viewportHeight / totalContentHeight).coerceIn(0f, 1f)

        if (visibleRatio >= 1f || maxScrollValue <= 0) {
            return@drawWithContent
        }

        val defaultTrackHeight = viewportHeight
        val actualTrackHeight = rememberedTrackHeight?.toPx()?.coerceAtMost(viewportHeight) ?: defaultTrackHeight
        val trackTopOffset = if (actualTrackHeight < viewportHeight) {
            (viewportHeight - actualTrackHeight) / 2f
        } else {
            0f
        }

        val minThumbHeight = rememberedWidth.toPx() * 2
        val scrollBarHeight = (visibleRatio * actualTrackHeight)
            .coerceAtLeast(minThumbHeight)
            .coerceAtMost(actualTrackHeight)
        val availableScrollSpace = maxScrollValue
        val availableTrackSpace = (actualTrackHeight - scrollBarHeight).coerceAtLeast(0f)
        val scrollProgress = if (availableScrollSpace > 0) scrollValue / availableScrollSpace else 0f
        val clampedScrollProgress = scrollProgress.coerceIn(0f, 1f)
        val scrollBarOffsetWithinTrack = clampedScrollProgress * availableTrackSpace
        val scrollBarTopOffset = trackTopOffset + scrollBarOffsetWithinTrack

        val cornerRadius = CornerRadius(rememberedCornerRadius)
        val barWidthPx = rememberedWidth.toPx()
        val paddingPx = rememberedEndPadding

        if (rememberedShowTrack) {
            drawRoundRect(
                color = rememberedTrackColor,
                topLeft = Offset(componentWidth - paddingPx - barWidthPx, trackTopOffset),
                size = Size(barWidthPx, actualTrackHeight),
                cornerRadius = cornerRadius
            )
        }

        drawRoundRect(
            color = rememberedScrollBarColor,
            topLeft = Offset(componentWidth - paddingPx - barWidthPx, scrollBarTopOffset),
            size = Size(barWidthPx, scrollBarHeight),
            cornerRadius = cornerRadius
        )
    }
}

@Composable
fun Modifier.verticalLazyColumnScrollbar(
    lazyListState: LazyListState,
    width: Dp = 4.dp,
    showScrollBarTrack: Boolean = true,
    scrollBarTrackColor: Color? = null,
    scrollBarColor: Color? = null,
    scrollBarCornerRadius: Float = 4f,
    endPadding: Float = 12f,
    trackHeight: Dp? = null,
    maxThumbHeightFraction: Float = 0.75f,      // Maximum thumb height as fraction of track height (0.0..1.0)
    // Content fade effect parameters
    enableTopFade: Boolean = false,
    enableBottomFade: Boolean = false,
    contentFadeHeight: Dp = DEFAULT_CONTENT_FADE_HEIGHT,
    contentFadeColor: Color? = null
): Modifier {
    val defaultTrackColor = scrollBarTrackColor ?: MaterialTheme.colorScheme.scrim
    val defaultScrollBarColor = scrollBarColor ?: MaterialTheme.colorScheme.onSurfaceVariant
    val defaultFadeColor = contentFadeColor ?: MaterialTheme.colorScheme.scrim
    val rememberedShowTrack by rememberUpdatedState(showScrollBarTrack)
    val rememberedTrackColor by rememberUpdatedState(defaultTrackColor)
    val rememberedScrollBarColor by rememberUpdatedState(defaultScrollBarColor)
    val rememberedWidth by rememberUpdatedState(width)
    val rememberedCornerRadius by rememberUpdatedState(scrollBarCornerRadius)
    val rememberedEndPadding by rememberUpdatedState(endPadding)
    val rememberedTrackHeight by rememberUpdatedState(trackHeight)
    val rememberedEnableTopFade by rememberUpdatedState(enableTopFade)
    val rememberedEnableBottomFade by rememberUpdatedState(enableBottomFade)
    val rememberedContentFadeHeight by rememberUpdatedState(contentFadeHeight)
    val rememberedContentFadeColor by rememberUpdatedState(defaultFadeColor)
    val rememberedMaxThumbHeightFraction by rememberUpdatedState(maxThumbHeightFraction)

    val layoutInfo = lazyListState.layoutInfo
    val visibleItemsInfo = layoutInfo.visibleItemsInfo

    return this.drawWithContent {
        drawContent()

        val componentWidth = size.width
        val componentHeight = size.height
        val viewportHeight = componentHeight.toFloat()

        // Calculate scroll position and total content height
        val firstVisibleItem = visibleItemsInfo.firstOrNull()
        
        if (firstVisibleItem == null || layoutInfo.totalItemsCount == 0) {
            return@drawWithContent
        }

        // Calculate current scroll position (pixels scrolled)
        val currentScrollValue = if (firstVisibleItem.index > 0) {
            // Estimate: sum of heights of items before first visible item
            // Use average item height from visible items as estimate
            val avgItemHeight = if (visibleItemsInfo.isNotEmpty()) {
                visibleItemsInfo.sumOf { it.size }.toFloat() / visibleItemsInfo.size
            } else {
                firstVisibleItem.size.toFloat()
            }
            (firstVisibleItem.index * avgItemHeight) - firstVisibleItem.offset
        } else {
            (-firstVisibleItem.offset).toFloat()
        }

        // Calculate total content height
        // Estimate based on visible items and total item count
        val avgItemHeight = if (visibleItemsInfo.isNotEmpty()) {
            visibleItemsInfo.sumOf { it.size }.toFloat() / visibleItemsInfo.size
        } else {
            firstVisibleItem.size.toFloat()
        }
        val estimatedTotalHeight = layoutInfo.totalItemsCount * avgItemHeight
        val maxScrollValue = (estimatedTotalHeight - viewportHeight).coerceAtLeast(0f)

        // --- Content Fade Logic ---
        val fadeHeightPx = rememberedContentFadeHeight.toPx()
        if (fadeHeightPx > 0f) {
            // --- Top Fade Calculation ---
            if (rememberedEnableTopFade) {
                val topAlpha = (currentScrollValue / fadeHeightPx).coerceIn(0f, 1f)
                if (topAlpha > 0f) {
                    val topFadeBrush = Brush.verticalGradient(
                        colors = listOf(rememberedContentFadeColor, Color.Transparent),
                        startY = 0f,
                        endY = fadeHeightPx.coerceAtMost(componentHeight)
                    )
                    drawRect(
                        brush = topFadeBrush,
                        alpha = topAlpha,
                        topLeft = Offset.Zero,
                        size = Size(componentWidth, fadeHeightPx.coerceAtMost(componentHeight))
                    )
                }
            }

            // --- Bottom Fade Calculation ---
            if (rememberedEnableBottomFade && maxScrollValue > 0) {
                val distanceToBottom = maxScrollValue - currentScrollValue
                val bottomAlpha = (distanceToBottom / fadeHeightPx).coerceIn(0f, 1f)
                if (bottomAlpha > 0f) {
                    val bottomFadeBrush = Brush.verticalGradient(
                        colors = listOf(Color.Transparent, rememberedContentFadeColor),
                        startY = (componentHeight - fadeHeightPx).coerceAtLeast(0f),
                        endY = componentHeight
                    )
                    drawRect(
                        brush = bottomFadeBrush,
                        alpha = bottomAlpha,
                        topLeft = Offset(0f, (componentHeight - fadeHeightPx).coerceAtLeast(0f)),
                        size = Size(componentWidth, fadeHeightPx.coerceAtMost(componentHeight))
                    )
                }
            }
        }

        // --- Scrollbar Logic ---
        val totalContentHeight = (maxScrollValue + viewportHeight).coerceAtLeast(viewportHeight)
        val scrollValue = currentScrollValue
        val visibleRatio = (viewportHeight / totalContentHeight).coerceIn(0f, 1f)

        if (visibleRatio >= 1f || maxScrollValue <= 0) {
            return@drawWithContent
        }

        val defaultTrackHeight = viewportHeight
        val actualTrackHeight = rememberedTrackHeight?.toPx()?.coerceAtMost(viewportHeight) ?: defaultTrackHeight
        val trackTopOffset = if (actualTrackHeight < viewportHeight) {
            (viewportHeight - actualTrackHeight) / 2f
        } else {
            0f
        }

        val minThumbHeight = rememberedWidth.toPx() * 2
        val maxThumbHeight = actualTrackHeight * rememberedMaxThumbHeightFraction.coerceIn(0f, 1f)
        val computedThumbHeight = visibleRatio * actualTrackHeight
        val scrollBarHeight = computedThumbHeight
            .coerceAtLeast(minThumbHeight)
            .coerceAtMost(maxThumbHeight)
        val availableScrollSpace = maxScrollValue
        val availableTrackSpace = (actualTrackHeight - scrollBarHeight).coerceAtLeast(0f)
        val scrollProgress = if (availableScrollSpace > 0) scrollValue / availableScrollSpace else 0f
        val clampedScrollProgress = scrollProgress.coerceIn(0f, 1f)
        val scrollBarOffsetWithinTrack = clampedScrollProgress * availableTrackSpace
        val scrollBarTopOffset = trackTopOffset + scrollBarOffsetWithinTrack

        val cornerRadius = CornerRadius(rememberedCornerRadius)
        val barWidthPx = rememberedWidth.toPx()
        val paddingPx = rememberedEndPadding

        if (rememberedShowTrack) {
            drawRoundRect(
                color = rememberedTrackColor,
                topLeft = Offset(componentWidth - paddingPx - barWidthPx, trackTopOffset),
                size = Size(barWidthPx, actualTrackHeight),
                cornerRadius = cornerRadius
            )
        }

        drawRoundRect(
            color = rememberedScrollBarColor,
            topLeft = Offset(componentWidth - paddingPx - barWidthPx, scrollBarTopOffset),
            size = Size(barWidthPx, scrollBarHeight),
            cornerRadius = cornerRadius
        )
    }
}

fun ensureRestSeparatedBySets(components: List<com.gabstra.myworkoutassistant.shared.sets.Set>): List<com.gabstra.myworkoutassistant.shared.sets.Set> {
    val adjustedComponents = mutableListOf<Set>()
    var lastWasSet = false

    for (component in components) {
        if(component !is RestSet) {
            adjustedComponents.add(component)
            lastWasSet = true
        }else{
            if(lastWasSet){
                adjustedComponents.add(component)
            }

            lastWasSet = false
        }
    }
    return adjustedComponents
}

fun ensureRestSeparatedByExercises(components: List<WorkoutComponent>): List<WorkoutComponent> {
    val adjustedComponents = mutableListOf<WorkoutComponent>()
    var lastWasExercise = false

    for (component in components) {
        if (component !is Rest) {
            adjustedComponents.add(component)
            lastWasExercise = true
        } else {
            if (lastWasExercise) {
                //check if the next component if exist is exercise and enabled
                val nextComponentIndex = components.indexOf(component) + 1
                if (nextComponentIndex < components.size) {
                    val nextComponent = components[nextComponentIndex]
                    if (nextComponent.enabled) {
                        adjustedComponents.add(component)
                    } else {
                        adjustedComponents.add(component.copy(enabled = false))
                    }
                }
            }

            lastWasExercise = false
        }
    }
    return adjustedComponents
}

fun dateRangeFor(range: FilterRange): Pair<LocalDate, LocalDate> {
    val today = LocalDate.now()

    return when (range) {
        FilterRange.LAST_WEEK -> {
            val thisMonday = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
            val lastMonday = thisMonday.minusWeeks(1)
            val lastSunday = lastMonday.plusDays(6)
            lastMonday to lastSunday
        }
        FilterRange.LAST_7_DAYS -> {
            val start = today.minusDays(6)
            start to today
        }
        FilterRange.LAST_30_DAYS -> {
            val start = today.minusDays(29)
            start to today
        }
        FilterRange.THIS_MONTH -> {
            val ym = YearMonth.now()
            ym.atDay(1) to ym.atEndOfMonth()
        }
        FilterRange.LAST_3_MONTHS -> {
            val start = today.minusMonths(3)
            start to today
        }
        FilterRange.ALL -> LocalDate.MIN to LocalDate.MAX
    }
}

fun List<WorkoutHistory>.filterBy(range: FilterRange): List<WorkoutHistory> {
    val (start, end) = dateRangeFor(range)
    return this.filter { it.date >= start && it.date <= end }
}

@SuppressLint("SuspiciousModifierThen")
@OptIn(ExperimentalComposeUiApi::class)
fun Modifier.repeatActionOnLongPressOrTap(
    coroutineScope: CoroutineScope,
    thresholdMillis: Long = 5000L,
    intervalMillis: Long = 1000L,
    onAction: () -> Unit,
    onTap: () -> Unit
): Modifier = this.then(
    pointerInput(Unit) {
        var repeatedActionHappening = false
        detectTapGestures(
            onPress = { _ ->
                val job = coroutineScope.launch {
                    delay(thresholdMillis)
                    do {
                        repeatedActionHappening = true
                        onAction()
                        delay(intervalMillis)
                    } while (true)
                }
                tryAwaitRelease()
                job.cancel()
                repeatedActionHappening = false
            },
            onTap = {
                if(!repeatedActionHappening) onTap()
            }
        )
    }
)

@SuppressLint("SuspiciousModifierThen")
@OptIn(ExperimentalComposeUiApi::class)
fun Modifier.repeatActionOnLongPress(
    coroutineScope: CoroutineScope,
    thresholdMillis: Long = 5000L,
    intervalMillis: Long = 1000L,
    onPressStart: () -> Unit,
    onBeforeLongPressRepeat: () -> Unit,
    onLongPressRepeat: () -> Unit,
    onRelease: () -> Unit
): Modifier = this.then(
    pointerInput(Unit) {
        detectTapGestures(
            onPress = { _ ->
                onPressStart()
                val job = coroutineScope.launch {
                    delay(thresholdMillis)
                    onBeforeLongPressRepeat()
                    do {
                        delay(intervalMillis)
                        onLongPressRepeat()
                    } while (isActive)
                }

                tryAwaitRelease()
                job.cancel()
                onRelease()
            }
        )
    }
)

suspend fun exportExerciseHistoryToMarkdown(
    context: Context,
    exercise: Exercise,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
    workouts: List<Workout>,
    workoutStore: WorkoutStore
) {
    try {
        when (val result = buildExerciseHistoryMarkdown(
            exercise = exercise,
            workoutHistoryDao = workoutHistoryDao,
            setHistoryDao = setHistoryDao,
            exerciseSessionProgressionDao = exerciseSessionProgressionDao,
            workouts = workouts,
            workoutStore = workoutStore
        )) {
            is ExerciseHistoryMarkdownResult.Success -> {
                val sdf = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault())
                val timestamp = sdf.format(Date())
                val sanitizedName = exercise.name.replace(Regex("[^a-zA-Z0-9]"), "_").take(50)
                val filename = "exercise_history_${sanitizedName}_$timestamp.md"
                writeMarkdownToDownloadsFolder(context, filename, result.markdown)
            }
            is ExerciseHistoryMarkdownResult.Failure -> {
                withContext(Dispatchers.Main) {
                    Toast.makeText(context, result.message, Toast.LENGTH_SHORT).show()
                }
            }
        }
    } catch (e: Exception) {
        Log.e("ExerciseExport", "Error exporting exercise history", e)
        withContext(Dispatchers.Main) {
            Toast.makeText(context, "Export failed: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }
}

suspend fun exportWorkoutPlanToMarkdown(
    context: Context,
    workoutStore: WorkoutStore
) {
    try {
        val markdown = buildWorkoutPlanMarkdown(workoutStore)
        val sdf = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault())
        val timestamp = sdf.format(Date())
        val filename = "workout_plan_export_$timestamp.md"
        writeMarkdownToDownloadsFolder(context, filename, markdown)
    } catch (e: Exception) {
        Log.e("WorkoutPlanExport", "Error exporting workout plan", e)
        withContext(Dispatchers.Main) {
            Toast.makeText(context, "Export failed: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }
}

suspend fun backfillExerciseSessionProgressions(
    workoutStore: WorkoutStore,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    exerciseInfoDao: ExerciseInfoDao,
    exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
    db: AppDatabase
) {
    try {
        Log.d("BackfillProgression", "Starting backfill of ExerciseSessionProgressions")
        
        // Get all completed workouts chronologically
        val allWorkouts = workoutHistoryDao.getAllWorkoutHistoriesByIsDone(isDone = true)
            ?: emptyList()
        
        if (allWorkouts.isEmpty()) {
            Log.d("BackfillProgression", "No completed workouts found, skipping backfill")
            return
        }
        
        val sortedWorkouts = allWorkouts.sortedWith(compareBy<WorkoutHistory> { it.date }.thenBy { it.time })
        Log.d("BackfillProgression", "Processing ${sortedWorkouts.size} completed workouts")

        // Build a map of workout ID to Workout for quick lookup
        val workouts = workoutStore.workouts ?: emptyList()
        val workoutMap = workouts.associateBy { it.id }
        
        // Build a map of exercise ID to Exercise for quick lookup
        val exerciseMap = mutableMapOf<UUID, Exercise>()
        workouts.forEach { workout ->
            workout.workoutComponents?.forEach { component ->
                when (component) {
                    is Exercise -> exerciseMap[component.id] = component
                    is Superset -> component.exercises?.forEach { exercise ->
                        exerciseMap[exercise.id] = exercise
                    }
                    is Rest -> Unit
                }
            }
        }

        // Build equipment map
        val equipments = workoutStore.equipments ?: emptyList()
        val equipmentMap = equipments.associateBy { it.id }
        
        // Track ExerciseInfo state as we process workouts chronologically
        // We start with empty state and build it up chronologically to ensure correctness
        val exerciseInfoStateMap = mutableMapOf<UUID, ExerciseInfo>()

        // Process each workout chronologically
        for (workoutHistory in sortedWorkouts) {
            val workout = workoutMap[workoutHistory.workoutId] ?: run {
                Log.d("BackfillProgression", "Workout ${workoutHistory.workoutId} not found in workout store, skipping")
                continue
            }
            
            // Get all exercises from this workout that have enableProgression
            val exercises = mutableListOf<Exercise>()
            workout.workoutComponents?.forEach { component ->
                when (component) {
                    is Exercise -> {
                        if (component.enableProgression && 
                            (component.exerciseType == ExerciseType.WEIGHT || 
                             component.exerciseType == ExerciseType.BODY_WEIGHT)) {
                            exercises.add(component)
                        }
                    }
                    is Superset -> {
                        component.exercises?.forEach { exercise ->
                            if (exercise.enableProgression && 
                                (exercise.exerciseType == ExerciseType.WEIGHT || 
                                 exercise.exerciseType == ExerciseType.BODY_WEIGHT)) {
                                exercises.add(exercise)
                            }
                        }
                    }
                    is Rest -> Unit
                }
            }

            // Get SetHistory entries for this workout
            val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)
                ?.filter { it.exerciseId != null } ?: emptyList()

            // Process each exercise
            for (exercise in exercises) {
                // Check if progression entry already exists
                val existingProgression = exerciseSessionProgressionDao
                    .getByWorkoutHistoryIdAndExerciseId(workoutHistory.id, exercise.id)
                
                if (existingProgression != null) {
                    // Entry already exists, skip
                    Log.d("BackfillProgression", "Progression entry already exists for exercise ${exercise.id} in workout ${workoutHistory.id}, skipping")
                    continue
                }

                // Get SetHistory entries for this exercise in this workout
                val exerciseSetHistories = setHistories
                    .filter { it.exerciseId == exercise.id }
                    .sortedBy { it.order }

                if (exerciseSetHistories.isEmpty()) {
                    // No sets for this exercise in this workout, skip
                    continue
                }

                // Filter out rest sets and rest pause sets
                val currentSession = exerciseSetHistories
                    .dropWhile { it.setData is RestSetData }
                    .dropLastWhile { it.setData is RestSetData }
                    .filter {
                        when (val setData = it.setData) {
                            is BodyWeightSetData -> setData.subCategory != SetSubCategory.RestPauseSet
                            is WeightSetData -> setData.subCategory != SetSubCategory.RestPauseSet
                            is RestSetData -> setData.subCategory != SetSubCategory.RestPauseSet
                            else -> true
                        }
                    }

                if (currentSession.isEmpty()) {
                    continue
                }

                // Convert executed sets to SimpleSet
                val executedSets = currentSession.mapNotNull { setHistory ->
                    when (val setData = setHistory.setData) {
                        is WeightSetData -> {
                            if (setData.subCategory == SetSubCategory.RestPauseSet) null
                            else SimpleSet(setData.getWeight(), setData.actualReps)
                        }
                        is BodyWeightSetData -> {
                            if (setData.subCategory == SetSubCategory.RestPauseSet) null
                            else SimpleSet(setData.getWeight(), setData.actualReps)
                        }
                        else -> null
                    }
                }

                if (executedSets.isEmpty()) {
                    continue
                }

                // Get or reconstruct ExerciseInfo state as it would have been BEFORE this workout
                val exerciseInfoBefore = exerciseInfoStateMap[exercise.id]

                // Calculate expected sets and progression state
                val (expectedSets, progressionState) = calculateExpectedSetsAndProgressionState(
                    exercise = exercise,
                    exerciseInfoBefore = exerciseInfoBefore,
                    workoutStore = workoutStore,
                    equipmentMap = equipmentMap,
                    workoutHistoryDate = workoutHistory.date
                )

                // Handle first sessions (when expectedSets is null because there's no previous session)
                val finalExpectedSets = expectedSets ?: executedSets
                val finalProgressionState = progressionState ?: ProgressionState.PROGRESS
                
                if (finalExpectedSets.isEmpty()) {
                    // No expected sets and no executed sets, skip
                    Log.d("BackfillProgression", "Skipping exercise ${exercise.id} - no sets available")
                    continue
                }

                // Calculate comparisons
                val vsExpected = compareSetListsUnordered(executedSets, finalExpectedSets)
                
                val previousSessionSets = exerciseInfoBefore?.lastSuccessfulSession?.mapNotNull { setHistory ->
                    when (val setData = setHistory.setData) {
                        is WeightSetData -> {
                            if (setData.subCategory == SetSubCategory.RestPauseSet) null
                            else SimpleSet(setData.getWeight(), setData.actualReps)
                        }
                        is BodyWeightSetData -> {
                            if (setData.subCategory == SetSubCategory.RestPauseSet) null
                            else SimpleSet(setData.getWeight(), setData.actualReps)
                        }
                        else -> null
                    }
                } ?: emptyList()

                val vsPrevious = if (previousSessionSets.isNotEmpty()) {
                    compareSetListsUnordered(executedSets, previousSessionSets)
                } else {
                    Ternary.EQUAL
                }

                // Calculate volumes
                val previousSessionVolume = exerciseInfoBefore?.lastSuccessfulSession?.mapNotNull { setHistory ->
                    when (val setData = setHistory.setData) {
                        is WeightSetData -> {
                            if (setData.subCategory == SetSubCategory.RestPauseSet) null
                            else SimpleSet(setData.getWeight(), setData.actualReps)
                        }
                        is BodyWeightSetData -> {
                            if (setData.subCategory == SetSubCategory.RestPauseSet) null
                            else SimpleSet(setData.getWeight(), setData.actualReps)
                        }
                        else -> null
                    }
                }?.sumOf { it.weight * it.reps } ?: 0.0

                val expectedVolume = finalExpectedSets.sumOf { it.weight * it.reps }
                val executedVolume = executedSets.sumOf { it.weight * it.reps }

                // Create and insert ExerciseSessionProgression entry
                val progressionEntry = ExerciseSessionProgression(
                    id = UUID.randomUUID(),
                    workoutHistoryId = workoutHistory.id,
                    exerciseId = exercise.id,
                    expectedSets = finalExpectedSets,
                    progressionState = finalProgressionState,
                    vsExpected = vsExpected,
                    vsPrevious = vsPrevious,
                    previousSessionVolume = previousSessionVolume,
                    expectedVolume = expectedVolume,
                    executedVolume = executedVolume
                )

                exerciseSessionProgressionDao.insert(progressionEntry)
                Log.d("BackfillProgression", "Created progression entry for exercise ${exercise.id} in workout ${workoutHistory.id}")

                // Update ExerciseInfo state for next iteration
                updateExerciseInfoState(
                    exerciseId = exercise.id,
                    currentSession = currentSession,
                    executedSets = executedSets,
                    progressionState = progressionState,
                    vsExpected = vsExpected,
                    exerciseInfoBefore = exerciseInfoBefore,
                    exerciseInfoStateMap = exerciseInfoStateMap,
                    workoutHistoryDate = workoutHistory.date
                )
            }
        }
    } catch (e: Exception) {
        Log.e("BackfillProgression", "Error backfilling ExerciseSessionProgressions", e)
    }
}

private suspend fun calculateExpectedSetsAndProgressionState(
    exercise: Exercise,
    exerciseInfoBefore: ExerciseInfo?,
    workoutStore: WorkoutStore,
    equipmentMap: Map<UUID, WeightLoadedEquipment>,
    workoutHistoryDate: LocalDate?
): Pair<List<SimpleSet>?, ProgressionState?> {
    try {
        // Get available weights
        val availableWeights = when (exercise.exerciseType) {
            ExerciseType.WEIGHT -> {
                exercise.equipmentId?.let { equipmentMap[it]?.getWeightsCombinations() } ?: emptySet()
            }
            ExerciseType.BODY_WEIGHT -> {
                val relativeBodyWeight = workoutStore.weightKg * (exercise.bodyWeightPercentage!! / 100)
                (exercise.equipmentId?.let {
                    equipmentMap[it]?.getWeightsCombinations()?.map { value -> relativeBodyWeight + value }!!.toSet()
                } ?: emptySet()) + setOf(relativeBodyWeight)
            }
            else -> return Pair(null, null)
        }

        if (availableWeights.isEmpty()) {
            return Pair(null, null)
        }

        // Get previous session sets
        val previousSessionSets = exerciseInfoBefore?.lastSuccessfulSession?.mapNotNull { setHistory ->
            when (val setData = setHistory.setData) {
                is WeightSetData -> {
                    if (setData.subCategory == SetSubCategory.RestPauseSet) null
                    else SimpleSet(setData.getWeight(), setData.actualReps)
                }
                is BodyWeightSetData -> {
                    if (setData.subCategory == SetSubCategory.RestPauseSet) null
                    else SimpleSet(setData.getWeight(), setData.actualReps)
                }
                else -> null
            }
        } ?: emptyList()

        if (previousSessionSets.isEmpty()) {
            // No previous session, cannot calculate expected sets
            return Pair(null, null)
        }

        // Compute progression state using the workout history date
        val progressionState = computeProgressionState(exerciseInfoBefore, workoutHistoryDate = workoutHistoryDate)

        // Calculate expected sets based on progression state
        val repsRange = IntRange(exercise.minReps, exercise.maxReps)
        val expectedSets = when (progressionState) {
            ProgressionState.DELOAD -> {
                DoubleProgressionHelper.planDeloadSession(
                    previousSets = previousSessionSets,
                    availableWeights = availableWeights,
                    repsRange = repsRange
                ).sets
            }
            ProgressionState.RETRY -> {
                // For retry, expected sets are the same as previous
                previousSessionSets
            }
            ProgressionState.PROGRESS -> {
                val jumpPolicy = DoubleProgressionHelper.LoadJumpPolicy(
                    defaultPct = exercise.loadJumpDefaultPct ?: 0.025,
                    maxPct = exercise.loadJumpMaxPct ?: 0.5,
                    overcapUntil = exercise.loadJumpOvercapUntil ?: 2
                )
                DoubleProgressionHelper.planNextSession(
                    previousSets = previousSessionSets,
                    availableWeights = availableWeights,
                    repsRange = repsRange,
                    jumpPolicy = jumpPolicy
                ).sets
            }
            ProgressionState.FAILED -> {
                // Should not happen during backfill, but handle it
                previousSessionSets
            }
        }

        return Pair(expectedSets, progressionState)
    } catch (e: Exception) {
        Log.e("BackfillProgression", "Error calculating expected sets", e)
        return Pair(null, null)
    }
}

private fun computeProgressionState(
    exerciseInfo: ExerciseInfo?,
    workoutHistoryDate: LocalDate?
): ProgressionState {
    val fails = exerciseInfo?.sessionFailedCounter?.toInt() ?: 0
    val lastWasDeload = exerciseInfo?.lastSessionWasDeload ?: false

    // For backfill, we use the date from the workout history if available
    val today = workoutHistoryDate ?: LocalDate.now()

    var weeklyCount = 0
    exerciseInfo?.weeklyCompletionUpdateDate?.let { lastUpdate ->
        val startOfThisWeek = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
        val startOfLastUpdateWeek = lastUpdate.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
        if (startOfThisWeek.isEqual(startOfLastUpdateWeek)) {
            weeklyCount = exerciseInfo.timesCompletedInAWeek
        }
    }

    val shouldDeload = false // temporarily disable deload: (fails >= 2) && !lastWasDeload
    val shouldRetry = !lastWasDeload && (fails >= 1 || weeklyCount > 1)

    return when {
        shouldDeload -> ProgressionState.DELOAD
        shouldRetry -> ProgressionState.RETRY
        else -> ProgressionState.PROGRESS
    }
}

private suspend fun updateExerciseInfoState(
    exerciseId: UUID,
    currentSession: List<SetHistory>,
    executedSets: List<SimpleSet>,
    progressionState: ProgressionState?,
    vsExpected: Ternary,
    exerciseInfoBefore: ExerciseInfo?,
    exerciseInfoStateMap: MutableMap<UUID, ExerciseInfo>,
    workoutHistoryDate: LocalDate
) {
    try {
        val today = workoutHistoryDate

        // Calculate weekly count
        var weeklyCount = 0
        if (exerciseInfoBefore != null) {
            val lastUpdate = exerciseInfoBefore.weeklyCompletionUpdateDate
            if (lastUpdate != null) {
                val startOfThisWeek = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
                val startOfLastUpdateWeek = lastUpdate.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
                if (startOfThisWeek.isEqual(startOfLastUpdateWeek)) {
                    weeklyCount = exerciseInfoBefore.timesCompletedInAWeek
                }
            }
        }
        weeklyCount++

        val isDeloadSession = progressionState == ProgressionState.DELOAD

        val updatedInfo = if (exerciseInfoBefore == null) {
            // First session for this exercise
            ExerciseInfo(
                id = exerciseId,
                bestSession = currentSession,
                lastSuccessfulSession = currentSession,
                successfulSessionCounter = 1u,
                sessionFailedCounter = 0u,
                timesCompletedInAWeek = weeklyCount,
                weeklyCompletionUpdateDate = today,
                lastSessionWasDeload = false
            )
        } else {
            var info = exerciseInfoBefore.copy(version = exerciseInfoBefore.version + 1u)

            if (isDeloadSession) {
                info = info.copy(
                    sessionFailedCounter = 0u,
                    successfulSessionCounter = 0u,
                    lastSessionWasDeload = true
                )
            } else {
                info = info.copy(lastSessionWasDeload = false)

                // Convert best session to SimpleSet list for comparison
                val bestSessionSets = info.bestSession.mapNotNull { setHistory ->
                    when (val setData = setHistory.setData) {
                        is WeightSetData -> {
                            if (setData.subCategory == SetSubCategory.RestPauseSet) return@mapNotNull null
                            SimpleSet(setData.getWeight(), setData.actualReps)
                        }
                        is BodyWeightSetData -> {
                            if (setData.subCategory == SetSubCategory.RestPauseSet) return@mapNotNull null
                            SimpleSet(setData.getWeight(), setData.actualReps)
                        }
                        else -> null
                    }
                }

                // Check if current session is better than best session
                val vsBest = compareSetListsUnordered(executedSets, bestSessionSets)
                if (vsBest == Ternary.ABOVE) {
                    info = info.copy(bestSession = currentSession)
                }

                if (progressionState != null) {
                    if (progressionState == ProgressionState.PROGRESS) {
                        // Success if executed sets are ABOVE or EQUAL to expected sets
                        val isSuccess = vsExpected == Ternary.ABOVE || vsExpected == Ternary.EQUAL

                        info = if (isSuccess) {
                            info.copy(
                                lastSuccessfulSession = currentSession,
                                successfulSessionCounter = info.successfulSessionCounter.inc(),
                                sessionFailedCounter = 0u
                            )
                        } else {
                            info.copy(
                                successfulSessionCounter = 0u,
                                sessionFailedCounter = info.sessionFailedCounter.inc()
                            )
                        }
                    } else {
                        // ProgressionState.RETRY as DELOAD was already handled
                        when (vsExpected) {
                            Ternary.ABOVE -> {
                                // Exceeded retry target - success
                                info = info.copy(
                                    lastSuccessfulSession = currentSession,
                                    successfulSessionCounter = info.successfulSessionCounter.inc(),
                                    sessionFailedCounter = 0u
                                )
                            }
                            Ternary.EQUAL -> {
                                // Met retry target exactly - complete retry, reset counters
                                info = info.copy(
                                    lastSuccessfulSession = currentSession,
                                    successfulSessionCounter = 0u,
                                    sessionFailedCounter = 0u
                                )
                            }
                            Ternary.BELOW, Ternary.MIXED -> {
                                // Below retry target - session failed, don't update counters
                                // Counters remain unchanged (will be incremented elsewhere if needed)
                            }
                        }
                    }
                } else {
                    // No progression state - compare against last successful session
                    val lastSessionSets = info.lastSuccessfulSession.mapNotNull { setHistory ->
                        when (val setData = setHistory.setData) {
                            is WeightSetData -> {
                                if (setData.subCategory == SetSubCategory.RestPauseSet) return@mapNotNull null
                                SimpleSet(setData.getWeight(), setData.actualReps)
                            }
                            is BodyWeightSetData -> {
                                if (setData.subCategory == SetSubCategory.RestPauseSet) return@mapNotNull null
                                SimpleSet(setData.getWeight(), setData.actualReps)
                            }
                            else -> null
                        }
                    }

                    val vsLast = compareSetListsUnordered(executedSets, lastSessionSets)
                    val isSuccess = vsLast == Ternary.ABOVE || vsLast == Ternary.EQUAL

                    info = if (isSuccess) {
                        info.copy(
                            lastSuccessfulSession = currentSession,
                            successfulSessionCounter = info.successfulSessionCounter.inc(),
                            sessionFailedCounter = 0u
                        )
                    } else {
                        info.copy(
                            successfulSessionCounter = 0u,
                            sessionFailedCounter = info.sessionFailedCounter.inc()
                        )
                    }
                }
            }

            info.copy(
                timesCompletedInAWeek = weeklyCount,
                weeklyCompletionUpdateDate = today
            )
        }

        exerciseInfoStateMap[exerciseId] = updatedInfo
    } catch (e: Exception) {
        Log.e("BackfillProgression", "Error updating ExerciseInfo state", e)
    }
}

object Spacing {
    val xs = 6.dp
    val sm = 8.dp
    val md = 12.dp
    val lg = 16.dp
    val xl = 24.dp
}