package com.gabstra.myworkoutassistant.motionrenderer

import com.google.gson.JsonObject
import kotlin.math.acos
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

/** Immutable, calibrated rig shared by phone and Wear playback. */
internal class FixedRigPlayback private constructor(
    val jointNames: List<String>,
    private val parents: IntArray,
    private val order: IntArray,
    private val offsets: Array<DoubleArray>,
    private val rotationSlots: IntArray,
    private val coordinates: Array<DoubleArray>,
    private val continuousVelocity: Boolean,
    private val smoothLimiter: Boolean,
) {
    private val roots = coordinates.map { it.copyOfRange(0, 3) }.toTypedArray()
    private val quaternionTracks = rotationSlots.map { slot ->
        if (slot < 0 || !continuousVelocity) null else coordinates.map {
            RigQuaternion.fromRotationVector(it, slot).toArray()
        }.toTypedArray()
    }

    fun sample(cursor: Double, wrap: Boolean): Map<String, DoubleArray> {
        val count = coordinates.size
        val bounded = if (wrap) ((cursor % count) + count) % count else cursor.coerceIn(0.0, count - 1.0)
        val first = bounded.toInt()
        val last = if (wrap) (first + 1) % count else (first + 1).coerceAtMost(count - 1)
        val alpha = bounded - first
        val a = coordinates[first]
        val b = coordinates[last]
        val rotations = Array(jointNames.size) { RigQuaternion.Identity }
        val points = Array(jointNames.size) { DoubleArray(3) }
        for (joint in order) {
            val slot = rotationSlots[joint]
            val local = if (slot < 0) RigQuaternion.Identity else if (continuousVelocity) {
                val q = interpolateRigTrack(checkNotNull(quaternionTracks[joint]), first, last, alpha, wrap, true, smoothLimiter)
                RigQuaternion(q[0], q[1], q[2], q[3])
            } else RigQuaternion.fromRotationVector(a, slot).slerp(RigQuaternion.fromRotationVector(b, slot), alpha)
            val parent = parents[joint]
            rotations[joint] = if (parent < 0) local else rotations[parent] * local
            points[joint] = if (parent < 0) {
                if (continuousVelocity) interpolateRigTrack(roots, first, last, alpha, wrap, false, smoothLimiter)
                else DoubleArray(3) { a[it] * (1 - alpha) + b[it] * alpha }
            } else {
                val offset = rotations[joint].rotate(offsets[joint])
                DoubleArray(3) { points[parent][it] + offset[it] }
            }
        }
        return jointNames.indices.associate { jointNames[it] to points[it] }
    }

    companion object {
        fun parse(value: JsonObject, frameCount: Int): FixedRigPlayback {
            require(!value.has("version") || value.get("version").asInt == 1) { "Unsupported fixed rig version" }
            val names = value.getAsJsonArray("jointNames").map { it.asString }
            val parents = value.getAsJsonArray("parents").map { it.asInt }.toIntArray()
            val order = value.getAsJsonArray("order").map { it.asInt }.toIntArray()
            val offsets = value.getAsJsonArray("offsets").map { row -> row.asJsonArray.map { it.asDouble }.toDoubleArray() }.toTypedArray()
            val rotationNames = value.getAsJsonArray("rotationJointNames").map { it.asString }
            val coordinates = value.getAsJsonArray("coordinates").map { row -> row.asJsonArray.map { it.asDouble }.toDoubleArray() }.toTypedArray()
            require(names.isNotEmpty() && names.toSet().size == names.size)
            require(parents.size == names.size && offsets.size == names.size)
            require(order.size == names.size && order.toSet() == names.indices.toSet())
            require(rotationNames.toSet().size == rotationNames.size && rotationNames.all { it in names })
            require(coordinates.size == frameCount && frameCount > 0)
            require(coordinates.all { row -> row.size == 3 + rotationNames.size * 3 && row.all { it.isFinite() } })
            require(offsets.all { row -> row.size == 3 && row.all { it.isFinite() } })
            val visited = mutableSetOf<Int>()
            for ((index, joint) in order.withIndex()) {
                require(if (index == 0) parents[joint] == -1 else parents[joint] in visited) { "Rig must be parent-first with one root" }
                visited += joint
            }
            val slots = IntArray(names.size) { -1 }
            rotationNames.forEachIndexed { index, name -> slots[names.indexOf(name)] = 3 + index * 3 }
            val interpolation = value.get("interpolation")?.asString
            val smoothLimiter = interpolation == "limited_quaternion_hermite_v2"
            val continuous = smoothLimiter || interpolation == "limited_quaternion_hermite_v1"
            return FixedRigPlayback(names, parents, order, offsets, slots, coordinates, continuous, smoothLimiter)
        }
    }
}

