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
private val backupFileWriteMutex = Mutex()

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
 * Reads a JSON file from Downloads folder using MediaStore.
 * Returns the file content as a string, or null if not found.
 */
suspend fun readJsonFromDownloadsFolder(context: Context, fileName: String): String? {
    return withContext(Dispatchers.IO) {
        try {
            val resolver = context.contentResolver
            val projection = arrayOf(
                MediaStore.Downloads._ID,
                MediaStore.Downloads.DISPLAY_NAME
            )
            val selection = "${MediaStore.Downloads.DISPLAY_NAME} = ?"
            val selectionArgs = arrayOf(fileName)
            
            resolver.query(
                MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                projection,
                selection,
                selectionArgs,
                null
            )?.use { cursor ->
                if (cursor.moveToFirst()) {
                    val idIndex = cursor.getColumnIndexOrThrow(MediaStore.Downloads._ID)
                    val id = cursor.getLong(idIndex)
                    val uri = ContentUris.withAppendedId(
                        MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                        id
                    )
                    
                    resolver.openInputStream(uri)?.use { inputStream ->
                        inputStream.bufferedReader().use { reader ->
                            reader.readText()
                        }
                    }
                } else {
                    null
                }
            }
        } catch (e: Exception) {
            Log.e("Utils", "Error reading file from Downloads folder: $fileName", e)
            null
        }
    }
}

/**
 * Helper function to find a file URI in Downloads folder.
 * Returns the URI if found, null otherwise.
 */
private suspend fun findFileInDownloadsFolder(context: Context, fileName: String): android.net.Uri? {
    return withContext(Dispatchers.IO) {
        try {
            val resolver = context.contentResolver
            val projection = arrayOf(MediaStore.Downloads._ID)
            val selection = "${MediaStore.Downloads.DISPLAY_NAME} = ?"
            val selectionArgs = arrayOf(fileName)
            
            resolver.query(
                MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                projection,
                selection,
                selectionArgs,
                null
            )?.use { cursor ->
                if (cursor.moveToFirst()) {
                    val idIndex = cursor.getColumnIndexOrThrow(MediaStore.Downloads._ID)
                    val id = cursor.getLong(idIndex)
                    ContentUris.withAppendedId(
                        MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                        id
                    )
                } else {
                    null
                }
            }
        } catch (e: Exception) {
            Log.e("Utils", "Error finding file in Downloads folder: $fileName", e)
            null
        }
    }
}

/**
 * Finds all files with the given name in Downloads folder and returns their URIs.
 * Used to clean up duplicate backup files.
 */
private suspend fun findAllFilesInDownloadsFolder(context: Context, fileName: String): List<android.net.Uri> {
    return withContext(Dispatchers.IO) {
        try {
            val resolver = context.contentResolver
            val projection = arrayOf(MediaStore.Downloads._ID, MediaStore.Downloads.DISPLAY_NAME)
            val selection = "${MediaStore.Downloads.DISPLAY_NAME} = ?"
            val selectionArgs = arrayOf(fileName)
            
            val uris = mutableListOf<android.net.Uri>()
            resolver.query(
                MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                projection,
                selection,
                selectionArgs,
                null
            )?.use { cursor ->
                val idIndex = cursor.getColumnIndexOrThrow(MediaStore.Downloads._ID)
                val nameIndex = cursor.getColumnIndexOrThrow(MediaStore.Downloads.DISPLAY_NAME)
                while (cursor.moveToNext()) {
                    val id = cursor.getLong(idIndex)
                    val name = cursor.getString(nameIndex)
                    // Double-check the name matches (MediaStore might have variations)
                    if (name == fileName) {
                        uris.add(
                            ContentUris.withAppendedId(
                                MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                                id
                            )
                        )
                    }
                }
            }
            uris
        } catch (e: Exception) {
            Log.e("Utils", "Error finding all files in Downloads folder: $fileName", e)
            emptyList()
        }
    }
}

private data class BackupFileEntry(
    val uri: android.net.Uri,
    val name: String,
    val dateModified: Long
)

private fun matchesBackupFileName(name: String, exactFileName: String): Boolean {
    val baseName = exactFileName.removeSuffix(".json")
    val escapedBaseName = Regex.escape(baseName)
    val pattern = Regex(
        "^$escapedBaseName(?:\\.json(?:\\s*\\(\\d+\\))?|\\s*\\(\\d+\\)\\.json)$",
        RegexOption.IGNORE_CASE
    )
    return pattern.matches(name)
}

private fun deleteBackupFile(context: Context, uri: android.net.Uri): Boolean {
    return context.contentResolver.delete(uri, null, null) > 0
}

/**
 * Finds all backup files that match the automatic backup pattern.
 * This includes exact matches and files that might have been created with variations.
 * Returns a list of URIs with their display names for content comparison.
 */
