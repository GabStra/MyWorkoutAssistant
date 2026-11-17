package com.gabstra.myworkoutassistant.motionrenderer

import com.google.gson.JsonObject
import kotlin.math.acos
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min
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
    private val contactFootTracks: Map<String, ContactFootTrack>,
    private val canonicalExecution: JsonObject?,
    private val supportJointTracks: Map<String, Array<String?>>,
    private val materialFrames: MaterialFrames? = null,
) {
    private val roots = coordinates.map { it.copyOfRange(0, 3) }.toTypedArray()
    private fun rotationTracks(values: Array<DoubleArray>) = rotationSlots.map { slot ->
        if (slot < 0 || !continuousVelocity) null else values.map {
            RigQuaternion.fromRotationVector(it, slot).toArray()
        }.toTypedArray()
    }
    private val quaternionTracks = rotationTracks(coordinates)
    private val referenceQuaternionTracks = materialFrames?.let { rotationTracks(it.coordinates) }
    val hasMaterialFrames: Boolean get() = materialFrames != null

    private fun globalRotations(
        values: Array<DoubleArray>, tracks: List<Array<DoubleArray>?>,
        first: Int, last: Int, alpha: Double, wrap: Boolean,
    ): Array<RigQuaternion> {
        val rotations = Array(jointNames.size) { RigQuaternion.Identity }
        for (joint in order) {
            val slot = rotationSlots[joint]
            val local = if (slot < 0) RigQuaternion.Identity else if (continuousVelocity) {
                val q = interpolateRigTrack(checkNotNull(tracks[joint]), first, last, alpha, wrap, true, smoothLimiter)
                RigQuaternion(q[0], q[1], q[2], q[3])
            } else RigQuaternion.fromRotationVector(values[first], slot)
                .slerp(RigQuaternion.fromRotationVector(values[last], slot), alpha)
            rotations[joint] = if (parents[joint] < 0) local else rotations[parents[joint]] * local
        }
        return rotations
    }

    private fun materialAxes(
        rotations: Array<RigQuaternion>, first: Int, last: Int, alpha: Double, wrap: Boolean,
    ): Map<String, DoubleArray> {
        val binding = materialFrames ?: return emptyMap()
        val reference = globalRotations(binding.coordinates,checkNotNull(referenceQuaternionTracks),first,last,alpha,wrap)
        return binding.sides.mapValues { (key, sides) ->
            val foot = jointNames.indexOf(key.substringAfter("->"))
            val frozen = binding.stationary[key].orEmpty().firstOrNull {
                first + alpha >= it.startFrame && first + alpha <= it.endFrame &&
                    first in it.activeFrames && (alpha == 0.0 || last in it.activeFrames)
            }
            val local = frozen?.localSide ?: run {
                val side = if (continuousVelocity) interpolateRigTrack(sides,first,last,alpha,wrap,false,smoothLimiter)
                    else DoubleArray(3) { sides[first][it]*(1-alpha)+sides[last][it]*alpha }
                reference[foot].inverseRotate(side)
            }
            val world = rotations[foot].rotate(local)
            val forward = normalized(rotations[foot].rotate(offsets[foot]),"material foot direction")
            normalized(DoubleArray(3) { world[it]-forward[it]*dot(world,forward) },"material frame side")
        }
    }

    fun sample(cursor: Double, wrap: Boolean): Map<String, DoubleArray> = samplePose(cursor, wrap).joints

    fun samplePose(
        cursor: Double,
        wrap: Boolean,
        originalMaterialSideAxes: Map<String, DoubleArray> = emptyMap(),
    ): FixedRigPose {
        val count = coordinates.size
        val bounded = if (wrap) ((cursor % count) + count) % count else cursor.coerceIn(0.0, count - 1.0)
        val first = bounded.toInt()
        val last = if (wrap) (first + 1) % count else (first + 1).coerceAtMost(count - 1)
        val alpha = bounded - first
        val a = coordinates[first]
        val b = coordinates[last]
        val rotations = globalRotations(coordinates,quaternionTracks,first,last,alpha,wrap)
        val points = Array(jointNames.size) { DoubleArray(3) }
        for (joint in order) {
            val parent = parents[joint]
            points[joint] = if (parent < 0) {
                if (continuousVelocity) interpolateRigTrack(roots, first, last, alpha, wrap, false, smoothLimiter)
                else DoubleArray(3) { a[it] * (1 - alpha) + b[it] * alpha }
            } else {
                val offset = rotations[joint].rotate(offsets[joint])
                DoubleArray(3) { points[parent][it] + offset[it] }
            }
        }
        // Native contact solving mutates the FK pose in place, so keep the
        // untouched sample for the mirrored chain and its material baseline.
        val originalPoints = Array(points.size) { points[it].copyOf() }
        val baselineAxes = if (hasMaterialFrames) materialAxes(rotations,first,last,alpha,wrap)
            else originalMaterialSideAxes
        val contactSideAxes = if (hasMaterialFrames) baselineAxes.toMutableMap()
            else mutableMapOf<String, DoubleArray>()
        if (alpha != 0.0) {
            contactFootTracks.forEach { (side, track) ->
                val firstActive = track.active[first]
                val lastActive = track.active[last]
                val transitionWeight = when {
                    firstActive && lastActive -> 1.0
                    !firstActive && !lastActive -> 0.0
                    lastActive -> smoothStep(alpha)
                    else -> 1.0 - smoothStep(alpha)
                }
                val weight = if (track.version == 2) mirrorContactWeight(track, first, last, alpha) else transitionWeight
                if (weight > 0.0) {
                    applyContactFootPose(points, side, track, first, last, alpha, wrap, weight,
                        protectedSupportId("${side}_knee", first, last, alpha),
                        baselineAxes["${side}_ankle->${side}_foot"])?.let {
                        contactSideAxes["${side}_ankle->${side}_foot"] = it
                    }
                }
            }
        } else {
            contactFootTracks.forEach { (side, track) ->
                if (track.version != 2 || !track.active[first]) return@forEach
                val protectedId = protectedSupportId("${side}_knee", first, last, alpha)
                if (protectedId != null) {
                    applyContactFootPose(points, side, track, first, first, 0.0, wrap, 1.0, protectedId, baselineAxes["${side}_ankle->${side}_foot"])?.let {
                        contactSideAxes["${side}_ankle->${side}_foot"] = it
                    }
                    return@forEach
                }
                val direction = normalized(subtract(points[jointNames.indexOf("${side}_foot")], points[jointNames.indexOf("${side}_ankle")]), "$side exact-key foot direction")
                val sideAxis = baselineAxes["${side}_ankle->${side}_foot"]
                    ?: checkNotNull(track.sideAxes)[first]
                contactSideAxes["${side}_ankle->${side}_foot"] = normalized(
                    DoubleArray(3) { sideAxis[it] - direction[it] * dot(sideAxis, direction) },
                    "$side exact-key side axis",
                )
            }
        }
        if (canonicalExecution?.get("legs")?.asString == "mirrored" && alpha > 1e-12 && alpha < 1.0 - 1e-12) {
            val leftWeight = mirrorContactWeight(contactFootTracks["left"], first, last, alpha)
            val rightWeight = mirrorContactWeight(contactFootTracks["right"], first, last, alpha)
            val leftActive = leftWeight > 0.0
            val rightActive = rightWeight > 0.0
            if (leftActive xor rightActive) {
                val driver = if (leftActive) "left" else "right"
                val opposite = if (leftActive) "right" else "left"
                val mirrorWeight = if (leftActive) leftWeight else rightWeight
                val oppositeAnkleProtected = protectedSupportId("${opposite}_ankle", first, last, alpha) != null
                val oppositeFootProtected = protectedSupportId("${opposite}_foot", first, last, alpha) != null
                if (!oppositeAnkleProtected && !oppositeFootProtected) {
                    for (part in listOf("knee", "ankle", "foot")) {
                        val leftLength = length(offsets[jointNames.indexOf("left_$part")])
                        val rightLength = length(offsets[jointNames.indexOf("right_$part")])
                        require(kotlin.math.abs(leftLength - rightLength) <= 1e-6 + 1e-6 * max(leftLength, rightLength)) {
                            "Mirrored native contact requires equal paired leg lengths"
                        }
                    }
                    val leftHip = points[jointNames.indexOf("left_hip")]
                    val rightHip = points[jointNames.indexOf("right_hip")]
                    val hipAxis = normalized(subtract(rightHip, leftHip), "mirrored hip axis")
                    val driverIndices = listOf("hip", "knee", "ankle", "foot").map { jointNames.indexOf("${driver}_$it") }
                    val oppositeIndices = listOf("hip", "knee", "ankle", "foot").map { jointNames.indexOf("${opposite}_$it") }
                    val oppositeKneeProtected = protectedSupportId("${opposite}_knee", first, last, alpha) != null
                    val firstBone = if (oppositeKneeProtected) 2 else 1
                    for (index in firstBone..3) {
                        // Rotate each original rigid segment toward the reflected
                        // driver direction; blending Cartesian points would
                        // shorten the paired bones.
                        val original = subtract(
                            originalPoints[oppositeIndices[index]],
                            originalPoints[oppositeIndices[index - 1]],
                        )
                        val driverBone = subtract(points[driverIndices[index]], points[driverIndices[index - 1]])
                        val mirrored = DoubleArray(3) { driverBone[it] - 2.0 * dot(driverBone, hipAxis) * hipAxis[it] }
                        val blended = blendRigidBone(original, mirrored, mirrorWeight)
                        points[oppositeIndices[index]] = add(points[oppositeIndices[index - 1]], blended)
                    }
                    val driverAxis = contactSideAxes["${driver}_ankle->${driver}_foot"]
                        ?: sampledTrackSideAxis(contactFootTracks[driver], first, last, alpha, wrap, originalPoints, driverIndices)
                    if (driverAxis != null) {
                        val reconstructedForward = normalized(
                            subtract(points[oppositeIndices[3]], points[oppositeIndices[2]]),
                            "mirrored foot direction",
                        )
                        val reflectedDriver = DoubleArray(3) {
                            -(driverAxis[it] - 2.0 * dot(driverAxis, hipAxis) * hipAxis[it])
                        }
                        val inferredAxis = normalized(
                            DoubleArray(3) {
                                reflectedDriver[it] - reconstructedForward[it] * dot(reflectedDriver, reconstructedForward)
                            },
                            "mirrored shoe side axis",
                        )
                        val originalForward = normalized(
                            subtract(originalPoints[oppositeIndices[3]], originalPoints[oppositeIndices[2]]),
                            "original mirrored foot direction",
                        )
                        val originalAxis = baselineAxes["${opposite}_ankle->${opposite}_foot"]
                            ?: sampledTrackSideAxis(contactFootTracks[driver], first, last, alpha, wrap, originalPoints, driverIndices)
                                ?.let { driverOriginal ->
                                    DoubleArray(3) {
                                        -(driverOriginal[it] - 2.0 * dot(driverOriginal, hipAxis) * hipAxis[it])
                                    }
                                }
                        if (originalAxis != null) {
                            val transported = transportMaterialSide(originalAxis, originalForward, reconstructedForward)
                            val twist = atan2(
                                dot(reconstructedForward, cross(transported, inferredAxis)),
                                dot(transported, inferredAxis),
                            ) * mirrorWeight
                            contactSideAxes["${opposite}_ankle->${opposite}_foot"] = normalized(
                                DoubleArray(3) {
                                    transported[it] * cos(twist) + cross(reconstructedForward, transported)[it] * sin(twist)
                                },
                                "mirrored blended shoe side axis",
                            )
                        }
                    }
                }
            }
        }
        return FixedRigPose(jointNames.indices.associate { jointNames[it] to points[it] }, contactSideAxes)
    }

    private fun protectedSupportId(joint: String, first: Int, last: Int, alpha: Double): String? {
        val ids = supportJointTracks[joint] ?: return null
        val start = ids[first]
        return if (alpha == 0.0) start else start?.takeIf { it.isNotBlank() && it == ids[last] }
    }

    /**
     * Mirrored propagation uses the driver's real native projection weight.
     * The interior envelope vanishes at both keys, so the blended opposite
     * chain meets the untouched exact-key pose without a jump.
     */
    private fun mirrorContactWeight(track: ContactFootTrack?, first: Int, last: Int, alpha: Double): Double {
        if (track == null || track.version != 2) return 0.0
        val firstActive = track.active[first]
        val lastActive = track.active[last]
        val transition = when {
            firstActive && lastActive -> 1.0
            !firstActive && !lastActive -> return 0.0
            lastActive -> smoothStep(alpha)
            else -> 1.0 - smoothStep(alpha)
        }
        if (transition <= 0.0) return 0.0
        if (firstActive && lastActive && !sameMirrorContact(track, first, last)) return 0.0
        return transition * 16.0 * alpha * alpha * (1.0 - alpha) * (1.0 - alpha)
    }

    /** Only one material episode may drive a mirrored interval. */
    private fun sameMirrorContact(track: ContactFootTrack, first: Int, last: Int): Boolean {
        val start = track.episodeByFrame.getOrNull(first) ?: return false
        val end = track.episodeByFrame.getOrNull(last) ?: return false
        if (start.mode != end.mode) return false
        val startAnchor = track.anchorIds.getOrNull(first)
        val endAnchor = track.anchorIds.getOrNull(last)
        return if (start.mode == "verticalOnly") {
            if (!verticalPlanesMatch(start, end)) return false
            start === end ||
                (start.startFrame == end.startFrame && start.endFrame == end.endFrame) ||
                (startAnchor != null && endAnchor != null && startAnchor == endAnchor)
        } else {
            startAnchor != null && endAnchor != null && startAnchor == endAnchor
        }
    }

    private fun verticalPlanesMatch(first: ContactEpisode, second: ContactEpisode): Boolean {
        val firstNormal = first.surfaceNormal ?: return false
        val secondNormal = second.surfaceNormal ?: return false
        if (!first.planeOffsetMeters.isFinite() || !second.planeOffsetMeters.isFinite()) return false
        val same = kotlin.math.abs(first.planeOffsetMeters - second.planeOffsetMeters) <= 1e-6 &&
            length(subtract(firstNormal, secondNormal)) <= 1e-6
        val flipped = kotlin.math.abs(first.planeOffsetMeters + second.planeOffsetMeters) <= 1e-6 &&
            length(add(firstNormal, secondNormal)) <= 1e-6
        return same || flipped
    }

    /** Fallback driver material axis from the serialized track on the original FK pose. */
    private fun sampledTrackSideAxis(
        track: ContactFootTrack?, first: Int, last: Int, alpha: Double, wrap: Boolean,
        originalPoints: Array<DoubleArray>, driverIndices: List<Int>,
    ): DoubleArray? {
        if (track == null || track.version != 2) return null
        val axes = track.sideAxes ?: return null
        val rawAxis = interpolateRigTrack(axes, first, last, alpha, wrap, false, smoothLimiter)
        val forward = normalized(
            subtract(originalPoints[driverIndices[3]], originalPoints[driverIndices[2]]),
            "mirrored driver material foot direction",
        )
        val projected = DoubleArray(3) { rawAxis[it] - forward[it] * dot(rawAxis, forward) }
        val projectedLength = length(projected)
        return if (projectedLength > 1e-9) scale(projected, 1.0 / projectedLength) else null
    }

    private fun applyContactFootPose(
        points: Array<DoubleArray>, side: String, track: ContactFootTrack,
        first: Int, last: Int, alpha: Double, wrap: Boolean, weight: Double,
        protectedSupportId: String? = null,
        originalMaterialSide: DoubleArray? = null,
    ): DoubleArray? {
        val hipIndex = jointNames.indexOf("${side}_hip")
        val kneeIndex = jointNames.indexOf("${side}_knee")
        val ankleIndex = jointNames.indexOf("${side}_ankle")
        val footIndex = jointNames.indexOf("${side}_foot")
        val rawToe = points[footIndex].copyOf()
        val rawAnkle = points[ankleIndex].copyOf()
        val rawDirection = normalized(subtract(rawToe, rawAnkle), "$side raw foot direction")
        if (track.version == 2 && firstActiveAndDifferent(track, first, last)) return null
        if (track.version == 2 && protectedSupportId != null) {
            val episode = track.episodeByFrame[firstActiveIndex(track, first, last)]
                ?: error("$side active contact has no bound episode")
            val axes = checkNotNull(track.sideAxes)
            val sideAxis = if (first == last) axes[first] else
                interpolateRigTrack(axes, first, last, alpha, wrap, false, smoothLimiter)
            val baselineSide = originalMaterialSide ?: sideAxis
            val originalLateral = normalized(
                DoubleArray(3) { baselineSide[it] - rawDirection[it] * dot(baselineSide, rawDirection) },
                "$side original supported side axis",
            )
            val targetLateral = normalized(
                DoubleArray(3) { sideAxis[it] - rawDirection[it] * dot(sideAxis, rawDirection) },
                "$side target supported side axis",
            )
            val blendedSide = DoubleArray(3) { originalLateral[it] * (1.0 - weight) + targetLateral[it] * weight }
            val projectedSide = normalized(
                DoubleArray(3) { blendedSide[it] - rawDirection[it] * dot(blendedSide, rawDirection) },
                "$side supported contact side axis",
            )
            val up = normalized(cross(projectedSide, rawDirection), "$side supported contact up axis")
            val footLength = length(offsets[footIndex])
            val local = scale(episode.materialOffsetLocalMeters, footLength / episode.referenceLengthMeters)
            val materialOffset = DoubleArray(3) {
                rawDirection[it] * local[0] + projectedSide[it] * local[1] + up[it] * local[2]
            }
            val materialPoint = add(rawAnkle, materialOffset)
            val target = if (episode.mode == "stationary") checkNotNull(episode.targetWorld).copyOf() else {
                val normal = checkNotNull(episode.surfaceNormal)
                val shift = episode.planeOffsetMeters - dot(normal, materialPoint)
                DoubleArray(3) { materialPoint[it] + normal[it] * shift }
            }
            val effectiveTarget = DoubleArray(3) { materialPoint[it] + weight * (target[it] - materialPoint[it]) }
            val fixedKnee = points[kneeIndex].copyOf()
            val ankle = solveKnee(
                fixedKnee, rawAnkle, materialPoint, effectiveTarget,
                length(subtract(rawAnkle, fixedKnee)), length(subtract(materialPoint, rawAnkle)), side,
            )
            val source = normalized(subtract(materialPoint, rawAnkle), "$side material support source direction")
            val destination = normalized(subtract(effectiveTarget, ankle), "$side material support target direction")
            val rotation = shortestRotation(source, destination, projectedSide)
            val toe = add(ankle, rotate(rotation, subtract(rawToe, rawAnkle)))
            val direction = normalized(subtract(toe, ankle), "$side supported foot direction")
            val transportedSide = rotate(rotation, projectedSide)
            val axis = normalized(DoubleArray(3) { transportedSide[it] - direction[it] * dot(transportedSide, direction) }, "$side supported shoe side axis")
            points[ankleIndex] = ankle
            points[footIndex] = toe
            return axis
        }
        val curveToe = if (track.version == 1) interpolateRigTrack(
            checkNotNull(track.toes), first, last, alpha, wrap, false, smoothLimiter,
        ) else null
        val yawFirst = first + track.frameCount
        val yawLast = last + track.frameCount + if (wrap && last <= first) track.frameCount else 0
        val yaw = interpolateRigTrack(track.yaw, yawFirst, yawLast, alpha, false, false, smoothLimiter)[0]
        val pitch = interpolateRigTrack(track.pitch, first, last, alpha, wrap, false, smoothLimiter)[0]
        val targetDirection = doubleArrayOf(sin(yaw) * cos(pitch), sin(pitch), cos(yaw) * cos(pitch))
        val direction = normalized(DoubleArray(3) { rawDirection[it] * (1.0 - weight) + targetDirection[it] * weight }, "$side blended foot direction")
        val footLength = length(offsets[footIndex])
        require(footLength > 1e-8) { "Contact foot track requires a nonzero $side ankle-to-foot length" }
        val toe: DoubleArray
        val ankle: DoubleArray
        var sampledSide: DoubleArray? = null
        if (track.version == 1) {
            val legacyToe = checkNotNull(curveToe)
            toe = DoubleArray(3) { rawToe[it] + weight * (legacyToe[it] - rawToe[it]) }
            ankle = DoubleArray(3) { toe[it] - footLength * direction[it] }
        } else {
            val episode = track.episodeByFrame[firstActiveIndex(track, first, last)]
                ?: error("$side active contact has no bound episode")
            val axes = checkNotNull(track.sideAxes)
            val sideAxis = interpolateRigTrack(axes, first, last, alpha, wrap, false, smoothLimiter)
            val targetSide = normalized(
                DoubleArray(3) { sideAxis[it] - targetDirection[it] * dot(sideAxis, targetDirection) },
                "$side target contact side axis",
            )
            val baselineSide = originalMaterialSide ?: targetSide
            val rawSide = normalized(
                DoubleArray(3) { baselineSide[it] - rawDirection[it] * dot(baselineSide, rawDirection) },
                "$side original material side axis",
            )
            val blendedSide = DoubleArray(3) { rawSide[it] * (1.0 - weight) + targetSide[it] * weight }
            val projectedSide = normalized(
                DoubleArray(3) { blendedSide[it] - direction[it] * dot(blendedSide, direction) },
                "$side contact side axis",
            )
            val up = normalized(cross(projectedSide, direction), "$side contact up axis")
            val local = scale(episode.materialOffsetLocalMeters, footLength / episode.referenceLengthMeters)
            val offset = DoubleArray(3) {
                direction[it] * local[0] + projectedSide[it] * local[1] + up[it] * local[2]
            }
            val materialPoint = add(rawAnkle, offset)
            val target = if (episode.mode == "stationary") {
                checkNotNull(episode.targetWorld).copyOf()
            } else {
                val normal = checkNotNull(episode.surfaceNormal)
                val shift = episode.planeOffsetMeters - dot(normal, materialPoint)
                DoubleArray(3) { materialPoint[it] + normal[it] * shift }
            }
            val targetAnkle = subtract(target, offset)
            ankle = DoubleArray(3) { rawAnkle[it] + weight * (targetAnkle[it] - rawAnkle[it]) }
            toe = DoubleArray(3) { ankle[it] + direction[it] * footLength }
            sampledSide = projectedSide
        }
        val rawHip = points[hipIndex].copyOf()
        val rawKnee = points[kneeIndex].copyOf()
        val upperLength = length(subtract(rawKnee, rawHip))
        val lowerLength = length(subtract(rawAnkle, rawKnee))
        if (length(subtract(ankle, rawAnkle)) <= 1e-9) {
            points[kneeIndex] = rawKnee
            points[ankleIndex] = ankle
            points[footIndex] = toe
            return sampledSide
        }
        points[kneeIndex] = solveKnee(rawHip, rawKnee, rawAnkle, ankle, upperLength, lowerLength, side)
        points[ankleIndex] = ankle
        points[footIndex] = toe
        return sampledSide
    }

    private fun firstActiveAndDifferent(track: ContactFootTrack, first: Int, last: Int): Boolean =
        track.version == 2 && track.active[first] && track.active[last] && track.anchorIds[first] != track.anchorIds[last]

    private fun firstActiveIndex(track: ContactFootTrack, first: Int, last: Int): Int =
        if (track.active[first]) first else last

    companion object {
        fun parse(
            value: JsonObject,
            frameCount: Int,
            nativeFootGeometry: WearNativeFootGeometry? = null,
            canonicalExecution: JsonObject? = null,
        ): FixedRigPlayback {
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
            val supportTracks = parseSupportJointTracks(value.get("supportJointTracks"), names, frameCount)
            val unboundRig = FixedRigPlayback(names, parents, order, offsets, slots, coordinates, continuous, smoothLimiter, emptyMap(), canonicalExecution, supportTracks)
            val firstPose = unboundRig.samplePose(0.0, wrap = false).joints
            fun span(first: String, last: String): Double {
                val a = firstPose[first] ?: return 0.0
                val b = firstPose[last] ?: return 0.0
                return length(subtract(a, b))
            }
            val canonicalFootScale = max(span("left_hip", "right_hip") * .98, span("left_shoulder", "right_shoulder") * .58)
            val contactTracks = parseContactFootTracks(
                value.getAsJsonObject("contactFootTracks"), names, parents, offsets, frameCount,
                nativeFootGeometry, canonicalFootScale,
            )
            val material = parseMaterialFrames(value.get("materialFrames"), names, parents, offsets, coordinates)
            val result = FixedRigPlayback(names, parents, order, offsets, slots, coordinates, continuous, smoothLimiter, contactTracks, canonicalExecution, supportTracks, material)
            if (material != null) {
                for (index in coordinates.indices) {
                    val reference = result.globalRotations(material.coordinates,checkNotNull(result.referenceQuaternionTracks),index,index,0.0,false)
                    for ((key, sides) in material.sides) {
                        val foot = names.indexOf(key.substringAfter("->"))
                        val forward = normalized(reference[foot].rotate(offsets[foot]),"reference foot direction")
                        normalized(DoubleArray(3) { sides[index][it]-forward[it]*dot(sides[index],forward) },"reference material side")
                    }
                }
            }
            return result
        }
    }
}

