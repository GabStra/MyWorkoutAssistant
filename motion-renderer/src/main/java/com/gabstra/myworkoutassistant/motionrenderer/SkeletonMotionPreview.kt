package com.gabstra.myworkoutassistant.motionrenderer

import android.content.Context
import android.graphics.Bitmap
import android.os.Handler
import android.os.Looper
import android.view.Choreographer
import android.view.Surface
import android.view.TextureView
import android.view.View
import android.widget.FrameLayout
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import com.gabstra.myworkoutassistant.shared.MediumGray
import com.google.android.filament.Camera
import com.google.android.filament.Engine
import com.google.android.filament.EntityManager
import com.google.android.filament.Filament
import com.google.android.filament.IndexBuffer
import com.google.android.filament.Material
import com.google.android.filament.MaterialInstance
import com.google.android.filament.RenderableManager
import com.google.android.filament.Renderer
import com.google.android.filament.Scene
import com.google.android.filament.SwapChain
import com.google.android.filament.Texture
import com.google.android.filament.VertexBuffer
import com.google.android.filament.Viewport
import com.google.android.filament.android.UiHelper
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.FloatBuffer
import java.nio.ShortBuffer
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt
import com.google.android.filament.Box as FilamentBox
import com.google.android.filament.View as FilamentView

private const val OrbitDegreesPerSecond = 18f
private const val FilamentPoseFloatCount = 7
private const val FilamentPoseStrideBytes = FilamentPoseFloatCount * 4
private const val FilamentPositionOffsetBytes = 0
private const val FilamentNormalOffsetBytes = 3 * 4
private const val FilamentColorFloatCount = 4
private const val FilamentColorStrideBytes = FilamentColorFloatCount * 4
private const val DragRotationDegreesPerPixel = 0.45f
private const val SkeletonPreviewContentDescription = "Exercise movement preview"
private const val ListThumbnailPixelSize = 160
private const val SkeletonKeyLightYawOffsetDegrees = -25f
private const val SkeletonKeyLightElevationDegrees = 50f
private const val SkeletonAmbientLightLevel = 0.38f
private const val SkeletonKeyLightStrength = 0.48f
private const val SkeletonFillLightStrength = 0.14f
private const val SkeletonHemisphereLightStrength = 0.10f

private val SkeletonFallbackBackground = Color.Black

private data class SkeletonPalette(
    val limbFill: Color,
    val coreFill: Color,
    val headFill: Color,
    val jointFill: Color,
    val grid: Color,
)

private fun createSkeletonPalette(primaryFill: Color): SkeletonPalette {
    return SkeletonPalette(
        limbFill = primaryFill,
        coreFill = primaryFill,
        headFill = primaryFill,
        jointFill = MediumGray,
        grid = primaryFill,
    )
}

private fun Float.srgbToLinearChannel(): Float {
    val channel = coerceIn(0f, 1f)
    return if (channel <= 0.04045f) {
        channel / 12.92f
    } else {
        Math.pow(((channel + 0.055f) / 1.055f).toDouble(), 2.4).toFloat()
    }
}

private data class WearSkeleton(
    val fps: Float,
    val frames: List<WearSkeletonFrame>,
    val bounds: WearSkeletonBounds,
    val display: WearSkeletonDisplay,
    val limbSidesByFrame: List<Map<LimbKey, WearSkeletonVec3>>,
)

private data class WearSkeletonDisplay(
    val viewYawDegrees: Float? = null,
    val viewPitchDegrees: Float? = null,
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

private data class StableBodyProportions(
    val hipWidth: Float,
    val shoulderWidth: Float,
    val segmentLengths: Map<LimbKey, Float>,
)

private data class SkeletonLoopPlayback(
    val frameIndex: Int,
    val visibility: Float,
    val motionElapsedSeconds: Double,
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

private enum class WearSkeletonDisplayCoordinateTransform {
    None,
    RotateXPi;

    fun apply(point: WearSkeletonVec3): WearSkeletonVec3 = when (this) {
        None -> point
        RotateXPi -> WearSkeletonVec3(point.x, -point.y, -point.z)
    }

    fun apply(bounds: WearSkeletonBounds): WearSkeletonBounds = when (this) {
        None -> bounds
        RotateXPi -> bounds.copy(
            minY = -bounds.maxY,
            maxY = -bounds.minY,
            minZ = -bounds.maxZ,
            maxZ = -bounds.minZ,
        )
    }
}

private data class LimbSpec(
    val startName: String,
    val endName: String,
    val profile: LimbProfile,
)

private data class LimbKey(
    val startName: String,
    val endName: String,
)

private data class BodyAxes(
    val side: WearSkeletonVec3,
    val up: WearSkeletonVec3,
    val forward: WearSkeletonVec3,
)

private data class GeneratedLowPolyMesh(
    val vertices: MutableList<WearSkeletonVec3> = mutableListOf(),
    val faces: MutableList<GeneratedLowPolyFace> = mutableListOf(),
)

private data class GeneratedLowPolyFace(
    val vertexIndices: List<Int>,
    val fill: Color,
)

private val VisibleJointCapNames = setOf(
    "left_hip",
    "right_hip",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
)

private val SkeletonLimbs = arrayOf(
    LimbSpec("left_hip", "left_knee", LimbProfile(0.27f, 0.215f, 0.46f, 1.24f, 0.42f)),
    LimbSpec("left_knee", "left_ankle", LimbProfile(0.225f, 0.165f, 0.44f, 1.18f, 0.46f)),
    LimbSpec("right_hip", "right_knee", LimbProfile(0.27f, 0.215f, 0.46f, 1.24f, 0.42f)),
    LimbSpec("right_knee", "right_ankle", LimbProfile(0.225f, 0.165f, 0.44f, 1.18f, 0.46f)),
    LimbSpec("left_shoulder", "left_elbow", LimbProfile(0.30f, 0.225f, 0.44f, 1.26f, 0.48f)),
    LimbSpec("left_elbow", "left_wrist", LimbProfile(0.235f, 0.175f, 0.42f, 1.16f, 0.40f)),
    LimbSpec("right_shoulder", "right_elbow", LimbProfile(0.30f, 0.225f, 0.44f, 1.26f, 0.48f)),
    LimbSpec("right_elbow", "right_wrist", LimbProfile(0.235f, 0.175f, 0.42f, 1.16f, 0.40f)),
)

@Composable
fun SkeletonMotionPreview(
    skeletonJson: String,
    modifier: Modifier = Modifier,
    backgroundColor: Color,
    primaryFill: Color,
    animated: Boolean = true,
    viewYawDegrees: Float = -28f,
    viewPitchDegrees: Float = 15f,
    orbitView: Boolean = false,
    loopRestartFadeMillis: Int = 0,
    dragRotationEnabled: Boolean = false,
    dragRotationDegreesPerPixel: Float = DragRotationDegreesPerPixel,
    dragRotationHorizontalInset: Dp = 0.dp,
    isRenderingActive: Boolean = true,
    listThumbnail: Boolean = false,
) {
    if (listThumbnail) {
        SkeletonListThumbnailPreview(
            skeletonJson = skeletonJson,
            modifier = modifier,
            backgroundColor = backgroundColor,
            primaryFill = primaryFill,
            isRenderingActive = isRenderingActive,
        )
        return
    }
    val skeleton = remember(skeletonJson) {
        parseWearSkeleton(skeletonJson)
    }
    val baseViewYawDegrees = skeleton.display.viewYawDegrees ?: viewYawDegrees
    val baseViewPitchDegrees = skeleton.display.viewPitchDegrees ?: viewPitchDegrees
    val keyLightDirection = remember(baseViewYawDegrees) {
        skeletonKeyLightDirection(baseViewYawDegrees)
    }
    val palette = remember(primaryFill) { createSkeletonPalette(primaryFill) }
    var playbackVisibility by rememberSaveable(skeletonJson) { mutableStateOf(1f) }
    var frameIndex by rememberSaveable(skeletonJson, animated) {
        mutableStateOf(if (animated) 0 else min(12, skeleton.frames.lastIndex))
    }
    var orbitYawDegrees by rememberSaveable(skeletonJson, baseViewYawDegrees) {
        mutableStateOf(baseViewYawDegrees)
    }
    var playbackElapsedSeconds by rememberSaveable(skeletonJson) { mutableStateOf(0f) }
    var orbitElapsedSeconds by rememberSaveable(skeletonJson, baseViewYawDegrees) { mutableStateOf(0f) }
    var dragYawOffsetDegrees by remember(skeletonJson, baseViewYawDegrees) { mutableFloatStateOf(0f) }
    var orbitPausedByTouch by remember { mutableStateOf(false) }
    val movementInteractionModifier = if (dragRotationEnabled) {
        Modifier.pointerInput(skeletonJson, dragRotationDegreesPerPixel, dragRotationHorizontalInset) {
            awaitEachGesture {
                val down = awaitFirstDown(requireUnconsumed = false)
                val horizontalInsetPx = dragRotationHorizontalInset.toPx()
                if (down.position.x < horizontalInsetPx || down.position.x > size.width - horizontalInsetPx) {
                    return@awaitEachGesture
                }
                down.consume()
                orbitPausedByTouch = true
                var previousX = down.position.x
                try {
                    while (true) {
                        val event = awaitPointerEvent()
                        val change = event.changes.firstOrNull { it.id == down.id } ?: break
                        val deltaX = change.position.x - previousX
                        if (deltaX != 0f) {
                            dragYawOffsetDegrees -= deltaX * dragRotationDegreesPerPixel
                        }
                        previousX = change.position.x
                        change.consume()
                        if (!change.pressed) break
                    }
                } finally {
                    orbitPausedByTouch = false
                }
            }
        }
    } else if (orbitView) {
        Modifier.pointerInput(Unit) {
            try {
                awaitPointerEventScope {
                    while (true) {
                        val event = awaitPointerEvent()
                        orbitPausedByTouch = event.changes.any { change -> change.pressed }
                    }
                }
            } finally {
                orbitPausedByTouch = false
            }
        }
    } else {
        Modifier
    }

    LaunchedEffect(
        animated,
        orbitView,
        isRenderingActive,
        skeleton.fps,
        skeleton.frames.size,
        baseViewYawDegrees,
        loopRestartFadeMillis,
    ) {
        if (!isRenderingActive) {
            return@LaunchedEffect
        }
        if (!animated && !orbitView) {
            playbackVisibility = 1f
            return@LaunchedEffect
        }
        var previousFrameTimeNanos: Long? = null
        while (true) {
            val frameTimeNanos = withFrameNanos { it }
            val previousFrameTime = previousFrameTimeNanos
            if (previousFrameTime != null) {
                val deltaSeconds = (frameTimeNanos - previousFrameTime) / 1_000_000_000f
                if (animated) {
                    playbackElapsedSeconds += deltaSeconds
                }
                if (orbitView && !orbitPausedByTouch) {
                    orbitElapsedSeconds += deltaSeconds
                }
            }
            previousFrameTimeNanos = frameTimeNanos
            if (animated && skeleton.frames.isNotEmpty()) {
                val playback = resolveLoopPlayback(
                    elapsedSeconds = playbackElapsedSeconds.toDouble(),
                    frameCount = skeleton.frames.size,
                    fps = skeleton.fps,
                    loopRestartFadeMillis = loopRestartFadeMillis,
                )
                if (frameIndex != playback.frameIndex) {
                    frameIndex = playback.frameIndex
                }
                if (playbackVisibility != playback.visibility) {
                    playbackVisibility = playback.visibility
                }
            }
            if (orbitView) {
                orbitYawDegrees =
                    baseViewYawDegrees + (orbitElapsedSeconds * OrbitDegreesPerSecond) % 360f
            }
        }
    }

    val resolvedYawDegrees = if (orbitView) {
        orbitYawDegrees
    } else {
        baseViewYawDegrees
    } + dragYawOffsetDegrees
    Box(modifier = modifier.fillMaxSize()) {
        WearSkeletonRenderer(
            skeleton = skeleton,
            frameIndex = frameIndex,
            viewYawDegrees = resolvedYawDegrees,
            viewPitchDegrees = baseViewPitchDegrees,
            palette = palette,
            visibility = playbackVisibility,
            backgroundColor = backgroundColor,
            keyLightDirection = keyLightDirection,
            isRenderingActive = isRenderingActive,
            modifier = Modifier.fillMaxSize(),
        )
        if (orbitView || dragRotationEnabled) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .then(movementInteractionModifier),
            )
        }
    }
}

@Composable
private fun SkeletonListThumbnailPreview(
    skeletonJson: String,
    modifier: Modifier,
    backgroundColor: Color,
    primaryFill: Color,
    isRenderingActive: Boolean,
) {
    val context = LocalContext.current.applicationContext
    var frameBitmap by remember { mutableStateOf<ImageBitmap?>(null) }
    val slotId = remember { Any() }
    DisposableEffect(skeletonJson, backgroundColor, primaryFill, isRenderingActive) {
        if (isRenderingActive) {
            SharedSkeletonThumbnailRuntime.register(
                context = context,
                slotId = slotId,
                skeletonJson = skeletonJson,
                backgroundColor = backgroundColor,
                primaryFill = primaryFill,
                onFrame = { frameBitmap = it },
            )
        }
        onDispose {
            SharedSkeletonThumbnailRuntime.unregister(slotId)
        }
    }
    Box(
        modifier = modifier
            .fillMaxSize()
            .background(backgroundColor)
            .semantics { contentDescription = SkeletonPreviewContentDescription },
    ) {
        frameBitmap?.let { bitmap ->
            Image(
                bitmap = bitmap,
                contentDescription = null,
                modifier = Modifier.fillMaxSize(),
                contentScale = ContentScale.Fit,
            )
        }
    }
}

