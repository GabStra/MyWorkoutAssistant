package com.gabstra.myworkoutassistant.composables

import androidx.annotation.RawRes
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.tooling.preview.Preview
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.tooling.preview.devices.WearDevices
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.presentation.theme.baseline
import com.gabstra.myworkoutassistant.presentation.theme.darkScheme
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt

private const val OrbitDegreesPerSecond = 36f
private val SkeletonViewLightDirection = WearSkeletonVec3(-0.35f, 0.78f, 0.52f).normalizedOr(WearSkeletonVec3(0f, 1f, 0f))

private val SkeletonBackground = Color(0xFF101418)

private data class SkeletonPalette(
    val limbFill: Color,
    val coreFill: Color,
    val headFill: Color,
    val grid: Color,
)

private fun Color.toNeonSkeletonPalette(): SkeletonPalette {
    return SkeletonPalette(
        limbFill = this,
        coreFill = this,
        headFill = this,
        grid = copy(alpha = 0.22f),
    )
}

private fun Color.mix(other: Color, amount: Float): Color {
    val clampedAmount = amount.coerceIn(0f, 1f)
    val inverseAmount = 1f - clampedAmount
    return Color(
        red = red * inverseAmount + other.red * clampedAmount,
        green = green * inverseAmount + other.green * clampedAmount,
        blue = blue * inverseAmount + other.blue * clampedAmount,
        alpha = alpha * inverseAmount + other.alpha * clampedAmount,
    )
}

private data class WearSkeleton(
    val fps: Float,
    val frames: List<WearSkeletonFrame>,
    val bounds: WearSkeletonBounds,
)

private data class WearSkeletonBounds(
    val minX: Float,
    val maxX: Float,
    val minY: Float,
    val maxY: Float,
    val minZ: Float,
    val maxZ: Float,
)

private data class WearSkeletonFrame(
    val joints: Map<String, WearSkeletonVec3>,
)

private data class WearSkeletonVec3(
    val x: Float,
    val y: Float,
    val z: Float,
) {
    operator fun plus(other: WearSkeletonVec3) = WearSkeletonVec3(x + other.x, y + other.y, z + other.z)
    operator fun minus(other: WearSkeletonVec3) = WearSkeletonVec3(x - other.x, y - other.y, z - other.z)
    operator fun times(value: Float) = WearSkeletonVec3(x * value, y * value, z * value)

    fun length(): Float = sqrt(x * x + y * y + z * z)
    fun lerp(other: WearSkeletonVec3, amount: Float): WearSkeletonVec3 = this * (1f - amount) + other * amount
    fun normalizedOr(fallback: WearSkeletonVec3): WearSkeletonVec3 {
        val vectorLength = length()
        return if (vectorLength <= 0.0001f) fallback else this * (1f / vectorLength)
    }
    fun cross(other: WearSkeletonVec3): WearSkeletonVec3 = WearSkeletonVec3(
        x = y * other.z - z * other.y,
        y = z * other.x - x * other.z,
        z = x * other.y - y * other.x,
    )
    fun dot(other: WearSkeletonVec3): Float = x * other.x + y * other.y + z * other.z
}

private data class WearSkeletonProjectedPoint(
    val point: Offset,
    val depth: Float,
)

private sealed class DrawSkeletonItem {
    abstract val depth: Float
}

private data class DrawPolygon(
    val points: List<Offset>,
    override val depth: Float,
    val fill: Color,
) : DrawSkeletonItem()

private data class DrawSphere(
    val center: Offset,
    val radius: Float,
    override val depth: Float,
    val fill: Color,
    val lightOffset: Offset,
) : DrawSkeletonItem()

private data class LimbSpec(
    val startName: String,
    val endName: String,
    val profile: LimbProfile,
)

private data class JointSpec(
    val name: String,
    val radius: Float,
)

private data class BodyAxes(
    val side: WearSkeletonVec3,
    val up: WearSkeletonVec3,
    val forward: WearSkeletonVec3,
)