internal data class FixedRigPose(
    val joints: Map<String, DoubleArray>,
    val contactSideAxes: Map<String, DoubleArray>,
)

private data class StationaryMaterialBinding(val startFrame: Int, val endFrame: Int, val activeFrames: Set<Int>, val localSide: DoubleArray)
private data class MaterialFrames(
    val coordinates: Array<DoubleArray>,
    val sides: Map<String, Array<DoubleArray>>,
    val stationary: Map<String,List<StationaryMaterialBinding>>,
)

private fun parseMaterialFrames(
    raw: com.google.gson.JsonElement?, names: List<String>, parents: IntArray,
    offsets: Array<DoubleArray>, current: Array<DoubleArray>,
): MaterialFrames? {
    if (raw == null) return null
    require(raw.isJsonObject) { "materialFrames must be an object" }
    val data = raw.asJsonObject
    fun integer(value: com.google.gson.JsonElement): Int {
        require(value.isJsonPrimitive && value.asJsonPrimitive.isNumber)
        val number=value.asDouble
        require(number.isFinite() && number==number.toInt().toDouble())
        return number.toInt()
    }
    require(integer(data.get("version"))==1) { "Unsupported materialFrames version" }
    fun rows(value: com.google.gson.JsonElement, width: Int): Array<DoubleArray> {
        require(value.isJsonArray && value.asJsonArray.size()==current.size)
        return value.asJsonArray.map { row ->
            require(row.isJsonArray && row.asJsonArray.size()==width)
            row.asJsonArray.map { number ->
                require(number.isJsonPrimitive && number.asJsonPrimitive.isNumber && number.asDouble.isFinite())
                number.asDouble
            }.toDoubleArray()
        }.toTypedArray()
    }
    val reference=rows(data.get("referenceCoordinates"),current[0].size)
    val expected=setOf("left_ankle->left_foot","right_ankle->right_foot")
    val source=data.get("referenceBoneSides")
    require(source.isJsonObject && source.asJsonObject.keySet()==expected)
    val sides=expected.associateWith { key ->
        val ankle=names.indexOf(key.substringBefore("->"));val foot=names.indexOf(key.substringAfter("->"))
        require(ankle>=0 && foot>=0 && parents[foot]==ankle && length(offsets[foot])>1e-10)
        rows(source.asJsonObject.get(key),3)
    }
    val stationary=mutableMapOf<String,List<StationaryMaterialBinding>>()
    if (data.has("stationaryLocalBindings")) {
        val bindings=data.get("stationaryLocalBindings")
        require(bindings.isJsonObject && bindings.asJsonObject.keySet().all { it in expected })
        for ((key, entries) in bindings.asJsonObject.entrySet()) {
            require(entries.isJsonArray)
            val seen=mutableSetOf<Int>()
            stationary[key]=entries.asJsonArray.map { entry ->
                require(entry.isJsonObject)
                val item=entry.asJsonObject
                val first=integer(item.get("startFrame"));val last=integer(item.get("endFrame"))
                require(first in current.indices && last in first..current.lastIndex)
                require(item.get("anchorId").isJsonPrimitive && item.get("anchorId").asJsonPrimitive.isString && item.get("anchorId").asString.isNotBlank())
                val active=item.get("activeFrames")
                require(active.isJsonArray)
                val indices=active.asJsonArray.map(::integer)
                require(indices.size>=2 && indices==indices.distinct().sorted() && indices.all { it in first..last && it !in seen })
                seen.addAll(indices)
                val axis=item.get("localSideAxis")
                require(axis.isJsonArray && axis.asJsonArray.size()==3)
                val side=axis.asJsonArray.map { n ->
                    require(n.isJsonPrimitive && n.asJsonPrimitive.isNumber && n.asDouble.isFinite());n.asDouble
                }.toDoubleArray()
                val forward=normalized(offsets[names.indexOf(key.substringAfter("->"))],"local foot axis")
                normalized(DoubleArray(3) { side[it]-forward[it]*dot(side,forward) },"stationary local material axis")
                StationaryMaterialBinding(first,last,indices.toSet(),side)
            }
        }
    }
    return MaterialFrames(reference,sides,stationary)
}