private fun resolveLoopPlayback(
    elapsedSeconds: Double,
    frameCount: Int,
    fps: Float,
    loopRestartFadeMillis: Int,
): SkeletonLoopPlayback {
    if (frameCount <= 0) {
        return SkeletonLoopPlayback(frameIndex = 0, visibility = 1f, motionElapsedSeconds = elapsedSeconds)
    }
    val safeFps = fps.coerceAtLeast(1f).toDouble()
    val fadeSeconds = if (loopRestartFadeMillis > 0 && frameCount > 1) {
        loopRestartFadeMillis / 1_000.0
    } else {
        0.0
    }
    if (fadeSeconds <= 0.0) {
        return SkeletonLoopPlayback(
            frameIndex = ((elapsedSeconds * safeFps).toInt()).floorMod(frameCount),
            visibility = 1f,
            motionElapsedSeconds = elapsedSeconds,
        )
    }

    val motionSeconds = frameCount / safeFps
    val cycleSeconds = motionSeconds + fadeSeconds * 2.0
    val phaseSeconds = elapsedSeconds % cycleSeconds
    val completedCycles = kotlin.math.floor(elapsedSeconds / cycleSeconds)
    val motionElapsedSeconds = completedCycles * motionSeconds + min(phaseSeconds, motionSeconds)
    return when {
        phaseSeconds < motionSeconds -> SkeletonLoopPlayback(
            frameIndex = min((phaseSeconds * safeFps).toInt(), frameCount - 1),
            visibility = 1f,
            motionElapsedSeconds = motionElapsedSeconds,
        )

        phaseSeconds < motionSeconds + fadeSeconds -> SkeletonLoopPlayback(
            frameIndex = frameCount - 1,
            visibility = (1.0 - ((phaseSeconds - motionSeconds) / fadeSeconds)).toFloat()
                .coerceIn(0f, 1f),
            motionElapsedSeconds = motionElapsedSeconds,
        )

        else -> SkeletonLoopPlayback(
            frameIndex = 0,
            visibility = ((phaseSeconds - motionSeconds - fadeSeconds) / fadeSeconds).toFloat()
                .coerceIn(0f, 1f),
            motionElapsedSeconds = motionElapsedSeconds,
        )
    }
}

@Composable
private fun WearSkeletonRenderer(
    skeleton: WearSkeleton,
    frameIndex: Int,
    viewYawDegrees: Float,
    viewPitchDegrees: Float,
    palette: SkeletonPalette,
    visibility: Float,
    backgroundColor: Color,
    keyLightDirection: WearSkeletonVec3,
    isRenderingActive: Boolean,
    modifier: Modifier = Modifier,
) {
    AndroidView(
        modifier = modifier
            .fillMaxSize()
            .background(backgroundColor)
            .semantics { contentDescription = SkeletonPreviewContentDescription },
        factory = { context ->
            WearSkeletonFilamentView(context).apply {
                setRenderingActive(isRenderingActive)
                updateSkeletonState(
                    skeleton = skeleton,
                    frameIndex = frameIndex,
                    viewYawDegrees = viewYawDegrees,
                    viewPitchDegrees = viewPitchDegrees,
                    palette = palette,
                    visibility = visibility,
                    backgroundColor = backgroundColor,
                    keyLightDirection = keyLightDirection,
                )
            }
        },
        update = { view ->
            view.setRenderingActive(isRenderingActive)
            view.updateSkeletonState(
                skeleton = skeleton,
                frameIndex = frameIndex,
                viewYawDegrees = viewYawDegrees,
                viewPitchDegrees = viewPitchDegrees,
                palette = palette,
                visibility = visibility,
                backgroundColor = backgroundColor,
                keyLightDirection = keyLightDirection,
            )
        },
        onRelease = { view ->
            view.release()
        },
    )
}

private class WearSkeletonFilamentView(
    context: Context,
) : FrameLayout(context), Choreographer.FrameCallback {
    private val renderView = TextureView(context)
    private val choreographer = Choreographer.getInstance()
    private val skeletonRenderer = WearSkeletonFilamentRenderer(context)
    private var rendering = false
    private var attached = false
    private var renderingRequested = true
    private var released = false

    init {
        setBackgroundColor(SkeletonFallbackBackground.toArgb())
        contentDescription = SkeletonPreviewContentDescription
        importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_YES
        addView(
            renderView,
            LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT),
        )
        skeletonRenderer.attachTo(renderView)
    }

    fun updateSkeletonState(
        skeleton: WearSkeleton,
        frameIndex: Int,
        viewYawDegrees: Float,
        viewPitchDegrees: Float,
        palette: SkeletonPalette,
        visibility: Float,
        backgroundColor: Color,
        keyLightDirection: WearSkeletonVec3,
    ) {
        if (released || !renderingRequested) {
            return
        }
        setBackgroundColor(backgroundColor.toArgb())
        skeletonRenderer.updateScene(
            skeleton = skeleton,
            frameIndex = frameIndex,
            viewYawDegrees = viewYawDegrees,
            viewPitchDegrees = viewPitchDegrees,
            palette = palette,
            visibility = visibility,
            backgroundColor = backgroundColor,
            keyLightDirection = keyLightDirection,
        )
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        attached = true
        updateRenderingState()
    }

    override fun onDetachedFromWindow() {
        attached = false
        updateRenderingState()
        super.onDetachedFromWindow()
    }

    fun setRenderingActive(active: Boolean) {
        renderingRequested = active
        updateRenderingState()
    }

    private fun updateRenderingState() {
        val shouldRender = attached && renderingRequested && !released
        if (shouldRender && !rendering) {
            rendering = true
            choreographer.postFrameCallback(this)
        } else if (!shouldRender && rendering) {
            rendering = false
            choreographer.removeFrameCallback(this)
        }
    }

    override fun doFrame(frameTimeNanos: Long) {
        if (released || !rendering) {
            return
        }
        skeletonRenderer.render(frameTimeNanos)
        choreographer.postFrameCallback(this)
    }

    fun release() {
        if (released) {
            return
        }
        released = true
        rendering = false
        choreographer.removeFrameCallback(this)
        skeletonRenderer.destroy()
    }
}