private suspend fun findAllBackupFilesInDownloadsFolder(context: Context, exactFileName: String): List<BackupFileEntry> {
    return withContext(Dispatchers.IO) {
        try {
            val resolver = context.contentResolver
            val projection = arrayOf(
                MediaStore.MediaColumns._ID,
                MediaStore.MediaColumns.DISPLAY_NAME,
                MediaStore.MediaColumns.DATE_MODIFIED,
                MediaStore.MediaColumns.RELATIVE_PATH
            )

            fun queryCollection(
                collectionUri: android.net.Uri,
                limitToDownloads: Boolean,
                restrictToOwner: Boolean
            ): List<BackupFileEntry> {
                val files = mutableListOf<BackupFileEntry>()
                val baseSelectionParts = mutableListOf<String>()
                val baseSelectionArgs = mutableListOf<String>()

                if (restrictToOwner && android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.Q) {
                    baseSelectionParts.add("${MediaStore.MediaColumns.OWNER_PACKAGE_NAME} = ?")
                    baseSelectionArgs.add(context.packageName)
                }

                if (limitToDownloads) {
                    baseSelectionParts.add("${MediaStore.MediaColumns.RELATIVE_PATH} LIKE ?")
                    baseSelectionArgs.add("${Environment.DIRECTORY_DOWNLOADS}/%")
                }

                val exactSelectionParts = baseSelectionParts.toMutableList().apply {
                    add("${MediaStore.MediaColumns.DISPLAY_NAME} = ?")
                }
                val exactSelection = exactSelectionParts.joinToString(" AND ")
                val exactSelectionArgs = (baseSelectionArgs + exactFileName).toTypedArray()

                resolver.query(
                    collectionUri,
                    projection,
                    exactSelection,
                    exactSelectionArgs,
                    null
                )?.use { cursor ->
                    val idIndex = cursor.getColumnIndexOrThrow(MediaStore.MediaColumns._ID)
                    val nameIndex = cursor.getColumnIndexOrThrow(MediaStore.MediaColumns.DISPLAY_NAME)
                    val dateIndex = cursor.getColumnIndexOrThrow(MediaStore.MediaColumns.DATE_MODIFIED)
                    while (cursor.moveToNext()) {
                        val id = cursor.getLong(idIndex)
                        val name = cursor.getString(nameIndex)
                        val dateModified = cursor.getLong(dateIndex)
                        if (name == exactFileName) {
                            files.add(
                                BackupFileEntry(
                                    ContentUris.withAppendedId(collectionUri, id),
                                    name,
                                    dateModified
                                )
                            )
                        }
                    }
                }

                val allSelection = if (baseSelectionParts.isEmpty()) {
                    null
                } else {
                    baseSelectionParts.joinToString(" AND ")
                }
                val allSelectionArgs = if (baseSelectionArgs.isEmpty()) {
                    null
                } else {
                    baseSelectionArgs.toTypedArray()
                }

                val allFiles = mutableListOf<BackupFileEntry>()
                resolver.query(
                    collectionUri,
                    projection,
                    allSelection,
                    allSelectionArgs,
                    "${MediaStore.MediaColumns.DATE_MODIFIED} DESC"
                )?.use { cursor ->
                    val idIndex = cursor.getColumnIndexOrThrow(MediaStore.MediaColumns._ID)
                    val nameIndex = cursor.getColumnIndexOrThrow(MediaStore.MediaColumns.DISPLAY_NAME)
                    val dateIndex = cursor.getColumnIndexOrThrow(MediaStore.MediaColumns.DATE_MODIFIED)
                    while (cursor.moveToNext()) {
                        val id = cursor.getLong(idIndex)
                        val name = cursor.getString(nameIndex)
                        val dateModified = cursor.getLong(dateIndex)
                        if (matchesBackupFileName(name, exactFileName)) {
                            allFiles.add(
                                BackupFileEntry(
                                    ContentUris.withAppendedId(collectionUri, id),
                                    name,
                                    dateModified
                                )
                            )
                        }
                    }
                }

                val existingUris = files.map { it.uri }.toSet()
                for (file in allFiles) {
                    if (file.uri !in existingUris) {
                        files.add(file)
                    }
                }

                return files
            }

            val downloadsFiles = queryCollection(
                MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                limitToDownloads = false,
                restrictToOwner = true
            )

            val downloadsFallbackFiles = if (downloadsFiles.isEmpty()) {
                Log.d(
                    "Utils",
                    "No backup files found in MediaStore.Downloads for owner; retrying without owner filter"
                )
                queryCollection(
                    MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                    limitToDownloads = false,
                    restrictToOwner = false
                )
            } else {
                emptyList()
            }

            val resolvedDownloadsFiles = if (downloadsFiles.isEmpty()) {
                downloadsFallbackFiles
            } else {
                downloadsFiles
            }

            val filesCollectionFiles = if (resolvedDownloadsFiles.isEmpty()) {
                Log.d(
                    "Utils",
                    "No backup files found in MediaStore.Downloads; checking MediaStore.Files for ${Environment.DIRECTORY_DOWNLOADS}"
                )
                queryCollection(
                    MediaStore.Files.getContentUri(MediaStore.VOLUME_EXTERNAL),
                    limitToDownloads = true,
                    restrictToOwner = false
                )
            } else {
                emptyList()
            }

            val files = (resolvedDownloadsFiles + filesCollectionFiles).distinctBy { it.uri }

            files.sortedWith(
                compareBy<BackupFileEntry> { it.name != exactFileName }
                    .thenByDescending { it.dateModified }
            )
        } catch (e: Exception) {
            Log.e("Utils", "Error finding all backup files in Downloads folder: $exactFileName", e)
            emptyList()
        }
    }
}

/**
 * Reads the content of a file from Downloads folder.
 * Returns null if the file doesn't exist or can't be read.
 */
