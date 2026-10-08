package com.gabstra.myworkoutassistant.shared.motion

import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.util.zip.GZIPOutputStream

/**
 * Compresses capture chunk files once a session reaches a terminal state, halving-or-better the
 * on-disk footprint of CSV sensor data that is never appended to again.
 */
object MotionCaptureChunkCompressor {

    /**
     * Gzips [source] to `source.name + ".gz"` in the same directory and deletes the original.
     * Returns the gzip file, or null when compression or source deletion failed (the original
     * file is left untouched in that case so no data is lost).
     */
    fun gzipFile(source: File): File? {
        val target = File(source.parentFile, source.name + ".gz")
        return try {
            GZIPOutputStream(FileOutputStream(target)).use { output ->
                FileInputStream(source).use { input -> input.copyTo(output) }
            }
            if (source.delete()) {
                target
            } else {
                target.delete()
                null
            }
        } catch (_: Exception) {
            target.delete()
            null
        }
    }
}
