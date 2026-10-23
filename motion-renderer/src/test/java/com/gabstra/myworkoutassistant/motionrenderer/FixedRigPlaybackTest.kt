package com.gabstra.myworkoutassistant.motionrenderer

import com.google.gson.JsonParser
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.cos
import kotlin.math.sin

class FixedRigPlaybackTest {
    @Test
    fun continuousVelocityPlaybackMatchesPythonAcrossFrameBoundariesAndSeam() {
        val data = JsonParser.parseString(checkNotNull(javaClass.classLoader?.getResource(
            "fixed-rig-continuous-parity.json")).readText()).asJsonObject
        for ((version, expectedKey) in listOf(1 to "expected", 2 to "expectedV2")) {
            val value = data.getAsJsonObject("rig").deepCopy()
            value.addProperty("interpolation", "limited_quaternion_hermite_v$version")
            val rig = FixedRigPlayback.parse(value, 8)
            val expected = data.getAsJsonArray(expectedKey)
            data.getAsJsonArray("cursors").forEachIndexed { frame, cursor ->
                val result = rig.sample(cursor.asDouble, wrap = true)
                rig.jointNames.forEachIndexed { joint, name ->
                    (0..2).forEach { axis ->
                        assertEquals(expected[frame].asJsonArray[joint].asJsonArray[axis].asDouble,
                            checkNotNull(result[name])[axis], 1e-9)
                    }
                }
            }
        }
    }

    private fun fixture() = JsonParser.parseString(
        checkNotNull(javaClass.classLoader?.getResource("fixed-rig-parity.json")).readText()
    ).asJsonObject

    @Test
    fun fractionalPlaybackMatchesPythonForwardKinematics() {
        val data = fixture()
        val rig = FixedRigPlayback.parse(data.getAsJsonObject("rig"), 2)
        val expected = data.getAsJsonArray("expected")
        data.getAsJsonArray("cursors").forEachIndexed { frame, cursor ->
            val result = rig.sample(cursor.asDouble, wrap = false)
            rig.jointNames.forEachIndexed { joint, name ->
                (0..2).forEach { axis ->
                    assertEquals(expected[frame].asJsonArray[joint].asJsonArray[axis].asDouble,
                        checkNotNull(result[name])[axis], 1e-9)
                }
            }
        }
    }

    @Test
    fun continuousLoopPreservesFractionalCursorAndVisibility() {
        val seam = resolveLoopPlayback(143.5 / 30, 144, 30f, 0, true)
        val next = resolveLoopPlayback(144.5 / 30, 144, 30f, 0, true)
        assertEquals(143.5, seam.frameCursor, 1e-9)
        assertEquals(.5, next.frameCursor, 1e-9)
        assertEquals(1f, seam.visibility, 0f)
        assertEquals(1f, next.visibility, 0f)
        val rig = FixedRigPlayback.parse(fixture().getAsJsonObject("rig"), 2)
        val middle = rig.sample(.5, wrap = true)
        val seamMiddle = rig.sample(1.5, wrap = true)
        rig.jointNames.forEach { name ->
            (0..2).forEach { axis ->
                assertEquals(checkNotNull(middle[name])[axis], checkNotNull(seamMiddle[name])[axis], 1e-9)
            }
        }
    }

    @Test(expected = IllegalArgumentException::class)
    fun invalidHierarchyIsRejected() {
        val data = fixture().getAsJsonObject("rig")
        data.getAsJsonArray("parents").set(0, com.google.gson.JsonPrimitive(0))
        FixedRigPlayback.parse(data, 2)
    }

