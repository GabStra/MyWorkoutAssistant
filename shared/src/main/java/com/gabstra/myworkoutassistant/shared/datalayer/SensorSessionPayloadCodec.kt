package com.gabstra.myworkoutassistant.shared.datalayer

import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.zip.GZIPInputStream
import java.util.zip.GZIPOutputStream
import java.util.zip.ZipEntry
import java.util.zip.ZipInputStream
import java.util.zip.ZipOutputStream

/**
 * Pure (JVM-only) encoding helpers for the sensor-session transfer payload.
 *
 * The payload is built from a `MotionCaptureExportService` export directory:
 *  1. every file in the export directory is zipped with entry names relative to the directory root
 *  2. the zip bytes are gzipped
 *  3. the gzip bytes are split into fixed-size chunks for DataItem transfer
 *
 * The phone receiver mirrors the steps in reverse (concatenate -> gunzip -> unzip) before
 * reconstructing Room rows from `metadata.json`.
 */
object SensorSessionPayloadCodec {
    const val CHUNK_SIZE_BYTES = 90_000
    const val METADATA_FILE_NAME = "metadata.json"
    const val EVENTS_FILE_NAME = "events.csv"

    /**
     * Zips every file under [sourceDirectory] (recursively) into a byte array.
     * Entry names are the paths relative to [sourceDirectory], using forward slashes.
     */
    fun zipDirectory(sourceDirectory: File): ByteArray {
        require(sourceDirectory.isDirectory) {
            "Payload source is not a directory: ${sourceDirectory.absolutePath}"
        }
        val output = ByteArrayOutputStream()
        ZipOutputStream(output).use { zipStream ->
            sourceDirectory.walkTopDown()
                .filter { it.isFile }
                .sortedBy { it.relativeTo(sourceDirectory).invariantSeparatorsPath }
                .forEach { file ->
                    val entryName = file.relativeTo(sourceDirectory).invariantSeparatorsPath
                    zipStream.putNextEntry(ZipEntry(entryName))
                    file.inputStream().use { it.copyTo(zipStream) }
                    zipStream.closeEntry()
                }
        }
        return output.toByteArray()
    }

    /** Unzips [payload] into [targetDirectory], rejecting entries that escape the directory. */
    fun unzip(payload: ByteArray, targetDirectory: File) {
        targetDirectory.mkdirs()
        val canonicalRoot = targetDirectory.canonicalFile
        ZipInputStream(ByteArrayInputStream(payload)).use { zipStream ->
            var entry = zipStream.nextEntry
            while (entry != null) {
                val entryFile = File(targetDirectory, entry.name)
                if (!entryFile.canonicalFile.path.startsWith(canonicalRoot.path + File.separator) &&
                    entryFile.canonicalFile != canonicalRoot
                ) {
                    throw SecurityException("Blocked zip entry outside target directory: ${entry.name}")
                }
                if (entry.isDirectory) {
                    entryFile.mkdirs()
                } else {
                    entryFile.parentFile?.mkdirs()
                    entryFile.outputStream().use { output -> zipStream.copyTo(output) }
                }
                zipStream.closeEntry()
                entry = zipStream.nextEntry
            }
        }
    }

    fun gzip(payload: ByteArray): ByteArray {
        val output = ByteArrayOutputStream()
        GZIPOutputStream(output).use { it.write(payload) }
        return output.toByteArray()
    }

    fun gunzip(payload: ByteArray): ByteArray {
        GZIPInputStream(ByteArrayInputStream(payload)).use { input ->
            val output = ByteArrayOutputStream()
            input.copyTo(output)
            return output.toByteArray()
        }
    }

    /** Splits [payload] into consecutive [CHUNK_SIZE_BYTES] slices (a single empty slice for empty payloads). */
    fun chunkPayload(payload: ByteArray): List<ByteArray> {
        if (payload.isEmpty()) {
            return listOf(payload)
        }
        val chunks = mutableListOf<ByteArray>()
        var offset = 0
        while (offset < payload.size) {
            val length = minOf(CHUNK_SIZE_BYTES, payload.size - offset)
            chunks += payload.copyOfRange(offset, offset + length)
            offset += length
        }
        return chunks
    }

    /** Combines ordered chunks back into the original payload bytes. */
    fun combineChunks(chunks: List<ByteArray>): ByteArray {
        val totalLength = chunks.sumOf { it.size }
        val combined = ByteArray(totalLength)
        var offset = 0
        for (chunk in chunks) {
            chunk.copyInto(combined, offset)
            offset += chunk.size
        }
        return combined
    }

    /**
     * Builds the wire error message used to request a missing-chunk retry. The watch parses this
     * with the same regex format used by the workout-history channel.
     */
    fun buildMissingChunksErrorMessage(
        expectedChunks: Int,
        receivedChunks: Int,
        missingIndices: List<Int>,
        retryGeneration: Int
    ): String {
        return "MISSING_CHUNKS: Retry generation: $retryGeneration. " +
            "Expected $expectedChunks chunks, received $receivedChunks. Missing indices: $missingIndices"
    }
}