private data class ContactEpisode(
    val startFrame: Int,
    val endFrame: Int,
    val anchorId: String,
    val mode: String,
    val materialOffsetLocalMeters: DoubleArray,
    val referenceLengthMeters: Double,
    val targetWorld: DoubleArray?,
    val surfaceNormal: DoubleArray?,
    val planeOffsetMeters: Double,
)

private data class ContactFootTrack(
    val version: Int,
    val frameCount: Int,
    val active: BooleanArray,
    val toes: Array<DoubleArray>?,
    val yaw: Array<DoubleArray>,
    val pitch: Array<DoubleArray>,
    val anchorIds: Array<String?> = emptyArray(),
    val episodes: List<ContactEpisode> = emptyList(),
    val episodeByFrame: Array<ContactEpisode?> = emptyArray(),
    val sideAxes: Array<DoubleArray>? = null,
)

private fun parseSupportJointTracks(
    value: com.google.gson.JsonElement?, jointNames: List<String>, frameCount: Int,
): Map<String, Array<String?>> {
    if (value == null) return emptyMap()
    require(value.isJsonObject) { "supportJointTracks must be an object" }
    val tracks = value.asJsonObject
    require(tracks.keySet() == setOf("version", "source", "joints")) {
        "supportJointTracks has unsupported fields"
    }
    val version = tracks.get("version")
    require(version != null && version.isJsonPrimitive && version.asJsonPrimitive.isNumber && version.asInt == 1 && version.asDouble == 1.0) {
        "Unsupported supportJointTracks version"
    }
    val source = tracks.get("source")
    require(source != null && source.isJsonPrimitive && source.asJsonPrimitive.isString && source.asString == "validated_stationary_body_support") {
        "Unsupported supportJointTracks source"
    }
    val jointsElement = tracks.get("joints")
    require(jointsElement != null && jointsElement.isJsonObject && jointsElement.asJsonObject.size() > 0) {
        "supportJointTracks.joints must be a nonempty object"
    }
    val joints = jointsElement.asJsonObject
    require(joints.keySet().all { it in jointNames }) { "supportJointTracks names an unknown joint" }
    return joints.entrySet().associate { (joint, element) ->
        require(element.isJsonObject) { "supportJointTracks.$joint must be an object" }
        val ids = element.asJsonObject
        require(ids.keySet() == setOf("episodeIds")) { "supportJointTracks.$joint has unsupported fields" }
        val array = ids.get("episodeIds")
        require(array != null && array.isJsonArray && array.asJsonArray.size() == frameCount) {
            "supportJointTracks.$joint.episodeIds must have $frameCount entries"
        }
        joint to Array<String?>(frameCount) { index ->
            val id = array.asJsonArray[index]
            if (id.isJsonNull) null else {
                require(id.isJsonPrimitive && id.asJsonPrimitive.isString && id.asString.isNotBlank()) {
                    "supportJointTracks.$joint.episodeIds must contain nonblank strings or null"
                }
                id.asString
            }
        }
    }
}