    @Test
    fun contactFootTracksCloseToeAndKneeBetweenKeysWithoutMovingBody() {
        val rigData = fixture().getAsJsonObject("rig")
        val baselineRig = FixedRigPlayback.parse(rigData.deepCopy(), 2)
        val keyPose = baselineRig.sample(0.0, wrap = false)
        val toe = checkNotNull(keyPose["left_foot"])
        val ankle = checkNotNull(keyPose["left_ankle"])
        val direction = normalizedForTest(DoubleArray(3) { toe[it] - ankle[it] })
        val tracks = JsonObject().apply {
            addProperty("version", 1)
            add("left", contactTrack(active = listOf(true, true), toes = listOf(toe, toe), directions = listOf(direction, direction)))
        }
        rigData.add("contactFootTracks", tracks)
        val rig = FixedRigPlayback.parse(rigData, 2)
        val repaired = rig.sample(0.5, wrap = false)
        val repairedToe = checkNotNull(repaired["left_foot"])
        val repairedAnkle = checkNotNull(repaired["left_ankle"])
        val repairedKnee = checkNotNull(repaired["left_knee"])
        val baselineMiddle = baselineRig.sample(0.5, wrap = false)
        val middleHip = checkNotNull(baselineMiddle["left_hip"])
        val baselineKnee = checkNotNull(baselineMiddle["left_knee"])
        val baselineAnkle = checkNotNull(baselineMiddle["left_ankle"])
        for (axis in 0..2) assertEquals(toe[axis], repairedToe[axis], 1e-9)
        assertEquals(distance(ankle, toe), distance(repairedAnkle, repairedToe), 1e-8)
        assertEquals(distance(middleHip, baselineKnee), distance(middleHip, repairedKnee), 1e-8)
        assertEquals(distance(baselineKnee, baselineAnkle), distance(repairedKnee, repairedAnkle), 1e-8)
        // Foot repair is local: the torso and root retain the regular FK result.
        for (joint in listOf("pelvis", "spine1", "spine2", "head", "right_knee")) {
            for (axis in 0..2) assertEquals(checkNotNull(baselineMiddle[joint])[axis], checkNotNull(repaired[joint])[axis], 1e-12)
        }
        // Exact key samples remain the legacy FK poses, including the original heel articulation.
        val exactKey = rig.sample(0.0, wrap = false)
        for (joint in rig.jointNames) for (axis in 0..2) {
            assertEquals(checkNotNull(keyPose[joint])[axis], checkNotNull(exactKey[joint])[axis], 1e-12)
        }

        // A contact beginning at the next key eases in with smoothstep weight .5 at the midpoint.
        val transitioningData = fixture().getAsJsonObject("rig")
        transitioningData.add("contactFootTracks", JsonObject().apply {
            addProperty("version", 1)
            add("left", contactTrack(active = listOf(false, true), toes = listOf(toe, toe), directions = listOf(direction, direction)))
        })
        val transitioningRig = FixedRigPlayback.parse(transitioningData, 2)
        val rawMiddleToe = checkNotNull(baselineMiddle["left_foot"])
        val transitionedToe = checkNotNull(transitioningRig.sample(0.5, wrap = false)["left_foot"])
        for (axis in 0..2) assertEquals(rawMiddleToe[axis] + .5 * (toe[axis] - rawMiddleToe[axis]), transitionedToe[axis], 1e-9)
    }

    @Test(expected = IllegalArgumentException::class)
    fun unreachableContactFootTrackFailsExplicitly() {
        val rigData = fixture().getAsJsonObject("rig")
        val baseline = FixedRigPlayback.parse(rigData.deepCopy(), 2)
        val pose = baseline.sample(0.0, wrap = false)
        val toe = checkNotNull(pose["left_foot"])
        val ankle = checkNotNull(pose["left_ankle"])
        val direction = normalizedForTest(DoubleArray(3) { toe[it] - ankle[it] })
        val unreachable = doubleArrayOf(toe[0] + 10.0, toe[1], toe[2])
        rigData.add("contactFootTracks", JsonObject().apply {
            addProperty("version", 1)
            add("left", contactTrack(active = listOf(true, true), toes = listOf(unreachable, unreachable), directions = listOf(direction, direction)))
        })
        FixedRigPlayback.parse(rigData, 2).sample(0.5, wrap = false)
    }

    @Test
    fun wrappedContactYawUsesContinuousBranchAcrossTheSeam() {
        val rigData = fixture().getAsJsonObject("rig")
        val original = FixedRigPlayback.parse(rigData.deepCopy(), 2)
        val toe = checkNotNull(original.sample(0.0, wrap = false)["left_foot"])
        val nearPositivePi = directionAtYaw(Math.toRadians(179.0))
        val nearNegativePi = directionAtYaw(Math.toRadians(-179.0))
        rigData.add("contactFootTracks", JsonObject().apply {
            addProperty("version", 1)
            add("left", contactTrack(
                active = listOf(true, true), toes = listOf(toe, toe),
                directions = listOf(nearPositivePi, nearNegativePi),
            ))
        })
        val rig = FixedRigPlayback.parse(rigData, 2)
        val seam = rig.sample(1.5, wrap = true)
        val direction = normalizedForTest(DoubleArray(3) {
            checkNotNull(seam["left_foot"])[it] - checkNotNull(seam["left_ankle"])[it]
        })
        assertTrue("wrapped yaw should interpolate through pi, not zero", direction[2] < -.99)
        assertTrue(kotlin.math.abs(direction[0]) < .02)
    }

    private fun contactTrack(active: List<Boolean>, toes: List<DoubleArray>, directions: List<DoubleArray>) = JsonObject().apply {
        add("active", JsonArray().also { array -> active.forEach { array.add(it) } })
        add("toes", vectorRows(toes))
        add("directions", vectorRows(directions))
    }

    private fun vectorRows(values: List<DoubleArray>) = JsonArray().also { rows ->
        values.forEach { vector -> rows.add(JsonArray().also { row -> vector.forEach(row::add) }) }
    }

    private fun normalizedForTest(value: DoubleArray): DoubleArray {
        val norm = distance(doubleArrayOf(0.0, 0.0, 0.0), value)
        return DoubleArray(3) { value[it] / norm }
    }

    private fun directionAtYaw(yaw: Double) = doubleArrayOf(sin(yaw), 0.0, cos(yaw))

    private fun distance(a: DoubleArray, b: DoubleArray) = kotlin.math.sqrt((0..2).sumOf { (a[it] - b[it]) * (a[it] - b[it]) })
}
