package com.gabstra.myworkoutassistant.composables

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.AnimationSpec
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.StartOffset
import androidx.compose.animation.core.TweenSpec
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.repeatable
import androidx.compose.animation.core.tween
import androidx.compose.foundation.MarqueeAnimationMode
import androidx.compose.foundation.MarqueeDefaults
import androidx.compose.foundation.MarqueeSpacing
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Stable
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Modifier
import androidx.compose.ui.MotionDurationScale
import androidx.compose.ui.focus.FocusEventModifierNode
import androidx.compose.ui.focus.FocusState
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.ContentDrawScope
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.graphics.layer.GraphicsLayer
import androidx.compose.ui.graphics.layer.drawLayer
import androidx.compose.ui.layout.IntrinsicMeasurable
import androidx.compose.ui.layout.IntrinsicMeasureScope
import androidx.compose.ui.layout.Measurable
import androidx.compose.ui.layout.MeasureResult
import androidx.compose.ui.layout.MeasureScope
import androidx.compose.ui.node.DrawModifierNode
import androidx.compose.ui.node.LayoutModifierNode
import androidx.compose.ui.node.ModifierNodeElement
import androidx.compose.ui.node.requireDensity
import androidx.compose.ui.node.requireGraphicsContext
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.constrainWidth
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlin.math.absoluteValue
import kotlin.math.ceil
import kotlin.math.roundToInt

@Stable
class TrackableMarqueeState internal constructor() {
    /** The actual translateX applied to the content when drawing (same value passed to translate(left = ...)). */
    @Volatile var translationXPx: Float = 0f
        internal set

    /** The internal clip-window offset used by the marquee algorithm (translationXPx == -clipWindowOffsetPx). */
    @Volatile var clipWindowOffsetPx: Float = 0f
        internal set

    @Volatile var contentWidthPx: Int = 0
        internal set

    @Volatile var containerWidthPx: Int = 0
        internal set

    @Volatile var spacingPx: Int = 0
        internal set

    /** True when the left edge is currently cutting through actual content (not at content boundary, not in spacing). */
    @Volatile var leftEdgeClipsContent: Boolean = false
        internal set

    /** True when the right edge is currently cutting through actual content (not at content boundary, not in spacing). */
    @Volatile var rightEdgeClipsContent: Boolean = false
        internal set
}

@Composable
fun rememberTrackableMarqueeState(): TrackableMarqueeState = remember { TrackableMarqueeState() }

fun Modifier.trackableMarquee(
    state: TrackableMarqueeState,
    iterations: Int = MarqueeDefaults.Iterations,
    animationMode: MarqueeAnimationMode = MarqueeAnimationMode.Immediately,
    repeatDelayMillis: Int = MarqueeDefaults.RepeatDelayMillis,
    initialDelayMillis: Int = if (animationMode == MarqueeAnimationMode.Immediately) repeatDelayMillis else 0,
    spacing: MarqueeSpacing = MarqueeDefaults.Spacing,
    velocity: Dp = MarqueeDefaults.Velocity,
    // NEW: optional edge fades drawn inside the marquee node so they update every frame.
    edgeFadeWidth: Dp = 0.dp,
    edgeFadeColor: Color = Color.Unspecified,
): Modifier =
    this.then(
        TrackableMarqueeElement(
            state = state,
            iterations = iterations,
            animationMode = animationMode,
            delayMillis = repeatDelayMillis,
            initialDelayMillis = initialDelayMillis,
            spacing = spacing,
            velocity = velocity,
            edgeFadeWidth = edgeFadeWidth,
            edgeFadeColor = edgeFadeColor,
        )
    )

private data class TrackableMarqueeElement(
    val state: TrackableMarqueeState,
    val iterations: Int,
    val animationMode: MarqueeAnimationMode,
    val delayMillis: Int,
    val initialDelayMillis: Int,
    val spacing: MarqueeSpacing,
    val velocity: Dp,
    val edgeFadeWidth: Dp,
    val edgeFadeColor: Color,
) : ModifierNodeElement<TrackableMarqueeNode>() {
    override fun create(): TrackableMarqueeNode =
        TrackableMarqueeNode(
            state = state,
            iterations = iterations,
            animationMode = animationMode,
            delayMillis = delayMillis,
            initialDelayMillis = initialDelayMillis,
            spacing = spacing,
            velocity = velocity,
            edgeFadeWidth = edgeFadeWidth,
            edgeFadeColor = edgeFadeColor,
        )

    override fun update(node: TrackableMarqueeNode) {
        node.update(
            state = state,
            iterations = iterations,
            animationMode = animationMode,
            delayMillis = delayMillis,
            initialDelayMillis = initialDelayMillis,
            spacing = spacing,
            velocity = velocity,
            edgeFadeWidth = edgeFadeWidth,
            edgeFadeColor = edgeFadeColor,
        )
    }
}