private fun parseContactFootTracks(
    value: JsonObject?, names: List<String>, parents: IntArray, offsets: Array<DoubleArray>, frameCount: Int,
    nativeFootGeometry: WearNativeFootGeometry?, canonicalFootScale: Double,
): Map<String, ContactFootTrack> {
    if (value == null) return emptyMap()
    val version = value.get("version")?.asInt
    require(version == 1 || version == 2) { "Unsupported contact foot track version" }
    require(version != 2 || nativeFootGeometry != null) { "Native material contact requires nativeFootGeometry" }
    require(version != 2 || canonicalFootScale.isFinite() && canonicalFootScale >= 0.0) {
        "Native material contact requires the canonical rig foot scale"
    }
    require(version != 2 || value.has("left") || value.has("right")) { "Native material contact has no side tracks" }
    val result = mutableMapOf<String, ContactFootTrack>()
    for (side in listOf("left", "right")) {
        val sideValue = value.getAsJsonObject(side) ?: continue
        val chainNames = listOf("${side}_hip", "${side}_knee", "${side}_ankle", "${side}_foot")
        val indices = chainNames.map { name -> names.indexOf(name).also { require(it >= 0) { "Contact foot track requires $name" } } }
        require(indices.drop(1).zip(indices).all { (child, parent) -> parents[child] == parent }) {
            "Contact foot track requires a direct hip-knee-ankle-foot chain for $side"
        }
        val activeJson = sideValue.getAsJsonArray("active")
        val toeJson = sideValue.getAsJsonArray("toes")
        val directionJson = sideValue.getAsJsonArray("directions")
        require(activeJson != null && activeJson.size() == frameCount) { "Contact foot active track for $side must have $frameCount frames" }
        require(version == 2 || toeJson != null && toeJson.size() == frameCount) { "Contact foot toe track for $side must have $frameCount frames" }
        require(directionJson != null && directionJson.size() == frameCount) { "Contact foot direction track for $side must have $frameCount frames" }
        if (version == 2) require(activeJson.all { it.isJsonPrimitive && it.asJsonPrimitive.isBoolean }) {
            "$side v2 active track must contain booleans"
        }
        val active = BooleanArray(frameCount) { activeJson[it].asBoolean }
        val toes = toeJson?.let { array -> Array(frameCount) { frame -> parseVector(array[frame], "Contact foot toe for $side frame $frame") } }
        val directions = Array(frameCount) { frame ->
            val vector = parseVector(directionJson[frame], "Contact foot direction for $side frame $frame", strictNumbers = version == 2)
            val magnitude = length(vector)
            if (version == 2) require(kotlin.math.abs(magnitude - 1.0) <= 1e-4) { "$side contact direction must be normalized" }
            normalized(vector, "Contact foot direction for $side frame $frame")
        }
        require(length(offsets[indices[1]]) > 1e-8 && length(offsets[indices[2]]) > 1e-8 && length(offsets[indices[3]]) > 1e-8) {
            "Contact foot track requires nonzero leg segment lengths for $side"
        }
        val rawYaw = DoubleArray(frameCount) { atan2(directions[it][0], directions[it][2]) }
        val yawValues = DoubleArray(frameCount * 3) { index -> rawYaw[index % frameCount] }
        for (frame in 1 until yawValues.size) {
            while (yawValues[frame] - yawValues[frame - 1] > Math.PI) yawValues[frame] -= 2.0 * Math.PI
            while (yawValues[frame] - yawValues[frame - 1] < -Math.PI) yawValues[frame] += 2.0 * Math.PI
        }
        val yaw = Array(yawValues.size) { doubleArrayOf(yawValues[it]) }
        val pitch = Array(frameCount) { doubleArrayOf(atan2(directions[it][1], hypot(directions[it][0], directions[it][2]))) }
        if (version == 1) {
            result[side] = ContactFootTrack(1, frameCount, active, toes, yaw, pitch)
            continue
        }
        val anchorsJson = sideValue.getAsJsonArray("anchorIds")
        val episodesJson = sideValue.getAsJsonArray("episodes")
        val sideAxesJson = sideValue.getAsJsonArray("sideAxes")
        require(anchorsJson != null && anchorsJson.size() == frameCount && episodesJson != null && sideAxesJson != null && sideAxesJson.size() == frameCount) {
            "$side v2 contact track is missing frame identity, episodes, or side axes"
        }
        val anchors = Array<String?>(frameCount) { index ->
            val element = anchorsJson[index]
            if (element.isJsonNull) null else {
                require(element.isJsonPrimitive && element.asJsonPrimitive.isString) { "$side anchorIds must be strings or null" }
                element.asString.also { require(it.isNotBlank()) }
            }
        }
        val sideAxes = Array(frameCount) { index ->
            val rawAxis = parseVector(sideAxesJson[index], "$side side axis $index", strictNumbers = true)
            require(kotlin.math.abs(length(rawAxis) - 1.0) <= 1e-4) { "$side side axis must be normalized" }
            val axis = normalized(rawAxis, "$side side axis $index")
            require(kotlin.math.abs(dot(axis, directions[index])) <= 1e-4) { "$side side axis must be perpendicular to direction" }
            axis
        }
        val episodes = episodesJson.mapIndexed { index, element ->
            val episode = element.asJsonObject
            fun integer(key: String): Int {
                val elementValue = episode.get(key) ?: error("$side episode $index missing $key")
                require(elementValue.isJsonPrimitive && elementValue.asJsonPrimitive.isNumber) { "$side episode $index $key must be an integer" }
                val number = elementValue.asDouble
                require(number.isFinite() && number % 1.0 == 0.0 && number in Int.MIN_VALUE.toDouble()..Int.MAX_VALUE.toDouble()) {
                    "$side episode $index $key must be an integer"
                }
                return number.toInt()
            }
            fun string(key: String): String {
                val elementValue = episode.get(key) ?: error("$side episode $index missing $key")
                require(elementValue.isJsonPrimitive && elementValue.asJsonPrimitive.isString) { "$side episode $index $key must be a string" }
                return elementValue.asString
            }
            val start = integer("startFrame")
            val end = integer("endFrame")
            val anchor = string("anchorId").takeIf { it.isNotBlank() } ?: error("$side episode $index missing anchorId")
            val role = string("regionRole")
            require(role in setOf("forefoot", "heel", "full_sole")) { "$side episode $index has unsupported regionRole" }
            val mode = string("mode")
            require(mode == "stationary" || mode == "verticalOnly") { "$side episode $index has unsupported mode" }
            require(string("primitiveId") == "wearShoe:${side}_ankle->${side}_foot") { "$side episode $index has wrong primitiveId" }
            val triangleIndex = integer("triangleIndex")
            require(triangleIndex in 0 until 48) { "$side episode $index has an invalid native shoe triangle" }
            val bary = episode.getAsJsonArray("barycentric") ?: error("$side episode $index missing barycentric")
            require(bary.size() == 3)
            val baryValues = bary.map {
                require(it.isJsonPrimitive && it.asJsonPrimitive.isNumber) { "$side barycentric weights must be numbers" }
                it.asDouble.also { v -> require(v.isFinite() && v >= 0.0) }
            }
            require(kotlin.math.abs(baryValues.sum() - 1.0) <= 1e-6)
            val localOffset = parseVector(episode.get("materialOffsetLocalMeters") ?: error("$side episode $index missing materialOffsetLocalMeters"), "$side material offset", strictNumbers = true)
            val referenceElement = episode.get("referenceLengthMeters") ?: error("$side episode $index missing referenceLengthMeters")
            require(referenceElement.isJsonPrimitive && referenceElement.asJsonPrimitive.isNumber)
            val referenceLength = referenceElement.asDouble
            require(referenceLength.isFinite() && referenceLength > 0.0)
            val target = episode.get("targetWorld")?.takeUnless { it.isJsonNull }?.let { parseVector(it, "$side targetWorld", strictNumbers = true) }
            val normal = episode.get("surfaceNormal")?.takeUnless { it.isJsonNull }?.let {
                val raw = parseVector(it, "$side surfaceNormal", strictNumbers = true)
                require(kotlin.math.abs(length(raw) - 1.0) <= 1e-4) { "$side surface normal must be normalized" }
                normalized(raw, "$side surfaceNormal")
            }
            val planeOffsetElement = episode.get("planeOffsetMeters")
            if (planeOffsetElement != null) require(planeOffsetElement.isJsonPrimitive && planeOffsetElement.asJsonPrimitive.isNumber)
            val planeOffset = planeOffsetElement?.asDouble ?: Double.NaN
            if (mode == "stationary") require(target != null) { "$side stationary episode needs targetWorld" }
            else require(target == null && normal != null && planeOffset.isFinite()) { "$side verticalOnly episode needs a plane and no targetWorld" }
            require(start in 0 until frameCount && end in start until frameCount) { "$side episode range is invalid" }
            if (index > 0) require(start > episodesJson[index - 1].asJsonObject.get("endFrame").asInt) { "$side episodes overlap" }
            val footIndex = indices[3]
            val boneLength = length(offsets[footIndex])
            val geometry = checkNotNull(nativeFootGeometry)
            val sideGeometry = if (side == "left") geometry.left else geometry.right
            for (frame in start..end) {
                val direction = directions[frame]
                val rawSide = sideAxes[frame]
                val ankle = WearSkeletonVec3(0f, 0f, 0f)
                val foot = WearSkeletonVec3(
                    (direction[0] * boneLength).toFloat(),
                    (direction[1] * boneLength).toFloat(),
                    (direction[2] * boneLength).toFloat(),
                )
                val mesh = nativeFootShoeVertices(
                    ankle = ankle,
                    foot = foot,
                    sideAxis = WearSkeletonVec3(rawSide[0].toFloat(), rawSide[1].toFloat(), rawSide[2].toFloat()),
                    fallbackSide = WearSkeletonVec3(rawSide[0].toFloat(), rawSide[1].toFloat(), rawSide[2].toFloat()),
                    geometry = sideGeometry,
                    footScale = canonicalFootScale.toFloat(),
                )
                val vertices = mesh.rings.flatten() + listOf(mesh.rearTip, mesh.toeTip)
                val triangle = nativeShoeTriangles[triangleIndex]
                val material = WearSkeletonVec3(
                    triangle.indices.sumOf { baryValues[it] * vertices[triangle[it]].x }.toFloat(),
                    triangle.indices.sumOf { baryValues[it] * vertices[triangle[it]].y }.toFloat(),
                    triangle.indices.sumOf { baryValues[it] * vertices[triangle[it]].z }.toFloat(),
                )
                val forward = normalized(direction, "$side contact direction")
                val lateral = normalized(
                    DoubleArray(3) { rawSide[it] - forward[it] * dot(rawSide, forward) },
                    "$side contact side axis",
                )
                val up = normalized(cross(lateral, forward), "$side contact up axis")
                val expectedOffset = doubleArrayOf(
                    (material.x * forward[0] + material.y * forward[1] + material.z * forward[2]) * referenceLength / boneLength,
                    (material.x * lateral[0] + material.y * lateral[1] + material.z * lateral[2]) * referenceLength / boneLength,
                    (material.x * up[0] + material.y * up[1] + material.z * up[2]) * referenceLength / boneLength,
                )
                require(expectedOffset.indices.all { kotlin.math.abs(expectedOffset[it] - localOffset[it]) <= 2e-5 }) {
                    "$side episode $index material offset does not match its native shoe triangle+barycentric binding"
                }
            }
            ContactEpisode(start, end, anchor, mode, localOffset, referenceLength, target, normal, planeOffset)
        }
        val byFrame = arrayOfNulls<ContactEpisode>(frameCount)
        episodes.forEach { episode ->
            for (frame in episode.startFrame..episode.endFrame) {
                require(byFrame[frame] == null && anchors[frame] == episode.anchorId) { "$side episode mapping overlaps or disagrees with anchorIds" }
                byFrame[frame] = episode
            }
        }
        for (frame in 0 until frameCount) {
            require(active[frame] == (byFrame[frame] != null) && (active[frame] || anchors[frame] == null)) {
                "$side active frame must map to exactly one episode"
            }
        }
        result[side] = ContactFootTrack(2, frameCount, active, null, yaw, pitch, anchors, episodes, byFrame, sideAxes)
    }
    return result
}