private suspend fun readFileContentFromDownloadsFolder(context: Context, uri: android.net.Uri): String? {
    return withContext(Dispatchers.IO) {
        try {
            context.contentResolver.openInputStream(uri)?.use { inputStream ->
                inputStream.bufferedReader().readText()
            }
        } catch (e: Exception) {
            Log.e("Utils", "Error reading file content from Downloads folder", e)
            null
        }
    }
}

/**
 * Finds all backup files matching both automatic and manual backup patterns.
 * - Automatic backups: workout_store_backup.json (and variations)
 * - Manual backups: workout_backup_*.json
 */
private suspend fun findAllBackupFiles(context: Context): List<BackupFileEntry> {
    return withContext(Dispatchers.IO) {
        try {
            val automaticBackups = findAllBackupFilesInDownloadsFolder(context, "workout_store_backup.json")
            
            // Find manual backups (workout_backup_*.json pattern)
            val manualBackups = findManualBackupFiles(context)
            
            // Combine and deduplicate by URI
            val allBackups = (automaticBackups + manualBackups).distinctBy { it.uri }
            
            Log.d("Utils", "Found ${allBackups.size} total backup files (${automaticBackups.size} automatic, ${manualBackups.size} manual)")
            allBackups
        } catch (e: Exception) {
            Log.e("Utils", "Error finding all backup files", e)
            emptyList()
        }
    }
}

/**
 * Finds manual backup files matching the pattern workout_backup_*.json
 */
private suspend fun findManualBackupFiles(context: Context): List<BackupFileEntry> {
    return withContext(Dispatchers.IO) {
        try {
            val resolver = context.contentResolver
            val projection = arrayOf(
                MediaStore.MediaColumns._ID,
                MediaStore.MediaColumns.DISPLAY_NAME,
                MediaStore.MediaColumns.DATE_MODIFIED,
                MediaStore.MediaColumns.RELATIVE_PATH
            )
            
            val manualBackupPattern = Regex("^workout_backup_.*\\.json$", RegexOption.IGNORE_CASE)
            val files = mutableListOf<BackupFileEntry>()
            
            fun queryCollection(
                collectionUri: android.net.Uri,
                limitToDownloads: Boolean,
                restrictToOwner: Boolean
            ): List<BackupFileEntry> {
                val foundFiles = mutableListOf<BackupFileEntry>()
                val baseSelectionParts = mutableListOf<String>()
                val baseSelectionArgs = mutableListOf<String>()
                
                if (restrictToOwner && android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.Q) {
                    baseSelectionParts.add("${MediaStore.MediaColumns.OWNER_PACKAGE_NAME} = ?")
                    baseSelectionArgs.add(context.packageName)
                }
                
                if (limitToDownloads) {
                    baseSelectionParts.add("${MediaStore.MediaColumns.RELATIVE_PATH} LIKE ?")
                    baseSelectionArgs.add("${Environment.DIRECTORY_DOWNLOADS}/%")
                }
                
                val allSelection = if (baseSelectionParts.isEmpty()) {
                    null
                } else {
                    baseSelectionParts.joinToString(" AND ")
                }
                val allSelectionArgs = if (baseSelectionArgs.isEmpty()) {
                    null
                } else {
                    baseSelectionArgs.toTypedArray()
                }
                
                resolver.query(
                    collectionUri,
                    projection,
                    allSelection,
                    allSelectionArgs,
                    "${MediaStore.MediaColumns.DATE_MODIFIED} DESC"
                )?.use { cursor ->
                    val idIndex = cursor.getColumnIndexOrThrow(MediaStore.MediaColumns._ID)
                    val nameIndex = cursor.getColumnIndexOrThrow(MediaStore.MediaColumns.DISPLAY_NAME)
                    val dateIndex = cursor.getColumnIndexOrThrow(MediaStore.MediaColumns.DATE_MODIFIED)
                    while (cursor.moveToNext()) {
                        val id = cursor.getLong(idIndex)
                        val name = cursor.getString(nameIndex)
                        val dateModified = cursor.getLong(dateIndex)
                        if (manualBackupPattern.matches(name)) {
                            foundFiles.add(
                                BackupFileEntry(
                                    ContentUris.withAppendedId(collectionUri, id),
                                    name,
                                    dateModified
                                )
                            )
                        }
                    }
                }
                
                return foundFiles
            }
            
            // Try Downloads first
            val downloadsFiles = queryCollection(
                MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                limitToDownloads = false,
                restrictToOwner = true
            )
            
            val downloadsFallbackFiles = if (downloadsFiles.isEmpty()) {
                queryCollection(
                    MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                    limitToDownloads = false,
                    restrictToOwner = false
                )
            } else {
                emptyList()
            }
            
            val resolvedDownloadsFiles = if (downloadsFiles.isEmpty()) {
                downloadsFallbackFiles
            } else {
                downloadsFiles
            }
            
            val filesCollectionFiles = if (resolvedDownloadsFiles.isEmpty()) {
                queryCollection(
                    MediaStore.Files.getContentUri(MediaStore.VOLUME_EXTERNAL),
                    limitToDownloads = true,
                    restrictToOwner = false
                )
            } else {
                emptyList()
            }
            
            (resolvedDownloadsFiles + filesCollectionFiles).distinctBy { it.uri }
        } catch (e: Exception) {
            Log.e("Utils", "Error finding manual backup files", e)
            emptyList()
        }
    }
}

/**
 * Reads file bytes from a URI.
 * Returns null if the file can't be read.
 */