private class WearSkeletonFilamentRenderer(
    private val context: Context,
    private val thumbnailMode: Boolean = false,
) {
    private val uiHelper = UiHelper(UiHelper.ContextErrorPolicy.DONT_CHECK)
    private val engine: Engine
    private val renderer: Renderer
    private val scene: Scene
    private val view: FilamentView
    private val cameraEntity: Int
    private val camera: Camera
    private val material: Material
    private val materialInstance: MaterialInstance
    private var swapChain: SwapChain? = null
    private var bodyEntity: Int = 0
    private var bodyVertexBuffer: VertexBuffer? = null
    private var bodyIndexBuffer: IndexBuffer? = null
    private var bodyVertexCount: Int = 0
    private var bodyIndexCount: Int = 0
    private var floorEntity: Int = 0
    private var floorVertexBuffer: VertexBuffer? = null
    private var floorIndexBuffer: IndexBuffer? = null
    private var poseUploadBuffer: FloatBuffer? = null
    private var colorUploadBuffer: FloatBuffer? = null
    private var indexUploadBuffer: ShortBuffer? = null
    private var viewportWidth: Int = 0
    private var viewportHeight: Int = 0
    private var lastSkeletonId: Int? = null
    private var lastFrameIndex: Int? = null
    private var lastPalette: SkeletonPalette? = null
    private var lastBounds: FilamentMeshBounds? = null
    private var lastCameraTarget: WearSkeletonVec3? = null
    private var lastOrbitHorizontalRadius: Float? = null
    private var lastOrbitVerticalHalfExtent: Float? = null
    private var lastYawDegrees: Float = -28f
    private var lastPitchDegrees: Float = 18f
    private var lastVisibility: Float? = null
    private var lastBackgroundColor: Color? = null
    private var lastKeyLightDirection: WearSkeletonVec3? = null
    private var destroyed = false

    init {
        WearSkeletonFilamentRuntime.ensureInitialized()
        engine = Engine.create(Engine.Backend.OPENGL)
        renderer = engine.createRenderer()
        scene = engine.createScene()
        view = engine.createView()
        cameraEntity = EntityManager.get().create()
        camera = engine.createCamera(cameraEntity)
        view.setScene(scene)
        view.setCamera(camera)
        if (thumbnailMode) {
            view.setPostProcessingEnabled(false)
            view.setAntiAliasing(FilamentView.AntiAliasing.NONE)
            view.setMultiSampleAntiAliasingOptions(
                FilamentView.MultiSampleAntiAliasingOptions().apply {
                    enabled = false
                }
            )
        } else {
            view.setPostProcessingEnabled(true)
            view.setAntiAliasing(FilamentView.AntiAliasing.FXAA)
            view.setMultiSampleAntiAliasingOptions(
                FilamentView.MultiSampleAntiAliasingOptions().apply {
                    enabled = false
                }
            )
        }
        renderer.setClearOptions(
            Renderer.ClearOptions().apply {
                clear = true
                discard = true
                clearColor[0] = SkeletonFallbackBackground.red.toDouble()
                clearColor[1] = SkeletonFallbackBackground.green.toDouble()
                clearColor[2] = SkeletonFallbackBackground.blue.toDouble()
                clearColor[3] = 1.0
            }
        )
        material = createVertexColorMaterial(context, engine)
        materialInstance = material.createInstance("wear-skeleton").apply {
            setDoubleSided(false)
            setCullingMode(Material.CullingMode.BACK)
            setParameter("ambientLight", SkeletonAmbientLightLevel)
            setParameter("keyLightStrength", SkeletonKeyLightStrength)
            setParameter("fillLightStrength", SkeletonFillLightStrength)
            setParameter("hemisphereLightStrength", SkeletonHemisphereLightStrength)
            setParameter("visibility", 1f)
            setParameter("keyLightDirection", 0f, 1f, 0f)
            setParameter("backgroundColor", 0f, 0f, 0f)
        }
        if (thumbnailMode) {
            viewportWidth = ListThumbnailPixelSize
            viewportHeight = ListThumbnailPixelSize
            view.setViewport(Viewport(0, 0, viewportWidth, viewportHeight))
            swapChain = engine.createSwapChain(viewportWidth, viewportHeight, 0)
        }
    }

    fun attachTo(renderView: TextureView) {
        uiHelper.setRenderCallback(
            object : UiHelper.RendererCallback {
                override fun onNativeWindowChanged(surface: Surface) {
                    swapChain?.let { engine.destroySwapChain(it) }
                    swapChain = engine.createSwapChain(surface, uiHelper.getSwapChainFlags())
                }

                override fun onDetachedFromSurface() {
                    swapChain?.let { chain ->
                        engine.destroySwapChain(chain)
                        engine.flushAndWait()
                    }
                    swapChain = null
                }

                override fun onResized(width: Int, height: Int) {
                    viewportWidth = width
                    viewportHeight = height
                    view.setViewport(Viewport(0, 0, width, height))
                    updateCamera()
                }
            }
        )
        uiHelper.attachTo(renderView)
    }

    fun updateScene(
        skeleton: WearSkeleton,
        frameIndex: Int,
        viewYawDegrees: Float,
        viewPitchDegrees: Float,
        palette: SkeletonPalette,
        visibility: Float,
        backgroundColor: Color,
        keyLightDirection: WearSkeletonVec3,
    ) {
        if (destroyed || skeleton.frames.isEmpty()) {
            return
        }

        if (lastBackgroundColor != backgroundColor) {
            updateClearColor(backgroundColor)
            materialInstance.setParameter(
                "backgroundColor",
                backgroundColor.red.srgbToLinearChannel(),
                backgroundColor.green.srgbToLinearChannel(),
                backgroundColor.blue.srgbToLinearChannel(),
            )
            lastBackgroundColor = backgroundColor
        }
        lastYawDegrees = viewYawDegrees
        lastPitchDegrees = viewPitchDegrees
        val resolvedFrameIndex = frameIndex.coerceIn(0, skeleton.frames.lastIndex)
        val skeletonId = System.identityHashCode(skeleton)
        updateLookUniforms(visibility, keyLightDirection)

        val skeletonChanged = lastSkeletonId != skeletonId
        val poseChanged = skeletonChanged || lastFrameIndex != resolvedFrameIndex
        val paletteChanged = lastPalette != palette

        if (skeletonChanged) {
            if (thumbnailMode) {
                val thumbnailBounds = skeleton.bounds.toStableFilamentBounds()
                lastBounds = thumbnailBounds
                lastCameraTarget = thumbnailBounds.center
                lastOrbitHorizontalRadius = null
                lastOrbitVerticalHalfExtent = null
            } else {
                val cameraFrame = skeleton.toStableRenderedSceneCameraFrame(
                    palette = palette,
                    pitchDegrees = viewPitchDegrees,
                )
                lastBounds = cameraFrame.bounds
                lastCameraTarget = cameraFrame.target
                lastOrbitHorizontalRadius = cameraFrame.orbitHorizontalRadius
                lastOrbitVerticalHalfExtent = cameraFrame.orbitVerticalHalfExtent
            }
            replaceFloorRenderable(buildFloorMesh(skeleton.bounds, palette.grid))
        } else if (paletteChanged) {
            replaceFloorRenderable(buildFloorMesh(skeleton.bounds, palette.grid))
        }

        if (poseChanged || paletteChanged) {
            val generatedMesh = buildSingleLowPolyMesh(
                joints = skeleton.frames[resolvedFrameIndex].joints,
                palette = palette,
                stableLimbSides = skeleton.limbSidesByFrame.getOrNull(resolvedFrameIndex).orEmpty(),
                bodyProportions = skeleton.stableBodyProportions(),
            ) ?: GeneratedLowPolyMesh()
            val reuseTopology = bodyEntity != 0 &&
                generatedMesh.vertices.size == bodyVertexCount &&
                bodyVertexCount > 0
            val includeColors = !reuseTopology || paletteChanged || skeletonChanged
            val mesh = generatedMesh.toShadedMesh(
                modelBounds = skeleton.bounds.toStableFilamentBounds(),
                includeColors = includeColors,
                includeIndices = !reuseTopology,
            )
            replaceBodyRenderable(mesh, uploadColors = includeColors)
            lastSkeletonId = skeletonId
            lastFrameIndex = resolvedFrameIndex
            lastPalette = palette
        }
        if (lastCameraTarget == null) {
            lastCameraTarget = lastBounds?.center
        }
        updateCamera()
    }

    private fun updateLookUniforms(
        visibility: Float,
        keyLightDirection: WearSkeletonVec3,
    ) {
        val resolvedVisibility = visibility.coerceIn(0f, 1f)
        if (lastVisibility != resolvedVisibility) {
            materialInstance.setParameter("visibility", resolvedVisibility)
            lastVisibility = resolvedVisibility
        }
        if (lastKeyLightDirection != keyLightDirection) {
            materialInstance.setParameter(
                "keyLightDirection",
                keyLightDirection.x,
                keyLightDirection.y,
                keyLightDirection.z,
            )
            lastKeyLightDirection = keyLightDirection
        }
    }

    private fun updateClearColor(backgroundColor: Color) {
        renderer.setClearOptions(
            Renderer.ClearOptions().apply {
                clear = true
                discard = true
                clearColor[0] = backgroundColor.red.toDouble()
                clearColor[1] = backgroundColor.green.toDouble()
                clearColor[2] = backgroundColor.blue.toDouble()
                clearColor[3] = backgroundColor.alpha.toDouble()
            }
        )
    }

    fun render(frameTimeNanos: Long) {
        val chain = swapChain ?: return
        if (destroyed || !uiHelper.isReadyToRender()) {
            return
        }
        if (renderer.beginFrame(chain, frameTimeNanos)) {
            renderer.render(view)
            renderer.endFrame()
        }
    }

    fun renderAndReadPixels(
        frameTimeNanos: Long,
        output: ByteBuffer,
        onComplete: () -> Unit,
    ) {
        val chain = swapChain
        if (destroyed || chain == null || viewportWidth <= 0 || viewportHeight <= 0) {
            onComplete()
            return
        }
        if (!renderer.beginFrame(chain, frameTimeNanos)) {
            onComplete()
            return
        }
        renderer.render(view)
        output.clear()
        val descriptor = Texture.PixelBufferDescriptor(
            output,
            Texture.Format.RGBA,
            Texture.Type.UBYTE,
        )
        descriptor.setCallback(Handler(Looper.getMainLooper())) {
            output.rewind()
            onComplete()
        }
        renderer.readPixels(0, 0, viewportWidth, viewportHeight, descriptor)
        renderer.endFrame()
    }

    fun destroy() {
        if (destroyed) {
            return
        }
        destroyed = true
        if (!thumbnailMode) {
            uiHelper.detach()
        }
        swapChain?.let { chain ->
            engine.destroySwapChain(chain)
            engine.flushAndWait()
        }
        swapChain = null
        clearBodyRenderable()
        clearFloorRenderable()
        engine.destroyMaterialInstance(materialInstance)
        engine.destroyMaterial(material)
        engine.destroyCameraComponent(cameraEntity)
        EntityManager.get().destroy(cameraEntity)
        engine.destroyView(view)
        engine.destroyScene(scene)
        engine.destroyRenderer(renderer)
        engine.destroy()
    }

    private fun replaceBodyRenderable(mesh: ShadedMeshData, uploadColors: Boolean) {
        if (mesh.poseVertices.isEmpty()) {
            clearBodyRenderable()
            return
        }

        val poseBuffer = writeDirectFloats(poseUploadBuffer, mesh.poseVertices)
        poseUploadBuffer = poseBuffer
        val reusableVertexBuffer = bodyVertexBuffer
        val reusableIndexBuffer = bodyIndexBuffer
        val canReuseTopology = bodyEntity != 0 &&
            reusableVertexBuffer != null &&
            reusableIndexBuffer != null &&
            bodyVertexCount == mesh.vertexCount &&
            (mesh.indices.isEmpty() || bodyIndexCount == mesh.indices.size)
        if (canReuseTopology) {
            reusableVertexBuffer.setBufferAt(engine, 0, poseBuffer)
            if (uploadColors && mesh.colors.isNotEmpty()) {
                val colorBuffer = writeDirectFloats(colorUploadBuffer, mesh.colors)
                colorUploadBuffer = colorBuffer
                reusableVertexBuffer.setBufferAt(engine, 1, colorBuffer)
            }
            return
        }

        if (mesh.indices.isEmpty() || mesh.colors.isEmpty()) {
            return
        }

        clearBodyRenderable()
        val colorBuffer = writeDirectFloats(colorUploadBuffer, mesh.colors)
        colorUploadBuffer = colorBuffer
        val indexBufferData = writeDirectShorts(indexUploadBuffer, mesh.indices)
        indexUploadBuffer = indexBufferData

        val newVertexBuffer = VertexBuffer.Builder()
            .vertexCount(mesh.vertexCount)
            .bufferCount(2)
            .attribute(
                VertexBuffer.VertexAttribute.POSITION,
                0,
                VertexBuffer.AttributeType.FLOAT3,
                FilamentPositionOffsetBytes,
                FilamentPoseStrideBytes,
            )
            .attribute(
                VertexBuffer.VertexAttribute.CUSTOM0,
                0,
                VertexBuffer.AttributeType.FLOAT4,
                FilamentNormalOffsetBytes,
                FilamentPoseStrideBytes,
            )
            .attribute(
                VertexBuffer.VertexAttribute.COLOR,
                1,
                VertexBuffer.AttributeType.FLOAT4,
                0,
                FilamentColorStrideBytes,
            )
            .build(engine)
        val newIndexBuffer = IndexBuffer.Builder()
            .indexCount(mesh.indices.size)
            .bufferType(IndexBuffer.Builder.IndexType.USHORT)
            .build(engine)

        newVertexBuffer.setBufferAt(engine, 0, poseBuffer)
        newVertexBuffer.setBufferAt(engine, 1, colorBuffer)
        newIndexBuffer.setBuffer(engine, indexBufferData)

        val entity = EntityManager.get().create()
        RenderableManager.Builder(1)
            .boundingBox(mesh.modelBounds.toFilamentBox())
            .geometry(
                0,
                RenderableManager.PrimitiveType.TRIANGLES,
                newVertexBuffer,
                newIndexBuffer,
                0,
                mesh.indices.size,
            )
            .material(0, materialInstance)
            .culling(true)
            .receiveShadows(false)
            .castShadows(false)
            .build(engine, entity)
        scene.addEntity(entity)

        bodyEntity = entity
        bodyVertexBuffer = newVertexBuffer
        bodyIndexBuffer = newIndexBuffer
        bodyVertexCount = mesh.vertexCount
        bodyIndexCount = mesh.indices.size
    }

    private fun replaceFloorRenderable(mesh: ShadedMeshData) {
        clearFloorRenderable()
        if (mesh.indices.isEmpty() || mesh.poseVertices.isEmpty()) {
            return
        }
        val poseBuffer = writeDirectFloats(null, mesh.poseVertices)
        val colorBuffer = writeDirectFloats(null, mesh.colors)
        val indexBufferData = writeDirectShorts(null, mesh.indices)
        val newVertexBuffer = VertexBuffer.Builder()
            .vertexCount(mesh.vertexCount)
            .bufferCount(2)
            .attribute(
                VertexBuffer.VertexAttribute.POSITION,
                0,
                VertexBuffer.AttributeType.FLOAT3,
                FilamentPositionOffsetBytes,
                FilamentPoseStrideBytes,
            )
            .attribute(
                VertexBuffer.VertexAttribute.CUSTOM0,
                0,
                VertexBuffer.AttributeType.FLOAT4,
                FilamentNormalOffsetBytes,
                FilamentPoseStrideBytes,
            )
            .attribute(
                VertexBuffer.VertexAttribute.COLOR,
                1,
                VertexBuffer.AttributeType.FLOAT4,
                0,
                FilamentColorStrideBytes,
            )
            .build(engine)
        val newIndexBuffer = IndexBuffer.Builder()
            .indexCount(mesh.indices.size)
            .bufferType(IndexBuffer.Builder.IndexType.USHORT)
            .build(engine)
        newVertexBuffer.setBufferAt(engine, 0, poseBuffer)
        newVertexBuffer.setBufferAt(engine, 1, colorBuffer)
        newIndexBuffer.setBuffer(engine, indexBufferData)

        val entity = EntityManager.get().create()
        RenderableManager.Builder(1)
            .boundingBox(mesh.modelBounds.toFilamentBox())
            .geometry(
                0,
                RenderableManager.PrimitiveType.TRIANGLES,
                newVertexBuffer,
                newIndexBuffer,
                0,
                mesh.indices.size,
            )
            .material(0, materialInstance)
            .culling(true)
            .receiveShadows(false)
            .castShadows(false)
            .build(engine, entity)
        scene.addEntity(entity)
        floorEntity = entity
        floorVertexBuffer = newVertexBuffer
        floorIndexBuffer = newIndexBuffer
    }

    private fun clearBodyRenderable() {
        if (bodyEntity != 0) {
            scene.removeEntity(bodyEntity)
            engine.renderableManager.destroy(bodyEntity)
            EntityManager.get().destroy(bodyEntity)
            bodyEntity = 0
        }
        bodyIndexBuffer?.let(engine::destroyIndexBuffer)
        bodyVertexBuffer?.let(engine::destroyVertexBuffer)
        bodyIndexBuffer = null
        bodyVertexBuffer = null
        bodyVertexCount = 0
        bodyIndexCount = 0
    }

    private fun clearFloorRenderable() {
        if (floorEntity != 0) {
            scene.removeEntity(floorEntity)
            engine.renderableManager.destroy(floorEntity)
            EntityManager.get().destroy(floorEntity)
            floorEntity = 0
        }
        floorIndexBuffer?.let(engine::destroyIndexBuffer)
        floorVertexBuffer?.let(engine::destroyVertexBuffer)
        floorIndexBuffer = null
        floorVertexBuffer = null
    }

    private fun updateCamera() {
        val bounds = lastBounds ?: return
        if (viewportWidth <= 0 || viewportHeight <= 0) {
            return
        }
        val cameraFrame = SkeletonCameraFrame(
            bounds = bounds,
            target = lastCameraTarget ?: bounds.center,
            orbitHorizontalRadius = lastOrbitHorizontalRadius,
            orbitVerticalHalfExtent = lastOrbitVerticalHalfExtent,
            yawDegrees = lastYawDegrees,
            pitchDegrees = lastPitchDegrees,
        )
        val eye = cameraFrame.eye
        val target = cameraFrame.target
        camera.lookAt(
            eye.x.toDouble(),
            eye.y.toDouble(),
            eye.z.toDouble(),
            target.x.toDouble(),
            target.y.toDouble(),
            target.z.toDouble(),
            0.0,
            1.0,
            0.0,
        )

        val aspect = viewportWidth.toDouble() / viewportHeight.toDouble()
        val projection = cameraFrame.fixedProjection(aspect)
        camera.setProjection(
            Camera.Projection.ORTHO,
            projection.left,
            projection.right,
            projection.bottom,
            projection.top,
            0.01,
            cameraFrame.farPlane.toDouble(),
        )
    }
}

private object WearSkeletonFilamentRuntime {
    private var initialized = false

    fun ensureInitialized() {
        if (!initialized) {
            Filament.init()
            initialized = true
        }
    }
}

private fun createListThumbnailBitmap(): Bitmap {
    return Bitmap.createBitmap(
        ListThumbnailPixelSize,
        ListThumbnailPixelSize,
        Bitmap.Config.ARGB_8888,
    )
}

private class ThumbnailSlot(
    val skeleton: WearSkeleton,
    val palette: SkeletonPalette,
    val backgroundColor: Color,
    val keyLightDirection: WearSkeletonVec3,
    val onFrame: (ImageBitmap) -> Unit,
    var elapsedSeconds: Double = 0.0,
) {
    private val bitmaps = arrayOf(createListThumbnailBitmap(), createListThumbnailBitmap())
    private val frames = arrayOf(bitmaps[0].asImageBitmap(), bitmaps[1].asImageBitmap())
    private var displayIndex = 1

    fun publishPixels(pixels: IntArray) {
        val writeIndex = 1 - displayIndex
        val width = ListThumbnailPixelSize
        bitmaps[writeIndex].setPixels(pixels, 0, width, 0, 0, width, width)
        displayIndex = writeIndex
        onFrame(frames[writeIndex])
    }
}

private object SharedSkeletonThumbnailRuntime : Choreographer.FrameCallback {
    private val choreographer = Choreographer.getInstance()
    private val slots = LinkedHashMap<Any, ThumbnailSlot>()
    private val scratchPixels = IntArray(ListThumbnailPixelSize * ListThumbnailPixelSize)
    private var renderer: WearSkeletonFilamentRenderer? = null
    private var pixelBuffer: ByteBuffer? = null
    private var nextSlotIndex = 0
    private var readInFlight = false
    private var scheduled = false
    private var lastFrameTimeNanos: Long? = null