private data class RigQuaternion(val x: Double, val y: Double, val z: Double, val w: Double) {
    fun toArray() = doubleArrayOf(x, y, z, w)
    operator fun times(b: RigQuaternion) = RigQuaternion(
        w * b.x + x * b.w + y * b.z - z * b.y,
        w * b.y - x * b.z + y * b.w + z * b.x,
        w * b.z + x * b.y - y * b.x + z * b.w,
        w * b.w - x * b.x - y * b.y - z * b.z,
    )

    fun rotate(v: DoubleArray): DoubleArray {
        val result = this * RigQuaternion(v[0], v[1], v[2], 0.0) * RigQuaternion(-x, -y, -z, w)
        return doubleArrayOf(result.x, result.y, result.z)
    }

    fun slerp(other: RigQuaternion, alpha: Double): RigQuaternion {
        var b = other
        var dot = x * b.x + y * b.y + z * b.z + w * b.w
        if (dot < 0) {
            b = RigQuaternion(-b.x, -b.y, -b.z, -b.w)
            dot = -dot
        }
        val angle = acos(dot.coerceIn(-1.0, 1.0))
        val first = if (angle < 1e-6) 1 - alpha else sin((1 - alpha) * angle) / sin(angle)
        val last = if (angle < 1e-6) alpha else sin(alpha * angle) / sin(angle)
        val q = RigQuaternion(x * first + b.x * last, y * first + b.y * last, z * first + b.z * last, w * first + b.w * last)
        val norm = sqrt(q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w)
        return RigQuaternion(q.x / norm, q.y / norm, q.z / norm, q.w / norm)
    }

    companion object {
        val Identity = RigQuaternion(0.0, 0.0, 0.0, 1.0)
        fun fromRotationVector(values: DoubleArray, start: Int): RigQuaternion {
            val angle = sqrt((0..2).sumOf { values[start + it] * values[start + it] })
            if (angle < 1e-12) return Identity
            val scale = sin(angle / 2) / angle
            return RigQuaternion(values[start] * scale, values[start + 1] * scale, values[start + 2] * scale, cos(angle / 2))
        }
    }
}

/** Normalized Hermite rotation paths use the same tangent at each side of a knot. */
private fun interpolateRigTrack(
    track: Array<DoubleArray>, first: Int, last: Int, t: Double, wrap: Boolean, quaternion: Boolean,
    smoothLimiter: Boolean,
): DoubleArray {
    fun dot(a: DoubleArray, b: DoubleArray) = a.indices.sumOf { a[it] * b[it] }
    fun norm(a: DoubleArray) = sqrt(dot(a, a))
    fun index(i: Int) = if (wrap) (i + track.size) % track.size else i.coerceIn(0, track.lastIndex)
    fun tangent(i: Int): DoubleArray {
        val current = track[i]
        val previous = track[index(i - 1)]
        val following = track[index(i + 1)]
        val previousSign = if (quaternion && dot(previous, current) < 0) -1.0 else 1.0
        val followingSign = if (quaternion && dot(following, current) < 0) -1.0 else 1.0
        val incoming = DoubleArray(current.size) { current[it] - previous[it] * previousSign }
        val outgoing = DoubleArray(current.size) { following[it] * followingSign - current[it] }
        if (quaternion) {
            val a = dot(incoming, current)
            val b = dot(outgoing, current)
            current.indices.forEach {
                incoming[it] -= a * current[it]
                outgoing[it] -= b * current[it]
            }
        }
        if (dot(incoming, outgoing) <= 0) return DoubleArray(current.size)
        val result = DoubleArray(current.size) { (incoming[it] + outgoing[it]) * .5 }
        val limit = 2 * minOf(norm(incoming), norm(outgoing))
        val scale = minOf(1.0, limit / maxOf(norm(result), 1e-12))
        val alignment = if (smoothLimiter) minOf(1.0, dot(incoming, outgoing) /
            maxOf(norm(incoming) * norm(outgoing), 1e-12)) else 1.0
        return DoubleArray(current.size) { result[it] * scale * alignment }
    }
    val a = track[first]
    val b = track[last]
    val ma = tangent(first)
    val mb = tangent(last)
    val sign = if (quaternion && dot(a, b) < 0) -1.0 else 1.0
    val result = DoubleArray(a.size) {
        (2*t*t*t - 3*t*t + 1)*a[it] + (t*t*t - 2*t*t + t)*ma[it] +
            (-2*t*t*t + 3*t*t)*b[it]*sign + (t*t*t - t*t)*mb[it]*sign
    }
    val length = if (quaternion) maxOf(norm(result), 1e-12) else 1.0
    return DoubleArray(result.size) { result[it] / length }
}
