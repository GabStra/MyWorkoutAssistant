package com.gabstra.myworkoutassistant.shared.motion

import java.io.File
import java.nio.file.Files
import java.util.zip.GZIPInputStream
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MotionCaptureChunkCompressorTest {

    @Test
    fun `gzipFile writes gz twin with identical content and deletes source`() {
        val root = Files.createTempDirectory("motion-compress-test").toFile()
        val source = File(root, "chunk_00001.csv")
        val payload = "sensorType,epochTimeMs,elapsedRealtimeNanos,accuracy,x,y,z,w\nACCELEROMETER,1000,10,3,1.0,2.0,3.0,\n".repeat(200)
        source.writeText(payload)

        val gzipped = MotionCaptureChunkCompressor.gzipFile(source)

        assertTrue(gzipped != null)
        assertEquals("chunk_00001.csv.gz", gzipped?.name)
        assertFalse(source.exists())
        val decompressed = GZIPInputStream(gzipped?.inputStream()).readBytes().decodeToString()
        assertEquals(payload, decompressed)
    }

    @Test
    fun `gzipFile returns null and writes no gz when source is missing`() {
        val root = Files.createTempDirectory("motion-compress-test").toFile()
        val missing = File(root, "missing.csv")

        val result = MotionCaptureChunkCompressor.gzipFile(missing)

        assertNull(result)
        assertFalse(File(root, "missing.csv.gz").exists())
    }
}
