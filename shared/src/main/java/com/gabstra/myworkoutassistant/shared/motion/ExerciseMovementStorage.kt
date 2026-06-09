package com.gabstra.myworkoutassistant.shared.motion

import android.content.Context
import java.io.File

object ExerciseMovementStorage {
    private const val DIRECTORY_NAME = "exercise_movements"

    fun readMovementJson(context: Context, movementRef: ExerciseMovementRef): String? {
        if (movementRef.format != ExerciseMovementRef.FORMAT_WEAR_SKELETON_JSON) {
            return null
        }

        val movementFile = movementFile(context, movementRef.movementId)
        if (!movementFile.exists()) {
            return null
        }

        val json = movementFile.readText(Charsets.UTF_8)
        val expectedHash = movementRef.contentHash
        if (expectedHash.isBlank()) {
            return json
        }

        val actualHash = ExerciseMovementRef.contentHashFor(json)
        return json.takeIf { actualHash.equals(expectedHash, ignoreCase = true) }
    }

    fun writeMovementJson(
        context: Context,
        movementRef: ExerciseMovementRef,
        json: String,
    ) {
        require(movementRef.format == ExerciseMovementRef.FORMAT_WEAR_SKELETON_JSON) {
            "Unsupported exercise movement format: ${movementRef.format}"
        }
        require(movementRef.contentHash.equals(ExerciseMovementRef.contentHashFor(json), ignoreCase = true)) {
            "Exercise movement content hash does not match the provided reference"
        }

        val movementFile = movementFile(context, movementRef.movementId)
        movementFile.parentFile?.mkdirs()
        val tempFile = File(movementFile.parentFile, "${movementFile.name}.tmp")
        tempFile.writeText(json, Charsets.UTF_8)
        if (movementFile.exists() && !movementFile.delete()) {
            tempFile.delete()
            error("Could not replace existing exercise movement file: ${movementFile.name}")
        }
        if (!tempFile.renameTo(movementFile)) {
            tempFile.delete()
            error("Could not commit exercise movement file: ${movementFile.name}")
        }
    }

    private fun movementFile(context: Context, movementId: String): File {
        val safeName = sanitizeMovementId(movementId)
        val suffix = ExerciseMovementRef.contentHashFor(movementId).take(12)
        return File(File(context.filesDir, DIRECTORY_NAME), "$safeName-$suffix.json")
    }

    private fun sanitizeMovementId(movementId: String): String {
        val safeName = movementId
            .map { char ->
                when {
                    char.isLetterOrDigit() || char == '.' || char == '_' || char == '-' -> char
                    else -> '_'
                }
            }
            .joinToString(separator = "")
            .trim('_', '.', '-')
            .take(80)

        return safeName.ifBlank { "movement" }
    }
}
