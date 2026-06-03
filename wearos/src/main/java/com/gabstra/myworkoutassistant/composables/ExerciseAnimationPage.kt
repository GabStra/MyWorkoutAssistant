package com.gabstra.myworkoutassistant.composables

import android.content.Context
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.FilledTonalButton
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.google.gson.Gson
import com.google.gson.annotations.SerializedName
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt

private const val DEFAULT_PLAYBACK_FPS = 30f
private const val DEFAULT_HEAD_RADIUS = 0.09f
private const val DEFAULT_FOOT_LENGTH = 0.12f
private const val DEFAULT_FLOOR_Y = 0.05f

@Composable
fun ExerciseAnimationPage(
    exercise: Exercise,
    motionSlugOverride: String? = null,
    labelOverride: String? = null,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val clipState = produceState<LoadedExerciseMotionClip?>(initialValue = null, exercise.name, motionSlugOverride) {
        value = withContext(Dispatchers.IO) {
            loadExerciseMotionClip(
                context = context,
                exercise = exercise,
                motionSlugOverride = motionSlugOverride,
                labelOverride = labelOverride,
            )
        }
    }

    val clip = clipState.value
    if (clip == null) {
        Box(
            modifier = modifier.fillMaxSize(),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = "Loading animation…",
                style = MaterialTheme.typography.bodyMedium,
                textAlign = TextAlign.Center,
            )
        }
        return
    }

    ExerciseAnimationViewer(
        asset = clip,
        label = clip.label,
        modifier = modifier,
    )
}

