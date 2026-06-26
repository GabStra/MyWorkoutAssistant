package com.gabstra.myworkoutassistant.shared.motion

import android.content.Context
import com.gabstra.myworkoutassistant.shared.ExerciseMovementBackup
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.decompressToString
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import java.util.Base64

fun collectExerciseMovementBackups(
    context: Context,
    workoutStore: WorkoutStore,
): List<ExerciseMovementBackup> {
    return workoutStore.workouts
        .asSequence()
        .flatMap { workout ->
            workout.workoutComponents.asSequence().flatMap { component ->
                when (component) {
                    is Exercise -> sequenceOf(component)
                    is Superset -> component.exercises.asSequence()
                    else -> emptySequence()
                }
            }
        }
        .mapNotNull { exercise -> exercise.movementRef }
        .distinctBy { movementRef -> movementRef.movementId to movementRef.contentHash }
        .mapNotNull { movementRef ->
            ExerciseMovementStorage.readCompressedMovementJsonBytes(context, movementRef)?.let { compressedJson ->
                ExerciseMovementBackup(
                    movementRef = movementRef,
                    compressedJsonBase64 = Base64.getEncoder().encodeToString(compressedJson),
                    compression = ExerciseMovementBackup.COMPRESSION_GZIP_BASE64,
                )
            }
        }
        .toList()
}

fun restoreExerciseMovementBackups(
    context: Context,
    movementBackups: List<ExerciseMovementBackup>,
) {
    movementBackups.forEach { movementBackup ->
        val compressedJson = movementBackup.compressedJsonBytesOrNull()
        if (compressedJson != null) {
            ExerciseMovementStorage.writeCompressedMovementJsonBytes(
                context = context,
                movementRef = movementBackup.movementRef,
                compressedJson = compressedJson,
            )
            return@forEach
        }

        val json = movementBackup.json ?: return@forEach
        ExerciseMovementStorage.writeMovementJson(context, movementBackup.movementRef, json)
    }
}

fun ExerciseMovementBackup.resolveMovementJson(): String? {
    json?.let { return it }
    return compressedJsonBytesOrNull()?.let { compressedJson -> decompressToString(compressedJson) }
}

private fun ExerciseMovementBackup.compressedJsonBytesOrNull(): ByteArray? {
    if (compression != ExerciseMovementBackup.COMPRESSION_GZIP_BASE64) {
        return null
    }
    val encodedJson = compressedJsonBase64?.takeIf { it.isNotBlank() } ?: return null
    return Base64.getDecoder().decode(encodedJson)
}