    fun register(
        context: Context,
        slotId: Any,
        skeletonJson: String,
        backgroundColor: Color,
        primaryFill: Color,
        onFrame: (ImageBitmap) -> Unit,
    ) {
        val skeleton = parseWearSkeleton(skeletonJson)
        val yaw = skeleton.display.viewYawDegrees ?: -28f
        slots[slotId] = ThumbnailSlot(
            skeleton = skeleton,
            palette = createSkeletonPalette(primaryFill),
            backgroundColor = backgroundColor,
            keyLightDirection = skeletonKeyLightDirection(yaw),
            onFrame = onFrame,
        )
        if (renderer == null) {
            renderer = WearSkeletonFilamentRenderer(context.applicationContext, thumbnailMode = true)
            pixelBuffer = ByteBuffer.allocateDirect(ListThumbnailPixelSize * ListThumbnailPixelSize * 4)
                .order(ByteOrder.nativeOrder())
        }
        start()
    }

    fun unregister(slotId: Any) {
        slots.remove(slotId)
        if (slots.isEmpty()) {
            stop()
        }
    }

    private fun start() {
        if (!scheduled) {
            scheduled = true
            choreographer.postFrameCallback(this)
        }
    }

    private fun stop() {
        scheduled = false
        lastFrameTimeNanos = null
        choreographer.removeFrameCallback(this)
    }

    override fun doFrame(frameTimeNanos: Long) {
        scheduled = false
        if (slots.isEmpty()) {
            lastFrameTimeNanos = null
            return
        }
        start()
        val previousFrameTimeNanos = lastFrameTimeNanos
        lastFrameTimeNanos = frameTimeNanos
        if (previousFrameTimeNanos != null) {
            val deltaSeconds = (frameTimeNanos - previousFrameTimeNanos) / 1_000_000_000.0
            slots.values.forEach { slot ->
                slot.elapsedSeconds += deltaSeconds
            }
        }
        if (readInFlight) {
            return
        }
        renderNext(frameTimeNanos)
    }

    private fun renderNext(frameTimeNanos: Long) {
        val renderer = renderer ?: return
        val pixelBuffer = pixelBuffer ?: return
        val slot = pickSlot() ?: return
        val playback = resolveLoopPlayback(
            elapsedSeconds = slot.elapsedSeconds,
            frameCount = slot.skeleton.frames.size,
            fps = slot.skeleton.fps,
            loopRestartFadeMillis = 0,
        )
        renderer.updateScene(
            skeleton = slot.skeleton,
            frameIndex = playback.frameIndex,
            viewYawDegrees = slot.skeleton.display.viewYawDegrees ?: -28f,
            viewPitchDegrees = slot.skeleton.display.viewPitchDegrees ?: 15f,
            palette = slot.palette,
            visibility = 1f,
            backgroundColor = slot.backgroundColor,
            keyLightDirection = slot.keyLightDirection,
        )
        readInFlight = true
        renderer.renderAndReadPixels(frameTimeNanos, pixelBuffer) {
            copyPixelsToSlot(slot, pixelBuffer)
            readInFlight = false
        }
    }

    private fun pickSlot(): ThumbnailSlot? {
        if (slots.isEmpty()) {
            return null
        }
        val values = slots.values.toList()
        val index = nextSlotIndex.floorMod(values.size)
        nextSlotIndex = index + 1
        return values[index]
    }

    private fun copyPixelsToSlot(slot: ThumbnailSlot, buffer: ByteBuffer) {
        val width = ListThumbnailPixelSize
        val height = ListThumbnailPixelSize
        buffer.rewind()
        var pixelIndex = 0
        for (y in 0 until height) {
            val sourceY = height - 1 - y
            var sourceIndex = sourceY * width * 4
            for (x in 0 until width) {
                val red = buffer.get(sourceIndex).toInt() and 0xff
                val green = buffer.get(sourceIndex + 1).toInt() and 0xff
                val blue = buffer.get(sourceIndex + 2).toInt() and 0xff
                val alpha = buffer.get(sourceIndex + 3).toInt() and 0xff
                scratchPixels[pixelIndex] = (alpha shl 24) or (red shl 16) or (green shl 8) or blue
                pixelIndex += 1
                sourceIndex += 4
            }
        }
        slot.publishPixels(scratchPixels)
    }
}

private data class ShadedMeshData(
    val poseVertices: FloatArray,
    val colors: FloatArray,
    val indices: IntArray,
    val vertexCount: Int,
    val modelBounds: FilamentMeshBounds,
)

private data class FilamentMeshBounds(
    val min: WearSkeletonVec3,
    val max: WearSkeletonVec3,
) {
    val center: WearSkeletonVec3 = WearSkeletonVec3(
        (min.x + max.x) * 0.5f,
        (min.y + max.y) * 0.5f,
        (min.z + max.z) * 0.5f,
    )

    val halfExtent: WearSkeletonVec3 = WearSkeletonVec3(
        max((max.x - min.x) * 0.5f, 0.001f),
        max((max.y - min.y) * 0.5f, 0.001f),
        max((max.z - min.z) * 0.5f, 0.001f),
    )

    val radius: Float = halfExtent.length().coerceAtLeast(0.001f)

    fun toFilamentBox(): FilamentBox = FilamentBox(
        center.x,
        center.y,
        center.z,
        halfExtent.x,
        halfExtent.y,
        halfExtent.z,
    )
}

private data class StableRenderedSceneCameraFrame(
    val bounds: FilamentMeshBounds,
    val target: WearSkeletonVec3,
    val orbitHorizontalRadius: Float,
    val orbitVerticalHalfExtent: Float,
)

private data class SkeletonCameraFrame(
    val bounds: FilamentMeshBounds,
    val target: WearSkeletonVec3,
    val orbitHorizontalRadius: Float?,
    val orbitVerticalHalfExtent: Float?,
    val yawDegrees: Float,
    val pitchDegrees: Float,
) {
    private val yaw = (yawDegrees * PI / 180.0).toFloat()
    private val pitch = (pitchDegrees * PI / 180.0).toFloat()
    private val eyeDirection = WearSkeletonVec3(
        x = sin(yaw) * cos(pitch),
        y = sin(pitch),
        z = cos(yaw) * cos(pitch),
    ).normalizedOr(WearSkeletonVec3(0f, 0f, 1f))
    val eye: WearSkeletonVec3 = target + eyeDirection * CameraDistance
    val farPlane: Float = CameraFarPlane

    fun fixedProjection(aspect: Double): CameraProjectionBounds {
        val safeAspect = aspect.toFloat().coerceAtLeast(0.001f)
        val fallbackHorizontalRadius = sqrt(
            bounds.halfExtent.x * bounds.halfExtent.x +
                bounds.halfExtent.z * bounds.halfExtent.z
        )
        val horizontalRadius = orbitHorizontalRadius ?: fallbackHorizontalRadius
        val projectedHalfHeight = orbitVerticalHalfExtent ?: (
            abs(cos(pitch)) * bounds.halfExtent.y +
                abs(sin(pitch)) * horizontalRadius
            )
        var halfWidth = horizontalRadius * CameraFrameSafetyScale
        var halfHeight = projectedHalfHeight * CameraFrameSafetyScale
        if (halfWidth / halfHeight < safeAspect) {
            halfWidth = halfHeight * safeAspect
        } else {
            halfHeight = halfWidth / safeAspect
        }

        return CameraProjectionBounds(
            left = (-halfWidth).toDouble(),
            right = halfWidth.toDouble(),
            bottom = (-halfHeight).toDouble(),
            top = halfHeight.toDouble(),
        )
    }
}

private const val CameraFrameSafetyScale = 1.02f
private const val CameraDistance = 8f
private const val CameraFarPlane = 20f

private data class CameraProjectionBounds(
    val left: Double,
    val right: Double,
    val bottom: Double,
    val top: Double,
)

private fun createVertexColorMaterial(context: Context, engine: Engine): Material {
    val materialBytes = context.resources
        .openRawResource(R.raw.wear_skeleton)
        .use { it.readBytes() }
    val buffer = ByteBuffer.allocateDirect(materialBytes.size)
        .order(ByteOrder.nativeOrder())
        .put(materialBytes)
        .apply { flip() }
    return Material.Builder()
        .payload(buffer, buffer.remaining())
        .build(engine)
}

private fun writeDirectFloats(existing: FloatBuffer?, values: FloatArray): FloatBuffer {
    val buffer = if (existing != null && existing.capacity() >= values.size) {
        existing
    } else {
        ByteBuffer.allocateDirect(values.size * 4).order(ByteOrder.nativeOrder()).asFloatBuffer()
    }
    buffer.clear()
    buffer.put(values)
    buffer.flip()
    return buffer
}

private fun writeDirectShorts(existing: ShortBuffer?, values: IntArray): ShortBuffer {
    val buffer = if (existing != null && existing.capacity() >= values.size) {
        existing
    } else {
        ByteBuffer.allocateDirect(values.size * 2).order(ByteOrder.nativeOrder()).asShortBuffer()
    }
    buffer.clear()
    values.forEach { index -> buffer.put(index.toShort()) }
    buffer.flip()
    return buffer
}

private fun GeneratedLowPolyMesh.toShadedMesh(
    modelBounds: FilamentMeshBounds,
    includeColors: Boolean = true,
    includeIndices: Boolean = true,
): ShadedMeshData {
    val vertexCount = vertices.size
    val normals = Array(vertexCount) { WearSkeletonVec3(0f, 0f, 0f) }
    val fills = if (includeColors) Array(vertexCount) { Color.White } else emptyArray()
    faces.forEach { face ->
        val points = face.vertexIndices.mapNotNull { index -> vertices.getOrNull(index) }
        if (points.size < 3) {
            return@forEach
        }
        val normal = (points[1] - points[0]).cross(points[2] - points[1])
        face.vertexIndices.forEach { index ->
            if (index in 0 until vertexCount) {
                normals[index] = normals[index] + normal
                if (includeColors) {
                    fills[index] = face.fill
                }
            }
        }
    }

    val poseVertices = FloatArray(vertexCount * FilamentPoseFloatCount)
    val colors = if (includeColors) {
        FloatArray(vertexCount * FilamentColorFloatCount)
    } else {
        FloatArray(0)
    }
    for (index in 0 until vertexCount) {
        val point = vertices[index]
        val normal = normals[index].normalizedOr(WearSkeletonVec3(0f, 1f, 0f))
        val poseOffset = index * FilamentPoseFloatCount
        poseVertices[poseOffset] = point.x
        poseVertices[poseOffset + 1] = point.y
        poseVertices[poseOffset + 2] = point.z
        poseVertices[poseOffset + 3] = normal.x
        poseVertices[poseOffset + 4] = normal.y
        poseVertices[poseOffset + 5] = normal.z
        poseVertices[poseOffset + 6] = 0f
        if (includeColors) {
            val colorOffset = index * FilamentColorFloatCount
            val fill = fills[index]
            colors[colorOffset] = fill.red.srgbToLinearChannel()
            colors[colorOffset + 1] = fill.green.srgbToLinearChannel()
            colors[colorOffset + 2] = fill.blue.srgbToLinearChannel()
            colors[colorOffset + 3] = fill.alpha
        }
    }

    val indices = if (!includeIndices) {
        intArrayOf()
    } else {
        val indexList = ArrayList<Int>()
        faces.forEach { face ->
            val corners = face.vertexIndices.filter { it in 0 until vertexCount }
            if (corners.size < 3) {
                return@forEach
            }
            for (fanIndex in 1 until corners.lastIndex) {
                require(indexList.size + 3 <= UShort.MAX_VALUE.toInt()) {
                    "Wear skeleton mesh exceeded 16-bit index capacity."
                }
                indexList += corners[0]
                indexList += corners[fanIndex]
                indexList += corners[fanIndex + 1]
            }
        }
        indexList.toIntArray()
    }

    return ShadedMeshData(
        poseVertices = poseVertices,
        colors = colors,
        indices = indices,
        vertexCount = vertexCount,
        modelBounds = modelBounds,
    )
}

private fun buildFloorMesh(
    bounds: WearSkeletonBounds,
    color: Color,
): ShadedMeshData {
    val poseVertices = ArrayList<Float>()
    val colors = ArrayList<Float>()
    val indices = ArrayList<Int>()
    val up = WearSkeletonVec3(0f, 1f, 0f)
    fun addFloorVertex(point: WearSkeletonVec3) {
        require(poseVertices.size / FilamentPoseFloatCount <= UShort.MAX_VALUE.toInt()) {
            "Wear skeleton mesh exceeded 16-bit index capacity."
        }
        poseVertices += point.x
        poseVertices += point.y
        poseVertices += point.z
        poseVertices += up.x
        poseVertices += up.y
        poseVertices += up.z
        poseVertices += 0f
        colors += color.red.srgbToLinearChannel()
        colors += color.green.srgbToLinearChannel()
        colors += color.blue.srgbToLinearChannel()
        colors += color.alpha
    }

    val height = (bounds.maxY - bounds.minY).coerceAtLeast(0.001f)
    val floorY = bounds.minY - (height * 0.014f)
    val width = (bounds.maxX - bounds.minX).coerceAtLeast(0.001f)
    val depth = (bounds.maxZ - bounds.minZ).coerceAtLeast(0.001f)
    val floorSize = max(width, depth) * 1.24f
    val halfFloorSize = floorSize * 0.5f
    val centerX = (bounds.minX + bounds.maxX) * 0.5f
    val centerZ = (bounds.minZ + bounds.maxZ) * 0.5f
    val minX = centerX - halfFloorSize
    val maxX = centerX + halfFloorSize
    val minZ = centerZ - halfFloorSize
    val maxZ = centerZ + halfFloorSize
    val lineHalfWidth = floorSize * 0.0046f
    val divisions = 4

    fun addFloorQuad(
        a: WearSkeletonVec3,
        b: WearSkeletonVec3,
        c: WearSkeletonVec3,
        d: WearSkeletonVec3,
    ) {
        val start = poseVertices.size / FilamentPoseFloatCount
        addFloorVertex(a)
        addFloorVertex(b)
        addFloorVertex(c)
        addFloorVertex(d)
        indices += start
        indices += start + 2
        indices += start + 1
        indices += start
        indices += start + 3
        indices += start + 2
    }

    for (index in 0..divisions) {
        val amount = index / divisions.toFloat()
        val x = minX + (maxX - minX) * amount
        val z = minZ + (maxZ - minZ) * amount
        addFloorQuad(
            WearSkeletonVec3(x - lineHalfWidth, floorY, minZ),
            WearSkeletonVec3(x + lineHalfWidth, floorY, minZ),
            WearSkeletonVec3(x + lineHalfWidth, floorY, maxZ),
            WearSkeletonVec3(x - lineHalfWidth, floorY, maxZ),
        )
        addFloorQuad(
            WearSkeletonVec3(minX, floorY, z - lineHalfWidth),
            WearSkeletonVec3(maxX, floorY, z - lineHalfWidth),
            WearSkeletonVec3(maxX, floorY, z + lineHalfWidth),
            WearSkeletonVec3(minX, floorY, z + lineHalfWidth),
        )
    }

    return ShadedMeshData(
        poseVertices = poseVertices.toFloatArray(),
        colors = colors.toFloatArray(),
        indices = indices.toIntArray(),
        vertexCount = poseVertices.size / FilamentPoseFloatCount,
        modelBounds = bounds.toStableFilamentBounds(),
    )
}