internal val nativeShoeTriangles: List<IntArray> = buildList {
    for (lower in listOf(0, 8)) {
        for (corner in 0 until 8) {
            val next = (corner + 1) % 8
            val a = lower + corner
            val b = lower + 8 + corner
            val c = lower + 8 + next
            val d = lower + next
            add(intArrayOf(a, b, c))
            add(intArrayOf(a, c, d))
        }
    }
    for (corner in 0 until 8) {
        val next = (corner + 1) % 8
        add(intArrayOf(24, corner, next))
        add(intArrayOf(25, 16 + next, 16 + corner))
    }
}

private fun parseVector(value: com.google.gson.JsonElement, description: String, strictNumbers: Boolean = false): DoubleArray {
    val array = value.asJsonArray
    require(array.size() == 3) { "$description must have three coordinates" }
    return DoubleArray(3) { index ->
        if (strictNumbers) require(array[index].isJsonPrimitive && array[index].asJsonPrimitive.isNumber) {
            "$description must contain numbers"
        }
        array[index].asDouble.also { coordinate -> require(coordinate.isFinite()) { "$description must be finite" } }
    }
}

private fun smoothStep(value: Double) = value * value * (3.0 - 2.0 * value)

private fun dot(a: DoubleArray, b: DoubleArray) = a.indices.sumOf { a[it] * b[it] }
private fun length(value: DoubleArray) = sqrt(dot(value, value))
private fun subtract(a: DoubleArray, b: DoubleArray) = DoubleArray(3) { a[it] - b[it] }
private fun add(a: DoubleArray, b: DoubleArray) = DoubleArray(3) { a[it] + b[it] }
private fun scale(value: DoubleArray, factor: Double) = DoubleArray(3) { value[it] * factor }
private fun cross(a: DoubleArray, b: DoubleArray) = doubleArrayOf(
    a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0],
)
private fun normalized(value: DoubleArray, description: String): DoubleArray {
    val magnitude = length(value)
    require(magnitude.isFinite() && magnitude > 1e-10) { "$description is degenerate" }
    return scale(value, 1.0 / magnitude)
}