private val SkeletonLimbs = arrayOf(
    LimbSpec("left_hip", "left_knee", LimbProfile(0.108f, 0.092f)),
    LimbSpec("left_knee", "left_ankle", LimbProfile(0.090f, 0.070f)),
    LimbSpec("left_ankle", "left_foot", LimbProfile(0.070f, 0.056f)),
    LimbSpec("right_hip", "right_knee", LimbProfile(0.108f, 0.092f)),
    LimbSpec("right_knee", "right_ankle", LimbProfile(0.090f, 0.070f)),
    LimbSpec("right_ankle", "right_foot", LimbProfile(0.070f, 0.056f)),
    LimbSpec("left_shoulder", "left_elbow", LimbProfile(0.084f, 0.066f)),
    LimbSpec("left_elbow", "left_wrist", LimbProfile(0.066f, 0.052f)),
    LimbSpec("right_shoulder", "right_elbow", LimbProfile(0.084f, 0.066f)),
    LimbSpec("right_elbow", "right_wrist", LimbProfile(0.066f, 0.052f)),
)

private val SkeletonJointCaps = arrayOf(
    JointSpec("left_hip", 0.064f),
    JointSpec("right_hip", 0.064f),
    JointSpec("left_knee", 0.066f),
    JointSpec("right_knee", 0.066f),
    JointSpec("left_ankle", 0.052f),
    JointSpec("right_ankle", 0.052f),
    JointSpec("left_shoulder", 0.064f),
    JointSpec("right_shoulder", 0.064f),
    JointSpec("left_elbow", 0.054f),
    JointSpec("right_elbow", 0.054f),
)

@Composable
fun WearSkeletonMotionPreview(
    modifier: Modifier = Modifier,
    @RawRes skeletonResId: Int = R.raw.youtube_uyumul_g_v0_loop_1_lock_feet,
    animated: Boolean = true,
    viewYawDegrees: Float = -28f,
    viewPitchDegrees: Float = 18f,
    orbitView: Boolean = false,
) {
    val context = LocalContext.current
    val skeleton = remember(skeletonResId) {
        context.resources.openRawResource(skeletonResId).bufferedReader().use { reader ->
            parseWearSkeleton(reader.readText())
        }
    }
    val themePrimary = MaterialTheme.colorScheme.primary
    val palette = remember(themePrimary) { themePrimary.toNeonSkeletonPalette() }
    var frameIndex by remember(skeleton.frames.size) { mutableIntStateOf(if (animated) 0 else min(12, skeleton.frames.lastIndex)) }
    var orbitYawDegrees by remember(viewYawDegrees) { mutableFloatStateOf(viewYawDegrees) }

    LaunchedEffect(animated, orbitView, skeleton.fps, skeleton.frames.size, viewYawDegrees) {
        if (!animated && !orbitView) {
            return@LaunchedEffect
        }
        while (true) {
            val frameTimeNanos = withFrameNanos { it }
            val seconds = frameTimeNanos / 1_000_000_000.0
            if (animated && skeleton.frames.isNotEmpty()) {
                val nextFrameIndex = ((seconds * skeleton.fps).toInt()).floorMod(skeleton.frames.size)
                if (frameIndex != nextFrameIndex) {
                    frameIndex = nextFrameIndex
                }
            }
            if (orbitView) {
                orbitYawDegrees = viewYawDegrees + ((seconds * OrbitDegreesPerSecond) % 360.0).toFloat()
            }
        }
    }

    val resolvedYawDegrees = if (orbitView) {
        orbitYawDegrees
    } else {
        viewYawDegrees
    }

    WearSkeletonRenderer(
        skeleton = skeleton,
        frameIndex = frameIndex,
        viewYawDegrees = resolvedYawDegrees,
        viewPitchDegrees = viewPitchDegrees,
        palette = palette,
        modifier = modifier,
    )
}