private suspend fun readFileBytes(context: Context, uri: android.net.Uri): ByteArray? {
    return withContext(Dispatchers.IO) {
        try {
            context.contentResolver.openInputStream(uri)?.use { inputStream ->
                inputStream.readBytes()
            }
        } catch (e: Exception) {
            Log.e("Utils", "Error reading file bytes from URI: $uri", e)
            null
        }
    }
}

/**
 * Calculates SHA-256 hash of byte array.
 * Returns hex string representation of the hash.
 */
private fun calculateContentHash(bytes: ByteArray): String {
    val digest = MessageDigest.getInstance("SHA-256")
    val hashBytes = digest.digest(bytes)
    return hashBytes.joinToString("") { "%02x".format(it) }
}

/**
 * Creates an AppBackup from the current workout store and database state.
 * This is a helper function that extracts the backup creation logic.
 */
suspend fun createAppBackup(workoutStore: WorkoutStore, db: AppDatabase): AppBackup? {
    return withContext(Dispatchers.IO + NonCancellable) {
        try {
            // Get all DAOs
            val workoutHistoryDao = db.workoutHistoryDao()
            val setHistoryDao = db.setHistoryDao()
            val exerciseInfoDao = db.exerciseInfoDao()
            val workoutScheduleDao = db.workoutScheduleDao()
            val workoutRecordDao = db.workoutRecordDao()
            val exerciseSessionProgressionDao = db.exerciseSessionProgressionDao()
            val errorLogDao = db.errorLogDao()

            // Get all workout histories from DB (do not filter by current workout store IDs).
            // A workout can be replaced/deleted from the store while its historical sessions still exist.
            // Filtering by current workout IDs would silently drop valid historical data from backups.
            val validWorkoutHistories = workoutHistoryDao.getAllWorkoutHistories()
            val validWorkoutHistoryIds = validWorkoutHistories
                .map { it.id }
                .toHashSet()

            // Filter set histories to match the histories included in the backup
            val setHistories = setHistoryDao.getAllSetHistories().filter { setHistory ->
                setHistory.workoutHistoryId != null &&
                    setHistory.workoutHistoryId in validWorkoutHistoryIds
            }

            // Get all exercise infos, workout schedules, workout records
            val exerciseInfos = exerciseInfoDao.getAllExerciseInfos()
            val workoutSchedules = workoutScheduleDao.getAllSchedules()
            val workoutRecords = workoutRecordDao.getAll()

            // Filter exercise session progressions to match valid workout histories
            val exerciseSessionProgressions = exerciseSessionProgressionDao.getAllExerciseSessionProgressions().filter { progression ->
                progression.workoutHistoryId in validWorkoutHistoryIds
            }

            // Get all error logs
            val errorLogs = errorLogDao.getAllErrorLogs().first()

            // Create AppBackup
            val appBackup = AppBackup(
                workoutStore,
                validWorkoutHistories,
                setHistories,
                exerciseInfos,
                workoutSchedules,
                workoutRecords,
                exerciseSessionProgressions,
                errorLogs.takeIf { it.isNotEmpty() }
            )

            // Check if AppBackup has any data before returning
            val hasData = appBackup.WorkoutStore.workouts.isNotEmpty() ||
                    appBackup.WorkoutHistories.isNotEmpty() ||
                    appBackup.SetHistories.isNotEmpty() ||
                    appBackup.ExerciseInfos.isNotEmpty() ||
                    appBackup.WorkoutSchedules.isNotEmpty() ||
                    appBackup.WorkoutRecords.isNotEmpty() ||
                    appBackup.ExerciseSessionProgressions.isNotEmpty() ||
                    run {
                        val errorLogs = appBackup.ErrorLogs
                        errorLogs != null && errorLogs.isNotEmpty()
                    }

            if (!hasData) {
                Log.d("Utils", "Skipping backup - no data to save")
                return@withContext null
            }

            appBackup
        } catch (e: Exception) {
            when (e) {
                is CancellationException -> {
                    Log.e("Utils", "Error creating AppBackup: Job was cancelled. " +
                            "Message: ${e.message}, " +
                            "Cause: ${e.cause?.javaClass?.simpleName ?: "none"}, " +
                            "Stack trace:\n${Log.getStackTraceString(e)}", e)
                }
                else -> {
                    Log.e("Utils", "Error creating AppBackup: ${e.javaClass.simpleName}. " +
                            "Message: ${e.message}, " +
                            "Cause: ${e.cause?.javaClass?.simpleName ?: "none"}, " +
                            "Stack trace:\n${Log.getStackTraceString(e)}", e)
                }
            }
            null
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
        saveWorkoutStoreToExternalStorage(context, workoutStore, db)
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
        saveWorkoutStoreToExternalStorage(context, workoutStore, db)
    }
}

/**
 * Cleans up duplicate backup files in Downloads folder.
 * This should be called once at app startup to remove any duplicate files that may have been created.
 * Keeps only the file with the exact name "workout_store_backup.json" if it exists, or the most recent one.
 */
suspend fun cleanupDuplicateBackupFiles(context: Context) {
    withContext(Dispatchers.IO) {
        try {
            fun showCleanupToast(message: String) {
                android.os.Handler(android.os.Looper.getMainLooper()).post {
                    Toast.makeText(context, message, Toast.LENGTH_SHORT).show()
                }
            }

            val downloadsPath = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS).absolutePath
            val folderLabel = "${Environment.DIRECTORY_DOWNLOADS} (MediaStore): $downloadsPath"
            val backupFileName = "workout_store_backup.json"
            val resolver = context.contentResolver

            Log.d("Utils", "Backup cleanup started in $folderLabel")
            
            // Find all existing files matching the backup pattern
            val allBackupFiles = findAllBackupFilesInDownloadsFolder(context, backupFileName)
            
            if (allBackupFiles.isEmpty()) {
                Log.d("Utils", "No backup files found to clean up")
                return@withContext
            }
            
            if (allBackupFiles.size == 1) {
                Log.d("Utils", "Only one backup file found, no cleanup needed")
                return@withContext
            }
            
            Log.d("Utils", "Found ${allBackupFiles.size} backup files, cleaning up duplicates")
            
            // Find the file with exact name match, or use the most recent one
            val exactMatch = allBackupFiles.firstOrNull { it.name == backupFileName }
            val targetFile = exactMatch ?: allBackupFiles.maxByOrNull { it.dateModified } ?: allBackupFiles.first()
            val targetUri = targetFile.uri
            
            // Delete all other files
            var deletedCount = 0
            for (file in allBackupFiles) {
                if (file.uri == targetUri) continue
                
                // Optionally check if content matches before deleting
                // (if content differs, we might want to keep it, but for cleanup we'll delete duplicates)
                try {
                    val deleted = deleteBackupFile(context, file.uri)
                    if (deleted) {
                        deletedCount++
                        Log.d("Utils", "Deleted duplicate backup file: ${file.name}")
                    } else {
                        Log.w("Utils", "No rows deleted for duplicate backup file: ${file.name}")
                    }
                } catch (e: Exception) {
                    Log.w("Utils", "Failed to delete duplicate backup file: ${file.name}", e)
                }
            }
            
            Log.d("Utils", "Cleanup complete: deleted $deletedCount duplicate backup file(s), kept: ${targetFile.name}")
            if (deletedCount > 0) {
                showCleanupToast("Deleted $deletedCount duplicate backup file(s)")
            }
        } catch (e: Exception) {
            Log.e("Utils", "Error cleaning up duplicate backup files", e)
        }
    }
}

