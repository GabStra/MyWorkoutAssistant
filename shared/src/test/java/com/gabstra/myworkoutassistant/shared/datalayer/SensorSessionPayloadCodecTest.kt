package com.gabstra.myworkoutassistant.shared.datalayer

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class SensorSessionPayloadCodecTest {

    @get:Rule
    val tempFolder = TemporaryFolder()

    @Test
    fun `zip and unzip round trip preserves nested files`() {
        val source = tempFolder.newFolder("export")
        File(source, "metadata.json").writeText("{\"session\":\"abc\"}")
        File(source, "events.csv").writeText("eventType,epochTimeMs\n")
        File(File(source, "nested").apply { mkdirs() }, "chunk_00001.csv.gz").writeBytes(byteArrayOf(1, 2, 3, 4, 5))

        val target = tempFolder.newFolder("restored")
        SensorSessionPayloadCodec.unzip(SensorSessionPayloadCodec.zipDirectory(source), target)

        assertEquals(
            File(source, "metadata.json").readText(),
            File(target, "metadata.json").readText()
        )
        assertArrayEquals(
            File(source, "nested/chunk_00001.csv.gz").readBytes(),
            File(target, "nested/chunk_00001.csv.gz").readBytes()
        )
    }

    @Test
    fun `unzip rejects entries escaping the target directory`() {
        val zipBytes = java.io.ByteArrayOutputStream().also { output ->
            java.util.zip.ZipOutputStream(output).use { zipStream ->
                zipStream.putNextEntry(java.util.zip.ZipEntry("../escape.csv"))
                zipStream.write("malicious".toByteArray())
                zipStream.closeEntry()
            }
        }.toByteArray()

        try {
            SensorSessionPayloadCodec.unzip(zipBytes, tempFolder.newFolder("target"))
            fail("Expected SecurityException for zip-slip entry")
        } catch (expected: SecurityException) {
            assertTrue(expected.message!!.contains("../escape.csv"))
        }
    }

    @Test
    fun `gzip and gunzip round trip preserves bytes`() {
        val payload = ByteArray(250_000) { (it % 251).toByte() }
        val gzipped = SensorSessionPayloadCodec.gzip(payload)
        assertArrayEquals(payload, SensorSessionPayloadCodec.gunzip(gzipped))
    }

    @Test
    fun `chunkPayload splits into fixed size chunks and combineChunks restores payload`() {
        val payload = ByteArray(SensorSessionPayloadCodec.CHUNK_SIZE_BYTES * 2 + 123) { (it % 7).toByte() }

        val chunks = SensorSessionPayloadCodec.chunkPayload(payload)

        assertEquals(3, chunks.size)
        assertEquals(SensorSessionPayloadCodec.CHUNK_SIZE_BYTES, chunks[0].size)
        assertEquals(SensorSessionPayloadCodec.CHUNK_SIZE_BYTES, chunks[1].size)
        assertEquals(123, chunks[2].size)
        assertArrayEquals(payload, SensorSessionPayloadCodec.combineChunks(chunks))
    }

    @Test
    fun `chunkPayload of empty payload yields single empty chunk`() {
        val chunks = SensorSessionPayloadCodec.chunkPayload(ByteArray(0))
        assertEquals(1, chunks.size)
        assertEquals(0, chunks[0].size)
    }

    @Test
    fun `missing chunks error message carries indices and retry generation in wire format`() {
        val message = SensorSessionPayloadCodec.buildMissingChunksErrorMessage(
            expectedChunks = 4,
            receivedChunks = 2,
            missingIndices = listOf(1, 3),
            retryGeneration = 7
        )

        assertTrue(message.startsWith("MISSING_CHUNKS:"))
        assertTrue(message.contains("Retry generation: 7"))
        assertTrue(message.contains("Missing indices: [1, 3]"))
    }
}
