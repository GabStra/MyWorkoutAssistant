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
        val firstFrame = (field(loaded, "frames") as List<*>).first()
        assertEquals(emptyMap<String, Any>(), field(firstFrame!!, "shoeOrientation"))
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
    fun shoeMaterialBasisLoadsAndInterpolatesAsAnOrthonormalFrame() {
        val payload = payload()
        val frames = payload.getAsJsonArray("frames")
        frames[0].asJsonObject.add("shoeOrientation", shoeOrientation(
            forward = listOf(0f, 0f, 1f),
            side = listOf(1f, 0f, 0f),
        ))
        frames[1].asJsonObject.add("shoeOrientation", shoeOrientation(
            forward = listOf(0.2f, 0f, 0.98f),
            side = listOf(0.98f, 0f, -0.2f),
        ))

        val skeleton = call("parseWearSkeleton", payload.toString())
        val frame = call("frameAt", skeleton, 0.5)
        val orientations = field(frame, "shoeOrientation") as Map<*, *>
        val left = checkNotNull(orientations["left"])
        val forward = field(left, "forward")
        val side = field(left, "side")
        val forwardLength = vectorLength(forward)
        val sideLength = vectorLength(side)
        val dot = vectorDot(forward, side)
        assertEquals(1f, forwardLength, 1e-5f)
        assertEquals(1f, sideLength, 1e-5f)
        assertEquals(0f, dot, 1e-5f)
        assertTrue((field(checkNotNull(forward), "z") as Float) > 0.99f)
        assertTrue((field(checkNotNull(side), "x") as Float) > 0.99f)
    }

    @Test
    fun explicitShoeBasisKeepsForefootPivotAndIgnoresStaticRestPitch() {
        val meshClass = Class.forName("com.gabstra.myworkoutassistant.motionrenderer.GeneratedLowPolyMesh")
        val vecClass = Class.forName("com.gabstra.myworkoutassistant.motionrenderer.WearSkeletonVec3")
        fun vector(x: Float, y: Float, z: Float): Any = vecClass.declaredConstructors.single().apply {
            isAccessible = true
        }.newInstance(x, y, z)
        val ankle = vector(0f, 0f, 0f)
        val foot = vector(0f, 0f, 0.2f)
        val axesClass = Class.forName("com.gabstra.myworkoutassistant.motionrenderer.BodyAxes")
        val axes = axesClass.declaredConstructors.single().apply { isAccessible = true }
            .newInstance(vector(-1f, 0f, 0f), vector(0f, 1f, 0f), vector(0f, 0f, 1f))
        val orientationClass = Class.forName("com.gabstra.myworkoutassistant.motionrenderer.WearSkeletonShoeOrientation")
        val orientation = orientationClass.declaredConstructors.single().apply { isAccessible = true }
            .newInstance(vector(0f, 0f, 1f), vector(-1f, 0f, 0f))
        val palette = call("createSkeletonPalette", Color.White.value.toLong())
        val renderShoe = renderer.declaredMethods.single {
            it.name == "addShoeBlockFromNames" && it.parameterCount == 10
        }.apply { isAccessible = true }
        fun build(restPitch: Float): List<Any> {
            val mesh = meshClass.declaredConstructors.single { it.parameterCount == 0 }
                .apply { isAccessible = true }.newInstance()
            renderShoe.invoke(
                null,
                mesh,
                mapOf("left_ankle" to ankle, "left_foot" to foot),
                "left_ankle",
                "left_foot",
                axes,
                0.3f,
                palette,
                null,
                restPitch,
                orientation,
            )
            @Suppress("UNCHECKED_CAST")
            return field(mesh, "vertices") as List<Any>
        }
        val unpitchedVertices = build(0f)
        val pitchedVertices = build(0.7f)
        assertEquals(unpitchedVertices.size, pitchedVertices.size)
        unpitchedVertices.zip(pitchedVertices).forEach { (before, after) ->
            for (axis in listOf("x", "y", "z")) {
                assertEquals(field(before, axis) as Float, field(after, axis) as Float, 1e-6f)
            }
        }
        val maximumForward = unpitchedVertices.maxOf { field(it, "z") as Float }
        assertEquals(0.2f + 0.056f * 0.20f, maximumForward, 1e-5f)
    }

    private fun shoeOrientation(forward: List<Float>, side: List<Float>) = JsonObject().apply {
        add("left", JsonObject().apply {
            add("forward", JsonArray().apply { forward.forEach(::add) })
            add("side", JsonArray().apply { side.forEach(::add) })
        })
    }

    private fun vectorLength(vector: Any?): Float {
        val x = field(checkNotNull(vector), "x") as Float
        val y = field(checkNotNull(vector), "y") as Float
        val z = field(checkNotNull(vector), "z") as Float
        return kotlin.math.sqrt(x * x + y * y + z * z)
    }

    private fun vectorDot(first: Any?, second: Any?): Float {
        val a = checkNotNull(first)
        val b = checkNotNull(second)
        return (field(a, "x") as Float) * (field(b, "x") as Float) +
            (field(a, "y") as Float) * (field(b, "y") as Float) +
            (field(a, "z") as Float) * (field(b, "z") as Float)
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