/**
 * Cleans up duplicate backup files by comparing content hashes.
 * Finds all backup files (both automatic and manual patterns), groups them by content hash,
 * and keeps only the most recent file from each unique content group.
 * This ensures that files with identical content are deduplicated while preserving unique versions.
 */
suspend fun cleanupDuplicateBackupFilesByContent(context: Context) {
    withContext(Dispatchers.IO) {
        try {
            fun showCleanupToast(message: String) {
                android.os.Handler(android.os.Looper.getMainLooper()).post {
                    Toast.makeText(context, message, Toast.LENGTH_SHORT).show()
                }
            }

            Log.d("Utils", "Content-based backup cleanup started")
            
            // Find all backup files (both automatic and manual patterns)
            val allBackupFiles = findAllBackupFiles(context)
            
            if (allBackupFiles.isEmpty()) {
                Log.d("Utils", "No backup files found to clean up")
                return@withContext
            }
            
            if (allBackupFiles.size == 1) {
                Log.d("Utils", "Only one backup file found, no cleanup needed")
                return@withContext
            }
            
            Log.d("Utils", "Found ${allBackupFiles.size} backup files, analyzing content for duplicates")
            
            // Read bytes and calculate hash for each file
            val fileHashes = mutableMapOf<String, MutableList<BackupFileEntry>>()
            
            for (file in allBackupFiles) {
                try {
                    val bytes = readFileBytes(context, file.uri)
                    if (bytes == null) {
                        Log.w("Utils", "Failed to read bytes from file: ${file.name}, skipping")
                        continue
                    }
                    
                    // Skip empty files
                    if (bytes.isEmpty()) {
                        Log.w("Utils", "File is empty: ${file.name}, skipping")
                        continue
                    }
                    
                    val hash = calculateContentHash(bytes)
                    fileHashes.getOrPut(hash) { mutableListOf() }.add(file)
                    Log.d("Utils", "File: ${file.name}, hash: ${hash.take(16)}..., size: ${bytes.size} bytes")
                } catch (e: Exception) {
                    Log.w("Utils", "Error processing file ${file.name}, skipping", e)
                }
            }
            
            // Group files by hash and identify duplicates
            var totalDuplicates = 0
            var deletedCount = 0
            
            for ((hash, files) in fileHashes) {
                if (files.size > 1) {
                    // Multiple files with same content - keep only the most recent
                    val sortedFiles = files.sortedByDescending { it.dateModified }
                    val fileToKeep = sortedFiles.first()
                    val duplicatesToDelete = sortedFiles.drop(1)
                    
                    totalDuplicates += duplicatesToDelete.size
                    Log.d("Utils", "Found ${duplicatesToDelete.size} duplicate(s) of ${fileToKeep.name} (hash: ${hash.take(16)}...), keeping most recent: ${fileToKeep.name}")
                    
                    for (duplicate in duplicatesToDelete) {
                        try {
                            val deleted = deleteBackupFile(context, duplicate.uri)
                            if (deleted) {
                                deletedCount++
                                Log.d("Utils", "Deleted duplicate backup file: ${duplicate.name} (same content as ${fileToKeep.name})")
                            } else {
                                Log.w("Utils", "No rows deleted for duplicate backup file: ${duplicate.name}")
                            }
                        } catch (e: Exception) {
                            Log.w("Utils", "Failed to delete duplicate backup file: ${duplicate.name}", e)
                        }
                    }
                } else {
                    // Single file with this content - keep it
                    Log.d("Utils", "File ${files.first().name} has unique content (hash: ${hash.take(16)}...), keeping")
                }
            }
            
            val uniqueFiles = fileHashes.size
            Log.d("Utils", "Cleanup complete: $uniqueFiles unique content(s), $totalDuplicates duplicate(s) found, $deletedCount deleted, ${allBackupFiles.size - deletedCount} kept")
            
            if (deletedCount > 0) {
                showCleanupToast("Deleted $deletedCount duplicate backup file(s), kept $uniqueFiles unique version(s)")
            } else if (totalDuplicates == 0) {
                Log.d("Utils", "No duplicates found - all backup files have unique content")
            }
        } catch (e: Exception) {
            Log.e("Utils", "Error cleaning up duplicate backup files by content", e)
        }
    }
}

