package com.gabstra.myworkoutassistant.shared.motion

import android.content.Context
import com.gabstra.myworkoutassistant.shared.compressString
import com.gabstra.myworkoutassistant.shared.decompressToString
import java.io.File

object ExerciseMovementStorage {
    private const val DIRECTORY_NAME = "exercise_movements"
    private const val LEGACY_JSON_EXTENSION = ".json"
    private const val COMPRESSED_JSON_EXTENSION = ".json.gz"

    fun readMovementJson(context: Context, movementRef: ExerciseMovementRef): String? {
        if (movementRef.format != ExerciseMovementRef.FORMAT_WEAR_SKELETON_JSON) {
            return null
        }

        val compressedMovementFile = compressedMovementFile(context, movementRef.movementId)
        if (compressedMovementFile.exists()) {
            val json = runCatching {
                decompressToString(compressedMovementFile.readBytes())
            }.getOrNull()
            if (json != null && contentHashMatches(json, movementRef)) {
                return json
            }
        }

        val legacyMovementFile = legacyMovementFile(context, movementRef.movementId)
        if (!legacyMovementFile.exists()) {
            return null
        }

        val json = legacyMovementFile.readText(Charsets.UTF_8)
        return json.takeIf { contentHashMatches(json, movementRef) }
    }

    fun readCompressedMovementJsonBytes(context: Context, movementRef: ExerciseMovementRef): ByteArray? {
        if (movementRef.format != ExerciseMovementRef.FORMAT_WEAR_SKELETON_JSON) {
            return null
        }

        val compressedMovementFile = compressedMovementFile(context, movementRef.movementId)
        if (compressedMovementFile.exists()) {
            val compressedBytes = compressedMovementFile.readBytes()
            val json = runCatching { decompressToString(compressedBytes) }.getOrNull()
            if (json != null && contentHashMatches(json, movementRef)) {
                return compressedBytes
            }
        }

        return readMovementJson(context, movementRef)?.let { json -> compressString(json) }
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

        writeCompressedMovementJsonBytes(
            context = context,
            movementRef = movementRef,
            compressedJson = compressString(json),
        )
    }

    fun writeCompressedMovementJsonBytes(
        context: Context,
        movementRef: ExerciseMovementRef,
        compressedJson: ByteArray,
    ) {
        require(movementRef.format == ExerciseMovementRef.FORMAT_WEAR_SKELETON_JSON) {
            "Unsupported exercise movement format: ${movementRef.format}"
        }
        val json = decompressToString(compressedJson)
        require(contentHashMatches(json, movementRef)) {
            "Exercise movement content hash does not match the provided reference"
        }

        val movementFile = compressedMovementFile(context, movementRef.movementId)
        movementFile.parentFile?.mkdirs()
        val tempFile = File(movementFile.parentFile, "${movementFile.name}.tmp")
        tempFile.writeBytes(compressedJson)
        if (movementFile.exists() && !movementFile.delete()) {
            tempFile.delete()
            error("Could not replace existing exercise movement file: ${movementFile.name}")
        }
        if (!tempFile.renameTo(movementFile)) {
            tempFile.delete()
            error("Could not commit exercise movement file: ${movementFile.name}")
        }
        legacyMovementFile(context, movementRef.movementId).delete()
    }

    private fun compressedMovementFile(context: Context, movementId: String): File =
        File(File(context.filesDir, DIRECTORY_NAME), movementFileName(movementId, COMPRESSED_JSON_EXTENSION))

    private fun legacyMovementFile(context: Context, movementId: String): File =
        File(File(context.filesDir, DIRECTORY_NAME), movementFileName(movementId, LEGACY_JSON_EXTENSION))

    private fun movementFileName(movementId: String, extension: String): String {
        val safeName = sanitizeMovementId(movementId)
        val suffix = ExerciseMovementRef.contentHashFor(movementId).take(12)
        return "$safeName-$suffix$extension"
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

    private fun contentHashMatches(json: String, movementRef: ExerciseMovementRef): Boolean {
        val expectedHash = movementRef.contentHash
        if (expectedHash.isBlank()) {
            return true
        }
        val actualHash = ExerciseMovementRef.contentHashFor(json)
        return actualHash.equals(expectedHash, ignoreCase = true)
    }
}