/**
 * Shortest-arc slerp of one rigid segment toward the reflected target while
 * preserving the original segment length.
 */
private fun blendRigidBone(original: DoubleArray, target: DoubleArray, weight: Double): DoubleArray {
    val originalUnit = normalized(original, "mirrored original leg segment")
    val targetUnit = normalized(target, "mirrored target leg segment")
    val rotation = RigQuaternion.fromUnitVectors(originalUnit, targetUnit)
    return RigQuaternion.Identity.slerp(rotation, weight).rotate(original)
}

/**
 * Minimal-rotation transport of a material side axis from one foot direction
 * to another, equivalent to the shared Python/JS transport.
 */
private fun transportMaterialSide(side: DoubleArray, oldForward: DoubleArray, newForward: DoubleArray): DoubleArray {
    val cosine = dot(oldForward, newForward).coerceIn(-1.0, 1.0)
    val rotationAxis = cross(oldForward, newForward)
    val crossSide = cross(rotationAxis, side)
    val denominator = max(1.0 + cosine, 1e-12)
    val transported = add(add(side, crossSide), scale(cross(rotationAxis, crossSide), 1.0 / denominator))
    val projected = DoubleArray(3) { transported[it] - newForward[it] * dot(transported, newForward) }
    val projectedLength = length(projected)
    val fallback = DoubleArray(3) { side[it] - newForward[it] * dot(side, newForward) }
    val fallbackLength = length(fallback)
    return if (cosine < -0.999999 || projectedLength <= 1e-8 || !projectedLength.isFinite()) {
        require(fallbackLength > 1e-10) { "mirrored material side transport fallback is degenerate" }
        scale(fallback, 1.0 / fallbackLength)
    } else {
        scale(projected, 1.0 / projectedLength)
    }
}