/**
 * Saves workout store backup to Downloads folder (persists after app uninstall).
 * Creates an AppBackup (including database data) and saves it to workout_store_backup.json.
 * This file can be used for recovery if the main workout_store.json gets corrupted.
 * Uses Downloads folder via MediaStore so the backup persists after uninstall and is accessible via file managers.
 */
suspend fun saveWorkoutStoreToExternalStorage(
    context: Context,
    workoutStore: WorkoutStore,
    db: AppDatabase
) {
    withContext(Dispatchers.IO + NonCancellable) {
        backupFileWriteMutex.withLock {
            try {
                val appBackup = createAppBackup(workoutStore, db)
                if (appBackup == null) {
                    Log.d("Utils", "No data to backup, skipping backup")
                    return@withContext
                }

                val jsonString = fromAppBackupToJSONPrettyPrint(appBackup)
                val backupFileName = "workout_store_backup.json"
                
                // Save to Downloads folder (persists after uninstall)
                val resolver = context.contentResolver
                val contentValues = ContentValues().apply {
                    put(MediaStore.MediaColumns.DISPLAY_NAME, backupFileName)
                    put(MediaStore.MediaColumns.MIME_TYPE, "application/json")
                    put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
                }

                // Find ALL backup files (including any duplicates that might exist)
                val allBackupFiles = findAllBackupFilesInDownloadsFolder(context, backupFileName)
                
                // Find the target file to use (exact match preferred, or most recent)
                val exactMatch = allBackupFiles.firstOrNull { it.name == backupFileName }
                val targetFile = exactMatch ?: allBackupFiles.maxByOrNull { it.dateModified }
                val targetUri = targetFile?.uri
                
                // Check if content has changed by comparing with target file
                var shouldSave = true
                if (targetUri != null) {
                    // Read existing content and compare
                    val existingContent = readFileContentFromDownloadsFolder(context, targetUri)
                    if (existingContent != null && existingContent == jsonString) {
                        Log.d("Utils", "Backup content unchanged, skipping save")
                        shouldSave = false
                        
                        // Still clean up any other duplicates
                        if (allBackupFiles.size > 1) {
                            cleanupDuplicateBackupFiles(context)
                        }
                    }
                }

                if (!shouldSave) {
                    return@withContext
                }

                val targetSaveUri = if (targetUri != null) {
                    if (targetFile?.name != backupFileName) {
                        try {
                            val renameValues = ContentValues().apply {
                                put(MediaStore.MediaColumns.DISPLAY_NAME, backupFileName)
                            }
                            resolver.update(targetUri, renameValues, null, null)
                        } catch (e: Exception) {
                            Log.w("Utils", "Failed to normalize backup file name", e)
                        }
                    }
                    targetUri
                } else {
                    try {
                        resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, contentValues)
                    } catch (e: Exception) {
                        Log.e("Utils", "Failed to create backup file", e)
                        null
                    }
                }

                targetSaveUri?.let { uri ->
                    try {
                        // Write the content
                        val wroteContent = resolver.openOutputStream(uri, "wt")?.use { outputStream ->
                            outputStream.write(jsonString.toByteArray())
                            outputStream.flush()
                            true
                        } ?: false
                        if (wroteContent) {
                            Log.d("Utils", "Backup saved to Downloads folder: $backupFileName")
                            
                            // Final cleanup after save to catch any duplicates that might have been created
                            kotlinx.coroutines.delay(200) // Give MediaStore time to index
                            cleanupDuplicateBackupFiles(context)
                        } else {
                            Log.e("Utils", "Failed to open output stream for backup file")
                        }
                    } catch (e: Exception) {
                        Log.e("Utils", "Error writing to backup file", e)
                        // Try to clean up the failed file
                        try {
                            resolver.delete(uri, null, null)
                        } catch (deleteException: Exception) {
                            Log.e("Utils", "Error cleaning up failed file", deleteException)
                        }
                    }
                } ?: run {
                    Log.e("Utils", "Failed to create backup file in Downloads folder")
                }
                
                // Also try to migrate old backup from external files dir (one-time migration)
                try {
                    val externalDir = context.getExternalFilesDir(null)
                    val oldBackupFile = externalDir?.let { java.io.File(it, backupFileName) }
                    oldBackupFile?.takeIf { it.exists() }?.delete()
                    Log.d("Utils", "Cleaned up old backup file from external files dir")
                } catch (e: Exception) {
                    // Ignore migration errors
                    Log.d("Utils", "Could not clean up old backup file", e)
                }
            } catch (e: Exception) {
                when (e) {
                    is CancellationException -> {
                        Log.e("Utils", "Error saving workout store to external storage: Job was cancelled. " +
                                "Message: ${e.message}, " +
                                "Cause: ${e.cause?.javaClass?.simpleName ?: "none"}, " +
                                "Stack trace:\n${Log.getStackTraceString(e)}", e)
                    }
                    else -> {
                        Log.e("Utils", "Error saving workout store to external storage: ${e.javaClass.simpleName}. " +
                                "Message: ${e.message}, " +
                                "Cause: ${e.cause?.javaClass?.simpleName ?: "none"}, " +
                                "Stack trace:\n${Log.getStackTraceString(e)}", e)
                    }
                }
            }
        }
    }
}

