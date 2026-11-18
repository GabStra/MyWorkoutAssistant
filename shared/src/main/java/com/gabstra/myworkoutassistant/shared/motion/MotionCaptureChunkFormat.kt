package com.gabstra.myworkoutassistant.shared.motion

import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Version-2 sensor chunk encoding: one columnar binary file per chunk, gzip-compressed at session
 * end. Lossless — float32 sample values survive bit-for-bit; timestamps are zigzag-varint deltas
 * from the previous sample. Value columns are byte-plane shuffled so smooth sensor signals compress
 * well (measured ~2.8x smaller than the CSV v1 chunks at gzip level 9).
 *
 * Layout: 4-byte magic, 1-byte version, u16-le sample count, i64-le base epoch ms, i64-le base
 * elapsed-realtime ns, then per-sample columns: u8 sensor type, i8 accuracy, varint epoch delta,
 * varint elapsed delta, then four float32 value columns (x, y, z, w; NaN where absent) stored as
 * byte planes (plane i holds byte i of every float).
 *
 * The Python loader (motion_annotation_pkg.loader) mirrors this layout and maps sensor types by
 * ordinal, so [MotionSensorType]'s declaration order is load-bearing — pinned by a unit test.
 */
object MotionCaptureChunkFormat {
    const val FILE_EXTENSION = ".bin"
    const val VERSION: Byte = 2
    private val MAGIC = byteArrayOf('M'.code.toByte(), 'C'.code.toByte(), 'F'.code.toByte(), '2'.code.toByte())
    private const val HEADER_BYTES = 23

    fun encode(samples: List<MotionSensorSample>): ByteArray {
        require(samples.isNotEmpty()) { "Cannot encode an empty chunk" }
        require(samples.size <= 0xFFFF) { "Chunk too large: ${samples.size} samples" }
        val out = ByteArrayOutputStream(HEADER_BYTES + samples.size * 32)
        out.write(MAGIC, 0, MAGIC.size)
        out.write(VERSION.toInt())
        writeShortLe(out, samples.size)
        writeLongLe(out, samples.first().epochTimeMs)
        writeLongLe(out, samples.first().elapsedRealtimeNanos)
        samples.forEach { out.write(it.sensorType.ordinal) }
        samples.forEach { out.write(it.accuracy) }
        var prevEpoch = samples.first().epochTimeMs
        samples.forEach { sample ->
            writeVarint(out, sample.epochTimeMs - prevEpoch)
            prevEpoch = sample.epochTimeMs
        }
        var prevElapsed = samples.first().elapsedRealtimeNanos
        samples.forEach { sample ->
            writeVarint(out, sample.elapsedRealtimeNanos - prevElapsed)
            prevElapsed = sample.elapsedRealtimeNanos
        }
        val bits = IntArray(samples.size)
        for (axis in 0..3) {
            samples.forEachIndexed { index, sample ->
                bits[index] = when (axis) {
                    0 -> sample.x.toRawBits()
                    1 -> sample.y.toRawBits()
                    2 -> sample.z.toRawBits()
                    else -> (sample.w ?: Float.NaN).toRawBits()
                }
            }
            for (byteIndex in 0..3) {
                for (bit in bits) {
                    out.write((bit shr (byteIndex * 8)) and 0xFF)
                }
            }
        }
        return out.toByteArray()
    }

    fun decode(bytes: ByteArray): List<MotionSensorSample> {
        val buffer = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
        val magic = ByteArray(MAGIC.size)
        buffer.get(magic)
        require(magic.contentEquals(MAGIC)) { "Not a motion chunk v2 file" }
        val version = buffer.get()
        require(version == VERSION) { "Unsupported motion chunk version $version" }
        val count = buffer.short.toInt() and 0xFFFF
        val baseEpoch = buffer.long
        val baseElapsed = buffer.long
        val types = ByteArray(count).also { buffer.get(it) }
        val accuracies = ByteArray(count).also { buffer.get(it) }
        val epochs = LongArray(count)
        var prevEpoch = baseEpoch
        for (index in 0 until count) {
            prevEpoch += readVarint(buffer)
            epochs[index] = prevEpoch
        }
        val elapseds = LongArray(count)
        var prevElapsed = baseElapsed
        for (index in 0 until count) {
            prevElapsed += readVarint(buffer)
            elapseds[index] = prevElapsed
        }
        val values = Array(4) { FloatArray(count) }
        for (axis in 0..3) {
            val shuffled = ByteArray(count * 4).also { buffer.get(it) }
            for (index in 0 until count) {
                val bits = (shuffled[index].toInt() and 0xFF) or
                    ((shuffled[count + index].toInt() and 0xFF) shl 8) or
                    ((shuffled[2 * count + index].toInt() and 0xFF) shl 16) or
                    ((shuffled[3 * count + index].toInt() and 0xFF) shl 24)
                values[axis][index] = Float.fromBits(bits)
            }
        }
        return (0 until count).map { index ->
            MotionSensorSample(
                sensorType = MotionSensorType.entries[types[index].toInt() and 0xFF],
                epochTimeMs = epochs[index],
                elapsedRealtimeNanos = elapseds[index],
                accuracy = accuracies[index].toInt(),
                x = values[0][index],
                y = values[1][index],
                z = values[2][index],
                w = values[3][index].takeUnless { it.isNaN() }
            )
        }
    }

    private fun writeShortLe(out: ByteArrayOutputStream, value: Int) {
        out.write(value and 0xFF)
        out.write((value shr 8) and 0xFF)
    }

    private fun writeLongLe(out: ByteArrayOutputStream, value: Long) {
        for (byteIndex in 0..7) {
            out.write(((value shr (byteIndex * 8)) and 0xFF).toInt())
        }
    }

    private fun writeVarint(out: ByteArrayOutputStream, value: Long) {
        var remaining = (value shl 1) xor (value shr 63) // zigzag: handles negative deltas
        while (remaining and 0x7FL.inv() != 0L) {
            out.write(((remaining and 0x7F) or 0x80).toInt())
            remaining = remaining ushr 7
        }
        out.write(remaining.toInt())
    }

    private fun readVarint(buffer: ByteBuffer): Long {
        var result = 0L
        var shift = 0
        while (true) {
            val byte = buffer.get().toInt() and 0xFF
            result = result or ((byte and 0x7F).toLong() shl shift)
            if (byte and 0x80 == 0) break
            shift += 7
        }
        return (result ushr 1) xor -(result and 1L) // un-zigzag
    }
}