@Composable
private fun WearSkeletonRenderer(
    skeleton: WearSkeleton,
    frameIndex: Int,
    viewYawDegrees: Float,
    viewPitchDegrees: Float,
    palette: SkeletonPalette,
    modifier: Modifier = Modifier,
) {
    Canvas(
        modifier = modifier
            .fillMaxSize()
            .background(SkeletonBackground)
    ) {
        if (skeleton.frames.isEmpty()) {
            return@Canvas
        }
        val frame = skeleton.frames[frameIndex.coerceIn(0, skeleton.frames.lastIndex)]
        val projector = SkeletonProjector(
            bounds = skeleton.bounds,
            canvasWidth = size.width,
            canvasHeight = size.height,
            yawDegrees = viewYawDegrees,
            pitchDegrees = viewPitchDegrees,
        )
        drawProjectedFloorGrid(skeleton.bounds, projector, palette)
        val items = buildSkeletonItems(frame, projector, density, palette)
            .sortedBy { it.depth }
        items.forEach { item ->
            when (item) {
                is DrawPolygon -> drawPolygon(item)
                is DrawSphere -> drawSphere(item)
            }
        }
    }
}

private fun DrawScope.drawProjectedFloorGrid(
    bounds: WearSkeletonBounds,
    projector: SkeletonProjector,
    palette: SkeletonPalette,
) {
    val floorY = bounds.minY
    val paddingX = (bounds.maxX - bounds.minX) * 0.18f
    val paddingZ = (bounds.maxZ - bounds.minZ) * 0.18f
    val minX = bounds.minX - paddingX
    val maxX = bounds.maxX + paddingX
    val minZ = bounds.minZ - paddingZ
    val maxZ = bounds.maxZ + paddingZ
    val divisions = 8

    for (index in 0..divisions) {
        val t = index / divisions.toFloat()
        val x = minX + (maxX - minX) * t
        val z = minZ + (maxZ - minZ) * t
        val xLineStart = projector.project(WearSkeletonVec3(x, floorY, minZ)).point
        val xLineEnd = projector.project(WearSkeletonVec3(x, floorY, maxZ)).point
        val zLineStart = projector.project(WearSkeletonVec3(minX, floorY, z)).point
        val zLineEnd = projector.project(WearSkeletonVec3(maxX, floorY, z)).point
        drawLine(
            color = palette.grid,
            start = xLineStart,
            end = xLineEnd,
            strokeWidth = 1.1f,
        )
        drawLine(
            color = palette.grid,
            start = zLineStart,
            end = zLineEnd,
            strokeWidth = 1.1f,
        )
    }
}

private fun buildSkeletonItems(
    frame: WearSkeletonFrame,
    projector: SkeletonProjector,
    density: Float,
    palette: SkeletonPalette,
): List<DrawSkeletonItem> {
    val items = mutableListOf<DrawSkeletonItem>()
    val joints = frame.joints

    fun joint(name: String): WearSkeletonVec3? = joints[name]

    addCoreShellPolygons(joints, projector, density, palette, items)
    addHeadSphere(joints, projector, density, palette, items)
    val bodyAxes = joints.toBodyAxes()
    SkeletonLimbs.forEach { limb ->
        val start = joint(limb.startName)
        val end = joint(limb.endName)
        if (start != null && end != null) {
            val rectangles = limbParallelepiped(
                start = start,
                end = end,
                profile = limb.profile,
                bodyAxes = bodyAxes,
                projector = projector,
                fill = palette.limbFill,
            )
            if (rectangles != null) {
                items += rectangles
            }
        }
    }
    addJointCaps(joints, projector, palette, items)
    return items
}

private fun addJointCaps(
    joints: Map<String, WearSkeletonVec3>,
    projector: SkeletonProjector,
    palette: SkeletonPalette,
    items: MutableList<DrawSkeletonItem>,
) {
    SkeletonJointCaps.forEach { joint ->
        val position = joints[joint.name] ?: return@forEach
        val projected = projector.project(position)
        val radius = joint.radius * projector.scale
        items += DrawSphere(
            center = projected.point,
            radius = radius,
            depth = projected.depth,
            fill = palette.limbFill,
            lightOffset = projector.sphereLightOffset(radius),
        )
    }
}