/**
 * Checks if an external backup file exists.
 * Checks both Downloads folder (new location) and external files dir (old location).
 * Note: This is a synchronous check, so it only checks the old location for performance.
 * For accurate results including Downloads folder, use loadExternalBackup() and check for null.
 */
fun hasExternalBackup(context: Context): Boolean {
    // Check old location (external files dir) synchronously
    val externalDir = context.getExternalFilesDir(null)
    val oldBackupFile = externalDir?.let { java.io.File(it, "workout_store_backup.json") }
    if (oldBackupFile?.exists() == true) {
        return true
    }
    
    // Downloads folder check requires async MediaStore query, so we can't do it synchronously
    // The loadExternalBackup function will check both locations properly
    return false
}

/**
 * Loads the external backup file and parses it as AppBackup.
 * First tries Downloads folder (new location), then falls back to external files dir (old location).
 * Returns null if the file doesn't exist or parsing fails.
 */
suspend fun loadExternalBackup(context: Context): AppBackup? {
    return withContext(Dispatchers.IO) {
        try {
            val backupFileName = "workout_store_backup.json"
            
            // First try Downloads folder (new location - persists after uninstall)
            val jsonString = readJsonFromDownloadsFolder(context, backupFileName)
            if (jsonString != null) {
                try {
                    val appBackup = fromJSONtoAppBackup(jsonString)
                    Log.d("Utils", "Backup loaded successfully from Downloads folder")
                    return@withContext appBackup
                } catch (e: Exception) {
                    when (e) {
                        is CancellationException -> {
                            Log.e("Utils", "Error parsing backup from Downloads folder: Job was cancelled. " +
                                    "Message: ${e.message}, " +
                                    "Cause: ${e.cause?.javaClass?.simpleName ?: "none"}, " +
                                    "Stack trace:\n${Log.getStackTraceString(e)}", e)
                        }
                        else -> {
                            Log.e("Utils", "Error parsing backup from Downloads folder: ${e.javaClass.simpleName}. " +
                                    "Message: ${e.message}, " +
                                    "Cause: ${e.cause?.javaClass?.simpleName ?: "none"}, " +
                                    "Stack trace:\n${Log.getStackTraceString(e)}", e)
                        }
                    }
                    // Continue to fallback location
                }
            }
            
            // Fallback to old location (external files dir) for backward compatibility
            val externalDir = context.getExternalFilesDir(null)
            if (externalDir == null) {
                Log.d("Utils", "External storage not available and no backup in Downloads")
                return@withContext null
            }
            val backupFile = java.io.File(externalDir, backupFileName)
            if (!backupFile.exists()) {
                Log.d("Utils", "Backup file does not exist in either location")
                return@withContext null
            }

            val oldJsonString = backupFile.readText()
            val appBackup = fromJSONtoAppBackup(oldJsonString)
            Log.d("Utils", "Backup loaded successfully from old location (external files dir)")
            appBackup
        } catch (e: Exception) {
            when (e) {
                is CancellationException -> {
                    Log.e("Utils", "Error loading backup from external storage: Job was cancelled. " +
                            "Message: ${e.message}, " +
                            "Cause: ${e.cause?.javaClass?.simpleName ?: "none"}, " +
                            "Stack trace:\n${Log.getStackTraceString(e)}", e)
                }
                else -> {
                    Log.e("Utils", "Error loading backup from external storage: ${e.javaClass.simpleName}. " +
                            "Message: ${e.message}, " +
                            "Cause: ${e.cause?.javaClass?.simpleName ?: "none"}, " +
                            "Stack trace:\n${Log.getStackTraceString(e)}", e)
                }
            }
            null
        }
    }
}

/**
 * Loads the most recent valid backup from Downloads folder.
 * Scans both automatic and manual backup naming patterns, newest first.
 */
suspend fun loadLatestBackupFromDownloads(context: Context): AppBackup? {
    return withContext(Dispatchers.IO) {
        try {
            val backupFiles = findAllBackupFiles(context)
                .sortedByDescending { it.dateModified }
            if (backupFiles.isEmpty()) {
                return@withContext null
            }

            for (file in backupFiles) {
                val jsonString = readFileContentFromDownloadsFolder(context, file.uri) ?: continue
                try {
                    val appBackup = fromJSONtoAppBackup(jsonString)
                    Log.d("Utils", "Loaded latest backup from Downloads: ${file.name}")
                    return@withContext appBackup
                } catch (e: Exception) {
                    Log.w("Utils", "Skipping invalid backup file: ${file.name}", e)
                }
            }
            null
        } catch (e: Exception) {
            Log.e("Utils", "Error loading latest backup from Downloads", e)
            null
        }
    }
}