private class TrackableMarqueeNode(
    private var state: TrackableMarqueeState,
    private var iterations: Int,
    animationMode: MarqueeAnimationMode,
    private var delayMillis: Int,
    private var initialDelayMillis: Int,
    spacing: MarqueeSpacing,
    private var velocity: Dp,
    private var edgeFadeWidth: Dp,
    private var edgeFadeColor: Color,
) : Modifier.Node(), LayoutModifierNode, DrawModifierNode, FocusEventModifierNode {

    private var contentWidth by mutableIntStateOf(0)
    private var containerWidth by mutableIntStateOf(0)
    private var hasFocus by mutableStateOf(false)
    private var animationJob: Job? = null
    private var marqueeLayer: GraphicsLayer? = null

    private var spacingImpl: MarqueeSpacing by mutableStateOf(spacing)
    private var animationModeImpl: MarqueeAnimationMode by mutableStateOf(animationMode)

    private val offset = Animatable(0f)

    private val spacingPx by derivedStateOf {
        with(spacingImpl) { requireDensity().calculateSpacing(contentWidth, containerWidth) }
    }

    override fun onAttach() {
        marqueeLayer?.let { requireGraphicsContext().releaseGraphicsLayer(it) }
        marqueeLayer = requireGraphicsContext().createGraphicsLayer()
        restartAnimation()
    }

    override fun onDetach() {
        animationJob?.cancel()
        animationJob = null
        marqueeLayer?.let { requireGraphicsContext().releaseGraphicsLayer(it) }
        marqueeLayer = null
    }

    fun update(
        state: TrackableMarqueeState,
        iterations: Int,
        animationMode: MarqueeAnimationMode,
        delayMillis: Int,
        initialDelayMillis: Int,
        spacing: MarqueeSpacing,
        velocity: Dp,
        edgeFadeWidth: Dp,
        edgeFadeColor: Color,
    ) {
        this.state = state
        this.spacingImpl = spacing
        this.animationModeImpl = animationMode
        this.edgeFadeWidth = edgeFadeWidth
        this.edgeFadeColor = edgeFadeColor

        if (
            this.iterations != iterations ||
            this.delayMillis != delayMillis ||
            this.initialDelayMillis != initialDelayMillis ||
            this.velocity != velocity
        ) {
            this.iterations = iterations
            this.delayMillis = delayMillis
            this.initialDelayMillis = initialDelayMillis
            this.velocity = velocity
            restartAnimation()
        }
    }

    override fun onFocusEvent(focusState: FocusState) {
        hasFocus = focusState.hasFocus
    }

    override fun MeasureScope.measure(measurable: Measurable, constraints: Constraints): MeasureResult {
        val childConstraints = constraints.copy(maxWidth = Constraints.Infinity)
        val placeable = measurable.measure(childConstraints)

        containerWidth = constraints.constrainWidth(placeable.width)
        contentWidth = placeable.width

        state.containerWidthPx = containerWidth
        state.contentWidthPx = contentWidth
        state.spacingPx = spacingPx

        return layout(containerWidth, placeable.height) {
            placeable.placeWithLayer(0, 0)
        }
    }

    override fun IntrinsicMeasureScope.minIntrinsicWidth(measurable: IntrinsicMeasurable, height: Int): Int = 0

    override fun IntrinsicMeasureScope.maxIntrinsicWidth(measurable: IntrinsicMeasurable, height: Int): Int =
        measurable.maxIntrinsicWidth(height)

    override fun IntrinsicMeasureScope.minIntrinsicHeight(measurable: IntrinsicMeasurable, width: Int): Int =
        measurable.minIntrinsicHeight(Constraints.Infinity)

    override fun IntrinsicMeasureScope.maxIntrinsicHeight(measurable: IntrinsicMeasurable, width: Int): Int =
        measurable.maxIntrinsicHeight(Constraints.Infinity)

    override fun ContentDrawScope.draw() {
        val spacingPxLocal = spacingPx
        val cw = contentWidth
        val vw = containerWidth

        if (cw <= 0 || vw <= 0) return

        // Same clip-window math as basicMarquee:
        val clipWindowOffset =
            if (velocity > 0.dp) {
                when (layoutDirection) {
                    LayoutDirection.Ltr -> offset.value
                    LayoutDirection.Rtl -> -offset.value + cw * 2 + spacingPxLocal - vw
                }
            } else {
                when (layoutDirection) {
                    LayoutDirection.Ltr -> -offset.value + cw + spacingPxLocal
                    LayoutDirection.Rtl -> offset.value + cw - vw
                }
            }

        // Expose translation / offset:
        state.clipWindowOffsetPx = clipWindowOffset
        state.translationXPx = -clipWindowOffset

        // Content ranges: [0, cw] and [cw+spacing, cw+spacing+cw]
        val leftEdge = clipWindowOffset
        val rightEdge = clipWindowOffset + vw
        val eps = 0.5f

        fun isInsideContent(x: Float): Boolean {
            val s = spacingPxLocal.toFloat()
            val w = cw.toFloat()
            val inFirst = x > 0f + eps && x < w - eps
            val inSecondStart = w + s
            val inSecond = x > inSecondStart + eps && x < inSecondStart + w - eps
            return inFirst || inSecond
        }

        val leftClips = isInsideContent(leftEdge)
        val rightClips = isInsideContent(rightEdge)
        state.leftEdgeClipsContent = leftClips
        state.rightEdgeClipsContent = rightClips

        val firstCopyVisible = clipWindowOffset < cw
        val secondCopyVisible = clipWindowOffset + vw > cw + spacingPxLocal
        val secondCopyOffset = (cw + spacingPxLocal).toFloat()
        val drawHeight = size.height

        marqueeLayer?.let { layer ->
            layer.record(size = IntSize(cw, drawHeight.roundToInt())) {
                this@draw.drawContent()
            }
        }

        clipRect(right = vw.toFloat()) {
            // draw marquee content
            translate(left = -clipWindowOffset) {
                val layer = marqueeLayer
                if (layer != null) {
                    if (firstCopyVisible) drawLayer(layer)
                    if (secondCopyVisible) translate(left = secondCopyOffset) { drawLayer(layer) }
                } else {
                    if (firstCopyVisible) this@draw.drawContent()
                    if (secondCopyVisible) translate(left = secondCopyOffset) { this@draw.drawContent() }
                }
            }

            // NEW: draw fades in the same draw pass so they animate correctly.
            if (cw > vw && edgeFadeWidth > 0.dp && edgeFadeColor != Color.Unspecified) {
                val fadeSize = edgeFadeWidth.toPx().coerceAtMost(vw.toFloat() / 2f)

                if (leftClips) {
                    val leftBrush = Brush.horizontalGradient(
                        colors = listOf(edgeFadeColor, edgeFadeColor.copy(alpha = 0f)),
                        startX = 0f,
                        endX = fadeSize
                    )
                    drawRect(
                        brush = leftBrush,
                        topLeft = Offset.Zero,
                        size = Size(fadeSize, size.height)
                    )
                }

                if (rightClips) {
                    val start = vw.toFloat() - fadeSize
                    val rightBrush = Brush.horizontalGradient(
                        colors = listOf(edgeFadeColor.copy(alpha = 0f), edgeFadeColor),
                        startX = start,
                        endX = vw.toFloat()
                    )
                    drawRect(
                        brush = rightBrush,
                        topLeft = Offset(start, 0f),
                        size = Size(fadeSize, size.height)
                    )
                }
            }
        }
    }

    private fun restartAnimation() {
        val oldJob = animationJob
        oldJob?.cancel()
        if (isAttached) {
            animationJob = coroutineScope.launch {
                oldJob?.join()
                runAnimation()
            }
        }
    }

    private suspend fun runAnimation() {
        if (iterations <= 0) return

        withContext(FixedMotionDurationScale) {
            snapshotFlow {
                if (contentWidth <= containerWidth) return@snapshotFlow null
                if (animationModeImpl == MarqueeAnimationMode.WhileFocused && !hasFocus) return@snapshotFlow null
                (contentWidth + spacingPx).toFloat()
            }.collectLatest { contentWithSpacingWidth ->
                if (contentWithSpacingWidth == null) return@collectLatest

                val spec =
                    createMarqueeAnimationSpec(
                        iterations = iterations,
                        targetValue = contentWithSpacingWidth,
                        initialDelayMillis = initialDelayMillis,
                        delayMillis = delayMillis,
                        velocity = velocity,
                        density = requireDensity(),
                    )

                offset.snapTo(0f)
                try {
                    offset.animateTo(contentWithSpacingWidth, spec)
                } finally {
                    offset.snapTo(0f)
                }
            }
        }
    }
}

private fun createMarqueeAnimationSpec(
    iterations: Int,
    targetValue: Float,
    initialDelayMillis: Int,
    delayMillis: Int,
    velocity: Dp,
    density: Density,
): AnimationSpec<Float> {
    val pxPerSec = with(density) { velocity.toPx() }
    val singleSpec =
        velocityBasedTween(
            velocity = pxPerSec.absoluteValue,
            targetValue = targetValue,
            delayMillis = delayMillis,
        )

    val startOffset = StartOffset(-delayMillis + initialDelayMillis)
    return if (iterations == Int.MAX_VALUE) {
        infiniteRepeatable(singleSpec, initialStartOffset = startOffset)
    } else {
        repeatable(iterations, singleSpec, initialStartOffset = startOffset)
    }
}

private fun velocityBasedTween(
    velocity: Float,      // px / sec
    targetValue: Float,   // px
    delayMillis: Int,
): TweenSpec<Float> {
    val pxPerMilli = velocity / 1000f
    return tween(
        durationMillis = ceil(targetValue / pxPerMilli).toInt(),
        easing = LinearEasing,
        delayMillis = delayMillis,
    )
}

private object FixedMotionDurationScale : MotionDurationScale {
    override val scaleFactor: Float get() = 1f
}