private fun limbParallelepiped(
    start: WearSkeletonVec3,
    end: WearSkeletonVec3,
    profile: LimbProfile,
    bodyAxes: BodyAxes,
    projector: SkeletonProjector,
    fill: Color,
): List<DrawPolygon>? {
    val segment = end - start
    val length = segment.length()
    if (length <= 0.0001f) {
        return null
    }
    val direction = segment * (1f / length)
    val gap = min(length * 0.17f, max(profile.startWidth, profile.endWidth) * 0.38f)
    val shortenedStart = start + direction * gap
    val shortenedEnd = end - direction * gap
    if ((shortenedEnd - shortenedStart).length() <= 0.0001f) {
        return null
    }
    val side = stableLimbSide(direction, bodyAxes)
    val depthAxis = direction.cross(side).normalizedOr(WearSkeletonVec3(0f, 0f, 1f))
    val startHalf = profile.startWidth * 0.5f
    val endHalf = profile.endWidth * 0.5f
    val startDepth = profile.startWidth * 0.28f
    val endDepth = profile.endWidth * 0.28f
    val startLeft = shortenedStart + side * startHalf
    val startRight = shortenedStart - side * startHalf
    val endRight = shortenedEnd - side * endHalf
    val endLeft = shortenedEnd + side * endHalf
    return prismFaces(
        front = listOf(
            startLeft + depthAxis * startDepth,
            endLeft + depthAxis * endDepth,
            endRight + depthAxis * endDepth,
            startRight + depthAxis * startDepth,
        ),
        back = listOf(
            startLeft - depthAxis * startDepth,
            endLeft - depthAxis * endDepth,
            endRight - depthAxis * endDepth,
            startRight - depthAxis * startDepth,
        ),
        projector = projector,
        fill = fill,
    )
}

private fun stableLimbSide(
    direction: WearSkeletonVec3,
    bodyAxes: BodyAxes,
): WearSkeletonVec3 {
    val sideProjection = bodyAxes.side - direction * bodyAxes.side.dot(direction)
    if (sideProjection.length() > 0.18f) {
        return sideProjection.normalizedOr(bodyAxes.side)
    }
    val forwardProjection = bodyAxes.forward - direction * bodyAxes.forward.dot(direction)
    if (forwardProjection.length() > 0.18f) {
        return forwardProjection.normalizedOr(bodyAxes.forward)
    }
    val upProjection = bodyAxes.up - direction * bodyAxes.up.dot(direction)
    return upProjection.normalizedOr(bodyAxes.forward)
}

private fun Map<String, WearSkeletonVec3>.toBodyAxes(): BodyAxes {
    val leftHip = this["left_hip"]
    val rightHip = this["right_hip"]
    val leftShoulder = this["left_shoulder"]
    val rightShoulder = this["right_shoulder"]
    val pelvis = this["pelvis"]
    val neck = this["neck"]

    val hipSide = if (leftHip != null && rightHip != null) {
        rightHip - leftHip
    } else {
        WearSkeletonVec3(1f, 0f, 0f)
    }
    val shoulderSide = if (leftShoulder != null && rightShoulder != null) {
        rightShoulder - leftShoulder
    } else {
        hipSide
    }
    val side = (hipSide + shoulderSide).normalizedOr(WearSkeletonVec3(1f, 0f, 0f))
    val up = if (pelvis != null && neck != null) {
        neck - pelvis
    } else {
        WearSkeletonVec3(0f, 1f, 0f)
    }.normalizedOr(WearSkeletonVec3(0f, 1f, 0f))
    val forward = side.cross(up).normalizedOr(WearSkeletonVec3(0f, 0f, 1f))
    return BodyAxes(side = side, up = up, forward = forward)
}

