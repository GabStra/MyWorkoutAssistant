package com.gabstra.myworkoutassistant.motionrenderer

import android.content.Context
import android.view.Choreographer
import android.view.Surface
import android.view.SurfaceView
import android.view.View
import android.widget.FrameLayout
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.Orientation
import androidx.compose.foundation.gestures.draggable
import androidx.compose.foundation.gestures.rememberDraggableState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.Velocity
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
import com.google.android.filament.VertexBuffer
import com.google.android.filament.Viewport
import com.google.android.filament.android.UiHelper
import com.google.android.filament.filamat.MaterialBuilder
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt
import com.google.android.filament.Box as FilamentBox
import com.google.android.filament.View as FilamentView

private const val OrbitDegreesPerSecond = 36f
private const val FilamentVertexFloatCount = 7
private const val FilamentVertexStrideBytes = FilamentVertexFloatCount * 4
private const val FilamentPositionOffsetBytes = 0
private const val FilamentColorOffsetBytes = 3 * 4
private const val KneeAndHipJointCapRadius = 0.060f
private const val AnkleJointCapRadius = 0.042f
private const val VisibleShoeAnkleJointCapRadius = 0.026f
private const val DragRotationDegreesPerPixel = 0.45f
private const val SkeletonPreviewContentDescription = "Exercise movement preview"
private val SkeletonTintLightDirection = WearSkeletonVec3(-0.42f, 0.72f, 0.55f).normalizedOr(WearSkeletonVec3(0f, 1f, 0f))

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

private fun SkeletonPalette.withVisibility(
    visibility: Float,
    backgroundColor: Color,
): SkeletonPalette {
    val amount = visibility.coerceIn(0f, 1f)
    return SkeletonPalette(
        limbFill = limbFill.blendToward(backgroundColor, amount),
        coreFill = coreFill.blendToward(backgroundColor, amount),
        headFill = headFill.blendToward(backgroundColor, amount),
        jointFill = jointFill.blendToward(backgroundColor, amount),
        grid = grid.blendToward(backgroundColor, amount),
    )
}

private fun Color.blendToward(backgroundColor: Color, amount: Float): Color {
    val resolvedAmount = amount.coerceIn(0f, 1f)
    return Color(
        red = backgroundColor.red + (red - backgroundColor.red) * resolvedAmount,
        green = backgroundColor.green + (green - backgroundColor.green) * resolvedAmount,
        blue = backgroundColor.blue + (blue - backgroundColor.blue) * resolvedAmount,
        alpha = alpha,
    )
}