private fun WearSkeletonBounds.toStableFilamentBounds(): FilamentMeshBounds {
    val height = (maxY - minY).coerceAtLeast(0.001f)
    val width = (maxX - minX).coerceAtLeast(0.001f)
    val depth = (maxZ - minZ).coerceAtLeast(0.001f)
    val horizontalPadding = max(width, depth) * 0.28f
    val bottomPadding = height * 0.04f
    val topPadding = height * 0.14f
    return FilamentMeshBounds(
        min = WearSkeletonVec3(
            minX - horizontalPadding,
            minY - bottomPadding,
            minZ - horizontalPadding,
        ),
        max = WearSkeletonVec3(
            maxX + horizontalPadding,
            maxY + topPadding,
            maxZ + horizontalPadding,
        ),
    )
}

private fun WearSkeleton.stableBodyProportions(): StableBodyProportions {
    frames.forEach { frame ->
        val leftHip = frame.joints["left_hip"] ?: return@forEach
        val rightHip = frame.joints["right_hip"] ?: return@forEach
        val leftShoulder = frame.joints["left_shoulder"] ?: return@forEach
        val rightShoulder = frame.joints["right_shoulder"] ?: return@forEach
        val hipWidth = (rightHip - leftHip).length()
        val shoulderWidth = (rightShoulder - leftShoulder).length()
        if (hipWidth > 0.0001f && shoulderWidth > 0.0001f) {
            val segmentLengths = buildMap {
                SkeletonLimbs.forEach { limb ->
                    val start = frame.joints[limb.startName] ?: return@forEach
                    val end = frame.joints[limb.endName] ?: return@forEach
                    put(LimbKey(limb.startName, limb.endName), (end - start).length())
                }
                listOf(
                    LimbKey("neck", "head"),
                    LimbKey("left_wrist", "left_hand"),
                    LimbKey("right_wrist", "right_hand"),
                ).forEach { key ->
                    val start = frame.joints[key.startName] ?: return@forEach
                    val end = frame.joints[key.endName] ?: return@forEach
                    put(key, (end - start).length())
                }
            }
            return StableBodyProportions(hipWidth, shoulderWidth, segmentLengths)
        }
    }
    return StableBodyProportions(0f, 0f, emptyMap())
}

private fun WearSkeleton.toStableRenderedSceneCameraFrame(
    palette: SkeletonPalette,
    pitchDegrees: Float,
): StableRenderedSceneCameraFrame {
    var minX = Float.POSITIVE_INFINITY
    var minY = Float.POSITIVE_INFINITY
    var minZ = Float.POSITIVE_INFINITY
    var maxX = Float.NEGATIVE_INFINITY
    var maxY = Float.NEGATIVE_INFINITY
    var maxZ = Float.NEGATIVE_INFINITY

    fun includeInBounds(point: WearSkeletonVec3) {
        minX = min(minX, point.x)
        minY = min(minY, point.y)
        minZ = min(minZ, point.z)
        maxX = max(maxX, point.x)
        maxY = max(maxY, point.y)
        maxZ = max(maxZ, point.z)
    }

    val frameVertices = ArrayList<List<WearSkeletonVec3>>(frames.size)
    val bodyProportions = stableBodyProportions()
    frames.forEachIndexed { frameIndex, frame ->
        val meshVertices = buildSingleLowPolyMesh(
            joints = frame.joints,
            palette = palette,
            stableLimbSides = limbSidesByFrame.getOrNull(frameIndex).orEmpty(),
            bodyProportions = bodyProportions,
        )?.vertices.orEmpty()
        meshVertices.forEach(::includeInBounds)
        frameVertices += meshVertices
    }

    val modelBounds = if (minX.isFinite() && minY.isFinite() && minZ.isFinite()) {
        FilamentMeshBounds(
            min = WearSkeletonVec3(minX, minY, minZ),
            max = WearSkeletonVec3(maxX, maxY, maxZ),
        )
    } else {
        bounds.toStableFilamentBounds()
    }
    val orbitCenterX = modelBounds.center.x
    val orbitCenterZ = modelBounds.center.z
    val verticalOriginY = modelBounds.center.y
    val pitch = pitchDegrees * PI.toFloat() / 180f
    val verticalScale = abs(cos(pitch))
    val depthScale = abs(sin(pitch))
    var orbitHorizontalRadius = 0f
    var minOrbitProjectedY = Float.POSITIVE_INFINITY
    var maxOrbitProjectedY = Float.NEGATIVE_INFINITY

    fun includeInOrbitEnvelope(point: WearSkeletonVec3) {
        val deltaX = point.x - orbitCenterX
        val deltaZ = point.z - orbitCenterZ
        val radialDistance = sqrt(deltaX * deltaX + deltaZ * deltaZ)
        orbitHorizontalRadius = max(orbitHorizontalRadius, radialDistance)
        val verticalCenter = verticalScale * (point.y - verticalOriginY)
        val orbitVerticalRadius = depthScale * radialDistance
        minOrbitProjectedY = min(minOrbitProjectedY, verticalCenter - orbitVerticalRadius)
        maxOrbitProjectedY = max(maxOrbitProjectedY, verticalCenter + orbitVerticalRadius)
    }

    frameVertices.forEach { vertices ->
        vertices.forEach(::includeInOrbitEnvelope)
    }

    val skeletonHeight = (bounds.maxY - bounds.minY).coerceAtLeast(0.001f)
    val skeletonWidth = (bounds.maxX - bounds.minX).coerceAtLeast(0.001f)
    val skeletonDepth = (bounds.maxZ - bounds.minZ).coerceAtLeast(0.001f)
    val floorY = bounds.minY - skeletonHeight * 0.014f
    val floorSize = max(skeletonWidth, skeletonDepth) * 1.24f
    val halfFloorSize = floorSize * 0.5f
    val floorLineHalfWidth = floorSize * 0.0046f
    val floorCenterX = (bounds.minX + bounds.maxX) * 0.5f
    val floorCenterZ = (bounds.minZ + bounds.maxZ) * 0.5f
    val floorMinimumCorner = WearSkeletonVec3(
        floorCenterX - halfFloorSize - floorLineHalfWidth,
        floorY,
        floorCenterZ - halfFloorSize - floorLineHalfWidth,
    )
    val floorMaximumCorner = WearSkeletonVec3(
        floorCenterX + halfFloorSize + floorLineHalfWidth,
        floorY,
        floorCenterZ + halfFloorSize + floorLineHalfWidth,
    )
    includeInBounds(floorMinimumCorner)
    includeInBounds(floorMaximumCorner)
    includeInOrbitEnvelope(floorMinimumCorner)
    includeInOrbitEnvelope(floorMaximumCorner)

    val renderedBounds = FilamentMeshBounds(
        min = WearSkeletonVec3(minX, minY, minZ),
        max = WearSkeletonVec3(maxX, maxY, maxZ),
    )
    val projectedCenterOffset = if (
        minOrbitProjectedY.isFinite() &&
        maxOrbitProjectedY.isFinite()
    ) {
        (minOrbitProjectedY + maxOrbitProjectedY) * 0.5f
    } else {
        0f
    }
    val verticalTargetOffset = if (verticalScale > 0.001f) {
        projectedCenterOffset / verticalScale
    } else {
        0f
    }
    val orbitVerticalHalfExtent = if (
        minOrbitProjectedY.isFinite() &&
        maxOrbitProjectedY.isFinite()
    ) {
        (maxOrbitProjectedY - minOrbitProjectedY) * 0.5f
    } else {
        modelBounds.halfExtent.y
    }
    return StableRenderedSceneCameraFrame(
        bounds = renderedBounds,
        target = WearSkeletonVec3(
            x = orbitCenterX,
            y = verticalOriginY + verticalTargetOffset,
            z = orbitCenterZ,
        ),
        orbitHorizontalRadius = orbitHorizontalRadius.coerceAtLeast(0.001f),
        orbitVerticalHalfExtent = orbitVerticalHalfExtent.coerceAtLeast(0.001f),
    )
}

private fun skeletonKeyLightDirection(initialViewYawDegrees: Float): WearSkeletonVec3 {
    val yawRadians = (initialViewYawDegrees + SkeletonKeyLightYawOffsetDegrees) * PI.toFloat() / 180f
    val elevationRadians = SkeletonKeyLightElevationDegrees * PI.toFloat() / 180f
    val horizontalScale = cos(elevationRadians)
    return WearSkeletonVec3(
        x = sin(yawRadians) * horizontalScale,
        y = sin(elevationRadians),
        z = cos(yawRadians) * horizontalScale,
    ).normalizedOr(WearSkeletonVec3(0f, 1f, 0f))
}

