package com.gabstra.myworkoutassistant.motionrenderer

import com.google.gson.JsonParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

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
}