private fun addCoreShellPolygons(
    joints: Map<String, WearSkeletonVec3>,
    projector: SkeletonProjector,
    density: Float,
    palette: SkeletonPalette,
    items: MutableList<DrawSkeletonItem>,
) {
    val pelvis = joints["pelvis"] ?: return
    val spine1 = joints["spine1"] ?: return
    val spine2 = joints["spine2"] ?: return
    val neck = joints["neck"] ?: return
    val leftHip = joints["left_hip"] ?: return
    val rightHip = joints["right_hip"] ?: return
    val leftShoulder = joints["left_shoulder"] ?: return
    val rightShoulder = joints["right_shoulder"] ?: return

    val hipCenter = leftHip.lerp(rightHip, 0.5f)
    val shoulderCenter = leftShoulder.lerp(rightShoulder, 0.5f)
    val hipWidth = (rightHip - leftHip).length()
    val shoulderWidth = (rightShoulder - leftShoulder).length()
    val hipSide = (rightHip - leftHip).normalizedOr(WearSkeletonVec3(1f, 0f, 0f))
    val shoulderSide = (rightShoulder - leftShoulder).normalizedOr(hipSide)
    val bodyAxes = joints.toBodyAxes()

    val pelvisRings = listOf(
        Ring(hipCenter.lerp(pelvis, 0.58f), hipSide, max(0.13f, hipWidth * 0.82f)),
        Ring(pelvis.lerp(spine1, 0.16f), hipSide, max(0.09f, hipWidth * 0.44f)),
    )
    items += trapezoidPrism(
        lower = pelvisRings[0],
        upper = pelvisRings[1],
        projector = projector,
        fill = palette.coreFill,
    )

    limbParallelepiped(
        start = pelvis.lerp(spine1, 0.28f),
        end = spine1.lerp(spine2, 0.18f),
        profile = LimbProfile(0.060f, 0.058f),
        bodyAxes = bodyAxes,
        projector = projector,
        fill = palette.coreFill,
    )?.let { items += it }

    limbParallelepiped(
        start = spine1.lerp(spine2, 0.42f),
        end = spine2.lerp(shoulderCenter, 0.28f),
        profile = LimbProfile(0.064f, 0.070f),
        bodyAxes = bodyAxes,
        projector = projector,
        fill = palette.coreFill,
    )?.let { items += it }

    val ribcageRings = listOf(
        Ring(spine2.lerp(shoulderCenter, 0.40f), shoulderSide, max(0.14f, shoulderWidth * 0.54f)),
        Ring(shoulderCenter.lerp(neck, 0.16f), shoulderSide, max(0.18f, shoulderWidth * 0.82f)),
    )
    items += trapezoidPrism(
        lower = ribcageRings[0],
        upper = ribcageRings[1],
        projector = projector,
        fill = palette.coreFill,
    )
}

private fun addHeadSphere(
    joints: Map<String, WearSkeletonVec3>,
    projector: SkeletonProjector,
    density: Float,
    palette: SkeletonPalette,
    items: MutableList<DrawSkeletonItem>,
) {
    val head = joints["head"] ?: return
    val neck = joints["neck"] ?: head
    val headLength = max(0.115f, min(0.165f, (head - neck).length() * 0.68f))
    val center = neck.lerp(head, 0.82f)
    val projectedHead = projector.project(center)
    val radius = headLength * projector.scale * 0.62f
    items += DrawSphere(
        center = projectedHead.point,
        radius = radius,
        depth = projectedHead.depth,
        fill = palette.headFill,
        lightOffset = projector.sphereLightOffset(radius),
    )
}

private data class Ring(
    val center: WearSkeletonVec3,
    val side: WearSkeletonVec3,
    val width: Float,
)

private fun trapezoidPrism(
    lower: Ring,
    upper: Ring,
    projector: SkeletonProjector,
    fill: Color,
): List<DrawPolygon> {
    val lowerHalf = lower.width * 0.5f
    val upperHalf = upper.width * 0.5f
    val vertical = (upper.center - lower.center).normalizedOr(WearSkeletonVec3(0f, 1f, 0f))
    val averageSide = (lower.side + upper.side).normalizedOr(WearSkeletonVec3(1f, 0f, 0f))
    val depthAxis = vertical.cross(averageSide).normalizedOr(WearSkeletonVec3(0f, 0f, 1f))
    val halfDepth = min(lower.width, upper.width) * 0.18f

    val lowerLeft = lower.center - lower.side * lowerHalf
    val lowerRight = lower.center + lower.side * lowerHalf
    val upperRight = upper.center + upper.side * upperHalf
    val upperLeft = upper.center - upper.side * upperHalf
    return prismFaces(
        front = listOf(lowerLeft, lowerRight, upperRight, upperLeft).map { it + depthAxis * halfDepth },
        back = listOf(lowerLeft, lowerRight, upperRight, upperLeft).map { it - depthAxis * halfDepth },
        projector = projector,
        fill = fill,
    )
}