private fun buildSingleLowPolyMesh(
    joints: Map<String, WearSkeletonVec3>,
    palette: SkeletonPalette,
    stableLimbSides: Map<LimbKey, WearSkeletonVec3>,
    bodyProportions: StableBodyProportions,
): GeneratedLowPolyMesh? {
    val pelvis = joints["pelvis"] ?: return null
    val neck = joints["neck"] ?: return null
    val head = joints["head"] ?: return null
    val leftHip = joints["left_hip"] ?: return null
    val rightHip = joints["right_hip"] ?: return null
    val leftShoulder = joints["left_shoulder"] ?: return null
    val rightShoulder = joints["right_shoulder"] ?: return null
    val bodyAxes = joints.toBodyAxes()
    val mesh = GeneratedLowPolyMesh()
    val hipCenter = leftHip.lerp(rightHip, 0.5f)
    val measuredHipWidth = (rightHip - leftHip).length()
    val measuredShoulderWidth = (rightShoulder - leftShoulder).length()
    val hipWidth = bodyProportions.hipWidth.takeIf { it > 0.0001f } ?: measuredHipWidth
    val shoulderWidth = bodyProportions.shoulderWidth.takeIf { it > 0.0001f } ?: measuredShoulderWidth
    val pelvisWidth = max(hipWidth * 1.08f, shoulderWidth * 0.64f)
    val footScale = max(hipWidth * 0.98f, shoulderWidth * 0.58f)
    val down = bodyAxes.up * -1f
    val resolvedJoints = joints.toMutableMap()
    fun ensureJoint(name: String, fallback: WearSkeletonVec3) {
        if (resolvedJoints[name] == null) {
            resolvedJoints[name] = fallback
        }
    }
    ensureJoint("left_knee", leftHip + down * (hipWidth * 0.45f))
    ensureJoint("right_knee", rightHip + down * (hipWidth * 0.45f))
    ensureJoint("left_ankle", resolvedJoints.getValue("left_knee") + down * (hipWidth * 0.45f))
    ensureJoint("right_ankle", resolvedJoints.getValue("right_knee") + down * (hipWidth * 0.45f))
    ensureJoint("left_foot", resolvedJoints.getValue("left_ankle") + bodyAxes.forward * (footScale * 0.35f))
    ensureJoint("right_foot", resolvedJoints.getValue("right_ankle") + bodyAxes.forward * (footScale * 0.35f))
    ensureJoint("left_elbow", leftShoulder + down * (shoulderWidth * 0.35f) + bodyAxes.side * -(shoulderWidth * 0.08f))
    ensureJoint("right_elbow", rightShoulder + down * (shoulderWidth * 0.35f) + bodyAxes.side * (shoulderWidth * 0.08f))
    ensureJoint("left_wrist", resolvedJoints.getValue("left_elbow") + down * (shoulderWidth * 0.28f))
    ensureJoint("right_wrist", resolvedJoints.getValue("right_elbow") + down * (shoulderWidth * 0.28f))
    ensureJoint("left_hand", resolvedJoints.getValue("left_wrist") + down * (shoulderWidth * 0.12f))
    ensureJoint("right_hand", resolvedJoints.getValue("right_wrist") + down * (shoulderWidth * 0.12f))
    val torsoUp = (neck - hipCenter).normalizedOr(bodyAxes.up)
    val torsoLength = (neck - hipCenter).length()
    val waistCenter = joints["spine1"] ?: (hipCenter + torsoUp * (torsoLength * 0.40f))
    val chestCenter = waistCenter.lerp(neck, 0.38f)
    val upperChestCenter = waistCenter.lerp(neck, 0.66f)
    val chestTopCenter = waistCenter.lerp(neck, 0.80f)
    val upperBackCenter = waistCenter.lerp(neck, 0.88f)
    val upperTransitionCenter = waistCenter.lerp(neck, 0.94f)
    val pelvisUp = (waistCenter - hipCenter).normalizedOr(torsoUp)
    val pelvisSide = (rightHip - leftHip)
        .projectOntoPlane(pelvisUp)
        .normalizedOr(bodyAxes.side)
    val pelvisAxes = BodyAxes(
        side = pelvisSide,
        up = pelvisUp,
        forward = pelvisSide.cross(pelvisUp).normalizedOr(bodyAxes.forward),
    )
    var previousRingAxes = pelvisAxes
    val waistAxes = alignRingAxes(
        previousRingAxes,
        spineRingAxes(hipCenter, waistCenter, chestCenter, bodyAxes),
    )
    previousRingAxes = waistAxes
    val chestAxes = alignRingAxes(
        previousRingAxes,
        spineRingAxes(waistCenter, chestCenter, upperChestCenter, bodyAxes),
    )
    previousRingAxes = chestAxes
    val upperChestAxes = alignRingAxes(
        previousRingAxes,
        spineRingAxes(chestCenter, upperChestCenter, chestTopCenter, bodyAxes),
    )
    previousRingAxes = upperChestAxes
    val chestTopAxes = alignRingAxes(
        previousRingAxes,
        spineRingAxes(upperChestCenter, chestTopCenter, upperBackCenter, bodyAxes),
    )
    previousRingAxes = chestTopAxes
    val upperBackAxes = alignRingAxes(
        previousRingAxes,
        spineRingAxes(chestTopCenter, upperBackCenter, upperTransitionCenter, bodyAxes),
    )
    previousRingAxes = upperBackAxes
    val upperTransitionAxes = alignRingAxes(
        previousRingAxes,
        spineRingAxes(upperBackCenter, upperTransitionCenter, neck, bodyAxes),
    )
    previousRingAxes = upperTransitionAxes
    val waistResolvedBackDepth = shoulderWidth * 0.18f
    val waistRing = addMeshDirectionalRing(
        mesh = mesh,
        center = waistCenter,
        side = waistAxes.side,
        depth = waistAxes.forward,
        halfWidth = shoulderWidth * 0.30f,
        frontDepth = shoulderWidth * 0.16f,
        backDepth = waistResolvedBackDepth,
    )
    val chestRings = mutableListOf(
        waistRing,
        addMeshDirectionalRing(
            mesh = mesh,
            center = chestCenter,
            side = chestAxes.side,
            depth = chestAxes.forward,
            halfWidth = shoulderWidth * 0.40f,
            frontDepth = shoulderWidth * 0.18f,
            backDepth = shoulderWidth * 0.24f,
        ),
        addMeshDirectionalRing(
            mesh = mesh,
            center = upperChestCenter,
            side = upperChestAxes.side,
            depth = upperChestAxes.forward,
            halfWidth = shoulderWidth * 0.44f,
            frontDepth = shoulderWidth * 0.17f,
            backDepth = shoulderWidth * 0.27f,
        ),
        addMeshDirectionalRing(
            mesh = mesh,
            center = chestTopCenter,
            side = chestTopAxes.side,
            depth = chestTopAxes.forward,
            halfWidth = shoulderWidth * 0.38f,
            frontDepth = shoulderWidth * 0.15f,
            backDepth = shoulderWidth * 0.25f,
        ),
    )
    chestRings.zipWithNext().forEach { (lower, upper) ->
        addMeshStrip(mesh, lower, upper, palette.coreFill)
    }
    val upperBackHalfWidth = shoulderWidth * 0.30f
    val upperBackRing = addMeshDirectionalRing(
        mesh = mesh,
        center = upperBackCenter,
        side = upperBackAxes.side,
        depth = upperBackAxes.forward,
        halfWidth = upperBackHalfWidth,
        frontDepth = shoulderWidth * 0.14f,
        backDepth = shoulderWidth * 0.24f,
    )
    addMeshStrip(mesh, chestRings.last(), upperBackRing, palette.coreFill)
    val upperTransitionHalfWidth = shoulderWidth * 0.18f
    val upperTransitionFrontDepth = shoulderWidth * 0.11f
    val upperTransitionBackDepth = shoulderWidth * 0.13f
    val upperTransitionRing = addMeshDirectionalRing(
        mesh = mesh,
        center = upperTransitionCenter,
        side = upperTransitionAxes.side,
        depth = upperTransitionAxes.forward,
        halfWidth = upperTransitionHalfWidth,
        frontDepth = upperTransitionFrontDepth,
        backDepth = upperTransitionBackDepth,
    )
    addMeshStrip(mesh, upperBackRing, upperTransitionRing, palette.coreFill)
    val neckMidLerp = 0.55f
    val neckConnector = addNeckConnector(
        mesh = mesh,
        neck = neck,
        lowerRing = upperTransitionRing,
        torsoTopCenter = upperTransitionCenter,
        bodyAxes = bodyAxes,
        referenceAxes = previousRingAxes,
        shoulderWidth = shoulderWidth,
        midLerp = neckMidLerp,
        neckFill = palette.jointFill,
    )
    val headAxes = alignRingAxes(
        neckConnector.axes,
        spineRingAxes(neck, neck.lerp(head, 0.5f), head, bodyAxes),
    )

    val pelvisTopCenter = hipCenter.lerp(waistCenter, 0.76f)
    val pelvisMidCenter = hipCenter.lerp(waistCenter, 0.38f)
    val pelvisBottomCenter = hipCenter.lerp(waistCenter, 0.06f)
    val pelvisJunctionCenter = pelvisTopCenter + pelvisAxes.forward * (pelvisWidth * 0.03f)
    val pelvisJunctionWidth = torsoBodyWidth(
        hipWidth,
        shoulderWidth,
        spineProgress(hipCenter, neck, pelvisJunctionCenter),
    )
    val pelvisMidWidth = torsoBodyWidth(
        hipWidth,
        shoulderWidth,
        spineProgress(hipCenter, neck, pelvisMidCenter),
    )
    val pelvisBackDepth = floatArrayOf(0f)
    val pelvisBottomRing = addMeshTorsoRing(
        mesh, pelvisBottomCenter, pelvisAxes.side, pelvisAxes.forward,
        hipWidth * 0.50f, hipWidth * 0.34f,
        latWidthScale = 1.06f, latDepthScale = 0.42f,
        erectorWidthScale = 0.44f, erectorDepthScale = 1.08f,
        grooveWidthScale = 0.14f, grooveDepthScale = 0.56f,
        backDepthTracker = pelvisBackDepth,
    )
    val pelvisMidRing = addMeshTorsoRing(
        mesh, pelvisMidCenter, pelvisAxes.side, pelvisAxes.forward,
        pelvisMidWidth * 0.52f, pelvisMidWidth * 0.36f,
        latWidthScale = 1.08f, latDepthScale = 0.40f,
        erectorWidthScale = 0.48f, erectorDepthScale = 1.14f,
        grooveWidthScale = 0.12f, grooveDepthScale = 0.54f,
        backDepthTracker = pelvisBackDepth,
    )
    pelvisBackDepth[0] = max(pelvisBackDepth[0], waistResolvedBackDepth * 0.96f)
    val pelvisJunctionRing = addMeshTorsoRing(
        mesh, pelvisJunctionCenter, pelvisAxes.side, pelvisAxes.forward,
        pelvisJunctionWidth * 0.50f, pelvisJunctionWidth * 0.30f,
        latWidthScale = 1.10f, latDepthScale = 0.36f,
        erectorWidthScale = 0.42f, erectorDepthScale = 1.10f,
        grooveWidthScale = 0.14f, grooveDepthScale = 0.62f,
        backDepthTracker = pelvisBackDepth,
    )
    val pelvisRings = listOf(pelvisJunctionRing, pelvisMidRing, pelvisBottomRing)
    addMeshStrip(mesh, pelvisRings[2], pelvisRings[1], palette.coreFill)
    addMeshStrip(mesh, pelvisRings[1], pelvisRings[0], palette.coreFill)
    addMeshCap(mesh, pelvisRings[2], palette.coreFill)
    addMeshStrip(mesh, pelvisRings[0], chestRings[0], palette.coreFill)

    fun stableSegmentLength(startName: String, endName: String): Float {
        val start = resolvedJoints[startName] ?: return 0f
        val end = resolvedJoints[endName] ?: return 0f
        return bodyProportions.segmentLengths[LimbKey(startName, endName)]
            ?: (end - start).length()
    }

    fun segmentScaledWidth(startName: String, endName: String, scale: Float): Float {
        return stableSegmentLength(startName, endName) * scale
    }

    addJointCap(mesh, leftHip, bodyAxes, segmentScaledWidth("left_hip", "left_knee", 0.27f) * 0.48f, palette.jointFill)
    addJointCap(mesh, rightHip, bodyAxes, segmentScaledWidth("right_hip", "right_knee", 0.27f) * 0.48f, palette.jointFill)
    addJointCap(mesh, leftShoulder, bodyAxes, segmentScaledWidth("left_shoulder", "left_elbow", 0.30f) * 0.48f, palette.jointFill)
    addJointCap(mesh, rightShoulder, bodyAxes, segmentScaledWidth("right_shoulder", "right_elbow", 0.30f) * 0.48f, palette.jointFill)
    addHeadVolume(
        mesh = mesh,
        neck = neck,
        headAxes = headAxes,
        shoulderWidth = shoulderWidth,
        headSegmentLength = stableSegmentLength("neck", "head"),
        neckUpperRing = neckConnector.upperRing,
        fill = palette.headFill,
    )

    SkeletonLimbs.forEach { limb ->
        val start = resolvedJoints.getValue(limb.startName)
        val end = resolvedJoints.getValue(limb.endName)
        val segmentLength = max(
            bodyProportions.segmentLengths[LimbKey(limb.startName, limb.endName)]
                ?: (end - start).length(),
            hipWidth * 0.08f,
        )
        val startWidth = segmentLength * limb.profile.startWidth
        val endWidth = segmentLength * limb.profile.endWidth
        addMeshSegment(
            mesh = mesh,
            start = start,
            end = end,
            bodyAxes = bodyAxes,
            startWidth = startWidth,
            endWidth = endWidth,
            depthScale = limb.profile.depthScale,
            sides = 4,
            fill = palette.limbFill,
            startInset = jointCapClearance(limb.startName, startWidth),
            endInset = jointCapClearance(limb.endName, endWidth),
            preferredSide = stableLimbSides[LimbKey(limb.startName, limb.endName)],
            muscleBulgeScale = limb.profile.muscleBulgeScale,
            muscleBulgePosition = limb.profile.muscleBulgePosition,
        )
    }
    fun addHand(
        wristName: String,
        handName: String,
        elbowName: String,
    ) {
        val wrist = resolvedJoints.getValue(wristName)
        val hand = resolvedJoints.getValue(handName)
        val handLength = max(
            stableSegmentLength(wristName, handName),
            shoulderWidth * 0.08f,
        )
        val wristWidth = max(
            segmentScaledWidth(elbowName, wristName, 0.17f) * 0.90f,
            handLength * 0.42f,
        )
        val palmWidth = max(wristWidth * 1.10f, handLength * 0.50f)
        addMeshSegment(
            mesh = mesh,
            start = wrist,
            end = hand,
            bodyAxes = bodyAxes,
            startWidth = wristWidth,
            endWidth = palmWidth * 0.90f,
            depthScale = 0.36f,
            sides = 4,
            fill = palette.limbFill,
            startInset = jointCapClearance(wristName, wristWidth),
            muscleBulgeScale = 1.12f,
            muscleBulgePosition = 0.58f,
        )
    }
    addHand("left_wrist", "left_hand", "left_elbow")
    addHand("right_wrist", "right_hand", "right_elbow")
    addShoeBlockFromNames(mesh, resolvedJoints, "left_ankle", "left_foot", bodyAxes, footScale, palette)
    addShoeBlockFromNames(mesh, resolvedJoints, "right_ankle", "right_foot", bodyAxes, footScale, palette)
    addJointCapAtNames(mesh, resolvedJoints, "left_elbow", bodyAxes, max(
        segmentScaledWidth("left_shoulder", "left_elbow", 0.225f),
        segmentScaledWidth("left_elbow", "left_wrist", 0.235f),
    ) * 0.40f, palette.jointFill)
    addJointCapAtNames(mesh, resolvedJoints, "right_elbow", bodyAxes, max(
        segmentScaledWidth("right_shoulder", "right_elbow", 0.225f),
        segmentScaledWidth("right_elbow", "right_wrist", 0.235f),
    ) * 0.40f, palette.jointFill)
    addJointCapAtNames(
        mesh,
        resolvedJoints,
        "left_wrist",
        bodyAxes,
        segmentScaledWidth("left_elbow", "left_wrist", 0.17f) * 0.30f,
        palette.jointFill,
    )
    addJointCapAtNames(
        mesh,
        resolvedJoints,
        "right_wrist",
        bodyAxes,
        segmentScaledWidth("right_elbow", "right_wrist", 0.17f) * 0.30f,
        palette.jointFill,
    )
    addJointCapAtNames(mesh, resolvedJoints, "left_knee", bodyAxes, max(
        segmentScaledWidth("left_hip", "left_knee", 0.215f),
        segmentScaledWidth("left_knee", "left_ankle", 0.225f),
    ) * 0.40f, palette.jointFill)
    addJointCapAtNames(mesh, resolvedJoints, "right_knee", bodyAxes, max(
        segmentScaledWidth("right_hip", "right_knee", 0.215f),
        segmentScaledWidth("right_knee", "right_ankle", 0.225f),
    ) * 0.40f, palette.jointFill)
    addJointCap(
        mesh = mesh,
        center = ankleCapCenter(
            resolvedJoints.getValue("left_knee"),
            resolvedJoints.getValue("left_ankle"),
            segmentScaledWidth("left_knee", "left_ankle", 0.165f),
        ),
        bodyAxes = bodyAxes,
        radius = segmentScaledWidth("left_knee", "left_ankle", 0.165f) * 0.40f,
        fill = palette.jointFill,
    )
    addJointCap(
        mesh = mesh,
        center = ankleCapCenter(
            resolvedJoints.getValue("right_knee"),
            resolvedJoints.getValue("right_ankle"),
            segmentScaledWidth("right_knee", "right_ankle", 0.165f),
        ),
        bodyAxes = bodyAxes,
        radius = segmentScaledWidth("right_knee", "right_ankle", 0.165f) * 0.40f,
        fill = palette.jointFill,
    )
    return mesh
}