private fun shortestRotation(from: DoubleArray, to: DoubleArray, sideAxis: DoubleArray): Array<DoubleArray> {
    val axis = cross(from, to)
    val cosine = dot(from, to).coerceIn(-1.0, 1.0)
    if (cosine <= -1.0 + 1e-10) {
        var pole = subtract(sideAxis, scale(from, dot(sideAxis, from)))
        if (length(pole) <= 1e-10) {
            val basis = DoubleArray(3).also { it[from.indices.minBy { index -> kotlin.math.abs(from[index]) }] = 1.0 }
            pole = subtract(basis, scale(from, dot(basis, from)))
        }
        val unit = normalized(pole, "supported material antiparallel rotation axis")
        return Array(3) { row -> DoubleArray(3) { column -> 2.0 * unit[row] * unit[column] - if (row == column) 1.0 else 0.0 } }
    }
    val skew = arrayOf(
        doubleArrayOf(0.0, -axis[2], axis[1]),
        doubleArrayOf(axis[2], 0.0, -axis[0]),
        doubleArrayOf(-axis[1], axis[0], 0.0),
    )
    return Array(3) { row -> DoubleArray(3) { column ->
        (if (row == column) 1.0 else 0.0) + skew[row][column] +
            (0..2).sumOf { k -> skew[row][k] * skew[k][column] } / (1.0 + cosine)
    } }
}