private data class LimbProfile(
    val startWidth: Float,
    val endWidth: Float,
)

private fun prismFaces(
    front: List<WearSkeletonVec3>,
    back: List<WearSkeletonVec3>,
    projector: SkeletonProjector,
    fill: Color,
): List<DrawPolygon> {
    return listOf(
        projectedFace(front, projector, fill),
        projectedFace(listOf(back[0], back[1], front[1], front[0]), projector, fill),
        projectedFace(listOf(back[1], back[2], front[2], front[1]), projector, fill),
        projectedFace(listOf(back[2], back[3], front[3], front[2]), projector, fill),
        projectedFace(listOf(back[3], back[0], front[0], front[3]), projector, fill),
        projectedFace(back.asReversed(), projector, fill),
    )
}

private fun projectedFace(
    points: List<WearSkeletonVec3>,
    projector: SkeletonProjector,
    fill: Color,
): DrawPolygon {
    val normal = (points[1] - points[0])
        .cross(points[2] - points[1])
        .normalizedOr(WearSkeletonVec3(0f, 1f, 0f))
    val projectedPoints = points.map { projector.project(it) }
    val litFill = projector.lightColor(fill, normal)
    return DrawPolygon(
        points = projectedPoints.map { it.point },
        depth = projectedPoints.sumOf { it.depth.toDouble() }.toFloat() / projectedPoints.size,
        fill = litFill,
    )
}

private fun DrawScope.drawPolygon(polygon: DrawPolygon) {
    if (polygon.points.size < 3) {
        return
    }
    val path = Path().apply {
        moveTo(polygon.points.first().x, polygon.points.first().y)
        polygon.points.drop(1).forEach { point ->
            lineTo(point.x, point.y)
        }
        close()
    }
    drawPath(path = path, color = polygon.fill)
}

private fun DrawScope.drawSphere(sphere: DrawSphere) {
    drawCircle(
        brush = Brush.radialGradient(
            colorStops = arrayOf(
                0.0f to sphere.fill.mix(Color.White, 0.26f),
                0.58f to sphere.fill,
                1.0f to sphere.fill.mix(Color.Black, 0.28f),
            ),
            center = sphere.center + sphere.lightOffset,
            radius = sphere.radius * 1.28f,
        ),
        radius = sphere.radius,
        center = sphere.center,
    )
}