private fun Color.scaleRgb(amount: Float): Color {
    val scale = amount.coerceIn(0f, 1f)
    return Color(
        red = (red * scale).coerceIn(0f, 1f),
        green = (green * scale).coerceIn(0f, 1f),
        blue = (blue * scale).coerceIn(0f, 1f),
        alpha = alpha,
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
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
)

private val SkeletonLimbs = arrayOf(
    LimbSpec("left_hip", "left_knee", LimbProfile(0.142f, 0.114f, 0.44f)),
    LimbSpec("left_knee", "left_ankle", LimbProfile(0.120f, 0.088f, 0.42f)),
    LimbSpec("right_hip", "right_knee", LimbProfile(0.142f, 0.114f, 0.44f)),
    LimbSpec("right_knee", "right_ankle", LimbProfile(0.120f, 0.088f, 0.42f)),
    LimbSpec("left_shoulder", "left_elbow", LimbProfile(0.106f, 0.084f, 0.42f)),
    LimbSpec("left_elbow", "left_wrist", LimbProfile(0.086f, 0.066f, 0.40f)),
    LimbSpec("right_shoulder", "right_elbow", LimbProfile(0.106f, 0.084f, 0.42f)),
    LimbSpec("right_elbow", "right_wrist", LimbProfile(0.086f, 0.066f, 0.40f)),
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
) {
    val skeleton = remember(skeletonJson) {
        parseWearSkeleton(skeletonJson)
    }
    val baseViewYawDegrees = skeleton.display.viewYawDegrees ?: viewYawDegrees
    val baseViewPitchDegrees = skeleton.display.viewPitchDegrees ?: viewPitchDegrees
    val palette = remember(primaryFill) { createSkeletonPalette(primaryFill) }
    var playbackVisibility by remember(skeleton.frames.size) { mutableFloatStateOf(1f) }
    var frameIndex by remember(skeleton.frames.size) { mutableIntStateOf(if (animated) 0 else min(12, skeleton.frames.lastIndex)) }
    var orbitYawDegrees by remember(baseViewYawDegrees) { mutableFloatStateOf(baseViewYawDegrees) }
    var dragYawOffsetDegrees by remember(skeletonJson, baseViewYawDegrees) { mutableFloatStateOf(0f) }
    var orbitPausedByTouch by remember { mutableStateOf(false) }
    val dragRotationState = rememberDraggableState { delta ->
        dragYawOffsetDegrees += delta * dragRotationDegreesPerPixel
    }
    val horizontalDragNestedScrollConnection = remember {
        object : NestedScrollConnection {
            override fun onPostScroll(
                consumed: Offset,
                available: Offset,
                source: NestedScrollSource,
            ): Offset {
                return Offset(x = available.x, y = 0f)
            }

            override suspend fun onPostFling(
                consumed: Velocity,
                available: Velocity,
            ): Velocity {
                return Velocity(x = available.x, y = 0f)
            }
        }
    }
    val dragRotationModifier = if (dragRotationEnabled) {
        Modifier
            .nestedScroll(horizontalDragNestedScrollConnection)
            .draggable(
                state = dragRotationState,
                orientation = Orientation.Horizontal,
            )
    } else {
        Modifier
    }
    val touchPauseModifier = if (orbitView) {
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

    LaunchedEffect(animated, orbitView, skeleton.fps, skeleton.frames.size, baseViewYawDegrees, loopRestartFadeMillis) {
        if (!animated && !orbitView) {
            playbackVisibility = 1f
            return@LaunchedEffect
        }
        var startTimeNanos: Long? = null
        var previousFrameTimeNanos: Long? = null
        var orbitElapsedSeconds = 0.0
        while (true) {
            val frameTimeNanos = withFrameNanos { it }
            val startedAt = startTimeNanos ?: frameTimeNanos.also { startTimeNanos = it }
            val seconds = (frameTimeNanos - startedAt) / 1_000_000_000.0
            val previousFrameTime = previousFrameTimeNanos
            if (previousFrameTime != null && orbitView && !orbitPausedByTouch) {
                orbitElapsedSeconds += (frameTimeNanos - previousFrameTime) / 1_000_000_000.0
            }
            previousFrameTimeNanos = frameTimeNanos
            if (animated && skeleton.frames.isNotEmpty()) {
                val playback = resolveLoopPlayback(
                    elapsedSeconds = seconds,
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
                orbitYawDegrees = baseViewYawDegrees + ((orbitElapsedSeconds * OrbitDegreesPerSecond) % 360.0).toFloat()
            }
        }
    }

    val resolvedYawDegrees = if (orbitView) {
        orbitYawDegrees
    } else {
        baseViewYawDegrees
    } + dragYawOffsetDegrees
    val visiblePalette = remember(palette, backgroundColor, playbackVisibility) {
        palette.withVisibility(playbackVisibility, backgroundColor)
    }

    Box(modifier = modifier.fillMaxSize()) {
        WearSkeletonRenderer(
            skeleton = skeleton,
            frameIndex = frameIndex,
            viewYawDegrees = resolvedYawDegrees,
            viewPitchDegrees = baseViewPitchDegrees,
            palette = visiblePalette,
            backgroundColor = backgroundColor,
            modifier = Modifier.fillMaxSize(),
        )
        if (orbitView || dragRotationEnabled) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .then(touchPauseModifier)
                    .then(dragRotationModifier),
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
    backgroundColor: Color,
    modifier: Modifier = Modifier,
) {
    AndroidView(
        modifier = modifier
            .fillMaxSize()
            .background(backgroundColor)
            .semantics { contentDescription = SkeletonPreviewContentDescription },
        factory = { context ->
            WearSkeletonFilamentView(context).apply {
                updateSkeletonState(
                    skeleton = skeleton,
                    frameIndex = frameIndex,
                    viewYawDegrees = viewYawDegrees,
                    viewPitchDegrees = viewPitchDegrees,
                    palette = palette,
                    backgroundColor = backgroundColor,
                )
            }
        },
        update = { view ->
            view.updateSkeletonState(
                skeleton = skeleton,
                frameIndex = frameIndex,
                viewYawDegrees = viewYawDegrees,
                viewPitchDegrees = viewPitchDegrees,
                palette = palette,
                backgroundColor = backgroundColor,
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
    private val surfaceView = SurfaceView(context)
    private val choreographer = Choreographer.getInstance()
    private val skeletonRenderer = WearSkeletonFilamentRenderer()
    private var rendering = false
    private var released = false

    init {
        setBackgroundColor(SkeletonFallbackBackground.toArgb())
        contentDescription = SkeletonPreviewContentDescription
        importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_YES
        addView(
            surfaceView,
            LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT),
        )
        skeletonRenderer.attachTo(surfaceView)
    }

    fun updateSkeletonState(
        skeleton: WearSkeleton,
        frameIndex: Int,
        viewYawDegrees: Float,
        viewPitchDegrees: Float,
        palette: SkeletonPalette,
        backgroundColor: Color,
    ) {
        if (released) {
            return
        }
        setBackgroundColor(backgroundColor.toArgb())
        skeletonRenderer.updateScene(
            skeleton = skeleton,
            frameIndex = frameIndex,
            viewYawDegrees = viewYawDegrees,
            viewPitchDegrees = viewPitchDegrees,
            palette = palette,
            backgroundColor = backgroundColor,
        )
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        if (!released && !rendering) {
            rendering = true
            choreographer.postFrameCallback(this)
        }
    }

    override fun onDetachedFromWindow() {
        rendering = false
        choreographer.removeFrameCallback(this)
        super.onDetachedFromWindow()
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

private class WearSkeletonFilamentRenderer {
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
    private var renderableEntity: Int = 0
    private var vertexBuffer: VertexBuffer? = null
    private var indexBuffer: IndexBuffer? = null
    private var viewportWidth: Int = 0
    private var viewportHeight: Int = 0
    private var lastGeometryKey: FilamentGeometryKey? = null
    private var lastBounds: FilamentMeshBounds? = null
    private var lastYawDegrees: Float = -28f
    private var lastPitchDegrees: Float = 18f
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
        view.setPostProcessingEnabled(true)
        view.setAntiAliasing(FilamentView.AntiAliasing.FXAA)
        view.setMultiSampleAntiAliasingOptions(
            FilamentView.MultiSampleAntiAliasingOptions().apply {
                enabled = true
                sampleCount = 4
            }
        )
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
        material = createVertexColorMaterial(engine)
        materialInstance = material.createInstance("wear-skeleton")
    }

    fun attachTo(surfaceView: SurfaceView) {
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
        uiHelper.attachTo(surfaceView)
    }

    fun updateScene(
        skeleton: WearSkeleton,
        frameIndex: Int,
        viewYawDegrees: Float,
        viewPitchDegrees: Float,
        palette: SkeletonPalette,
        backgroundColor: Color,
    ) {
        if (destroyed || skeleton.frames.isEmpty()) {
            return
        }

        updateClearColor(backgroundColor)
        lastYawDegrees = viewYawDegrees
        lastPitchDegrees = viewPitchDegrees
        val resolvedFrameIndex = frameIndex.coerceIn(0, skeleton.frames.lastIndex)
        val geometryKey = FilamentGeometryKey(
            skeletonId = System.identityHashCode(skeleton),
            frameIndex = resolvedFrameIndex,
            palette = palette,
        )

        if (geometryKey != lastGeometryKey) {
            val frame = skeleton.frames[resolvedFrameIndex]
            val mesh = buildFilamentMesh(frame, skeleton.bounds, palette)
            replaceRenderable(mesh)
            lastGeometryKey = geometryKey
            lastBounds = skeleton.bounds.toStableFilamentBounds()
        }
        updateCamera()
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

    fun destroy() {
        if (destroyed) {
            return
        }
        destroyed = true
        uiHelper.detach()
        clearRenderable()
        engine.destroyMaterialInstance(materialInstance)
        engine.destroyMaterial(material)
        engine.destroyCameraComponent(cameraEntity)
        EntityManager.get().destroy(cameraEntity)
        engine.destroyView(view)
        engine.destroyScene(scene)
        engine.destroyRenderer(renderer)
        engine.destroy()
    }

    private fun replaceRenderable(mesh: FilamentMeshData) {
        clearRenderable()
        if (mesh.indices.isEmpty() || mesh.vertices.isEmpty()) {
            return
        }

        val vertexData = ByteBuffer
            .allocateDirect(mesh.vertices.size * 4)
            .order(ByteOrder.nativeOrder())
            .asFloatBuffer()
            .apply {
                put(mesh.vertices)
                flip()
            }
        val indexData = ByteBuffer
            .allocateDirect(mesh.indices.size * 2)
            .order(ByteOrder.nativeOrder())
            .asShortBuffer()
            .apply {
                mesh.indices.forEach { put(it.toShort()) }
                flip()
            }

        val newVertexBuffer = VertexBuffer.Builder()
            .vertexCount(mesh.vertexCount)
            .bufferCount(1)
            .attribute(
                VertexBuffer.VertexAttribute.POSITION,
                0,
                VertexBuffer.AttributeType.FLOAT3,
                FilamentPositionOffsetBytes,
                FilamentVertexStrideBytes,
            )
            .attribute(
                VertexBuffer.VertexAttribute.COLOR,
                0,
                VertexBuffer.AttributeType.FLOAT4,
                FilamentColorOffsetBytes,
                FilamentVertexStrideBytes,
            )
            .build(engine)
        val newIndexBuffer = IndexBuffer.Builder()
            .indexCount(mesh.indices.size)
            .bufferType(IndexBuffer.Builder.IndexType.USHORT)
            .build(engine)

        newVertexBuffer.setBufferAt(engine, 0, vertexData)
        newIndexBuffer.setBuffer(engine, indexData)

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
            .culling(false)
            .receiveShadows(false)
            .castShadows(false)
            .build(engine, entity)
        scene.addEntity(entity)

        renderableEntity = entity
        vertexBuffer = newVertexBuffer
        indexBuffer = newIndexBuffer
    }

    private fun clearRenderable() {
        if (renderableEntity != 0) {
            scene.removeEntity(renderableEntity)
            engine.renderableManager.destroy(renderableEntity)
            EntityManager.get().destroy(renderableEntity)
            renderableEntity = 0
        }
        indexBuffer?.let(engine::destroyIndexBuffer)
        vertexBuffer?.let(engine::destroyVertexBuffer)
        indexBuffer = null
        vertexBuffer = null
    }

    private fun updateCamera() {
        val bounds = lastBounds ?: return
        if (viewportWidth <= 0 || viewportHeight <= 0) {
            return
        }
        val cameraFrame = SkeletonCameraFrame(
            bounds = bounds,
            yawDegrees = lastYawDegrees,
            pitchDegrees = lastPitchDegrees,
        )
        val eye = cameraFrame.eye
        val target = bounds.center
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
            MaterialBuilder.init()
            initialized = true
        }
    }
}

private data class FilamentGeometryKey(
    val skeletonId: Int,
    val frameIndex: Int,
    val palette: SkeletonPalette,
)

private data class FilamentMeshData(
    val vertices: FloatArray,
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

private data class SkeletonCameraFrame(
    val bounds: FilamentMeshBounds,
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
    val eye: WearSkeletonVec3 = bounds.center + eyeDirection * (bounds.radius * 4.2f)
    val farPlane: Float = bounds.radius * 9.0f

    fun fixedProjection(aspect: Double): CameraProjectionBounds {
        val safeAspect = aspect.toFloat().coerceAtLeast(0.001f)
        var halfWidth = bounds.radius * 1.08f
        var halfHeight = bounds.radius * 1.08f
        if (safeAspect >= 1f) {
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

private data class CameraProjectionBounds(
    val left: Double,
    val right: Double,
    val bottom: Double,
    val top: Double,
)

private fun createVertexColorMaterial(engine: Engine): Material {
    val materialPackage = MaterialBuilder()
        .name("Wear skeleton vertex colors")
        .shading(MaterialBuilder.Shading.UNLIT)
        .require(MaterialBuilder.VertexAttribute.COLOR)
        .doubleSided(true)
        .material(
            """
            void material(inout MaterialInputs material) {
                prepareMaterial(material);
                material.baseColor = getColor();
            }
            """.trimIndent()
        )
        .targetApi(MaterialBuilder.TargetApi.OPENGL)
        .platform(MaterialBuilder.Platform.MOBILE)
        .build(engine)
    check(materialPackage.isValid) { "Unable to compile Wear skeleton Filament material." }
    val buffer = materialPackage.buffer
    buffer.rewind()
    return Material.Builder()
        .payload(buffer, buffer.remaining())
        .build(engine)
}

private fun buildFilamentMesh(
    frame: WearSkeletonFrame,
    bounds: WearSkeletonBounds,
    palette: SkeletonPalette,
): FilamentMeshData {
    val generatedMesh = buildSingleLowPolyMesh(frame.joints, palette) ?: GeneratedLowPolyMesh()
    val modelBounds = bounds.toStableFilamentBounds()
    val vertexValues = mutableListOf<Float>()
    val indices = mutableListOf<Int>()

    generatedMesh.faces.forEach { face ->
        val points = face.vertexIndices.mapNotNull { index -> generatedMesh.vertices.getOrNull(index) }
        if (points.size < 3) {
            return@forEach
        }
        val normal = (points[1] - points[0])
            .cross(points[2] - points[1])
            .normalizedOr(WearSkeletonVec3(0f, 1f, 0f))
        val fill = tintColorForLightDirection(face.fill, normal)
        for (index in 1 until points.lastIndex) {
            addFilamentTriangle(
                vertices = vertexValues,
                indices = indices,
                a = points[0],
                b = points[index],
                c = points[index + 1],
                color = fill,
            )
        }
    }
    addFilamentFloorGrid(vertexValues, indices, bounds, palette.grid)

    return FilamentMeshData(
        vertices = vertexValues.toFloatArray(),
        indices = indices.toIntArray(),
        vertexCount = vertexValues.size / FilamentVertexFloatCount,
        modelBounds = modelBounds,
    )
}

private fun WearSkeletonBounds.toStableFilamentBounds(): FilamentMeshBounds {
    val height = (maxY - minY).coerceAtLeast(0.001f)
    val width = (maxX - minX).coerceAtLeast(0.001f)
    val depth = (maxZ - minZ).coerceAtLeast(0.001f)
    val horizontalPadding = max(width, depth) * 0.28f
    val bottomPadding = height * 0.04f
    val topPadding = height * 0.20f
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

private fun addFilamentVertex(
    vertices: MutableList<Float>,
    indices: MutableList<Int>,
    point: WearSkeletonVec3,
    color: Color,
) {
    val index = vertices.size / FilamentVertexFloatCount
    require(index <= UShort.MAX_VALUE.toInt()) {
        "Wear skeleton mesh exceeded 16-bit index capacity."
    }
    vertices += point.x
    vertices += point.y
    vertices += point.z
    vertices += color.red.srgbToLinearChannel()
    vertices += color.green.srgbToLinearChannel()
    vertices += color.blue.srgbToLinearChannel()
    vertices += color.alpha
    indices += index
}

private fun addFilamentTriangle(
    vertices: MutableList<Float>,
    indices: MutableList<Int>,
    a: WearSkeletonVec3,
    b: WearSkeletonVec3,
    c: WearSkeletonVec3,
    color: Color,
) {
    addFilamentVertex(vertices, indices, a, color)
    addFilamentVertex(vertices, indices, b, color)
    addFilamentVertex(vertices, indices, c, color)
}

private fun tintColorForLightDirection(
    fill: Color,
    worldNormal: WearSkeletonVec3,
): Color {
    val normal = worldNormal.normalizedOr(WearSkeletonVec3(0f, 1f, 0f))
    val diffuse = normal.dot(SkeletonTintLightDirection).coerceIn(0f, 1f)
    val lightLevel = 0.58f + diffuse * 0.42f
    return fill.scaleRgb(lightLevel)
}

private fun addFilamentFloorGrid(
    vertices: MutableList<Float>,
    indices: MutableList<Int>,
    bounds: WearSkeletonBounds,
    color: Color,
) {
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

    for (index in 0..divisions) {
        val amount = index / divisions.toFloat()
        val x = minX + (maxX - minX) * amount
        val z = minZ + (maxZ - minZ) * amount
        addFilamentQuad(
            vertices = vertices,
            indices = indices,
            a = WearSkeletonVec3(x - lineHalfWidth, floorY, minZ),
            b = WearSkeletonVec3(x + lineHalfWidth, floorY, minZ),
            c = WearSkeletonVec3(x + lineHalfWidth, floorY, maxZ),
            d = WearSkeletonVec3(x - lineHalfWidth, floorY, maxZ),
            color = color,
        )
        addFilamentQuad(
            vertices = vertices,
            indices = indices,
            a = WearSkeletonVec3(minX, floorY, z - lineHalfWidth),
            b = WearSkeletonVec3(maxX, floorY, z - lineHalfWidth),
            c = WearSkeletonVec3(maxX, floorY, z + lineHalfWidth),
            d = WearSkeletonVec3(minX, floorY, z + lineHalfWidth),
            color = color,
        )
    }
}

private fun addFilamentQuad(
    vertices: MutableList<Float>,
    indices: MutableList<Int>,
    a: WearSkeletonVec3,
    b: WearSkeletonVec3,
    c: WearSkeletonVec3,
    d: WearSkeletonVec3,
    color: Color,
) {
    addFilamentTriangle(vertices, indices, a, c, b, color)
    addFilamentTriangle(vertices, indices, a, d, c, color)
}

private fun buildSingleLowPolyMesh(
    joints: Map<String, WearSkeletonVec3>,
    palette: SkeletonPalette,
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
    val shoulderCenter = leftShoulder.lerp(rightShoulder, 0.5f)
    val hipWidth = (rightHip - leftHip).length()
    val shoulderWidth = (rightShoulder - leftShoulder).length()
    val pelvisWidth = max(hipWidth * 1.08f, shoulderWidth * 0.64f)
    val footScale = max(hipWidth * 0.98f, shoulderWidth * 0.58f)
    val torsoUp = (neck - hipCenter).normalizedOr(bodyAxes.up)
    val torsoLength = (neck - hipCenter).length()
    val chestForward = bodyAxes.forward * (shoulderWidth * 0.04f)
    val waistCenter = hipCenter + torsoUp * (torsoLength * 0.40f)
    val chestCenter = hipCenter + torsoUp * (torsoLength * 0.60f)
    val chestTopCenter = shoulderCenter.lerp(neck, 0.04f) + chestForward

    val chestRings = listOf(
        addMeshBoxRing(mesh, waistCenter, bodyAxes.side, bodyAxes.forward, shoulderWidth * 0.34f, shoulderWidth * 0.16f),
        addMeshBoxRing(mesh, chestCenter + chestForward, bodyAxes.side, bodyAxes.forward, shoulderWidth * 0.43f, shoulderWidth * 0.19f),
        addMeshBoxRing(mesh, chestTopCenter, bodyAxes.side, bodyAxes.forward, shoulderWidth * 0.49f, shoulderWidth * 0.20f),
    )
    chestRings.zipWithNext().forEach { (lower, upper) ->
        addMeshStrip(mesh, lower, upper, palette.coreFill)
    }
    addMeshCap(mesh, chestRings.first().asReversed(), palette.coreFill)
    addMeshCap(mesh, chestRings.last(), palette.coreFill)

    val pelvisTopCenter = hipCenter + torsoUp * (torsoLength * 0.28f)
    val pelvisMidCenter = hipCenter + torsoUp * (torsoLength * 0.15f)
    val pelvisBottomCenter = hipCenter + torsoUp * (torsoLength * 0.02f)
    val pelvisRings = listOf(
        addMeshBoxRing(mesh, pelvisTopCenter + bodyAxes.forward * (pelvisWidth * 0.03f), bodyAxes.side, bodyAxes.forward, pelvisWidth * 0.44f, pelvisWidth * 0.27f),
        addMeshBoxRing(mesh, pelvisMidCenter + bodyAxes.forward * (pelvisWidth * 0.08f), bodyAxes.side, bodyAxes.forward, pelvisWidth * 0.56f, pelvisWidth * 0.36f),
        addMeshBoxRing(mesh, pelvisBottomCenter - bodyAxes.forward * (pelvisWidth * 0.02f), bodyAxes.side, bodyAxes.forward, pelvisWidth * 0.40f, pelvisWidth * 0.26f),
    )
    addMeshStrip(mesh, pelvisRings[0], pelvisRings[1], palette.coreFill)
    addMeshStrip(mesh, pelvisRings[1], pelvisRings[2], palette.coreFill)
    addMeshCap(mesh, pelvisRings[0].asReversed(), palette.coreFill)
    addMeshCap(mesh, pelvisRings[2], palette.coreFill)
    addCoreConnector(
        mesh = mesh,
        pelvisTopCenter = pelvisTopCenter,
        torsoBottomCenter = waistCenter,
        bodyAxes = bodyAxes,
        hipWidth = hipWidth,
        shoulderWidth = shoulderWidth,
        fill = palette.jointFill,
    )

    addJointCap(mesh, neck, bodyAxes, shoulderWidth * 0.12f, palette.jointFill)
    addJointCap(mesh, leftHip - bodyAxes.side * (hipWidth * 0.18f), bodyAxes, KneeAndHipJointCapRadius, palette.jointFill)
    addJointCap(mesh, rightHip + bodyAxes.side * (hipWidth * 0.18f), bodyAxes, KneeAndHipJointCapRadius, palette.jointFill)
    addJointCap(mesh, leftShoulder - bodyAxes.side * (shoulderWidth * 0.07f), bodyAxes, shoulderWidth * 0.14f, palette.jointFill)
    addJointCap(mesh, rightShoulder + bodyAxes.side * (shoulderWidth * 0.07f), bodyAxes, shoulderWidth * 0.14f, palette.jointFill)
    addNeckConnector(mesh, neck, chestTopCenter, bodyAxes, torsoLength, shoulderWidth, palette.jointFill)
    addHeadVolume(mesh, neck, head, bodyAxes, shoulderWidth, palette.headFill)

    SkeletonLimbs.forEach { limb ->
        val start = joints[limb.startName]
        val end = joints[limb.endName]
        if (start != null && end != null) {
            addMeshSegment(
                mesh = mesh,
                start = start,
                end = end,
                bodyAxes = bodyAxes,
                startWidth = limb.profile.startWidth,
                endWidth = limb.profile.endWidth,
                depthScale = limb.profile.depthScale,
                sides = 4,
                fill = palette.limbFill,
                startInset = jointCapClearance(limb.startName, limb.profile.startWidth),
                endInset = jointCapClearance(limb.endName, limb.profile.endWidth),
            )
        }
    }
    addMeshSegmentFromNames(mesh, joints, "left_wrist", "left_hand", bodyAxes, 0.050f, 0.056f, 0.32f, palette.jointFill)
    addMeshSegmentFromNames(mesh, joints, "right_wrist", "right_hand", bodyAxes, 0.050f, 0.056f, 0.32f, palette.jointFill)
    val leftShoeAdded = addShoeBlockFromNames(mesh, joints, "left_ankle", "left_foot", bodyAxes, footScale, palette)
    val rightShoeAdded = addShoeBlockFromNames(mesh, joints, "right_ankle", "right_foot", bodyAxes, footScale, palette)
    addJointCapAtNames(mesh, joints, "left_elbow", bodyAxes, 0.046f, palette.jointFill)
    addJointCapAtNames(mesh, joints, "right_elbow", bodyAxes, 0.046f, palette.jointFill)
    addJointCapAtNames(mesh, joints, "left_knee", bodyAxes, KneeAndHipJointCapRadius, palette.jointFill)
    addJointCapAtNames(mesh, joints, "right_knee", bodyAxes, KneeAndHipJointCapRadius, palette.jointFill)
    addJointCapAtNames(
        mesh = mesh,
        joints = joints,
        jointName = "left_ankle",
        bodyAxes = bodyAxes,
        radius = if (leftShoeAdded) VisibleShoeAnkleJointCapRadius else AnkleJointCapRadius,
        fill = palette.jointFill,
    )
    addJointCapAtNames(
        mesh = mesh,
        joints = joints,
        jointName = "right_ankle",
        bodyAxes = bodyAxes,
        radius = if (rightShoeAdded) VisibleShoeAnkleJointCapRadius else AnkleJointCapRadius,
        fill = palette.jointFill,
    )
    return mesh
}

private fun addMeshSegmentFromNames(
    mesh: GeneratedLowPolyMesh,
    joints: Map<String, WearSkeletonVec3>,
    startName: String,
    endName: String,
    bodyAxes: BodyAxes,
    startWidth: Float,
    endWidth: Float,
    depthScale: Float,
    fill: Color,
) {
    val start = joints[startName] ?: return
    val end = joints[endName] ?: return
    addMeshSegment(mesh, start, end, bodyAxes, startWidth, endWidth, depthScale, 4, fill)
}

private fun jointCapClearance(
    jointName: String,
    limbWidth: Float,
): Float {
    return if (jointName in VisibleJointCapNames) {
        when (jointName) {
            "left_hip", "right_hip" -> limbWidth * 0.46f
            "left_shoulder", "right_shoulder" -> limbWidth * 0.32f
            "left_ankle", "right_ankle" -> limbWidth * 0.44f
            else -> limbWidth * 0.20f
        }
    } else {
        0f
    }
}

private data class ShoeProfilePoint(
    val center: WearSkeletonVec3,
    val halfWidthScale: Float,
)

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
    val horizontalFoot = footVector - worldUp * footVector.dot(worldUp)
    val horizontalLength = horizontalFoot.length()
    val bodyForward = bodyAxes.forward - worldUp * bodyAxes.forward.dot(worldUp)
    val stableForward = bodyForward.normalizedOr(WearSkeletonVec3(0f, 0f, 1f))
    val footForward = if (horizontalLength > 0.0001f) {
        horizontalFoot * (1f / horizontalLength)
    } else {
        stableForward
    }
    val fallbackSide = (bodyAxes.side - worldUp * bodyAxes.side.dot(worldUp)).normalizedOr(bodyAxes.side)
    val footSide = worldUp.cross(footForward).normalizedOr(fallbackSide)
    val shoeUp = worldUp
    val shoeScale = if (horizontalLength > 0.0001f) {
        horizontalLength
    } else {
        footScale * 0.60f
    }
    val length = max(shoeScale * 1.12f, footScale * 0.45f)
    val halfWidth = max(shoeScale * 0.20f, footScale * 0.12f)
    val height = max(shoeScale * 0.24f, footScale * 0.14f)
    val profile = listOf(
        ShoeProfilePoint(
            center = ankle - footForward * (length * 0.04f) - shoeUp * (height * 0.38f),
            halfWidthScale = 0.70f,
        ),
        ShoeProfilePoint(
            center = ankle + footForward * (length * 0.14f) - shoeUp * (height * 0.62f),
            halfWidthScale = 0.95f,
        ),
        ShoeProfilePoint(
            center = ankle + footForward * (length * 0.84f) - shoeUp * (height * 0.62f),
            halfWidthScale = 1.00f,
        ),
        ShoeProfilePoint(
            center = ankle + footForward * (length * 1.02f) - shoeUp * (height * 0.30f),
            halfWidthScale = 0.78f,
        ),
        ShoeProfilePoint(
            center = ankle + footForward * (length * 0.82f) + shoeUp * (height * 0.10f),
            halfWidthScale = 0.88f,
        ),
        ShoeProfilePoint(
            center = ankle + footForward * (length * 0.08f) + shoeUp * (height * 0.12f),
            halfWidthScale = 0.74f,
        ),
    )
    val outerSide = profile.map { point ->
        addMeshVertex(mesh, point.center + footSide * (halfWidth * point.halfWidthScale))
    }
    val innerSide = profile.map { point ->
        addMeshVertex(mesh, point.center - footSide * (halfWidth * point.halfWidthScale))
    }

    val fill = palette.limbFill
    mesh.faces += GeneratedLowPolyFace(outerSide, fill)
    mesh.faces += GeneratedLowPolyFace(innerSide.asReversed(), fill)
    for (index in profile.indices) {
        val next = (index + 1) % profile.size
        mesh.faces += GeneratedLowPolyFace(
            listOf(innerSide[index], innerSide[next], outerSide[next], outerSide[index]),
            fill,
        )
    }
    return true
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

private fun addCoreConnector(
    mesh: GeneratedLowPolyMesh,
    pelvisTopCenter: WearSkeletonVec3,
    torsoBottomCenter: WearSkeletonVec3,
    bodyAxes: BodyAxes,
    hipWidth: Float,
    shoulderWidth: Float,
    fill: Color,
) {
    val span = torsoBottomCenter - pelvisTopCenter
    if (span.length() <= 0.0001f) {
        return
    }
    val lowerCenter = pelvisTopCenter - span * 0.12f
    val upperCenter = torsoBottomCenter + span * 0.12f
    val baseWidth = max(hipWidth * 1.10f, shoulderWidth * 0.62f)
    val lowerRing = addMeshBoxRing(
        mesh = mesh,
        center = lowerCenter + bodyAxes.forward * (baseWidth * 0.02f),
        side = bodyAxes.side,
        depth = bodyAxes.forward,
        halfWidth = baseWidth * 0.22f,
        halfDepth = baseWidth * 0.15f,
    )
    val upperRing = addMeshBoxRing(
        mesh = mesh,
        center = upperCenter + bodyAxes.forward * (baseWidth * 0.02f),
        side = bodyAxes.side,
        depth = bodyAxes.forward,
        halfWidth = baseWidth * 0.24f,
        halfDepth = baseWidth * 0.16f,
    )
    addMeshStrip(mesh, lowerRing, upperRing, fill)
}

private fun addNeckConnector(
    mesh: GeneratedLowPolyMesh,
    neck: WearSkeletonVec3,
    torsoTopCenter: WearSkeletonVec3,
    bodyAxes: BodyAxes,
    torsoLength: Float,
    shoulderWidth: Float,
    fill: Color,
) {
    val span = neck - torsoTopCenter
    val height = max(max(torsoLength * 0.10f, shoulderWidth * 0.22f), span.length() * 1.25f)
    val lower = addMeshBoxRing(
        mesh = mesh,
        center = torsoTopCenter - bodyAxes.up * (height * 0.10f),
        side = bodyAxes.side,
        depth = bodyAxes.forward,
        halfWidth = shoulderWidth * 0.120f,
        halfDepth = shoulderWidth * 0.085f,
    )
    val upper = addMeshBoxRing(
        mesh = mesh,
        center = neck + bodyAxes.up * (height * 0.26f),
        side = bodyAxes.side,
        depth = bodyAxes.forward,
        halfWidth = shoulderWidth * 0.095f,
        halfDepth = shoulderWidth * 0.070f,
    )
    addMeshStrip(mesh, lower, upper, fill)
    addMeshCap(mesh, upper, fill)
}

private fun addHeadVolume(
    mesh: GeneratedLowPolyMesh,
    neck: WearSkeletonVec3,
    head: WearSkeletonVec3,
    bodyAxes: BodyAxes,
    shoulderWidth: Float,
    fill: Color,
) {
    val segment = head - neck
    val height = segment.length()
    if (height <= 0.0001f) {
        return
    }
    val up = bodyAxes.up
    val side = bodyAxes.side
    val depth = bodyAxes.forward
    val scale = max(shoulderWidth, height)
    val headHeight = max(height * 1.75f, scale * 0.54f)
    val headWidth = max(height * 1.04f, scale * 0.46f)
    val headDepth = headWidth * 0.84f
    val base = neck + up * (headHeight * 0.06f)
    val center = base + up * (headHeight * 0.44f)
    val rings = listOf(
        addMeshBoxRing(mesh, base, side, depth, headWidth * 0.34f, headDepth * 0.34f),
        addMeshBoxRing(mesh, center, side, depth, headWidth * 0.52f, headDepth * 0.52f),
        addMeshBoxRing(mesh, base + up * headHeight, side, depth, headWidth * 0.44f, headDepth * 0.44f),
    )
    addMeshStrip(mesh, rings[0], rings[1], fill)
    addMeshStrip(mesh, rings[1], rings[2], fill)
    addMeshCap(mesh, rings[0].asReversed(), fill)
    addMeshCap(mesh, rings[2], fill)
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
) {
    val segment = end - start
    val length = segment.length()
    if (length <= 0.0001f) {
        return
    }
    val direction = segment * (1f / length)
    val maxInset = length * 0.10f
    val safeStart = start + direction * min(startInset, maxInset)
    val safeEnd = end - direction * min(endInset, maxInset)
    if ((safeEnd - safeStart).length() <= 0.0001f) {
        return
    }
    val side = stableLimbSide(direction, bodyAxes)
    val depth = direction.cross(side).normalizedOr(bodyAxes.forward)
    val startRing = addMeshSegmentRing(mesh, safeStart, side, depth, startWidth, depthScale, sides)
    val endRing = addMeshSegmentRing(mesh, safeEnd, side, depth, endWidth, depthScale, sides)
    addMeshStrip(mesh, startRing, endRing, fill)
    addMeshCap(mesh, startRing.asReversed(), fill)
    addMeshCap(mesh, endRing, fill)
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
        center = center - up * (radius * 0.35f),
        side = side,
        depth = depth,
        halfWidth = radius * 0.82f,
        halfDepth = radius * 0.70f,
        sides = 6,
    )
    val upperRing = addMeshRing(
        mesh = mesh,
        center = center + up * (radius * 0.35f),
        side = side,
        depth = depth,
        halfWidth = radius * 0.88f,
        halfDepth = radius * 0.74f,
        sides = 6,
    )
    addMeshFan(mesh, bottom, lowerRing.asReversed(), fill)
    addMeshStrip(mesh, lowerRing, upperRing, fill)
    addMeshFan(mesh, top, upperRing, fill)
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
    if (ring.size >= 3) {
        mesh.faces += GeneratedLowPolyFace(ring, fill)
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
