package com.gabstra.myworkoutassistant.motionrenderer

import com.google.gson.JsonParser
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.hypot

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

    @Test
    fun nativeMaterialContactKeepsBoundPointAndReturnsTheResolvedShoeSideAxis() {
        val data = fixture()
        val rigData = data.getAsJsonObject("rig").deepCopy()
        val names = rigData.getAsJsonArray("rotationJointNames").map { it.asString }
        val kneeSlot = 3 + names.indexOf("left_knee") * 3
        rigData.getAsJsonArray("coordinates")[1].asJsonArray[kneeSlot + 2] = com.google.gson.JsonPrimitive(
            rigData.getAsJsonArray("coordinates")[1].asJsonArray[kneeSlot + 2].asDouble + .12,
        )
        rigData.getAsJsonArray("coordinates")[1].asJsonArray[2] = com.google.gson.JsonPrimitive(
            rigData.getAsJsonArray("coordinates")[1].asJsonArray[2].asDouble + .04,
        )
        val baseline = FixedRigPlayback.parse(rigData.deepCopy(), 2)
        val raw = baseline.sample(.5, wrap = false)
        val rawAnkle = checkNotNull(raw["left_ankle"])
        val legLength = distance(checkNotNull(raw["left_ankle"]), checkNotNull(raw["left_foot"]))

        // The keys yaw by 20 degrees and twist their lateral basis by the same amount.
        val angle = Math.toRadians(20.0)
        val midDirection = normalizedForTest(doubleArrayOf(sin(Math.toRadians(80.0)), 0.0, cos(Math.toRadians(80.0))))
        val midSide = normalizedForTest(doubleArrayOf(-sin(angle) * .5, 0.0, (1.0 + cos(angle)) * .5))
        val midUp = doubleArrayOf(
            midSide[1] * midDirection[2] - midSide[2] * midDirection[1],
            midSide[2] * midDirection[0] - midSide[0] * midDirection[2],
            midSide[0] * midDirection[1] - midSide[1] * midDirection[0],
        )
        val contactTemplate = nativeContactFixture().getAsJsonObject("track")
        val episode = contactTemplate.getAsJsonObject("left").getAsJsonArray("episodes")[0].asJsonObject
        episode.addProperty("regionRole", "full_sole")
        val local = episode.getAsJsonArray("materialOffsetLocalMeters").map { it.asDouble }.toDoubleArray()
        val referenceLength = episode.get("referenceLengthMeters").asDouble
        val localScale = legLength / referenceLength
        val offset = DoubleArray(3) { i ->
            localScale * (midDirection[i] * local[0] + midSide[i] * local[1] + midUp[i] * local[2])
        }
        val target = DoubleArray(3) { rawAnkle[it] + offset[it] }
        val track = contactTemplate.deepCopy()
        val left = track.getAsJsonObject("left")
        left.getAsJsonArray("directions").set(0, vector(doubleArrayOf(1.0, 0.0, 0.0)))
        left.getAsJsonArray("directions").set(1, vector(doubleArrayOf(cos(angle), 0.0, sin(angle))))
        left.getAsJsonArray("sideAxes").set(0, vector(doubleArrayOf(0.0, 0.0, 1.0)))
        left.getAsJsonArray("sideAxes").set(1, vector(doubleArrayOf(-sin(angle), 0.0, cos(angle))))
        left.getAsJsonArray("episodes")[0].asJsonObject.add("targetWorld", vector(target))
        rigData.add("contactFootTracks", track)

        val repairedRig = parseNativeRig(rigData)
        val repaired = repairedRig.samplePose(.5, wrap = false)
        val ankle = checkNotNull(repaired.joints["left_ankle"])
        val ball = checkNotNull(repaired.joints["left_foot"])
        val direction = normalizedForTest(DoubleArray(3) { ball[it] - ankle[it] })
        val sideAxis = checkNotNull(repaired.contactSideAxes["left_ankle->left_foot"])
        assertEquals(1.0, distance(doubleArrayOf(0.0, 0.0, 0.0), sideAxis), 1e-8)
        assertEquals(0.0, (0..2).sumOf { sideAxis[it] * direction[it] }, 1e-8)
        val up = doubleArrayOf(
            sideAxis[1] * direction[2] - sideAxis[2] * direction[1],
            sideAxis[2] * direction[0] - sideAxis[0] * direction[2],
            sideAxis[0] * direction[1] - sideAxis[1] * direction[0],
        )
        val expectedOffset = DoubleArray(3) { i ->
            localScale * (direction[i] * local[0] + sideAxis[i] * local[1] + up[i] * local[2])
        }
        for (i in 0..2) assertEquals(target[i], ankle[i] + expectedOffset[i], 1e-8)
        assertEquals(legLength, distance(ankle, ball), 1e-8)
        assertTrue("material anchor should move the ball relative to raw FK", distance(raw["left_foot"]!!, ball) > .02)
        assertTrue("direction Hermite path should preserve the yaw change", direction[2] > .1)

        val verticalRigData = rigData.deepCopy()
        val verticalTrack = track.deepCopy()
        val verticalEpisode = verticalTrack.getAsJsonObject("left").getAsJsonArray("episodes")[0].asJsonObject
        verticalEpisode.addProperty("mode", "verticalOnly")
        verticalEpisode.remove("targetWorld")
        verticalEpisode.add("surfaceNormal", vector(doubleArrayOf(0.0, 1.0, 0.0)))
        verticalEpisode.addProperty("planeOffsetMeters", target[1])
        verticalRigData.add("contactFootTracks", verticalTrack)
        val nativeFixture = nativeContactFixture()
        val nativeGeometry = checkNotNull(parseNativeFootGeometry(nativeFixture))
        val sample = nativeFixture.getAsJsonObject("sample")
        val expectedMinFromAnchor = sample.get("nativeShoeMinY").asDouble -
            sample.getAsJsonArray("materialPointWorld")[1].asDouble
        val barycentric = sample.getAsJsonArray("barycentric").map { it.asDouble }
        val triangleIndex = sample.get("triangleIndex").asInt
        val footScale = sample.get("footScaleMeters").asFloat
        val scalePose = FixedRigPlayback.parse(fixture().getAsJsonObject("rig"), 2).sample(0.0, false)
        val canonicalFootScale = maxOf(
            distance(checkNotNull(scalePose["left_hip"]), checkNotNull(scalePose["right_hip"])) * .98,
            distance(checkNotNull(scalePose["left_shoulder"]), checkNotNull(scalePose["right_shoulder"])) * .58,
        )
        assertEquals("one first-rig-frame scale is shared with the rendered shoe mesh",
            footScale.toDouble(), canonicalFootScale, 2e-7)
        val originalMiddle = FixedRigPlayback.parse(fixture().getAsJsonObject("rig"), 2).samplePose(.5, false).joints
        assertTrue("fixture must include upstream knee articulation",
            distance(checkNotNull(originalMiddle["left_knee"]), checkNotNull(raw["left_knee"])) > .001)
        for (cursor in listOf(.5)) {
            val verticalPose = parseNativeRig(verticalRigData.deepCopy()).samplePose(cursor, false)
            val verticalAnkle = checkNotNull(verticalPose.joints["left_ankle"])
            val verticalBall = checkNotNull(verticalPose.joints["left_foot"])
            val verticalSide = checkNotNull(verticalPose.contactSideAxes["left_ankle->left_foot"])
            val shoe = nativeFootShoeVertices(
                WearSkeletonVec3(verticalAnkle[0].toFloat(), verticalAnkle[1].toFloat(), verticalAnkle[2].toFloat()),
                WearSkeletonVec3(verticalBall[0].toFloat(), verticalBall[1].toFloat(), verticalBall[2].toFloat()),
                WearSkeletonVec3(verticalSide[0].toFloat(), verticalSide[1].toFloat(), verticalSide[2].toFloat()),
                WearSkeletonVec3(verticalSide[0].toFloat(), verticalSide[1].toFloat(), verticalSide[2].toFloat()),
                nativeGeometry.left,
                footScale,
            )
            val vertices = shoe.rings.flatten() + listOf(shoe.rearTip, shoe.toeTip)
            val triangle = nativeShoeTriangles[triangleIndex]
            val materialY = triangle.indices.sumOf { barycentric[it] * vertices[triangle[it]].y }
            val minY = vertices.minOf { it.y.toDouble() }
            assertEquals("full-sole triangle remains on its horizontal support plane", target[1], materialY.toDouble(), 2e-5)
            assertEquals("whole native shoe extrema remain coherent through yaw and knee motion",
                target[1] + expectedMinFromAnchor, minY, 3e-5)
            assertTrue(vertices.all { it.y >= minY.toFloat() - 1e-5f })
        }
    }

    @Test(expected = IllegalArgumentException::class)
    fun nativeMaterialContactRejectsMalformedRecognizedTrack() {
        val rig = fixture().getAsJsonObject("rig")
        val track = JsonParser.parseString(checkNotNull(javaClass.classLoader?.getResource(
            "native_material_contact_tracks_v2.json")).readText()).asJsonObject.getAsJsonObject("track").deepCopy()
        track.getAsJsonObject("left").getAsJsonArray("episodes")[0].asJsonObject.addProperty("primitiveId", "wearShoe:right_ankle->right_foot")
        rig.add("contactFootTracks", track)
        parseNativeRig(rig)
    }

    @Test(expected = IllegalArgumentException::class)
    fun nativeMaterialContactRejectsOffsetThatDoesNotMatchNativeTriangle() {
        val rig = fixture().getAsJsonObject("rig")
        val track = nativeContactFixture().getAsJsonObject("track").deepCopy()
        val offset = track.getAsJsonObject("left").getAsJsonArray("episodes")[0].asJsonObject
            .getAsJsonArray("materialOffsetLocalMeters")
        offset[0] = com.google.gson.JsonPrimitive(offset[0].asDouble + .01)
        rig.add("contactFootTracks", track)
        parseNativeRig(rig)
    }

    private fun nativeContactFixture() = JsonParser.parseString(
        checkNotNull(javaClass.classLoader?.getResource("native_material_contact_tracks_v2.json")).readText(),
    ).asJsonObject

    @Test
    fun mirroredUnilateralNativeContactReflectsOtherLegAndInfersShoeAxis() {
        val rigData = fixture().getAsJsonObject("rig").deepCopy()
        val native = nativeContactFixture()
        val contact = native.getAsJsonObject("track").deepCopy()
        val raw = FixedRigPlayback.parse(rigData.deepCopy(), 2).samplePose(.5, false).joints
        val ankle = checkNotNull(raw["left_ankle"])
        val direction = normalizedForTest(DoubleArray(3) { raw["left_foot"]!![it] - ankle[it] })
        val sourceSide = contact.getAsJsonObject("left").getAsJsonArray("sideAxes")[0].asJsonArray.map { it.asDouble }.toDoubleArray()
        val side = normalizedForTest(DoubleArray(3) { sourceSide[it] - direction[it] * (0..2).sumOf { j -> sourceSide[j] * direction[j] } })
        val up = doubleArrayOf(
            side[1] * direction[2] - side[2] * direction[1],
            side[2] * direction[0] - side[0] * direction[2],
            side[0] * direction[1] - side[1] * direction[0],
        )
        val episode = contact.getAsJsonObject("left").getAsJsonArray("episodes")[0].asJsonObject
        val local = episode.getAsJsonArray("materialOffsetLocalMeters").map { it.asDouble }
        val scale = distance(ankle, checkNotNull(raw["left_foot"])) / episode.get("referenceLengthMeters").asDouble
        val target = DoubleArray(3) { i -> ankle[i] + scale * (direction[i] * local[0] + side[i] * local[1] + up[i] * local[2]) }
        episode.add("targetWorld", vector(target))
        rigData.add("contactFootTracks", contact)
        val execution = JsonObject().apply { addProperty("legs", "mirrored") }
        val rig = FixedRigPlayback.parse(
            rigData, 2, checkNotNull(parseNativeFootGeometry(native)), execution,
        )
        val pose = rig.samplePose(.5, wrap = false)
        val points = pose.joints
        val hips = checkNotNull(points["right_hip"]).zip(checkNotNull(points["left_hip"]))
            .map { it.first - it.second }.toDoubleArray()
        val axis = normalizedForTest(hips)
        for (part in listOf("knee", "ankle", "foot")) {
            val leftBone = DoubleArray(3) { points["left_$part"]!![it] - points["left_${if (part == "knee") "hip" else if (part == "ankle") "knee" else "ankle"}"]!![it] }
            val rightParent = if (part == "knee") "hip" else if (part == "ankle") "knee" else "ankle"
            val rightBone = DoubleArray(3) { points["right_$part"]!![it] - points["right_$rightParent"]!![it] }
            val reflected = DoubleArray(3) { leftBone[it] - 2 * (0..2).sumOf { j -> leftBone[j] * axis[j] } * axis[it] }
            for (i in 0..2) assertEquals(reflected[i], rightBone[i], 1e-8)
        }
        val inferredSide = checkNotNull(pose.contactSideAxes["right_ankle->right_foot"])
        val forward = normalizedForTest(DoubleArray(3) { points["right_foot"]!![it] - points["right_ankle"]!![it] })
        assertEquals(0.0, (0..2).sumOf { inferredSide[it] * forward[it] }, 1e-8)
        assertEquals(1.0, distance(doubleArrayOf(0.0, 0.0, 0.0), inferredSide), 1e-8)

        val noPolicy = FixedRigPlayback.parse(rigData.deepCopy(), 2, checkNotNull(parseNativeFootGeometry(native)))
            .samplePose(.5, false)
        assertEquals(raw["right_foot"]!![0], noPolicy.joints["right_foot"]!![0], 1e-9)
        val exactWithPolicy = rig.samplePose(0.0, false)
        val exactWithoutPolicy = noPolicyRig(rigData, native).samplePose(0.0, false)
        for (joint in exactWithPolicy.joints.keys) for (i in 0..2) {
            assertEquals(exactWithoutPolicy.joints[joint]!![i], exactWithPolicy.joints[joint]!![i], 1e-12)
        }
        val bothActive = contact.deepCopy().also {
            val right = it.getAsJsonObject("left").deepCopy()
            val rightAnkle = checkNotNull(raw["right_ankle"])
            val rightDirection = normalizedForTest(DoubleArray(3) { raw["right_foot"]!![it] - rightAnkle[it] })
            val rawRightSide = right.getAsJsonArray("sideAxes")[0].asJsonArray.map { it.asDouble }.toDoubleArray()
            val rightSide = normalizedForTest(DoubleArray(3) { rawRightSide[it] - rightDirection[it] * (0..2).sumOf { j -> rawRightSide[j] * rightDirection[j] } })
            val rightUp = doubleArrayOf(
                rightSide[1] * rightDirection[2] - rightSide[2] * rightDirection[1],
                rightSide[2] * rightDirection[0] - rightSide[0] * rightDirection[2],
                rightSide[0] * rightDirection[1] - rightSide[1] * rightDirection[0],
            )
            val rightTarget = DoubleArray(3) { i -> rightAnkle[i] + scale * (rightDirection[i] * local[0] + rightSide[i] * local[1] + rightUp[i] * local[2]) }
            right.getAsJsonArray("episodes")[0].asJsonObject.add("targetWorld", vector(rightTarget))
            right.getAsJsonArray("anchorIds").set(0, com.google.gson.JsonPrimitive("right:stationary:0"))
            right.getAsJsonArray("anchorIds").set(1, com.google.gson.JsonPrimitive("right:stationary:0"))
            right.getAsJsonArray("episodes")[0].asJsonObject.addProperty("anchorId", "right:stationary:0")
            right.getAsJsonArray("episodes")[0].asJsonObject.addProperty("primitiveId", "wearShoe:right_ankle->right_foot")
            it.add("right", right)
        }
        val bothRigData = rigData.deepCopy().also { it.add("contactFootTracks", bothActive) }
        val bothWithoutPolicy = FixedRigPlayback.parse(bothRigData.deepCopy(), 2, checkNotNull(parseNativeFootGeometry(native)))
            .samplePose(.5, false)
        val bothWithPolicy = FixedRigPlayback.parse(bothRigData, 2, checkNotNull(parseNativeFootGeometry(native)), execution)
            .samplePose(.5, false)
        for (joint in bothWithPolicy.joints.keys) for (i in 0..2) {
            assertEquals(bothWithoutPolicy.joints[joint]!![i], bothWithPolicy.joints[joint]!![i], 1e-12)
        }
    }

    @Test
    fun mirroredNativeContactBlendsRigidlyFromOriginalPoseAndMaterialFrame() {
        val native = nativeContactFixture()
        val animation = fixture().getAsJsonObject("rig").deepCopy()
        val contact = native.getAsJsonObject("track").deepCopy()
        val raw = FixedRigPlayback.parse(animation.deepCopy(), 2).samplePose(.5, false).joints
        val ankle = checkNotNull(raw["left_ankle"])
        val direction = normalizedForTest(DoubleArray(3) { raw["left_foot"]!![it] - ankle[it] })
        val sourceSide = contact.getAsJsonObject("left").getAsJsonArray("sideAxes")[0].asJsonArray
            .map { it.asDouble }.toDoubleArray()
        val side = normalizedForTest(DoubleArray(3) {
            sourceSide[it] - direction[it] * (0..2).sumOf { j -> sourceSide[j] * direction[j] }
        })
        val up = doubleArrayOf(
            side[1] * direction[2] - side[2] * direction[1],
            side[2] * direction[0] - side[0] * direction[2],
            side[0] * direction[1] - side[1] * direction[0],
        )
        val episode = contact.getAsJsonObject("left").getAsJsonArray("episodes")[0].asJsonObject
        val local = episode.getAsJsonArray("materialOffsetLocalMeters").map { it.asDouble }
        val scale = distance(ankle, checkNotNull(raw["left_foot"])) / episode.get("referenceLengthMeters").asDouble
        val target = DoubleArray(3) { i ->
            ankle[i] + scale * (direction[i] * local[0] + side[i] * local[1] + up[i] * local[2])
        }
        episode.add("targetWorld", vector(target))
        animation.add("contactFootTracks", contact)
        val execution = JsonObject().apply { addProperty("legs", "mirrored") }
        val nativeGeometry = checkNotNull(parseNativeFootGeometry(native))

        // Original material authority differs from the rendered inactive contact track.
        val originalForward = normalizedForTest(DoubleArray(3) { raw["right_foot"]!![it] - raw["right_ankle"]!![it] })
        val rawBaseline = normalizedForTest(doubleArrayOf(1.0, 0.0, 0.2))
        val baselineAxis = normalizedForTest(DoubleArray(3) {
            rawBaseline[it] - originalForward[it] * (0..2).sumOf { j -> rawBaseline[j] * originalForward[j] }
        })
        val baseline = mapOf("right_ankle->right_foot" to baselineAxis)

        val rig = FixedRigPlayback.parse(animation, 2, nativeGeometry, execution)
        val exact = rig.samplePose(0.0, false)
        val originalRight = listOf("right_hip", "right_knee", "right_ankle", "right_foot")
            .associateWith { checkNotNull(exact.joints[it]).copyOf() }

        // The interior envelope must drive the mirrored correction to zero at the key.
        val nearKey = rig.samplePose(1e-4, false, baseline)
        for (joint in listOf("right_knee", "right_ankle", "right_foot")) {
            assertTrue("$joint should approach the original FK pose at the key",
                distance(originalRight.getValue(joint), checkNotNull(nearKey.joints[joint])) < 1e-6)
        }
        val nearAxis = checkNotNull(nearKey.contactSideAxes["right_ankle->right_foot"])
        assertTrue("material side axis should approach the original rendered authority",
            dotForTest(nearAxis, baselineAxis) > 1 - 1e-6)

        // Full weight inside one stationary episode mirrors the corrected driver.
        val full = rig.samplePose(.5, false, baseline)
        val points = full.joints
        val hipAxis = normalizedForTest(DoubleArray(3) {
            checkNotNull(points["right_hip"])[it] - checkNotNull(points["left_hip"])[it]
        })
        for ((part, parent) in listOf("knee" to "hip", "ankle" to "knee", "foot" to "ankle")) {
            val leftBone = DoubleArray(3) { points["left_$part"]!![it] - points["left_$parent"]!![it] }
            val rightBone = DoubleArray(3) { points["right_$part"]!![it] - points["right_$parent"]!![it] }
            val reflected = DoubleArray(3) { leftBone[it] - 2 * (0..2).sumOf { j -> leftBone[j] * hipAxis[j] } * hipAxis[it] }
            for (i in 0..2) assertEquals("full-weight mirrored $part", reflected[i], rightBone[i], 1e-8)
            val originalLength = distance(
                originalRight.getValue("right_$parent"),
                originalRight.getValue("right_$part"),
            )
            assertEquals("rigid $part length", originalLength,
                distance(checkNotNull(points["right_$parent"]), checkNotNull(points["right_$part"])), 1e-9)
        }
        assertTrue("the original key pose is visibly different from the full mirror",
            distance(originalRight.getValue("right_foot"), checkNotNull(points["right_foot"])) > .01)
        val fullAxis = checkNotNull(full.contactSideAxes["right_ankle->right_foot"])
        val driverAxis = checkNotNull(full.contactSideAxes["left_ankle->left_foot"])
        val forward = normalizedForTest(DoubleArray(3) {
            points["right_foot"]!![it] - points["right_ankle"]!![it]
        })
        val reflectedDriver = DoubleArray(3) {
            -(driverAxis[it] - 2 * (0..2).sumOf { j -> driverAxis[j] * hipAxis[j] } * hipAxis[it])
        }
        val expectedAxis = normalizedForTest(DoubleArray(3) {
            reflectedDriver[it] - forward[it] * (0..2).sumOf { j -> reflectedDriver[j] * forward[j] }
        })
        for (i in 0..2) assertEquals("full-weight material frame", expectedAxis[i], fullAxis[i], 1e-8)
        assertTrue("full weight must not keep the original material frame", dotForTest(fullAxis, baselineAxis) < .999)

        // Protected knee keeps the original fractional FK pose, not frame zero.
        val kneeProtected = FixedRigPlayback.parse(
            animation.deepCopy().also { data -> data.add("supportJointTracks", supportTrack("right_knee")) },
            2, nativeGeometry, execution,
        ).samplePose(.5, false, baseline)
        for (i in 0..2) {
            assertEquals("protected knee stays at the original sample",
                raw.getValue("right_knee")[i], checkNotNull(kneeProtected.joints["right_knee"])[i], 1e-12)
        }
        for (part in listOf("ankle", "foot")) {
            val originalLength = distance(originalRight.getValue("right_$part"),
                checkNotNull(exact.joints["right_${if (part == "ankle") "knee" else "ankle"}"]))
            val parent = checkNotNull(kneeProtected.joints["right_${if (part == "ankle") "knee" else "ankle"}"])
            assertEquals("protected knee keeps rigid $part", originalLength,
                distance(parent, checkNotNull(kneeProtected.joints["right_$part"])), 1e-8)
            val parentName = if (part == "ankle") "knee" else "ankle"
            val driverBone = DoubleArray(3) {
                kneeProtected.joints["left_$part"]!![it] - kneeProtected.joints["left_$parentName"]!![it]
            }
            val reflected = DoubleArray(3) { driverBone[it] - 2 * dotForTest(driverBone,hipAxis)*hipAxis[it] }
            val oppositeBone = DoubleArray(3) { kneeProtected.joints["right_$part"]!![it]-parent[it] }
            assertArrayEquals("protected knee still reflects the distal $part segment",reflected,oppositeBone,1e-8)
        }

        // A protected distal contact skips all opposite propagation.
        for (joint in listOf("right_ankle", "right_foot")) {
            val skipped = FixedRigPlayback.parse(
                animation.deepCopy().also { data -> data.add("supportJointTracks", supportTrack(joint)) },
                2, nativeGeometry, execution,
            ).samplePose(.5, false, baseline)
            for (part in listOf("knee", "ankle", "foot")) {
                for (i in 0..2) assertEquals("protected $joint leaves right_$part untouched",
                    raw.getValue("right_$part")[i], checkNotNull(skipped.joints["right_$part"])[i], 1e-12)
            }
        }
    }

    @Test
    fun nativeDriverUsesOneBlendedFrameForContactAndRenderedMaterial() {
        val native = nativeContactFixture()
        val data = fixture().getAsJsonObject("rig").deepCopy()
        val rawRig = FixedRigPlayback.parse(data.deepCopy(), 2)
        val contact = native.getAsJsonObject("track").deepCopy()
        val episode = contact.getAsJsonObject("left").getAsJsonArray("episodes")[0].asJsonObject
        val local = episode.getAsJsonArray("materialOffsetLocalMeters").map { it.asDouble }
        val target = episode.getAsJsonArray("targetWorld").map { it.asDouble }.toDoubleArray()
        data.add("contactFootTracks", contact)
        val raw = rawRig.samplePose(0.0, false).joints
        val forward = normalizedForTest(DoubleArray(3) { raw["left_foot"]!![it]-raw["left_ankle"]!![it] })
        val proposedSide = doubleArrayOf(.3, .2, 1.0)
        val baseline = normalizedForTest(DoubleArray(3) { proposedSide[it]-forward[it]*dotForTest(proposedSide,forward) })
        val axes = mapOf("left_ankle->left_foot" to baseline)
        data.add("materialFrames",JsonObject().apply {
            addProperty("version",1);add("referenceCoordinates",data.getAsJsonArray("coordinates").deepCopy())
            add("referenceBoneSides",JsonObject().apply {
                for (leg in listOf("left","right")) {
                    val f=normalizedForTest(DoubleArray(3) { raw["${leg}_foot"]!![it]-raw["${leg}_ankle"]!![it] })
                    val side=normalizedForTest(DoubleArray(3) { proposedSide[it]-f[it]*dotForTest(proposedSide,f) })
                    add("${leg}_ankle->${leg}_foot",vectorRows(listOf(side,side)))
                }
            })
        })
        val rig = FixedRigPlayback.parse(data, 2, checkNotNull(parseNativeFootGeometry(native)))
        val exact = rig.samplePose(0.0, false, axes)
        assertArrayEquals(raw["left_ankle"],exact.joints["left_ankle"],1e-12)
        assertArrayEquals(baseline,exact.contactSideAxes["left_ankle->left_foot"],1e-12)
        val ratio = distance(raw["left_ankle"]!!,raw["left_foot"]!!)/episode.get("referenceLengthMeters").asDouble
        fun marker(pose: FixedRigPose, ankleOverride: DoubleArray? = null): DoubleArray {
            val ankle = pose.joints["left_ankle"]!!
            val f = normalizedForTest(DoubleArray(3) { pose.joints["left_foot"]!![it]-ankle[it] })
            val side = pose.contactSideAxes["left_ankle->left_foot"]!!
            val up = doubleArrayOf(side[1]*f[2]-side[2]*f[1],side[2]*f[0]-side[0]*f[2],side[0]*f[1]-side[1]*f[0])
            return DoubleArray(3) { (ankleOverride ?: ankle)[it]+ratio*(f[it]*local[0]+side[it]*local[1]+up[it]*local[2]) }
        }
        val near = rig.samplePose(1e-5,false,axes)
        assertTrue("driver material approaches original key frame", distance(marker(exact),marker(near))<1e-7)
        assertTrue("driver side approaches serialized authority",distance(baseline,near.contactSideAxes["left_ankle->left_foot"]!!)<1e-7)
        fun vertices(pose: FixedRigPose): List<WearSkeletonVec3> {
            fun vector(value: DoubleArray) = WearSkeletonVec3(value[0].toFloat(),value[1].toFloat(),value[2].toFloat())
            val side = vector(pose.contactSideAxes["left_ankle->left_foot"]!!)
            val shoe = nativeFootShoeVertices(vector(pose.joints["left_ankle"]!!),
                vector(pose.joints["left_foot"]!!),side,side,
                checkNotNull(parseNativeFootGeometry(native)).left,
                native.getAsJsonObject("sample").get("footScaleMeters").asFloat)
            return shoe.rings.flatten()+listOf(shoe.rearTip,shoe.toeTip)
        }
        vertices(exact).zip(vertices(near)).forEach { (a,b) ->
            assertEquals(a.x.toDouble(),b.x.toDouble(),2e-7)
            assertEquals(a.y.toDouble(),b.y.toDouble(),2e-7)
            assertEquals(a.z.toDouble(),b.z.toDouble(),2e-7)
        }
        val alpha=.25
        val pose=rig.samplePose(alpha,false,axes)
        val rawAnkle=rawRig.samplePose(alpha,false).joints["left_ankle"]!!
        val before=marker(pose,rawAnkle)
        val weight=16*alpha*alpha*(1-alpha)*(1-alpha)
        val expected=DoubleArray(3) { before[it]+weight*(target[it]-before[it]) }
        assertArrayEquals("rendered material uses the target solver's exact blended frame",expected,marker(pose),1e-9)
    }

    @Test
    fun fullFkMaterialFramesPreserveTerminalTwistAtKeysFractionsAndSeam() {
        val data=fixture().getAsJsonObject("rig").deepCopy()
        data.addProperty("interpolation","limited_quaternion_hermite_v2")
        val names=data.getAsJsonArray("jointNames").map { it.asString }
        val rotations=data.getAsJsonArray("rotationJointNames").map { it.asString }
        val foot=names.indexOf("right_foot")
        val slot=3+3*rotations.indexOf("right_foot")
        val offset=data.getAsJsonArray("offsets")[foot].asJsonArray.map { it.asDouble }.toDoubleArray()
        val axis=normalizedForTest(offset)
        val candidate=doubleArrayOf(1.0,0.0,0.0)
        val side=normalizedForTest(DoubleArray(3) { candidate[it]-axis[it]*dotForTest(candidate,axis) })
        fun rotate(v: DoubleArray, angle: Double): DoubleArray {
            val cross=doubleArrayOf(axis[1]*v[2]-axis[2]*v[1],axis[2]*v[0]-axis[0]*v[2],axis[0]*v[1]-axis[1]*v[0])
            return DoubleArray(3) { v[it]*cos(angle)+cross[it]*sin(angle)+axis[it]*dotForTest(axis,v)*(1-cos(angle)) }
        }
        // Nonzero reference local rotation commutes with the local-offset twist:
        // exp(.2*axis) * exp(delta*axis), not an arbitrary rotvec component edit.
        for (row in data.getAsJsonArray("coordinates")) {
            for (i in 3 until row.asJsonArray.size()) row.asJsonArray.set(i,com.google.gson.JsonPrimitive(0.0))
            for (i in 0..2) row.asJsonArray.set(slot+i,com.google.gson.JsonPrimitive(.2*axis[i]))
        }
        val material=JsonObject().apply {
            addProperty("version",1)
            add("referenceCoordinates",data.getAsJsonArray("coordinates").deepCopy())
            add("referenceBoneSides",JsonObject().apply {
                for (leg in listOf("left","right")) {
                    val localOffset=data.getAsJsonArray("offsets")[names.indexOf("${leg}_foot")].asJsonArray.map { it.asDouble }.toDoubleArray()
                    val forward=normalizedForTest(localOffset)
                    val lateral=normalizedForTest(DoubleArray(3) { candidate[it]-forward[it]*dotForTest(candidate,forward) })
                    add("${leg}_ankle->${leg}_foot",vectorRows(listOf(lateral,lateral)))
                }
            })
        }
        val original=FixedRigPlayback.parse(data.deepCopy(),2)
        data.add("materialFrames",material)
        for ((index,row) in data.getAsJsonArray("coordinates").withIndex()) {
            for (i in 0..2) row.asJsonArray.set(slot+i,com.google.gson.JsonPrimitive((.3+.1*index)*axis[i]))
        }
        val rig=FixedRigPlayback.parse(data,2)
        val native=nativeContactFixture()
        val geometry=checkNotNull(parseNativeFootGeometry(native)).right
        fun vertices(pose: FixedRigPose, lateral: DoubleArray): List<WearSkeletonVec3> {
            fun vector(v: DoubleArray)=WearSkeletonVec3(v[0].toFloat(),v[1].toFloat(),v[2].toFloat())
            val shoe=nativeFootShoeVertices(vector(pose.joints["right_ankle"]!!),vector(pose.joints["right_foot"]!!),
                vector(lateral),vector(lateral),geometry,native.getAsJsonObject("sample").get("footScaleMeters").asFloat)
            return shoe.rings.flatten()+listOf(shoe.rearTip,shoe.toeTip)
        }
        for ((cursor,angle) in listOf(0.0 to .1,.5 to .15,1.0 to .2,1.5 to .15)) {
            val pose=rig.samplePose(cursor,true,mapOf("right_ankle->right_foot" to doubleArrayOf(1.0,0.0,0.0)))
            val before=original.samplePose(cursor,true)
            for (name in names) assertArrayEquals("pure twist leaves $name unchanged",before.joints[name],pose.joints[name],1e-12)
            val actual=pose.contactSideAxes["right_ankle->right_foot"]!!
            assertArrayEquals("full FK side at $cursor",rotate(side,angle),actual,1e-10)
            val expected=vertices(pose,rotate(side,angle));val rendered=vertices(pose,actual)
            rendered.zip(expected).forEach { (a,b) -> assertEquals(a,b) }
            assertTrue("native vertices must move under terminal twist",
                vertices(before,side).zip(rendered).any { (a,b) -> kotlin.math.abs(a.y-b.y)+kotlin.math.abs(a.z-b.z)+kotlin.math.abs(a.x-b.x)>.001 })
        }
        material.add("stationaryLocalBindings",JsonObject().apply {
            add("right_ankle->right_foot",JsonArray().apply { add(JsonObject().apply {
                addProperty("startFrame",0);addProperty("endFrame",1);addProperty("anchorId","sole-a")
                add("activeFrames",JsonArray().apply { add(0);add(1) });add("localSideAxis",vector(side))
            }) })
        })
        val bound=FixedRigPlayback.parse(data,2)
        for ((cursor,angle) in listOf(0.0 to .3,.5 to .35,1.0 to .4,1.5 to .15)) {
            assertArrayEquals("frozen local axis with inclusive interval at $cursor",rotate(side,angle),
                bound.samplePose(cursor,true).contactSideAxes["right_ankle->right_foot"],1e-10)
        }
        for (bad in listOf<(JsonObject)->Unit>(
            { it.addProperty("version",2) },
            { it.add("referenceCoordinates",JsonArray()) },
            { it.getAsJsonObject("referenceBoneSides").remove("left_ankle->left_foot") },
            { it.getAsJsonObject("stationaryLocalBindings").getAsJsonArray("right_ankle->right_foot")[0].asJsonObject.add("activeFrames",JsonArray().apply { add(1);add(0) }) },
        )) {
            val malformed=data.deepCopy();bad(malformed.getAsJsonObject("materialFrames"))
            try { FixedRigPlayback.parse(malformed,2);throw AssertionError("malformed materialFrames accepted") }
            catch (_: IllegalArgumentException) { }
        }
    }

    private fun supportTrack(joint: String) = JsonObject().apply {
        addProperty("version", 1)
        addProperty("source", "validated_stationary_body_support")
        add("joints", JsonObject().apply {
            add(joint, JsonObject().apply {
                add("episodeIds", JsonArray().also { it.add("support-a"); it.add("support-a") })
            })
        })
    }

    @Test
    fun validatedSupportEpisodeKeepsKneeFixedAndProjectsNativeShoeAtKeysFractionsAndSeam() {
        val native = nativeContactFixture()
        val rigData = fixture().getAsJsonObject("rig").deepCopy()
        val contact = native.getAsJsonObject("track").deepCopy()
        val raw = FixedRigPlayback.parse(rigData.deepCopy(), 2).samplePose(.5, false).joints
        val rawAnkle = checkNotNull(raw["left_ankle"])
        val rawFoot = checkNotNull(raw["left_foot"])
        val rawDirection = normalizedForTest(DoubleArray(3) { rawFoot[it] - rawAnkle[it] })
        val episode = contact.getAsJsonObject("left").getAsJsonArray("episodes")[0].asJsonObject
        val local = episode.getAsJsonArray("materialOffsetLocalMeters").map { it.asDouble }
        val referenceLength = episode.get("referenceLengthMeters").asDouble
        val rawSide = contact.getAsJsonObject("left").getAsJsonArray("sideAxes")[0].asJsonArray.map { it.asDouble }.toDoubleArray()
        val side = normalizedForTest(DoubleArray(3) { rawSide[it] - rawDirection[it] * (0..2).sumOf { j -> rawSide[j] * rawDirection[j] } })
        val up = doubleArrayOf(
            side[1] * rawDirection[2] - side[2] * rawDirection[1],
            side[2] * rawDirection[0] - side[0] * rawDirection[2],
            side[0] * rawDirection[1] - side[1] * rawDirection[0],
        )
        val footLength = distance(rawAnkle, rawFoot)
        val ratio = footLength / referenceLength
        val material = DoubleArray(3) { i -> rawAnkle[i] + ratio * (rawDirection[i] * local[0] + side[i] * local[1] + up[i] * local[2]) }
        val target = material.copyOf().also { it[2] += .01 }
        episode.add("targetWorld", vector(target))
        rigData.add("contactFootTracks", contact)
        val support = JsonObject().apply {
            addProperty("version", 1)
            addProperty("source", "validated_stationary_body_support")
            add("joints", JsonObject().apply {
                add("left_knee", JsonObject().apply {
                    add("episodeIds", JsonArray().also { it.add("body-support-a"); it.add("body-support-a") })
                })
            })
        }
        rigData.add("supportJointTracks", support)
        val rig = FixedRigPlayback.parse(rigData, 2, checkNotNull(parseNativeFootGeometry(native)))
        for (cursor in listOf(0.0, .5, 1.5)) {
            val pose = rig.samplePose(cursor, wrap = cursor == 1.5)
            val knee = checkNotNull(pose.joints["left_knee"])
            val baselineKnee = checkNotNull(FixedRigPlayback.parse(fixture().getAsJsonObject("rig"), 2)
                .samplePose(cursor, wrap = cursor == 1.5).joints["left_knee"])
            for (i in 0..2) assertEquals("protected knee at cursor $cursor", baselineKnee[i], knee[i], 1e-9)
            val ankle = checkNotNull(pose.joints["left_ankle"])
            val toe = checkNotNull(pose.joints["left_foot"])
            val axis = checkNotNull(pose.contactSideAxes["left_ankle->left_foot"])
            assertEquals(footLength, distance(ankle, toe), 1e-8)
            assertEquals(distance(checkNotNull(raw["left_knee"]), rawAnkle), distance(knee, ankle), 1e-7)
            assertEquals(1.0, distance(doubleArrayOf(0.0, 0.0, 0.0), axis), 1e-8)
            assertEquals(0.0, (0..2).sumOf { axis[it] * (toe[it] - ankle[it]) }, 1e-8)
            val forward = normalizedForTest(DoubleArray(3) { toe[it] - ankle[it] })
            val shoeUp = doubleArrayOf(
                axis[1] * forward[2] - axis[2] * forward[1],
                axis[2] * forward[0] - axis[0] * forward[2],
                axis[0] * forward[1] - axis[1] * forward[0],
            )
            val boundPoint = DoubleArray(3) { i ->
                ankle[i] + ratio * (forward[i] * local[0] + axis[i] * local[1] + shoeUp[i] * local[2])
            }
            for (i in 0..2) assertEquals("material target at cursor $cursor", target[i], boundPoint[i], 1e-6)
        }

        for (ids in listOf(listOf("body-support-a", "body-support-b"), listOf("body-support-a", null), listOf(null, null))) {
            val transitioned = rigData.deepCopy().also { data ->
                data.getAsJsonObject("supportJointTracks").getAsJsonObject("joints")
                    .getAsJsonObject("left_knee").add("episodeIds", JsonArray().also { a -> ids.forEach { if (it == null) a.add(com.google.gson.JsonNull.INSTANCE) else a.add(it) } })
            }
            val transitionedPose = FixedRigPlayback.parse(transitioned, 2, checkNotNull(parseNativeFootGeometry(native)))
                .samplePose(.5, false)
            val legacyData = rigData.deepCopy().also { it.remove("supportJointTracks") }
            val legacyPose = FixedRigPlayback.parse(legacyData, 2, checkNotNull(parseNativeFootGeometry(native)))
                .samplePose(.5, false)
            for (i in 0..2) assertEquals(legacyPose.joints["left_knee"]!![i], transitionedPose.joints["left_knee"]!![i], 1e-10)
        }
    }

    @Test(expected = IllegalArgumentException::class)
    fun malformedSupportJointTrackIsRejected() {
        val data = fixture().getAsJsonObject("rig")
        data.add("supportJointTracks", JsonObject().apply {
            addProperty("version", 1)
            addProperty("source", "validated_stationary_body_support")
            add("joints", JsonObject().apply {
                add("left_knee", JsonObject().apply { add("episodeIds", JsonArray().also { it.add("too-few") }) })
            })
        })
        FixedRigPlayback.parse(data, 2)
    }

    private fun noPolicyRig(rig: JsonObject, native: JsonObject) = FixedRigPlayback.parse(
        rig.deepCopy(), 2, checkNotNull(parseNativeFootGeometry(native)),
    )

    private fun parseNativeRig(rig: JsonObject): FixedRigPlayback {
        val contract = nativeContactFixture()
        return FixedRigPlayback.parse(
            rig,
            2,
            checkNotNull(parseNativeFootGeometry(contract)),
        )
    }

    private fun contactTrack(active: List<Boolean>, toes: List<DoubleArray>, directions: List<DoubleArray>) = JsonObject().apply {
        add("active", JsonArray().also { array -> active.forEach { array.add(it) } })
        add("toes", vectorRows(toes))
        add("directions", vectorRows(directions))
    }

    private fun vectorRows(values: List<DoubleArray>) = JsonArray().also { rows ->
        values.forEach { vector -> rows.add(JsonArray().also { row -> vector.forEach(row::add) }) }
    }

    private fun vector(values: DoubleArray) = JsonArray().also { row -> values.forEach(row::add) }

    private fun normalizedForTest(value: DoubleArray): DoubleArray {
        val norm = distance(doubleArrayOf(0.0, 0.0, 0.0), value)
        return DoubleArray(3) { value[it] / norm }
    }

    private fun directionAtYaw(yaw: Double) = doubleArrayOf(sin(yaw), 0.0, cos(yaw))

    private fun distance(a: DoubleArray, b: DoubleArray) = kotlin.math.sqrt((0..2).sumOf { (a[it] - b[it]) * (a[it] - b[it]) })

    private fun dotForTest(a: DoubleArray, b: DoubleArray) = (0..2).sumOf { a[it] * b[it] }
}