@Composable
private fun ExerciseAnimationViewer(
    asset: LoadedExerciseMotionClip,
    label: String,
    modifier: Modifier = Modifier,
) {
    val clip = asset.clip
    var yaw by remember { mutableFloatStateOf(-0.25f) }
    var pitch by remember { mutableFloatStateOf(0.18f) }
    var zoom by remember { mutableFloatStateOf(1.0f) }
    var frameIndex by remember(clip) { mutableStateOf(0) }
    val headColor = MaterialTheme.colorScheme.secondary
    val footColor = MaterialTheme.colorScheme.tertiary
    val jointColor = MaterialTheme.colorScheme.onBackground.copy(alpha = 0.5f)

    LaunchedEffect(clip) {
        if (clip.frames.isEmpty()) return@LaunchedEffect
        val frameDurationMs = max(16L, (1000f / clip.fps.coerceAtLeast(1f)).toLong())
        while (true) {
            kotlinx.coroutines.delay(frameDurationMs)
            frameIndex = (frameIndex + 1) % clip.frames.size
        }
    }

    Box(
        modifier = modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
    ) {
        Canvas(
            modifier = Modifier
                .fillMaxSize()
                .semantics { contentDescription = "Animation viewer canvas" }
                .pointerInput(clip) {
                    detectTransformGestures { _, pan, gestureZoom, _ ->
                        yaw += pan.x * 0.01f
                        pitch = (pitch - pan.y * 0.01f).coerceIn(-0.8f, 0.8f)
                        zoom = (zoom * gestureZoom).coerceIn(0.65f, 1.85f)
                    }
                }
        ) {
            drawExerciseFrame(
                frame = clip.frames[frameIndex],
                jointNames = clip.jointNames,
                groundPlane = asset.groundPlane,
                yaw = yaw,
                pitch = pitch,
                zoom = zoom,
                headColor = headColor,
                footColor = footColor,
                jointColor = jointColor,
            )
        }

        Column(
            modifier = Modifier
                .align(Alignment.TopCenter)
                .fillMaxWidth()
                .padding(top = 8.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            Text(
                text = exerciseHint(label),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.primary,
                textAlign = TextAlign.Center,
            )
            Text(
                text = "Drag to rotate",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onBackground.copy(alpha = 0.72f),
                textAlign = TextAlign.Center,
            )
        }

        Row(
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth()
                .padding(horizontal = 18.dp, vertical = 12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            FilledTonalButton(
                onClick = { zoom = (zoom * 0.9f).coerceAtLeast(0.65f) },
                modifier = Modifier
                    .size(36.dp)
                    .semantics { contentDescription = "Animation zoom out" },
                shape = CircleShape,
            ) {
                Text("−")
            }
            FilledTonalButton(
                onClick = {
                    yaw = -0.25f
                    pitch = 0.18f
                    zoom = 1.0f
                },
                modifier = Modifier
                    .padding(horizontal = 8.dp)
                    .semantics { contentDescription = "Animation reset view" },
            ) {
                Text("Reset")
            }
            FilledTonalButton(
                onClick = { zoom = (zoom * 1.1f).coerceAtMost(1.85f) },
                modifier = Modifier
                    .size(36.dp)
                    .semantics { contentDescription = "Animation zoom in" },
                shape = CircleShape,
            ) {
                Text("+")
            }
        }
    }
}

private fun DrawScope.drawExerciseFrame(
    frame: ExerciseMotionFrame,
    jointNames: List<String>,
    groundPlane: RenderGroundPlane?,
    yaw: Float,
    pitch: Float,
    zoom: Float,
    headColor: Color,
    footColor: Color,
    jointColor: Color,
) {
    val points = frame.joints
    if (points.isEmpty()) return

    val pelvis = points["pelvis"] ?: points["root"] ?: points["hips"] ?: points.values.first()
    val sceneOrigin = groundPlane?.origin ?: Vec3(pelvis.x, 0f, pelvis.z)
    val rightAxis = estimateRightAxis(points)
    val forwardAxis = normalize(cross(Vec3(0f, 1f, 0f), rightAxis)).ifZero(Vec3(0f, 0f, -1f))
    val centerX = size.width * 0.5f
    val centerY = size.height * 0.56f
    val baseScale = min(size.width, size.height) * 0.34f * zoom

    val projected = points.mapValues { (_, point) ->
        projectPoint(
            point = point - sceneOrigin,
            yaw = yaw,
            pitch = pitch,
            scale = baseScale,
            centerX = centerX,
            centerY = centerY,
        )
    }

    drawGroundPlane(
        sceneOrigin = sceneOrigin,
        groundPlane = groundPlane,
        yaw = yaw,
        pitch = pitch,
        scale = baseScale,
        centerX = centerX,
        centerY = centerY,
    )

    val footSegments = buildFootSegments(points, forwardAxis).map { (name, start, end) ->
        RenderSegment(
            key = name,
            start = projectPoint(start - sceneOrigin, yaw, pitch, baseScale, centerX, centerY),
            end = projectPoint(end - sceneOrigin, yaw, pitch, baseScale, centerX, centerY),
            radius = 0.055f,
            color = footColor,
        )
    }

    val bodySegments = BODY_SEGMENTS.mapNotNull { segment ->
        val start = projected[segment.start] ?: return@mapNotNull null
        val end = projected[segment.end] ?: return@mapNotNull null
        RenderSegment(
            key = "${segment.start}-${segment.end}",
            start = start,
            end = end,
            radius = segment.radius,
            color = segment.color,
        )
    }

    val head = buildHead(points)?.let { (center, radius) ->
        RenderSphere(
            center = projectPoint(center - sceneOrigin, yaw, pitch, baseScale, centerX, centerY),
            radius = radius,
            color = headColor,
        )
    }

    val renderItems = mutableListOf<DepthSortable>()
    renderItems += bodySegments
    renderItems += footSegments
    if (head != null) {
        renderItems += head
    }

    renderItems.sortedBy { it.depth }.forEach { item ->
        when (item) {
            is RenderSegment -> drawCapsule(item)
            is RenderSphere -> drawSphere(item)
        }
    }

    val visibleJoints = jointNames.mapNotNull { projected[it] }
    visibleJoints.forEach { point ->
        drawCircle(
            color = jointColor,
            radius = point.scalePixels(0.018f),
            center = point.offset,
        )
    }
}

private fun DrawScope.drawGroundPlane(
    sceneOrigin: Vec3,
    groundPlane: RenderGroundPlane?,
    yaw: Float,
    pitch: Float,
    scale: Float,
    centerX: Float,
    centerY: Float,
) {
    val plane = groundPlane ?: return
    if (abs(plane.normal.y) < 0.5f) return

    val groundY = (-plane.offset / plane.normal.y) - sceneOrigin.y
    val groundOrigin = plane.origin - sceneOrigin
    val gridHalfSize = 0.75f
    val linePositions = listOf(-0.6f, -0.3f, 0f, 0.3f, 0.6f)
    val lineColor = plane.color

    linePositions.forEach { position ->
        drawProjectedFloorLine(
            start = Vec3(groundOrigin.x - gridHalfSize, groundY, groundOrigin.z + position),
            end = Vec3(groundOrigin.x + gridHalfSize, groundY, groundOrigin.z + position),
            yaw = yaw,
            pitch = pitch,
            scale = scale,
            centerX = centerX,
            centerY = centerY,
            color = lineColor,
            width = if (position == 0f) 2.6f else 1.4f,
        )
        drawProjectedFloorLine(
            start = Vec3(groundOrigin.x + position, groundY, groundOrigin.z - gridHalfSize),
            end = Vec3(groundOrigin.x + position, groundY, groundOrigin.z + gridHalfSize),
            yaw = yaw,
            pitch = pitch,
            scale = scale,
            centerX = centerX,
            centerY = centerY,
            color = lineColor,
            width = if (position == 0f) 2.6f else 1.4f,
        )
    }
}

private fun DrawScope.drawProjectedFloorLine(
    start: Vec3,
    end: Vec3,
    yaw: Float,
    pitch: Float,
    scale: Float,
    centerX: Float,
    centerY: Float,
    color: Color,
    width: Float,
) {
    val startPoint = projectPoint(
        point = start,
        yaw = yaw,
        pitch = pitch,
        scale = scale,
        centerX = centerX,
        centerY = centerY,
    )
    val endPoint = projectPoint(
        point = end,
        yaw = yaw,
        pitch = pitch,
        scale = scale,
        centerX = centerX,
        centerY = centerY,
    )
    drawLine(
        color = color,
        start = startPoint.offset,
        end = endPoint.offset,
        strokeWidth = width,
        cap = StrokeCap.Round,
    )
}

private fun DrawScope.drawCapsule(segment: RenderSegment) {
    drawLine(
        color = segment.color,
        start = segment.start.offset,
        end = segment.end.offset,
        strokeWidth = ((segment.start.scalePixels(segment.radius) + segment.end.scalePixels(segment.radius)) * 0.5f)
            .coerceAtLeast(4f),
        cap = StrokeCap.Round,
    )
}

private fun DrawScope.drawSphere(sphere: RenderSphere) {
    drawCircle(
        color = sphere.color,
        radius = sphere.center.scalePixels(sphere.radius).coerceAtLeast(4f),
        center = sphere.center.offset,
    )
}

private fun buildHead(points: Map<String, Vec3>): Pair<Vec3, Float>? {
    val head = points["head"]
    val neck = points["neck"]
    return when {
        head != null && neck != null -> {
            val radius = max(DEFAULT_HEAD_RADIUS * 0.8f, distance(head, neck) * 0.9f)
            head to radius
        }
        head != null -> head to DEFAULT_HEAD_RADIUS
        neck != null -> (neck + Vec3(0f, DEFAULT_HEAD_RADIUS * 1.15f, 0f)) to DEFAULT_HEAD_RADIUS
        else -> null
    }
}

private fun buildFootSegments(points: Map<String, Vec3>, forwardAxis: Vec3): List<Triple<String, Vec3, Vec3>> {
    val footForward = forwardAxis * DEFAULT_FOOT_LENGTH
    return listOfNotNull(
        points["left_ankle"]?.let { ankle ->
            Triple("left_foot", ankle, ankle + footForward + Vec3(0f, -0.015f, 0f))
        },
        points["right_ankle"]?.let { ankle ->
            Triple("right_foot", ankle, ankle + footForward + Vec3(0f, -0.015f, 0f))
        },
        points["l_ankle"]?.let { ankle ->
            Triple("left_foot_alt", ankle, ankle + footForward + Vec3(0f, -0.015f, 0f))
        },
        points["r_ankle"]?.let { ankle ->
            Triple("right_foot_alt", ankle, ankle + footForward + Vec3(0f, -0.015f, 0f))
        },
    )
}

private fun estimateRightAxis(points: Map<String, Vec3>): Vec3 {
    val left = points["left_hip"] ?: points["left_shoulder"] ?: Vec3(-0.2f, 0f, 0f)
    val right = points["right_hip"] ?: points["right_shoulder"] ?: Vec3(0.2f, 0f, 0f)
    return normalize(right - left).ifZero(Vec3(1f, 0f, 0f))
}

private fun projectPoint(
    point: Vec3,
    yaw: Float,
    pitch: Float,
    scale: Float,
    centerX: Float,
    centerY: Float,
): ProjectedPoint {
    val cy = cos(yaw)
    val sy = sin(yaw)
    val cx = cos(pitch)
    val sx = sin(pitch)

    val yawRotated = Vec3(
        x = point.x * cy + point.z * sy,
        y = point.y,
        z = -point.x * sy + point.z * cy,
    )
    val rotated = Vec3(
        x = yawRotated.x,
        y = yawRotated.y * cx - yawRotated.z * sx,
        z = yawRotated.y * sx + yawRotated.z * cx,
    )

    val perspective = 1f / (1f + rotated.z * 0.35f)
    return ProjectedPoint(
        offset = Offset(
            x = centerX + rotated.x * scale * perspective,
            y = centerY - rotated.y * scale * perspective,
        ),
        depth = rotated.z,
        perspective = perspective,
    )
}

private fun exerciseHint(label: String): String =
    if (label.isBlank()) "Animation preview" else "Animation preview • $label"

private fun loadExerciseMotionClip(
    context: Context,
    exercise: Exercise,
    motionSlugOverride: String?,
    labelOverride: String?,
): LoadedExerciseMotionClip {
    val slugCandidates = buildSlugCandidates(exercise, motionSlugOverride)
    for (slug in slugCandidates) {
        val exerciseDir = context.filesDir.resolve("exercise_motion").resolve(slug)
        val fileCandidate = exerciseDir.resolve("motion.cleaned.json")
        if (fileCandidate.exists()) {
            parseMotionClip(
                json = fileCandidate.readText(),
                label = labelOverride ?: slug,
                groundJson = exerciseDir.resolve("ground.metadata.json").takeIf { it.exists() }?.readText(),
            )?.let { return it }
        }

        val assetBase = "exercise_motion/$slug"
        val assetCandidate = "$assetBase/motion.cleaned.json"
        runCatching {
            context.assets.open(assetCandidate).bufferedReader().use { it.readText() }
        }.getOrNull()?.let { text ->
            val groundJson = runCatching {
                context.assets.open("$assetBase/ground.metadata.json").bufferedReader().use { it.readText() }
            }.getOrNull()
            parseMotionClip(json = text, label = labelOverride ?: slug, groundJson = groundJson)?.let { return it }
        }
    }

    return LoadedExerciseMotionClip(
        clip = buildFallbackMotionClip(exercise),
        groundPlane = RenderGroundPlane(
            normal = Vec3(0f, 1f, 0f),
            offset = -DEFAULT_FLOOR_Y,
            origin = Vec3(0f, DEFAULT_FLOOR_Y, 0f),
            color = Color(0x3386E0C2),
        ),
        label = labelOverride ?: "demo",
    )
}

private fun buildSlugCandidates(exercise: Exercise, motionSlugOverride: String?): List<String> {
    val base = slugify(exercise.name)
    val variants = mutableListOf(base)
    if (!motionSlugOverride.isNullOrBlank()) {
        variants.add(0, slugify(motionSlugOverride))
    }
    if (exercise.exerciseType == ExerciseType.BODY_WEIGHT) {
        variants += "${base}-body-weight"
    }
    return variants.distinct().filter { it.isNotBlank() }
}

private fun parseMotionClip(
    json: String,
    label: String,
    groundJson: String? = null,
): LoadedExerciseMotionClip? {
    return runCatching {
        val payload = Gson().fromJson(json, MotionJsonPayload::class.java)
        val frames = payload.frames.orEmpty().mapNotNull { frame ->
            val joints = frame.joints.orEmpty().mapNotNull { (name, coords) ->
                val x = coords.getOrNull(0)?.toFloat() ?: return@mapNotNull null
                val y = coords.getOrNull(1)?.toFloat() ?: return@mapNotNull null
                val z = coords.getOrNull(2)?.toFloat() ?: return@mapNotNull null
                name to Vec3(x, y, z)
            }.toMap()
            if (joints.isEmpty()) {
                null
            } else {
                ExerciseMotionFrame(
                    timeSec = frame.timeSec ?: 0f,
                    joints = joints,
                )
            }
        }
        if (frames.isEmpty()) {
            null
        } else {
            LoadedExerciseMotionClip(
                clip = ExerciseMotionClip(
                    fps = payload.fps ?: DEFAULT_PLAYBACK_FPS,
                    jointNames = payload.jointNames.orEmpty(),
                    frames = frames,
                ),
                groundPlane = payload.metadata?.ground?.toRenderGroundPlane()
                    ?: parseGroundMetadata(groundJson),
                label = label,
            )
        }
    }.getOrNull()
}

private fun buildFallbackMotionClip(exercise: Exercise): ExerciseMotionClip {
    val frames = (0 until 48).map { index ->
        val phase = index / 47f
        val pulse = sin(phase * Math.PI).toFloat()
        val pelvisY = 1.0f - pulse * 0.18f
        val handLift = if (exercise.exerciseType == ExerciseType.WEIGHT) pulse * 0.12f else 0f
        ExerciseMotionFrame(
            timeSec = index / DEFAULT_PLAYBACK_FPS,
            joints = mapOf(
                "pelvis" to Vec3(0f, pelvisY, 0f),
                "spine" to Vec3(0f, pelvisY + 0.22f, 0f),
                "neck" to Vec3(0f, pelvisY + 0.43f, 0f),
                "head" to Vec3(0f, pelvisY + 0.58f, 0f),
                "left_shoulder" to Vec3(-0.18f, pelvisY + 0.4f, 0f),
                "right_shoulder" to Vec3(0.18f, pelvisY + 0.4f, 0f),
                "left_elbow" to Vec3(-0.24f, pelvisY + 0.24f + handLift, 0f),
                "right_elbow" to Vec3(0.24f, pelvisY + 0.24f + handLift, 0f),
                "left_wrist" to Vec3(-0.26f, pelvisY + 0.05f + handLift * 1.2f, 0f),
                "right_wrist" to Vec3(0.26f, pelvisY + 0.05f + handLift * 1.2f, 0f),
                "left_hip" to Vec3(-0.12f, pelvisY - 0.04f, 0f),
                "right_hip" to Vec3(0.12f, pelvisY - 0.04f, 0f),
                "left_knee" to Vec3(-0.12f, 0.54f - pulse * 0.16f, 0f),
                "right_knee" to Vec3(0.12f, 0.54f - pulse * 0.16f, 0f),
                "left_ankle" to Vec3(-0.12f, 0.05f, 0f),
                "right_ankle" to Vec3(0.12f, 0.05f, 0f),
            ),
        )
    }
    return ExerciseMotionClip(
        fps = DEFAULT_PLAYBACK_FPS,
        jointNames = frames.first().joints.keys.toList(),
        frames = frames,
    )
}

private fun slugify(value: String): String {
    val builder = StringBuilder()
    var previousDash = false
    value.lowercase().forEach { char ->
        when {
            char.isLetterOrDigit() -> {
                builder.append(char)
                previousDash = false
            }
            !previousDash -> {
                builder.append('-')
                previousDash = true
            }
        }
    }
    return builder.toString().trim('-')
}

private data class LoadedExerciseMotionClip(
    val clip: ExerciseMotionClip,
    val groundPlane: RenderGroundPlane?,
    val label: String,
)

private data class ExerciseMotionClip(
    val fps: Float,
    val jointNames: List<String>,
    val frames: List<ExerciseMotionFrame>,
)

private data class ExerciseMotionFrame(
    val timeSec: Float,
    val joints: Map<String, Vec3>,
)

private data class MotionJsonPayload(
    @SerializedName("fps") val fps: Float? = null,
    @SerializedName("jointNames") val jointNames: List<String>? = null,
    @SerializedName("frames") val frames: List<MotionJsonFrame>? = null,
    @SerializedName("metadata") val metadata: MotionMetadataPayload? = null,
)

private data class MotionJsonFrame(
    @SerializedName("timeSec") val timeSec: Float? = null,
    @SerializedName("joints") val joints: Map<String, List<Double>>? = null,
)

private data class MotionMetadataPayload(
    @SerializedName("ground") val ground: GroundMetadataPayload? = null,
)

private data class GroundMetadataPayload(
    @SerializedName("renderGroundPlane") val renderGroundPlane: GroundPlanePayload? = null,
    @SerializedName("renderGroundOrigin") val renderGroundOrigin: GroundOriginPayload? = null,
)

private data class GroundPlanePayload(
    @SerializedName("normal") val normal: List<Double>? = null,
    @SerializedName("offset") val offset: Double? = null,
)

private data class GroundOriginPayload(
    @SerializedName("point") val point: List<Double>? = null,
)

private data class BodySegment(
    val start: String,
    val end: String,
    val radius: Float,
    val color: Color,
)

private val BODY_SEGMENTS = listOf(
    BodySegment("pelvis", "spine", 0.09f, Color(0xFF86E0C2)),
    BodySegment("spine", "neck", 0.08f, Color(0xFF86E0C2)),
    BodySegment("neck", "left_shoulder", 0.055f, Color(0xFFF0D48A)),
    BodySegment("left_shoulder", "left_elbow", 0.055f, Color(0xFFF0D48A)),
    BodySegment("left_elbow", "left_wrist", 0.045f, Color(0xFFF0D48A)),
    BodySegment("neck", "right_shoulder", 0.055f, Color(0xFFF0D48A)),
    BodySegment("right_shoulder", "right_elbow", 0.055f, Color(0xFFF0D48A)),
    BodySegment("right_elbow", "right_wrist", 0.045f, Color(0xFFF0D48A)),
    BodySegment("pelvis", "left_hip", 0.06f, Color(0xFF8FB7FF)),
    BodySegment("left_hip", "left_knee", 0.06f, Color(0xFF8FB7FF)),
    BodySegment("left_knee", "left_ankle", 0.05f, Color(0xFF8FB7FF)),
    BodySegment("pelvis", "right_hip", 0.06f, Color(0xFF8FB7FF)),
    BodySegment("right_hip", "right_knee", 0.06f, Color(0xFF8FB7FF)),
    BodySegment("right_knee", "right_ankle", 0.05f, Color(0xFF8FB7FF)),
)

private sealed interface DepthSortable {
    val depth: Float
}

private data class RenderSegment(
    val key: String,
    val start: ProjectedPoint,
    val end: ProjectedPoint,
    val radius: Float,
    val color: Color,
) : DepthSortable {
    override val depth: Float = (start.depth + end.depth) * 0.5f
}

private data class RenderSphere(
    val center: ProjectedPoint,
    val radius: Float,
    val color: Color,
) : DepthSortable {
    override val depth: Float = center.depth
}

private data class RenderGroundPlane(
    val normal: Vec3,
    val offset: Float,
    val origin: Vec3,
    val color: Color,
)

private data class ProjectedPoint(
    val offset: Offset,
    val depth: Float,
    val perspective: Float,
) {
    fun scalePixels(baseRadius: Float): Float = (baseRadius * perspective * 180f).coerceAtLeast(3f)
}

private data class Vec3(
    val x: Float,
    val y: Float,
    val z: Float,
) {
    operator fun plus(other: Vec3): Vec3 = Vec3(x + other.x, y + other.y, z + other.z)
    operator fun minus(other: Vec3): Vec3 = Vec3(x - other.x, y - other.y, z - other.z)
    operator fun times(scale: Float): Vec3 = Vec3(x * scale, y * scale, z * scale)
    fun ifZero(fallback: Vec3): Vec3 = if (abs(x) + abs(y) + abs(z) < 1e-5f) fallback else this
}

private fun GroundMetadataPayload.toRenderGroundPlane(): RenderGroundPlane? {
    val planePayload = renderGroundPlane ?: return null
    val rawNormal = planePayload.normal ?: return null
    val normalX = rawNormal.getOrNull(0)?.toFloat() ?: return null
    val normalY = rawNormal.getOrNull(1)?.toFloat() ?: return null
    val normalZ = rawNormal.getOrNull(2)?.toFloat() ?: return null
    val rawOffset = planePayload.offset?.toFloat() ?: return null
    val groundY = if (abs(normalY) > 1e-5f) (-rawOffset / normalY) else 0f
    val originCoords = renderGroundOrigin?.point
    return RenderGroundPlane(
        normal = normalize(Vec3(normalX, normalY, normalZ)).ifZero(Vec3(0f, 1f, 0f)),
        offset = rawOffset,
        origin = Vec3(
            x = originCoords?.getOrNull(0)?.toFloat() ?: 0f,
            y = originCoords?.getOrNull(1)?.toFloat() ?: groundY,
            z = originCoords?.getOrNull(2)?.toFloat() ?: 0f,
        ),
        color = Color(0x3386E0C2),
    )
}

private fun parseGroundMetadata(json: String?): RenderGroundPlane? {
    if (json.isNullOrBlank()) return null
    return runCatching {
        Gson().fromJson(json, GroundMetadataPayload::class.java)
            ?.toRenderGroundPlane()
    }.getOrNull()
}

private fun distance(left: Vec3, right: Vec3): Float {
    val dx = right.x - left.x
    val dy = right.y - left.y
    val dz = right.z - left.z
    return sqrt(dx * dx + dy * dy + dz * dz)
}

private fun normalize(vector: Vec3): Vec3 {
    val length = sqrt(vector.x * vector.x + vector.y * vector.y + vector.z * vector.z)
    if (length <= 1e-5f) return Vec3(0f, 0f, 0f)
    return Vec3(vector.x / length, vector.y / length, vector.z / length)
}

private fun cross(left: Vec3, right: Vec3): Vec3 =
    Vec3(
        x = left.y * right.z - left.z * right.y,
        y = left.z * right.x - left.x * right.z,
        z = left.x * right.y - left.y * right.x,
    )