private fun spineProgress(
    hipCenter: WearSkeletonVec3,
    neck: WearSkeletonVec3,
    point: WearSkeletonVec3,
): Float {
    val axis = neck - hipCenter
    val lengthSq = axis.dot(axis)
    if (lengthSq <= 1e-6f) return 0.5f
    return ((point - hipCenter).dot(axis) / lengthSq).coerceIn(0f, 1f)
}

private fun torsoBodyWidth(
    hipWidth: Float,
    shoulderWidth: Float,
    progress: Float,
): Float = hipWidth + (shoulderWidth - hipWidth) * progress.coerceIn(0f, 1f)

private fun alignRingAxes(reference: BodyAxes, candidate: BodyAxes): BodyAxes {
    val up = candidate.up
    var side = candidate.side
    if (side.dot(reference.side) < 0f) {
        side = side * -1f
    }
    val forward = side.cross(up).normalizedOr(candidate.forward)
    return BodyAxes(side = side, up = up, forward = forward)
}

private fun spineRingAxes(
    previous: WearSkeletonVec3,
    center: WearSkeletonVec3,
    next: WearSkeletonVec3,
    bodyAxes: BodyAxes,
): BodyAxes {
    val tangent = (next - previous).normalizedOr(
        (next - center).normalizedOr(bodyAxes.up)
    )
    val side = bodyAxes.side
        .projectOntoPlane(tangent)
        .normalizedOr(bodyAxes.side)
    val forward = side.cross(tangent).normalizedOr(bodyAxes.forward)
    return BodyAxes(side = side, up = tangent, forward = forward)
}

private fun jointCapClearance(
    jointName: String,
    limbWidth: Float,
): Float {
    return if (jointName in VisibleJointCapNames) {
        when (jointName) {
            "left_hip", "right_hip" -> limbWidth * 0.12f
            "left_shoulder", "right_shoulder" -> limbWidth * 0.12f
            "left_ankle", "right_ankle" -> limbWidth * 0.65f
            else -> limbWidth * 0.08f
        }
    } else {
        0f
    }
}

private fun addShoeBlockFromNames(
    mesh: GeneratedLowPolyMesh,
    joints: Map<String, WearSkeletonVec3>,
    ankleName: String,
    footName: String,
    bodyAxes: BodyAxes,
    footScale: Float,
    palette: SkeletonPalette,
): Boolean {
    val ankle = joints[ankleName] ?: return false
    val foot = joints[footName] ?: return false
    val worldUp = WearSkeletonVec3(0f, 1f, 0f)
    val footVector = foot - ankle
    val footLength = footVector.length()
    val bodyForward = bodyAxes.forward - worldUp * bodyAxes.forward.dot(worldUp)
    val stableForward = bodyForward.normalizedOr(WearSkeletonVec3(0f, 0f, 1f))
    val footForward = if (footLength > 0.0001f) {
        footVector * (1f / footLength)
    } else {
        stableForward
    }
    val shoeUp = (worldUp - footForward * worldUp.dot(footForward)).normalizedOr(bodyAxes.up)
    val fallbackSide = bodyAxes.side.projectOntoPlane(footForward).normalizedOr(bodyAxes.side)
    // Box-ring winding expects side x up to point opposite the extrusion.
    val footSide = footForward.cross(shoeUp).normalizedOr(fallbackSide)
    val shoeScale = if (footLength > 0.0001f) {
        footLength
    } else {
        footScale * 0.60f
    }
    val length = max(shoeScale * 1.45f, footScale * 0.58f)
    val halfWidth = max(shoeScale * 0.32f, footScale * 0.18f)
    val height = max(shoeScale * 0.28f, footScale * 0.15f)
    val fill = palette.limbFill
    val profile = listOf(
        floatArrayOf(-0.02f, -0.08f, 0.72f, 0.48f),
        floatArrayOf(0.16f, -0.02f, 0.82f, 0.58f),
        floatArrayOf(0.38f, -0.04f, 0.94f, 0.60f),
        floatArrayOf(0.76f, -0.22f, 1.06f, 0.42f),
        floatArrayOf(1.00f, -0.30f, 0.90f, 0.30f),
    )
    val rings = profile.map { point ->
        addMeshBoxRing(
            mesh = mesh,
            center = ankle + footForward * (length * (point[0] - 0.12f)) + shoeUp * (height * point[1]),
            side = footSide,
            depth = shoeUp,
            halfWidth = halfWidth * point[2],
            halfDepth = height * point[3],
        )
    }
    rings.zipWithNext().forEach { (rear, front) -> addMeshStrip(mesh, rear, front, fill) }
    addMeshCap(mesh, rings.first(), fill)
    addMeshCap(mesh, rings.last().asReversed(), fill)
    return true
}

private fun ankleCapCenter(
    knee: WearSkeletonVec3,
    ankle: WearSkeletonVec3,
    lowerLegEndWidth: Float,
): WearSkeletonVec3 {
    val shin = ankle - knee
    val shinLength = shin.length()
    if (shinLength <= 0.0001f) return ankle
    val clearance = min(lowerLegEndWidth * 0.65f, shinLength * 0.10f)
    return ankle - shin * (clearance * 0.5f / shinLength)
}

private fun addJointCapAtNames(
    mesh: GeneratedLowPolyMesh,
    joints: Map<String, WearSkeletonVec3>,
    jointName: String,
    bodyAxes: BodyAxes,
    radius: Float,
    fill: Color,
) {
    val center = joints[jointName] ?: return
    addJointCap(mesh, center, bodyAxes, radius, fill)
}

private fun addJointCap(
    mesh: GeneratedLowPolyMesh,
    center: WearSkeletonVec3,
    bodyAxes: BodyAxes,
    radius: Float,
    fill: Color,
) {
    addLowPolySphere(
        mesh = mesh,
        center = center,
        up = bodyAxes.up,
        side = bodyAxes.side,
        depth = bodyAxes.forward,
        radius = radius,
        fill = fill,
    )
}

private data class NeckConnectorResult(
    val axes: BodyAxes,
    val upperRing: List<Int>,
)

private fun addNeckConnector(
    mesh: GeneratedLowPolyMesh,
    neck: WearSkeletonVec3,
    lowerRing: List<Int>,
    torsoTopCenter: WearSkeletonVec3,
    bodyAxes: BodyAxes,
    referenceAxes: BodyAxes,
    shoulderWidth: Float,
    midLerp: Float,
    neckFill: Color,
): NeckConnectorResult {
    val midCenter = torsoTopCenter.lerp(neck, midLerp)
    val neckAxes = alignRingAxes(
        referenceAxes,
        spineRingAxes(torsoTopCenter, midCenter, neck, bodyAxes),
    )
    val upperCenter = neck
    val midHalfWidth = shoulderWidth * 0.14f
    val upperHalfWidth = shoulderWidth * 0.115f
    val midRing = addMeshDirectionalRing(
        mesh = mesh,
        center = midCenter,
        side = neckAxes.side,
        depth = neckAxes.forward,
        halfWidth = midHalfWidth,
        frontDepth = shoulderWidth * 0.105f,
        backDepth = shoulderWidth * 0.09f,
    )
    val upperRing = addMeshDirectionalRing(
        mesh = mesh,
        center = upperCenter,
        side = neckAxes.side,
        depth = neckAxes.forward,
        halfWidth = upperHalfWidth,
        frontDepth = shoulderWidth * 0.085f,
        backDepth = shoulderWidth * 0.075f,
    )
    addMeshStrip(mesh, lowerRing, midRing, neckFill)
    addMeshStrip(mesh, midRing, upperRing, neckFill)
    return NeckConnectorResult(neckAxes, upperRing)
}

private fun addHeadVolume(
    mesh: GeneratedLowPolyMesh,
    neck: WearSkeletonVec3,
    headAxes: BodyAxes,
    shoulderWidth: Float,
    headSegmentLength: Float,
    neckUpperRing: List<Int>,
    fill: Color,
) {
    val height = max(headSegmentLength, shoulderWidth * 0.12f)
    val up = headAxes.up
    val side = headAxes.side
    val depth = headAxes.forward
    val headHeight = max(height * 1.65f, shoulderWidth * 0.45f)
    val headWidth = max(height * 1.08f, shoulderWidth * 0.37f)
    val headDepth = headWidth * 0.82f
    val base = neck + up * (headHeight * 0.02f)
    val center = base + up * (headHeight * 0.44f)
    val rings = listOf(
        addMeshBoxRing(
            mesh,
            base,
            side,
            depth,
            shoulderWidth * 0.12f,
            shoulderWidth * 0.08f,
        ),
        addMeshBoxRing(mesh, center, side, depth, headWidth * 0.52f, headDepth * 0.52f),
        addMeshBoxRing(mesh, base + up * headHeight, side, depth, headWidth * 0.44f, headDepth * 0.44f),
    )
    addMeshStrip(mesh, neckUpperRing, rings[0], fill)
    addMeshStrip(mesh, rings[0], rings[1], fill)
    addMeshStrip(mesh, rings[1], rings[2], fill)
    addMeshCap(mesh, rings[2].asReversed(), fill)
}

private fun addMeshSegment(
    mesh: GeneratedLowPolyMesh,
    start: WearSkeletonVec3,
    end: WearSkeletonVec3,
    bodyAxes: BodyAxes,
    startWidth: Float,
    endWidth: Float,
    depthScale: Float,
    sides: Int,
    fill: Color,
    startInset: Float = 0f,
    endInset: Float = 0f,
    preferredSide: WearSkeletonVec3? = null,
    muscleBulgeScale: Float = 1f,
    muscleBulgePosition: Float = 0.5f,
) {
    val segment = end - start
    val rawLength = segment.length()
    val direction = if (rawLength > 0.0001f) {
        segment * (1f / rawLength)
    } else {
        bodyAxes.up
    }
    val length = max(rawLength, 0.001f)
    val resolvedEnd = if (rawLength > 0.0001f) end else start + direction * length
    val maxInset = length * 0.10f
    val safeStart = start + direction * min(startInset, maxInset)
    val safeEnd = resolvedEnd - direction * min(endInset, maxInset)
    val safeSpan = safeEnd - safeStart
    val safeLength = max(safeSpan.length(), 0.001f)
    val safeDirection = if (safeSpan.length() > 0.0001f) {
        safeSpan * (1f / safeSpan.length())
    } else {
        direction
    }
    val emitEnd = if (safeSpan.length() > 0.0001f) safeEnd else safeStart + safeDirection * safeLength
    val side = preferredSide
        ?.projectOntoPlane(safeDirection)
        ?.normalizedOr(stableLimbSide(safeDirection, bodyAxes))
        ?: stableLimbSide(safeDirection, bodyAxes)
    val depth = side.cross(safeDirection).normalizedOr(bodyAxes.forward)
    val startRing = addMeshSegmentRing(mesh, safeStart, side, depth, max(startWidth, 0.001f), depthScale, sides)
    val endRing = addMeshSegmentRing(mesh, emitEnd, side, depth, max(endWidth, 0.001f), depthScale, sides)
    if (muscleBulgeScale > 1f) {
        val safeBulgePosition = muscleBulgePosition.coerceIn(0.2f, 0.8f)
        val bulgeCenter = safeStart.lerp(emitEnd, safeBulgePosition)
        val interpolatedWidth = startWidth + (endWidth - startWidth) * safeBulgePosition
        val bulgeWidth = max(startWidth, max(endWidth, interpolatedWidth)) * muscleBulgeScale
        val bulgeRing = addMeshSegmentRing(
            mesh,
            bulgeCenter,
            side,
            depth,
            bulgeWidth,
            depthScale,
            sides,
        )
        addMeshStrip(mesh, startRing, bulgeRing, fill)
        addMeshStrip(mesh, bulgeRing, endRing, fill)
    } else {
        addMeshStrip(mesh, startRing, endRing, fill)
    }
    addMeshCap(mesh, startRing, fill)
    addMeshCap(mesh, endRing.asReversed(), fill)
}

private fun addLowPolySphere(
    mesh: GeneratedLowPolyMesh,
    center: WearSkeletonVec3,
    up: WearSkeletonVec3,
    side: WearSkeletonVec3,
    depth: WearSkeletonVec3,
    radius: Float,
    fill: Color,
) {
    val bottom = addMeshVertex(mesh, center - up * radius)
    val top = addMeshVertex(mesh, center + up * radius)
    val lowerRing = addMeshRing(
        mesh = mesh,
        center = center - up * (radius * 0.50f),
        side = side,
        depth = depth,
        halfWidth = radius * 0.866f,
        halfDepth = radius * 0.866f,
        sides = 8,
    )
    val middleRing = addMeshRing(
        mesh = mesh,
        center = center,
        side = side,
        depth = depth,
        halfWidth = radius,
        halfDepth = radius,
        sides = 8,
    )
    val upperRing = addMeshRing(
        mesh = mesh,
        center = center + up * (radius * 0.50f),
        side = side,
        depth = depth,
        halfWidth = radius * 0.866f,
        halfDepth = radius * 0.866f,
        sides = 8,
    )
    addMeshFan(mesh, bottom, lowerRing, fill)
    addMeshStrip(mesh, lowerRing, middleRing, fill)
    addMeshStrip(mesh, middleRing, upperRing, fill)
    addMeshFan(mesh, top, upperRing.asReversed(), fill)
}