private class SkeletonProjector(
    bounds: WearSkeletonBounds,
    canvasWidth: Float,
    canvasHeight: Float,
    yawDegrees: Float,
    pitchDegrees: Float,
) {
    private val yaw = (yawDegrees * PI / 180.0).toFloat()
    private val pitch = (pitchDegrees * PI / 180.0).toFloat()
    private val center = WearSkeletonVec3(
        (bounds.minX + bounds.maxX) * 0.5f,
        bounds.minY,
        (bounds.minZ + bounds.maxZ) * 0.5f,
    )
    val scale: Float

    private val canvasCenter = Offset(canvasWidth * 0.5f, canvasHeight * 0.70f)

    init {
        val corners = listOf(
            WearSkeletonVec3(bounds.minX, bounds.minY, bounds.minZ),
            WearSkeletonVec3(bounds.minX, bounds.minY, bounds.maxZ),
            WearSkeletonVec3(bounds.minX, bounds.maxY, bounds.minZ),
            WearSkeletonVec3(bounds.minX, bounds.maxY, bounds.maxZ),
            WearSkeletonVec3(bounds.maxX, bounds.minY, bounds.minZ),
            WearSkeletonVec3(bounds.maxX, bounds.minY, bounds.maxZ),
            WearSkeletonVec3(bounds.maxX, bounds.maxY, bounds.minZ),
            WearSkeletonVec3(bounds.maxX, bounds.maxY, bounds.maxZ),
        ).map { rotate(it - center).first }
        val width = corners.maxOf { it.x } - corners.minOf { it.x }
        val maxAboveFloor = corners.maxOf { it.y }.coerceAtLeast(0.001f)
        val maxBelowFloor = (-corners.minOf { it.y }).coerceAtLeast(0.001f)
        val horizontalScale = canvasWidth * 0.80f / max(width, 0.001f)
        val upwardScale = canvasCenter.y * 0.90f / maxAboveFloor
        val downwardScale = (canvasHeight - canvasCenter.y) * 0.88f / maxBelowFloor
        scale = min(horizontalScale, min(upwardScale, downwardScale))
    }

    fun project(point: WearSkeletonVec3): WearSkeletonProjectedPoint {
        val (rotated, depth) = rotate(point - center)
        return WearSkeletonProjectedPoint(
            point = Offset(
                x = canvasCenter.x + rotated.x * scale,
                y = canvasCenter.y - rotated.y * scale,
            ),
            depth = depth,
        )
    }

    fun lightColor(fill: Color, worldNormal: WearSkeletonVec3): Color {
        val viewNormal = rotateDirection(worldNormal).normalizedOr(WearSkeletonVec3(0f, 1f, 0f))
        val diffuse = ((viewNormal.dot(SkeletonViewLightDirection) + 1f) * 0.5f).coerceIn(0f, 1f)
        return when {
            diffuse > 0.72f -> fill.mix(Color.White, (diffuse - 0.72f) * 0.46f)
            diffuse < 0.38f -> fill.mix(Color.Black, (0.38f - diffuse) * 0.72f)
            else -> fill
        }
    }

    fun sphereLightOffset(radius: Float): Offset {
        val light = SkeletonViewLightDirection.normalizedOr(WearSkeletonVec3(0f, 1f, 0f))
        return Offset(
            x = light.x * radius * 0.34f,
            y = -light.y * radius * 0.34f,
        )
    }

    private fun rotateDirection(point: WearSkeletonVec3): WearSkeletonVec3 {
        val x1 = cos(yaw) * point.x + sin(yaw) * point.z
        val z1 = -sin(yaw) * point.x + cos(yaw) * point.z
        val y2 = cos(pitch) * point.y - sin(pitch) * z1
        val z2 = sin(pitch) * point.y + cos(pitch) * z1
        return WearSkeletonVec3(x1, y2, z2)
    }

    private fun rotate(point: WearSkeletonVec3): Pair<WearSkeletonVec3, Float> {
        val rotated = rotateDirection(point)
        return rotated to rotated.z
    }
}

private fun parseWearSkeleton(json: String): WearSkeleton {
    val root = JsonParser.parseString(json).asJsonObject
    val boundsObject = root.getAsJsonObject("bounds")
    val frames = root.getAsJsonArray("frames").map { frameElement ->
        val jointsObject = frameElement.asJsonObject.getAsJsonObject("joints")
        WearSkeletonFrame(
            joints = jointsObject.entrySet().associate { (name, element) ->
                val values = element.asJsonArray
                name to WearSkeletonVec3(
                    x = values[0].asFloat,
                    y = values[1].asFloat,
                    z = values[2].asFloat,
                )
            }
        )
    }
    return WearSkeleton(
        fps = root.get("fps")?.asFloat ?: 30f,
        bounds = boundsObject.toWearSkeletonBounds(),
        frames = frames,
    )
}

private fun JsonObject.toWearSkeletonBounds(): WearSkeletonBounds = WearSkeletonBounds(
    minX = get("minX").asFloat,
    maxX = get("maxX").asFloat,
    minY = get("minY").asFloat,
    maxY = get("maxY").asFloat,
    minZ = get("minZ").asFloat,
    maxZ = get("maxZ").asFloat,
)

private fun Int.floorMod(modulus: Int): Int = ((this % modulus) + modulus) % modulus

@Preview(device = WearDevices.LARGE_ROUND, showBackground = true)
@Composable
private fun WearSkeletonMotionPreviewPreview() {
    MaterialTheme(
        colorScheme = darkScheme,
        typography = baseline,
    ) {
        Box(modifier = Modifier.fillMaxSize()) {
            WearSkeletonMotionPreview(
                modifier = Modifier.fillMaxSize(),
                animated = true,
                orbitView = true,
            )
        }
    }
}
