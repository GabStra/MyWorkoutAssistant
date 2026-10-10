package com.gabstra.myworkoutassistant.motionrenderer

import androidx.compose.ui.graphics.Color
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MovementSceneLoadingTest {
    private val renderer = Class.forName("com.gabstra.myworkoutassistant.motionrenderer.SkeletonMotionPreviewKt")

    private fun call(name: String, vararg arguments: Any): Any = checkNotNull(renderer.declaredMethods
        .single { (it.name == name || it.name.startsWith("$name-")) && it.parameterCount == arguments.size }
        .apply { isAccessible = true }.invoke(null, *arguments))

    private fun field(value: Any, name: String): Any? = value.javaClass.getDeclaredField(name)
        .apply { isAccessible = true }.get(value)

    private fun payload(): JsonObject {
        val fixture = JsonParser.parseString(checkNotNull(javaClass.classLoader?.getResource(
            "fixed-rig-continuous-parity.json")).readText()).asJsonObject
        val rig = fixture.getAsJsonObject("rig")
        val playback = FixedRigPlayback.parse(rig, 8)
        return JsonObject().apply {
            addProperty("fps", 30)
            add("loop", JsonObject().apply { addProperty("enabled", true) })
            add("fixedRig", rig.deepCopy())
            add("bounds", JsonParser.parseString("""{"minX":-2,"maxX":2,"minY":0,"maxY":3,"minZ":-2,"maxZ":2}"""))
            add("frames", JsonArray().apply {
                repeat(8) { index ->
                    add(JsonObject().apply {
                        add("joints", JsonObject().apply {
                            playback.sample(index.toDouble(), true).forEach { (name, point) ->
                                add(name, JsonArray().apply { point.forEach { add(it) } })
                            }
                        })
                    })
                }
            })
        }
    }

    @Test
    fun loadingPreservesValidatedRigAndUsesItForSceneBounds() {
        val payload = payload()
        val expected = FixedRigPlayback.parse(payload.getAsJsonObject("fixedRig"), 8)
        // Saved joints are deliberately stale: framing must evaluate the rig.
        payload.getAsJsonArray("frames").forEach { frame ->
            frame.asJsonObject.getAsJsonObject("joints").entrySet().forEach { (_, point) ->
                point.asJsonArray.set(0, com.google.gson.JsonPrimitive(100))
            }
        }
        val loaded = call("parseWearSkeleton", payload.toString())
        val actual = field(loaded, "fixedRig") as FixedRigPlayback
        for (cursor in listOf(0.0, 1.25, 7.5)) {
            expected.sample(cursor, true).forEach { (name, point) ->
                point.forEachIndexed { axis, coordinate ->
                    assertEquals(coordinate, checkNotNull(actual.sample(cursor, true)[name])[axis], 1e-9)
                }
            }
        }
        val palette = call("createSkeletonPalette", Color.White.value.toLong())
        val scene = call("toStableRenderedSceneCameraFrame", loaded, palette, 15f)
        val target = checkNotNull(field(scene, "target"))
        assertTrue(kotlin.math.abs(field(target, "x") as Float) < 10f)
    }

    @Test
    fun gridThicknessSurvivesSmallViewportsAndObliqueViews() {
        for (height in listOf(2.0, 12.0)) {
            for (pixels in listOf(160, 400)) {
                for (pitch in listOf(15f, 45f)) {
                    val halfWidth = call("floorLineHalfWidth", height, pixels, pitch) as Float
                    val projectedPixels = 2 * halfWidth * kotlin.math.sin(Math.toRadians(pitch.toDouble())) * pixels / height
                    assertTrue(projectedPixels >= 0.999999)
                    assertTrue(halfWidth >= 0.0023f)
                }
            }
        }
    }

    @Test
    fun gridCellsKeepTheirSizeAcrossDifferentMovementExtents() {
        val palette = call("createSkeletonPalette", Color.White.value.toLong())
        val scene = call("toStableRenderedSceneCameraFrame", call("parseWearSkeleton", payload().toString()), palette, 15f)
        val floor = checkNotNull(field(scene, "floor"))
        val constructor = floor.javaClass.declaredConstructors.single().apply { isAccessible = true }
        for (size in listOf(1.5f, 4f)) {
            val placement = constructor.newInstance(0f, 0f, 0f, size)
            val mesh = call("buildFloorMesh", placement, Color.White.value.toLong(), 0.0023f)
            val vertices = field(mesh, "poseVertices") as FloatArray
            val count = field(mesh, "vertexCount") as Int
            val stride = vertices.size / count
            assertEquals(0.0046f, vertices[stride] - vertices[0], 1e-6f)
            val lineCenters = (0 until count step 8).map { vertex ->
                (vertices[vertex * stride] + vertices[(vertex + 1) * stride]) * 0.5f
            }
            assertEquals((size / 0.25f).toInt() + 1, lineCenters.size)
            lineCenters.zipWithNext().forEach { (a, b) -> assertEquals(0.25f, b - a, 1e-6f) }
        }
    }

    @Test
    fun groundMetadataControlsPlacementAndCameraEnvelope() {
        val payload = payload().apply { addProperty("renderFloorY", -2f) }
        val palette = call("createSkeletonPalette", Color.White.value.toLong())
        val grounded = call("toStableRenderedSceneCameraFrame", call("parseWearSkeleton", payload.toString()), palette, 15f)
        assertEquals(-2f, field(checkNotNull(field(grounded, "floor")), "floorY") as Float, 0f)
        payload.addProperty("groundContactMode", "none")
        val airborne = call("toStableRenderedSceneCameraFrame", call("parseWearSkeleton", payload.toString()), palette, 15f)
        assertNull(field(airborne, "floor"))
        assertTrue((field(airborne, "orbitVerticalHalfExtent") as Float) <
            (field(grounded, "orbitVerticalHalfExtent") as Float))
        payload.remove("groundContactMode")
        payload.add("bakedPreviewConfiguration", JsonParser.parseString("""
            {"wearCoordinateNormalization":{"sceneInversionRemoved":true,"transform":"rotate_x_pi"}}
        """))
        val inverted = call("toStableRenderedSceneCameraFrame", call("parseWearSkeleton", payload.toString()), palette, 15f)
        assertEquals(2f, field(checkNotNull(field(inverted, "floor")), "floorY") as Float, 0f)
    }
}