private fun addMeshSegmentRing(
    mesh: GeneratedLowPolyMesh,
    center: WearSkeletonVec3,
    side: WearSkeletonVec3,
    depth: WearSkeletonVec3,
    width: Float,
    depthScale: Float,
    sides: Int,
): List<Int> {
    return if (sides <= 4) {
        addMeshBoxRing(
            mesh = mesh,
            center = center,
            side = side,
            depth = depth,
            halfWidth = width * 0.5f,
            halfDepth = width * depthScale,
        )
    } else {
        addMeshRing(
            mesh = mesh,
            center = center,
            side = side,
            depth = depth,
            halfWidth = width * 0.5f,
            halfDepth = width * depthScale,
            sides = sides,
        )
    }
}

private fun addMeshVertex(
    mesh: GeneratedLowPolyMesh,
    point: WearSkeletonVec3,
): Int {
    mesh.vertices += point
    return mesh.vertices.lastIndex
}

private fun addMeshRing(
    mesh: GeneratedLowPolyMesh,
    center: WearSkeletonVec3,
    side: WearSkeletonVec3,
    depth: WearSkeletonVec3,
    halfWidth: Float,
    halfDepth: Float,
    sides: Int,
): List<Int> {
    return List(sides.coerceAtLeast(4)) { index ->
        val angle = (2.0 * PI * index / sides).toFloat()
        val point = center + side * (cos(angle) * halfWidth) + depth * (sin(angle) * halfDepth)
        mesh.vertices += point
        mesh.vertices.lastIndex
    }
}

private fun addMeshBoxRing(
    mesh: GeneratedLowPolyMesh,
    center: WearSkeletonVec3,
    side: WearSkeletonVec3,
    depth: WearSkeletonVec3,
    halfWidth: Float,
    halfDepth: Float,
): List<Int> {
    val corners = listOf(
        center + side * halfWidth + depth * halfDepth,
        center - side * halfWidth + depth * halfDepth,
        center - side * halfWidth - depth * halfDepth,
        center + side * halfWidth - depth * halfDepth,
    )
    return corners.map { point ->
        mesh.vertices += point
        mesh.vertices.lastIndex
    }
}

private fun addMeshTorsoRing(
    mesh: GeneratedLowPolyMesh,
    center: WearSkeletonVec3,
    side: WearSkeletonVec3,
    depth: WearSkeletonVec3,
    halfWidth: Float,
    halfDepth: Float,
    latWidthScale: Float,
    latDepthScale: Float,
    erectorWidthScale: Float,
    erectorDepthScale: Float,
    grooveWidthScale: Float,
    grooveDepthScale: Float,
    backDepthTracker: FloatArray? = null,
    backDepthBoost: Float = 1.0f,
    backCenterBias: WearSkeletonVec3 = WearSkeletonVec3(0f, 0f, 0f),
    minBackDepth: Float? = null,
): List<Int> {
    val latScale = latWidthScale.coerceIn(1.0f, 1.18f)
    val frontDepth = (halfDepth * (0.90f + latDepthScale * 0.08f))
        .coerceIn(halfDepth * 0.85f, halfDepth * 1.08f)
    var backDepth = (halfDepth * (0.92f + erectorDepthScale * 0.04f))
        .coerceIn(halfDepth * 0.86f, halfDepth * 1.12f)
    backDepth *= backDepthBoost
    if (backDepthTracker != null && backDepthTracker[0] > 0f) {
        backDepth = max(backDepth, backDepthTracker[0])
    }
    if (minBackDepth != null) {
        backDepth = max(backDepth, minBackDepth)
    }
    if (backDepthTracker != null) {
        backDepthTracker[0] = max(backDepthTracker[0], backDepth)
    }
    val width = halfWidth * latScale
    return addMeshDirectionalRing(
        mesh = mesh,
        center = center,
        side = side,
        depth = depth,
        halfWidth = width,
        frontDepth = frontDepth,
        backDepth = backDepth,
        backCenterBias = backCenterBias,
    )
}

private fun addMeshDirectionalRing(
    mesh: GeneratedLowPolyMesh,
    center: WearSkeletonVec3,
    side: WearSkeletonVec3,
    depth: WearSkeletonVec3,
    halfWidth: Float,
    frontDepth: Float,
    backDepth: Float,
    backCenterBias: WearSkeletonVec3 = WearSkeletonVec3(0f, 0f, 0f),
): List<Int> {
    val backCenter = center + backCenterBias
    val corners = listOf(
        center + side * halfWidth + depth * frontDepth,
        center - side * halfWidth + depth * frontDepth,
        backCenter - side * halfWidth - depth * backDepth,
        backCenter + side * halfWidth - depth * backDepth,
    )
    return corners.map { point ->
        mesh.vertices += point
        mesh.vertices.lastIndex
    }
}

private fun addMeshFan(
    mesh: GeneratedLowPolyMesh,
    centerIndex: Int,
    ring: List<Int>,
    fill: Color,
) {
    for (index in ring.indices) {
        val next = (index + 1) % ring.size
        mesh.faces += GeneratedLowPolyFace(listOf(centerIndex, ring[index], ring[next]), fill)
    }
}

private fun addMeshStrip(
    mesh: GeneratedLowPolyMesh,
    lower: List<Int>,
    upper: List<Int>,
    fill: Color,
) {
    val count = min(lower.size, upper.size)
    for (index in 0 until count) {
        val next = (index + 1) % count
        mesh.faces += GeneratedLowPolyFace(listOf(lower[index], upper[index], upper[next], lower[next]), fill)
    }
}

private fun addMeshCap(
    mesh: GeneratedLowPolyMesh,
    ring: List<Int>,
    fill: Color,
) {
    if (ring.size == 3) {
        mesh.faces += GeneratedLowPolyFace(ring, fill)
        return
    }
    if (ring.size == 4) {
        mesh.faces += GeneratedLowPolyFace(ring, fill)
        return
    }
    for (index in 1 until ring.size - 1) {
        mesh.faces += GeneratedLowPolyFace(listOf(ring[0], ring[index], ring[index + 1]), fill)
    }
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

private fun WearSkeletonVec3.projectOntoPlane(normal: WearSkeletonVec3): WearSkeletonVec3 =
    this - normal * dot(normal)

private fun buildStableLimbSides(
    frames: List<WearSkeletonFrame>,
): List<Map<LimbKey, WearSkeletonVec3>> {
    var previousSides = emptyMap<LimbKey, WearSkeletonVec3>()
    return frames.map { frame ->
        val bodyAxes = frame.joints.toBodyAxes()
        val currentSides = buildMap {
            SkeletonLimbs.forEach { limb ->
                val start = frame.joints[limb.startName] ?: return@forEach
                val end = frame.joints[limb.endName] ?: return@forEach
                val segment = end - start
                val length = segment.length()
                if (length <= 0.0001f) return@forEach

                val direction = segment * (1f / length)
                val key = LimbKey(limb.startName, limb.endName)
                val previousSide = previousSides[key]
                val transportedSide = previousSide
                    ?.projectOntoPlane(direction)
                    ?.takeIf { it.length() > 0.0001f }
                    ?.normalizedOr(bodyAxes.side)
                var resolvedSide = transportedSide ?: stableLimbSide(direction, bodyAxes)
                if (previousSide != null && resolvedSide.dot(previousSide) < 0f) {
                    resolvedSide = resolvedSide * -1f
                }
                put(key, resolvedSide)
            }
        }
        previousSides = currentSides
        currentSides
    }
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

private data class LimbProfile(
    val startWidth: Float,
    val endWidth: Float,
    val depthScale: Float,
    val muscleBulgeScale: Float,
    val muscleBulgePosition: Float,
)

private fun parseWearSkeleton(json: String): WearSkeleton {
    val root = JsonParser.parseString(json).asJsonObject
    val boundsObject = root.getAsJsonObject("bounds")
    // Browser exports keep coordinates canonical; restore removed preview-only transforms when drawing.
    val displayCoordinateTransform = root.toWearSkeletonDisplayCoordinateTransform()
    val frames = root.getAsJsonArray("frames").map { frameElement ->
        val jointsObject = frameElement.asJsonObject.getAsJsonObject("joints")
        WearSkeletonFrame(
            joints = jointsObject.entrySet().associate { (name, element) ->
                val values = element.asJsonArray
                name to displayCoordinateTransform.apply(
                    WearSkeletonVec3(
                        x = values[0].asFloat,
                        y = values[1].asFloat,
                        z = values[2].asFloat,
                    )
                )
            }
        )
    }
    return WearSkeleton(
        fps = root.get("fps")?.asFloat ?: 30f,
        bounds = displayCoordinateTransform.apply(boundsObject.toWearSkeletonBounds()),
        frames = frames,
        display = root.toWearSkeletonDisplay(),
        limbSidesByFrame = buildStableLimbSides(frames),
    )
}

private fun JsonObject.toWearSkeletonDisplay(): WearSkeletonDisplay {
    val wearDisplay = optionalJsonObject("wearDisplay")
    val selectedPreviewSettings = optionalJsonObject("selectedPreviewSettings")
    val bakedPreviewConfiguration = optionalJsonObject("bakedPreviewConfiguration")
    return WearSkeletonDisplay(
        viewYawDegrees = wearDisplay?.optionalFloat("viewYawDegrees")
            ?: selectedPreviewSettings?.optionalFloat("cameraYawDegrees")
            ?: bakedPreviewConfiguration?.optionalFloat("cameraYawDegrees"),
        viewPitchDegrees = wearDisplay?.optionalFloat("viewPitchDegrees")
            ?: selectedPreviewSettings?.optionalFloat("cameraPitchDegrees")
            ?: bakedPreviewConfiguration?.optionalFloat("cameraPitchDegrees"),
    )
}

private fun JsonObject.toWearSkeletonDisplayCoordinateTransform(): WearSkeletonDisplayCoordinateTransform {
    val normalization = optionalJsonObject("bakedPreviewConfiguration")
        ?.optionalJsonObject("wearCoordinateNormalization")
        ?: return WearSkeletonDisplayCoordinateTransform.None
    val sceneInversionRemoved = normalization.optionalBoolean("sceneInversionRemoved") == true
    val transform = normalization.optionalString("transform")
    return if (sceneInversionRemoved && transform.equals("rotate_x_pi", ignoreCase = true)) {
        WearSkeletonDisplayCoordinateTransform.RotateXPi
    } else {
        WearSkeletonDisplayCoordinateTransform.None
    }
}

private fun JsonObject.toWearSkeletonBounds(): WearSkeletonBounds = WearSkeletonBounds(
    minX = get("minX").asFloat,
    maxX = get("maxX").asFloat,
    minY = get("minY").asFloat,
    maxY = get("maxY").asFloat,
    minZ = get("minZ").asFloat,
    maxZ = get("maxZ").asFloat,
)

private fun JsonObject.optionalJsonObject(name: String): JsonObject? {
    val element = get(name) ?: return null
    return if (element.isJsonObject) element.asJsonObject else null
}

private fun JsonObject.optionalFloat(name: String): Float? {
    val element = get(name) ?: return null
    if (!element.isJsonPrimitive) {
        return null
    }
    return runCatching { element.asFloat }.getOrNull()
}

private fun JsonObject.optionalBoolean(name: String): Boolean? {
    val element = get(name) ?: return null
    if (!element.isJsonPrimitive) {
        return null
    }
    return runCatching { element.asBoolean }.getOrNull()
}

private fun JsonObject.optionalString(name: String): String? {
    val element = get(name) ?: return null
    if (!element.isJsonPrimitive) {
        return null
    }
    return runCatching { element.asString }.getOrNull()
}

private fun Int.floorMod(modulus: Int): Int = ((this % modulus) + modulus) % modulus

@Preview(showBackground = true, widthDp = 240, heightDp = 240)
@Composable
private fun SkeletonMotionPreviewPreview() {
    Box(modifier = Modifier.fillMaxSize()) {
        SkeletonMotionPreview(
            skeletonJson = SampleSkeletonJson,
            modifier = Modifier.fillMaxSize(),
            backgroundColor = Color(0xFF000000),
            primaryFill = Color(0xFFFFD500),
            animated = true,
            orbitView = true,
        )
    }
}

private const val SampleSkeletonJson = """
{
  "fps": 30,
  "bounds": { "minX": -0.5, "maxX": 0.5, "minY": 0.0, "maxY": 1.8, "minZ": -0.3, "maxZ": 0.3 },
  "frames": [
    {
      "joints": {
        "pelvis": [0.0, 0.9, 0.0],
        "neck": [0.0, 1.45, 0.0],
        "head": [0.0, 1.68, 0.02],
        "left_shoulder": [-0.22, 1.36, 0.0],
        "right_shoulder": [0.22, 1.36, 0.0],
        "left_elbow": [-0.32, 1.05, 0.0],
        "right_elbow": [0.32, 1.05, 0.0],
        "left_wrist": [-0.34, 0.78, 0.0],
        "right_wrist": [0.34, 0.78, 0.0],
        "left_hip": [-0.13, 0.82, 0.0],
        "right_hip": [0.13, 0.82, 0.0],
        "left_knee": [-0.14, 0.44, 0.02],
        "right_knee": [0.14, 0.44, 0.02],
        "left_ankle": [-0.14, 0.08, 0.0],
        "right_ankle": [0.14, 0.08, 0.0]
      }
    }
  ]
}
"""
