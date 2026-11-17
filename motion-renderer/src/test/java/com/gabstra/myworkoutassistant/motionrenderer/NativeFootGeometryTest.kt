package com.gabstra.myworkoutassistant.motionrenderer

import com.google.gson.JsonParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class NativeFootGeometryTest {
    private fun fixture() = JsonParser.parseString(
        checkNotNull(javaClass.classLoader?.getResource("native_foot_geometry_v1.json")).readText()
    ).asJsonObject

    private fun payloadRoot(geometryKey: String = "reference") = fixture().let { fixture ->
        JsonParser.parseString("{}").asJsonObject.apply {
            add("nativeFootGeometry", fixture.getAsJsonObject(geometryKey))
        }
    }

    @Test
    fun parsesNativeGeometryWithoutChangingLocalMarkers() {
        val source = fixture()
        val root = payloadRoot()
        val expected = source.getAsJsonObject("reference").getAsJsonObject("sides")
            .getAsJsonObject("left")
        val parsed = checkNotNull(parseNativeFootGeometry(root))
        assertEquals(0.134302f, parsed.left.ankleToFootJointLengthMeters, 1e-7f)
        assertEquals(expected.getAsJsonArray("heelFromAnkleLocalMeters")[0].asFloat,
            parsed.left.heelFromAnkleLocalMeters.x, 1e-7f)
        assertEquals(expected.getAsJsonArray("toeFromAnkleLocalMeters")[0].asFloat,
            parsed.left.toeFromAnkleLocalMeters.x, 1e-7f)
        assertEquals(parsed.left, parsed.right)
    }

    @Test
    fun absentGeometryKeepsLegacyPayloadPath() {
        assertNull(parseNativeFootGeometry(JsonParser.parseString("{}").asJsonObject))
    }

    @Test
    fun malformedRecognizedGeometryIsRejected() {
        val root = payloadRoot()
        root.getAsJsonObject("nativeFootGeometry").getAsJsonObject("sides")
            .getAsJsonObject("left").add("toeFromAnkleLocalMeters", JsonParser.parseString("[0.1, 0.2]"))
        assertThrows(IllegalArgumentException::class.java) { parseNativeFootGeometry(root) }
    }

    @Test
    fun nativeShoeVerticesStayRigidUnderRotationMirrorAndRetargetScale() {
        val fixture = fixture()
        val parsed = checkNotNull(parseNativeFootGeometry(payloadRoot()))
        val reference = fixture.getAsJsonObject("neutralCase")
        fun vec(array: com.google.gson.JsonArray) = WearSkeletonVec3(
            array[0].asFloat, array[1].asFloat, array[2].asFloat)
        val baseAnkle = vec(reference.getAsJsonArray("ankle"))
        val baseFoot = vec(reference.getAsJsonArray("footJoint"))
        val baseSide = vec(reference.getAsJsonArray("sideAxis"))
        val base = nativeFootShoeVertices(baseAnkle, baseFoot, baseSide, baseSide, parsed.left, .2f)
        val basePoints = base.rings.flatten() + base.rearTip + base.toeTip
        assertEquals(26, basePoints.size)

        val cases = fixture.getAsJsonArray("rigidCases")
        for (caseElement in cases) {
            val case = caseElement.asJsonObject
            val rotation = case.getAsJsonArray("rotationMatrix").map { row ->
                row.asJsonArray.map { it.asDouble }
            }
            val translation = vec(case.getAsJsonArray("translation"))
            val scale = case.get("scale").asFloat
            fun transform(point: WearSkeletonVec3): WearSkeletonVec3 = WearSkeletonVec3(
                (rotation[0][0] * point.x + rotation[0][1] * point.y + rotation[0][2] * point.z).toFloat() * scale + translation.x,
                (rotation[1][0] * point.x + rotation[1][1] * point.y + rotation[1][2] * point.z).toFloat() * scale + translation.y,
                (rotation[2][0] * point.x + rotation[2][1] * point.y + rotation[2][2] * point.z).toFloat() * scale + translation.z,
            )
            val determinant = (
                rotation[0][0] * (rotation[1][1] * rotation[2][2] - rotation[1][2] * rotation[2][1]) -
                    rotation[0][1] * (rotation[1][0] * rotation[2][2] - rotation[1][2] * rotation[2][0]) +
                    rotation[0][2] * (rotation[1][0] * rotation[2][1] - rotation[1][1] * rotation[2][0]))
            var side = transform(baseSide) - translation
            if (determinant < 0.0) side = side * -1f
            val posed = nativeFootShoeVertices(
                transform(baseAnkle), transform(baseFoot), side, side,
                parsed.left, .2f * scale)
            val posedPoints = posed.rings.flatten() + posed.rearTip + posed.toeTip
            val pointCount = if (determinant < 0.0) basePoints.size - 2 else basePoints.size
            basePoints.take(pointCount).map(::transform).forEachIndexed { index, expected ->
                assertTrue("${case.get("name").asString} vertex $index", posedPoints.any { actual ->
                    (expected - actual).length() <= 2e-6f
                })
            }
            assertEquals((posed.rings.first()[0] + posed.rings.first()[4]) * 0.5f,
                posed.rearTip)
            assertEquals((posed.rings.last()[0] + posed.rings.last()[4]) * 0.5f,
                posed.toeTip)
        }
    }

    @Test
    fun nonzeroMarkerOffsetsRetargetWithAxialTwistAndMatchFullMeshFloor() {
        val fixture = fixture()
        val geometry = checkNotNull(parseNativeFootGeometry(payloadRoot("twistedRetargetGeometry")))
        val case = fixture.getAsJsonObject("twistedRetargetCase")
        val expected = case.getAsJsonObject("expected")
        fun vec(name: String) = case.getAsJsonArray(name).let { array ->
            WearSkeletonVec3(array[0].asFloat, array[1].asFloat, array[2].asFloat)
        }
        val ankle = vec("ankle")
        val foot = vec("footJoint")
        val side = vec("sideAxis")
        val result = nativeFootShoeVertices(ankle, foot, side, side, geometry.left, .25f)
        val points = result.rings.flatten() + result.rearTip + result.toeTip
        assertEquals(26, points.size)
        assertEquals(expected.get("meshMinY").asFloat, points.minOf { it.y }, 1e-7f)

        val forward = (foot - ankle).normalizedOr(WearSkeletonVec3(1f, 0f, 0f))
        val lateral = (side - forward * side.dot(forward)).normalizedOr(side)
        val up = lateral.cross(forward)
        val factor = (foot - ankle).length() / geometry.left.ankleToFootJointLengthMeters
        fun expectedMarker(key: String): WearSkeletonVec3 {
            val marker = expected.getAsJsonArray(key)
            return WearSkeletonVec3(marker[0].asFloat, marker[1].asFloat, marker[2].asFloat)
        }
        listOf(
            expectedMarker("heel") to geometry.left.heelFromAnkleLocalMeters,
            expectedMarker("toe") to geometry.left.toeFromAnkleLocalMeters,
        ).forEach { (wanted, local) ->
            val actual = ankle + forward * (local.x * factor) + lateral * (local.y * factor) + up * (local.z * factor)
            assertEquals(wanted.x, actual.x, 1e-7f)
            assertEquals(wanted.y, actual.y, 1e-7f)
            assertEquals(wanted.z, actual.z, 1e-7f)
        }
        assertEquals(foot, ankle + forward * (geometry.left.ankleToFootJointLengthMeters * factor))
    }
}