suspend fun saveWorkoutStoreToDownloads(context: Context, workoutStore: WorkoutStore, db: AppDatabase) {
    withContext(Dispatchers.IO) {
        try {
            val resolver = context.contentResolver

            // Get all DAOs
            val workoutHistoryDao = db.workoutHistoryDao()
            val setHistoryDao = db.setHistoryDao()
            val exerciseInfoDao = db.exerciseInfoDao()
            val workoutScheduleDao = db.workoutScheduleDao()
            val workoutRecordDao = db.workoutRecordDao()
            val exerciseSessionProgressionDao = db.exerciseSessionProgressionDao()
            val errorLogDao = db.errorLogDao()

            // Keep all workout histories from DB in export backup for the same reason as createAppBackup().
            val validWorkoutHistories = workoutHistoryDao.getAllWorkoutHistories()
            val validWorkoutHistoryIds = validWorkoutHistories
                .map { it.id }
                .toHashSet()

            // Filter set histories to match valid workout histories
            val setHistories = setHistoryDao.getAllSetHistories().filter { setHistory ->
                setHistory.workoutHistoryId != null &&
                    setHistory.workoutHistoryId in validWorkoutHistoryIds
            }

            // Get all exercise infos, workout schedules, workout records
            val exerciseInfos = exerciseInfoDao.getAllExerciseInfos()
            val workoutSchedules = workoutScheduleDao.getAllSchedules()
            val workoutRecords = workoutRecordDao.getAll()

            // Filter exercise session progressions to match valid workout histories
            val exerciseSessionProgressions = exerciseSessionProgressionDao.getAllExerciseSessionProgressions().filter { progression ->
                progression.workoutHistoryId in validWorkoutHistoryIds
            }

            // Get all error logs
            val errorLogs = errorLogDao.getAllErrorLogs().first()

            // Create AppBackup with the same structure as original manual backup
            val appBackup = AppBackup(
                workoutStore,
                validWorkoutHistories,
                setHistories,
                exerciseInfos,
                workoutSchedules,
                workoutRecords,
                exerciseSessionProgressions,
                errorLogs.takeIf { it.isNotEmpty() }
            )

            // Check if AppBackup has any data before saving
            val hasData = appBackup.WorkoutStore.workouts.isNotEmpty() ||
                    appBackup.WorkoutHistories.isNotEmpty() ||
                    appBackup.SetHistories.isNotEmpty() ||
                    appBackup.ExerciseInfos.isNotEmpty() ||
                    appBackup.WorkoutSchedules.isNotEmpty() ||
                    appBackup.WorkoutRecords.isNotEmpty() ||
                    appBackup.ExerciseSessionProgressions.isNotEmpty() ||
                    run {
                        val errorLogs = appBackup.ErrorLogs
                        errorLogs != null && errorLogs.isNotEmpty()
                    }

            if (!hasData) {
                Log.d("Utils", "Skipping backup - no data to save")
                return@withContext
            }

            val jsonString = fromAppBackupToJSONPrettyPrint(appBackup)

            // Helper function to try inserting a file with a given filename
            fun tryInsertFile(fileNameToTry: String): android.net.Uri? {
                val contentValues = ContentValues().apply {
                    put(MediaStore.MediaColumns.DISPLAY_NAME, fileNameToTry)
                    put(MediaStore.MediaColumns.MIME_TYPE, "application/json")
                    put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
                }

                return try {
                    resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, contentValues)
                } catch (e: IllegalStateException) {
                    // MediaStore couldn't create unique file, likely because file already exists
                    Log.w("Utils", "Failed to insert file with name $fileNameToTry: ${e.message}")
                    null
                } catch (e: Exception) {
                    Log.e("Utils", "Unexpected error inserting file with name $fileNameToTry", e)
                    null
                }
            }

            // Generate timestamp-based filename
            val sdf = java.text.SimpleDateFormat("yyyyMMdd_HHmmss", java.util.Locale.getDefault())
            val timestamp = sdf.format(java.util.Date())
            val fileName = "workout_store_$timestamp.json"

            // Try to insert file with timestamped name
            val uri = tryInsertFile(fileName)

            // Write the content if we successfully created the file
            if (uri != null) {
                try {
                    resolver.openOutputStream(uri)?.use { outputStream ->
                        outputStream.write(jsonString.toByteArray())
                        outputStream.flush()
                    } ?: run {
                        Log.e("Utils", "Failed to open output stream for backup file: $fileName")
                        // Clean up the failed file
                        try {
                            resolver.delete(uri, null, null)
                        } catch (deleteException: Exception) {
                            Log.e("Utils", "Error cleaning up failed file insert", deleteException)
                        }
                    }
                } catch (e: Exception) {
                    Log.e("Utils", "Error writing to backup file: $fileName", e)
                    // Try to clean up the failed insert
                    try {
                        resolver.delete(uri, null, null)
                    } catch (deleteException: Exception) {
                        Log.e("Utils", "Error cleaning up failed file insert", deleteException)
                    }
                }
            } else {
                Log.e("Utils", "Failed to create backup file - could not insert with filename: $fileName")
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

