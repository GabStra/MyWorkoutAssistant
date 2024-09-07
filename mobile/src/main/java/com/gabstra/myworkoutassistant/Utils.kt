package com.gabstra.myworkoutassistant

import android.content.ContentValues
import android.content.Context
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import android.widget.Toast
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.State
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import com.gabstra.myworkoutassistant.shared.AppBackup
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.adapters.LocalDateAdapter
import com.gabstra.myworkoutassistant.shared.adapters.SetAdapter
import com.gabstra.myworkoutassistant.shared.adapters.SetDataAdapter
import com.gabstra.myworkoutassistant.shared.adapters.WorkoutComponentAdapter
import com.gabstra.myworkoutassistant.shared.compressString
import com.gabstra.myworkoutassistant.shared.fromAppBackupToJSON
import com.gabstra.myworkoutassistant.shared.fromAppBackupToJSONPrettyPrint
import com.gabstra.myworkoutassistant.shared.fromWorkoutStoreToJSON
import com.gabstra.myworkoutassistant.shared.logLargeString
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.ExerciseGroup
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.PutDataMapRequest
import com.google.gson.Gson
import com.google.gson.GsonBuilder
import kotlinx.coroutines.delay
import java.time.DayOfWeek
import java.time.LocalDate
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

        val startRequest = PutDataMapRequest.create("/backupChunkPath").apply {
            dataMap.putBoolean("isStart", true)
            dataMap.putInt("chunksCount", chunks.size)
            dataMap.putString("timestamp", System.currentTimeMillis().toString())
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

        if (workoutComponent is ExerciseGroup) {
            val result = findWorkoutComponentById(workoutComponent, id)
            if (result != null) {
                return result
            }
        }
    }
    return null
}

fun findWorkoutComponentById(exerciseGroup: ExerciseGroup, id: UUID): WorkoutComponent? {
    for (workoutComponent in exerciseGroup.workoutComponents) {
        if (workoutComponent.id == id) {
            return workoutComponent
        }

        if (workoutComponent is ExerciseGroup) {
            val result = findWorkoutComponentById(workoutComponent, id)
            if (result != null) {
                return result
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
        is ExerciseGroup -> workoutComponent.enabled
        else -> false // Default case if the component type is unknown
    }
}

fun getStartOfWeek(date: LocalDate): LocalDate {
    return date.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
}

fun getEndOfWeek(date: LocalDate): LocalDate {
    return date.with(TemporalAdjusters.nextOrSame(DayOfWeek.SUNDAY))
}