private fun rotate(rotation: Array<DoubleArray>, vector: DoubleArray) = DoubleArray(3) { row ->
    dot(rotation[row], vector)
}

private fun solveKnee(
    hip: DoubleArray, rawKnee: DoubleArray, oldAnkle: DoubleArray, ankle: DoubleArray,
    upperLength: Double, lowerLength: Double, side: String,
): DoubleArray {
    require(upperLength > 1e-8 && lowerLength > 1e-8) { "Contact foot track has a degenerate $side leg" }
    val oldAxis = normalized(subtract(oldAnkle, hip), "$side original hip-to-ankle axis")
    val rawPole = subtract(rawKnee, hip)
    val oldAlong = dot(rawPole, oldAxis)
    val transportedPole = normalized(DoubleArray(3) { rawPole[it] - oldAxis[it] * oldAlong }, "$side knee bend plane")
    val newDelta = subtract(ankle, hip)
    val distance = length(newDelta)
    require(distance > 1e-8) { "Contact foot target collapses the $side leg" }
    val minimum = kotlin.math.abs(upperLength - lowerLength)
    val maximum = upperLength + lowerLength
    require(distance >= minimum - 1e-7 && distance <= maximum + 1e-7) {
        "Contact foot target is unreachable for $side leg (distance=$distance, range=$minimum..$maximum)"
    }
    val newAxis = scale(newDelta, 1.0 / distance)
    val rotationAxis = cross(oldAxis, newAxis)
    val rotationMagnitude = length(rotationAxis)
    val axisDot = dot(oldAxis, newAxis).coerceIn(-1.0, 1.0)
    val pole = if (rotationMagnitude > 1e-10) {
        val unitAxis = scale(rotationAxis, 1.0 / rotationMagnitude)
        val angle = atan2(rotationMagnitude, axisDot)
        val rotated = add(add(scale(transportedPole, cos(angle)), scale(cross(unitAxis, transportedPole), sin(angle))),
            scale(unitAxis, dot(unitAxis, transportedPole) * (1.0 - cos(angle))))
        normalized(rotated, "$side transported knee pole")
    } else transportedPole
    val along = (upperLength * upperLength - lowerLength * lowerLength + distance * distance) / (2.0 * distance)
    val height = sqrt(max(0.0, upperLength * upperLength - along * along))
    return add(add(hip, scale(newAxis, along)), scale(pole, height))
}

private data class RigQuaternion(val x: Double, val y: Double, val z: Double, val w: Double) {
    fun toArray() = doubleArrayOf(x, y, z, w)
    fun inverseRotate(v: DoubleArray) = RigQuaternion(-x,-y,-z,w).rotate(v)
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

        /** Shortest-arc rotation that maps one unit vector onto another. */
        fun fromUnitVectors(from: DoubleArray, to: DoubleArray): RigQuaternion {
            val cosine = (0..2).sumOf { from[it] * to[it] }
            if (cosine < -1.0 + 1e-10) {
                val basisIndex = from.indices.minBy { index -> kotlin.math.abs(from[index]) }
                val basis = DoubleArray(3).also { it[basisIndex] = 1.0 }
                val along = (0..2).sumOf { basis[it] * from[it] }
                val axis = DoubleArray(3) { basis[it] - from[it] * along }
                val axisLength = length(axis)
                return RigQuaternion(axis[0] / axisLength, axis[1] / axisLength, axis[2] / axisLength, 0.0)
            }
            val axis = cross(from, to)
            val quaternion = RigQuaternion(axis[0], axis[1], axis[2], 1.0 + cosine)
            val norm = sqrt(quaternion.x * quaternion.x + quaternion.y * quaternion.y +
                quaternion.z * quaternion.z + quaternion.w * quaternion.w)
            return RigQuaternion(quaternion.x / norm, quaternion.y / norm, quaternion.z / norm, quaternion.w / norm)
        }

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
