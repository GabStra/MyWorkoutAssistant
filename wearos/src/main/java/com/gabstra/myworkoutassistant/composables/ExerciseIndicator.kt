package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.key
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.CircularProgressIndicator
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ProgressIndicatorDefaults
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import java.util.UUID
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin

private fun computeEdgeDotsReserveDeg(
    ringRadiusPx: Float,
    dotDiameterPx: Float,
    gapDeg: Float,
    paddingDeg: Float,
    arcStrokeWidthPx: Float = 0f,
    includePadding: Boolean = true,
    includeStrokeClearance: Boolean = false
): Float {
    if (ringRadiusPx <= 0f) return 0f
    val x = (dotDiameterPx / (4f * ringRadiusPx)).coerceIn(0f, 1f)
    val halfDotDeg = Math.toDegrees(2.0 * kotlin.math.asin(x.toDouble())).toFloat()
    val strokeHalfDeg = if (includeStrokeClearance && arcStrokeWidthPx > 0f) {
        Math.toDegrees(kotlin.math.atan2(arcStrokeWidthPx / 2f, ringRadiusPx).toDouble()).toFloat()
    } else 0f
    val padding = if (includePadding) paddingDeg else 0f
    return 3f * gapDeg + padding + 2f * halfDotDeg + 2f * strokeHalfDeg
}

@OptIn(ExperimentalHorologistApi::class)
@Composable
fun ExerciseIndicator(
    viewModel: AppViewModel,
    set: WorkoutState.Set,
    selectedExerciseId: UUID? = null
) {
    // --- Flattened order: every exercise once; supersets kept contiguous ---
    val exerciseIds = remember { viewModel.setsByExerciseId.keys.toList() }
    val flatExerciseOrder = remember(exerciseIds, viewModel.supersetIdByExerciseId) {
        val seenSupers = mutableSetOf<UUID>()
        buildList {
            exerciseIds.forEach { eid ->
                val sid = viewModel.supersetIdByExerciseId[eid]
                if (sid != null) {
                    if (seenSupers.add(sid)) {
                        addAll(exerciseIds.filter { viewModel.supersetIdByExerciseId[it] == sid })
                    }
                } else add(eid)
            }
        }
    }
    val globalIndexByExerciseId = remember(flatExerciseOrder) {
        flatExerciseOrder.withIndex().associate { (i, eid) -> eid to i }
    }
    val exerciseCount = flatExerciseOrder.size

    // Focus (by selected or current)
    val focusId = selectedExerciseId?.takeIf { flatExerciseOrder.contains(it) } ?: set.exerciseId
    val focusIdx = globalIndexByExerciseId[focusId] ?: 0
    val currentGlobalIdx = globalIndexByExerciseId[set.exerciseId] ?: 0

    // --- Sliding window over FLAT list (no wrap) ---
    val maxVisible = 10
    val visibleCount = minOf(exerciseCount, maxVisible)
    val half = visibleCount / 2
    val startIdx = maxOf(0, minOf(focusIdx - half, exerciseCount - visibleCount))
    val endIdx = startIdx + visibleCount - 1
    val visibleIndices = (startIdx..endIdx).toList()

    // --- Edge overflow (dots) & angles ---
    val hiddenLeft = startIdx
    val hiddenRight = (exerciseCount - 1) - endIdx
    val showLeftDots = hiddenLeft > 0
    val showRightDots = hiddenRight > 0

    val startingAngle = -60f
    val totalArcAngle = 120f
    val paddingAngle = 2f

    val dotAngleGapDeg = 4f
    val dotSpan = 2 * dotAngleGapDeg
    val dotsReserve = dotSpan + dotAngleGapDeg + paddingAngle

    val leftReserve = if (showLeftDots) dotsReserve else 0f
    val rightReserve = if (showRightDots) dotsReserve else 0f

    val startAngleEffective = startingAngle + leftReserve
    val totalArcEffective = totalArcAngle - leftReserve - rightReserve
    val segmentArcAngle = (totalArcEffective - (visibleCount - 1) * paddingAngle) / visibleCount

    @Composable
    fun ShowRotatingIndicator(exerciseId: UUID) {
        val idx = globalIndexByExerciseId[exerciseId] ?: return
        val posInWindow = if (idx in startIdx..endIdx) idx - startIdx else -1
        if (posInWindow >= 0) {
            val baseStart = startAngleEffective + posInWindow * (segmentArcAngle + paddingAngle)
            val mid = baseStart + segmentArcAngle / 2f
            RotatingIndicator(mid, MaterialTheme.colorScheme.onBackground)
        }
    }

    Box(modifier = Modifier.fillMaxSize().padding(10.dp)) {
        // --- OUTER RING for visible superset ranges (drawn first) ---
        OuterSupersetOverlay(
            visibleIndices = visibleIndices,
            flatExerciseOrder = flatExerciseOrder,
            supersetIdByExerciseId = viewModel.supersetIdByExerciseId,
            startAngleEffective = startAngleEffective,
            segmentArcAngle = segmentArcAngle,
            paddingAngle = paddingAngle,
            ringInset = 1.dp,
            strokeWidth = 2.dp,
            tickWidth = 2.dp,
            tickLength = 4.dp,
            arcColor = MaterialTheme.colorScheme.onBackground,
            badgeColor = MaterialTheme.colorScheme.onBackground
        )
    }

    Box(modifier = Modifier.fillMaxSize()) {
        // --- INNER segments: every exercise gets same arc ---
        visibleIndices.forEachIndexed { posInWindow, globalIdx ->
            val eid = flatExerciseOrder[globalIdx]
            val eIdx = globalIndexByExerciseId[eid] ?: Int.MAX_VALUE
            val isCurrent = eIdx == currentGlobalIdx
            val isCompleted = eIdx < currentGlobalIdx

            val indicatorColor =
                if (isCurrent) MaterialTheme.colorScheme.primary
                else MaterialTheme.colorScheme.primary.copy(alpha = 0.65f)

            val indicatorProgress = if (isCompleted || isCurrent) 1f else 0f

            val startA = startAngleEffective + posInWindow * (segmentArcAngle + paddingAngle)
            val endA = startA + segmentArcAngle

            key(eid) {
                CircularProgressIndicator(
                    colors = ProgressIndicatorDefaults.colors(indicatorColor = indicatorColor),
                    progress = { indicatorProgress },
                    modifier = Modifier.fillMaxSize(),
                    strokeWidth = 4.dp,
                    startAngle = startA,
                    endAngle = endA,
                    gapSize = 0.dp
                )
            }
        }

        // Edge dots (global)
        val minVisibleIndex = visibleIndices.first()
        EdgeOverflowDots(
            angleDeg = startingAngle + (dotsReserve / 2),
            show = showLeftDots,
            dotAngleGapDeg = dotAngleGapDeg,
            color = when {
                minVisibleIndex > currentGlobalIdx -> MaterialTheme.colorScheme.primary
                minVisibleIndex == currentGlobalIdx -> MaterialTheme.colorScheme.primary.copy(alpha = 0.65f)
                else -> MaterialTheme.colorScheme.surfaceContainer
            }
        )
        EdgeOverflowDots(
            angleDeg = startingAngle + totalArcAngle - (dotSpan + dotAngleGapDeg + paddingAngle) / 2f,
            show = showRightDots,
            dotAngleGapDeg = dotAngleGapDeg
        )


    }

    Box(modifier = Modifier.fillMaxSize().padding(6.dp)) {
        if (selectedExerciseId != null && flatExerciseOrder.contains(selectedExerciseId)) {
            ShowRotatingIndicator(selectedExerciseId)
        } else {
            ShowRotatingIndicator(set.exerciseId)
        }
    }

}


/* ===== Helpers ===== */
@Composable
private fun EdgeOverflowDots(
    angleDeg: Float,
    show: Boolean,
    ringInset: Dp = 2.dp,      // ≈ strokeWidth / 2 of your arcs
    radialGap: Dp = 0.dp,      // extra distance outside the ring
    dotSize: Dp = 3.dp,        // dot diameter
    dotAngleGapDeg: Float = 6f,
    color: Color = MaterialTheme.colorScheme.surfaceContainer
) {
    if (!show) return
    Canvas(Modifier.fillMaxSize()) {
        val cx = size.width / 2f
        val cy = size.height / 2f
        val ringRadius = min(size.width, size.height) / 2f - ringInset.toPx()
        val r = ringRadius + radialGap.toPx()
        val dotR = dotSize.toPx() / 2f
        for (k in -1..1) {
            val theta = Math.toRadians((angleDeg + k * dotAngleGapDeg).toDouble())
            val x = cx + r * cos(theta).toFloat()
            val y = cy + r * sin(theta).toFloat()
            drawCircle(color = color, radius = dotR, center = Offset(x, y))
        }
    }
}

@Composable
private fun OuterSupersetOverlay(
    visibleIndices: List<Int>,
    flatExerciseOrder: List<UUID>,
    supersetIdByExerciseId: Map<UUID, UUID>,
    startAngleEffective: Float,
    segmentArcAngle: Float,
    paddingAngle: Float,
    ringInset: Dp,
    strokeWidth: Dp,
    tickWidth: Dp,
    tickLength: Dp,
    arcColor: Color,
    badgeColor: Color,
    dotAngleGapDeg: Float = 4f
) {
    // Build contiguous ranges by superset (include singletons)
    val ranges = remember(visibleIndices, flatExerciseOrder, supersetIdByExerciseId) {
        val local = mutableListOf<Triple<Int, Int, UUID>>() // startLocal, endLocal, supersetId
        val ids = visibleIndices.map { flatExerciseOrder[it] }
        var i = 0
        while (i < ids.size) {
            val sid = supersetIdByExerciseId[ids[i]]
            if (sid == null) { i++; continue }
            var j = i
            while (j + 1 < ids.size && supersetIdByExerciseId[ids[j + 1]] == sid) j++
            local += Triple(i, j, sid) // NOTE: include singletons
            i = j + 1
        }
        local.toList()
    }
    if (ranges.isEmpty()) return

    // Local dot sizing/reserve to keep (arc + dots) == raw group sweep
    val dotSpan = 2f * dotAngleGapDeg
    val dotsReserve = dotSpan + dotAngleGapDeg + paddingAngle
    val dotsRingInsetForOverlay = ringInset + (strokeWidth / 2f) // place dots on overlay's arc centerline

    BoxWithConstraints(Modifier.fillMaxSize()) {
        val density = LocalDensity.current
        val wPx = with(density) { maxWidth.toPx() }
        val hPx = with(density) { maxHeight.toPx() }
        val ringInsetPx = with(density) { ringInset.toPx() }
        val strokePx = with(density) { strokeWidth.toPx() }
        val tickPx = with(density) { tickWidth.toPx() }
        val tickLengthPx = with(density) { tickLength.toPx() }

        val cx = wPx / 2f
        val cy = hPx / 2f
        val baseR = min(wPx, hPx) / 2f - ringInsetPx
        val r = baseR - strokePx / 2f

        // 1) Draw the outer arcs (with truncation reserves for dots)
        Canvas(Modifier.fillMaxSize()) {
            ranges.forEach { (startLocal, endLocal, sid) ->
                val segCount = (endLocal - startLocal + 1)

                val globalStart = visibleIndices[startLocal]
                val globalEnd = visibleIndices[endLocal]

                val startsBeforeWindow =
                    globalStart > 0 &&
                            supersetIdByExerciseId[flatExerciseOrder[globalStart - 1]] == sid
                val endsAfterWindow =
                    globalEnd < flatExerciseOrder.lastIndex &&
                            supersetIdByExerciseId[flatExerciseOrder[globalEnd + 1]] == sid

                val groupStartRaw = startAngleEffective +
                        (globalStart - visibleIndices.first()) * (segmentArcAngle + paddingAngle)
                val groupSweepRaw =
                    segCount * segmentArcAngle + (segCount - 1) * paddingAngle

                val offset = .5f

                val startA = groupStartRaw + offset
                val sweep = groupSweepRaw.coerceAtLeast(0f) -(offset*2)

                drawArc(
                    color = arcColor,
                    startAngle = startA,
                    sweepAngle = sweep,
                    useCenter = false,
                    topLeft = Offset(cx - r, cy - r),
                    size = Size(r * 2, r * 2),
                    style = Stroke(width = strokePx, cap = StrokeCap.Butt)
                )

                val tickLen = strokePx
                val innerR = r - tickLen / 2f
                val outerR = r + tickLen / 2f + tickLengthPx

                fun drawTick(atAngle: Float) {
                    val rad = Math.toRadians(atAngle.toDouble())
                    val sx = cx + innerR * cos(rad).toFloat()
                    val sy = cy + innerR * sin(rad).toFloat()
                    val ex = cx + outerR * cos(rad).toFloat()
                    val ey = cy + outerR * sin(rad).toFloat()
                    drawLine(
                        color = arcColor,
                        start = Offset(sx, sy),
                        end = Offset(ex, ey),
                        strokeWidth = tickPx,
                        cap = StrokeCap.Butt
                    )
                }

                if (!startsBeforeWindow && sweep > 0f) {
                    // tick at group start (visible boundary)
                    drawTick(startA)
                }
                if (!endsAfterWindow && sweep > 0f) {
                    // tick at group end (visible boundary)
                    drawTick(startA + sweep)
                }
            }
        }

        // 2) Truncation dots at overlay edges (consume the same reserve we subtracted above)
        ranges.forEach { (startLocal, endLocal, sid) ->
            val segCount = (endLocal - startLocal + 1)
            val globalStart = visibleIndices[startLocal]
            val globalEnd = visibleIndices[endLocal]

            val startsBeforeWindow =
                globalStart > 0 &&
                        supersetIdByExerciseId[flatExerciseOrder[globalStart - 1]] == sid
            val endsAfterWindow =
                globalEnd < flatExerciseOrder.lastIndex &&
                        supersetIdByExerciseId[flatExerciseOrder[globalEnd + 1]] == sid

            if (!startsBeforeWindow && !endsAfterWindow) return@forEach

            val groupStartRaw = startAngleEffective +
                    (globalStart - visibleIndices.first()) * (segmentArcAngle + paddingAngle)
            val groupSweepRaw =
                segCount * segmentArcAngle + (segCount - 1) * paddingAngle


            // Left overlay dots (centered within its reserve)
            EdgeOverflowDots(
                angleDeg = groupStartRaw + dotsReserve / 2f,
                show = startsBeforeWindow,
                ringInset = dotsRingInsetForOverlay,
                dotAngleGapDeg = dotAngleGapDeg,
                color = arcColor,
            )

            // Right overlay dots (mirrors global formula)
            EdgeOverflowDots(
                angleDeg = groupStartRaw + groupSweepRaw + (dotSpan + dotAngleGapDeg + paddingAngle) / 2f,
                show = endsAfterWindow,
                ringInset = dotsRingInsetForOverlay,
                dotAngleGapDeg = dotAngleGapDeg,
                color = arcColor,
            )
        }

        // 3) Superset badge at the first visible join (only if at least 2 visible in the block)
        ranges.forEach { (startLocal, endLocal, _) ->
            val segCount = (endLocal - startLocal + 1)
            //if (segCount < 2) return@forEach

            val globalStart = visibleIndices[startLocal]

            val groupStartRaw = startAngleEffective +
                    (globalStart - visibleIndices.first()) * (segmentArcAngle + paddingAngle)
            val groupSweepRaw =
                segCount * segmentArcAngle + (segCount - 1) * paddingAngle

            val startA = groupStartRaw
            val sweep = (groupSweepRaw).coerceAtLeast(0f)

            val joinAngle = startA + (sweep / 2f)

            SupersetBadge(
                angleDeg = joinAngle,
                outerRadius = r,
                tint = badgeColor,
                iconSize = 15.dp,
                rotateClockwiseTangent = true
            )
        }
    }
}

@Composable
private fun SupersetBadge(
    angleDeg: Float,
    outerRadius: Float,                    // in px (same as before)
    iconSize: Dp = 15.dp,
    tint: Color = Color.Unspecified,
    rotateClockwiseTangent: Boolean = true // perpendicular to radius, along tangent
) {
    BoxWithConstraints(Modifier.fillMaxSize()) {
        val density = LocalDensity.current
        val wPx = with(density) { maxWidth.toPx() }
        val hPx = with(density) { maxHeight.toPx() }
        val iconPx = with(density) { iconSize.toPx() +(1.dp.toPx())}

        val cx = wPx / 2f
        val cy = hPx / 2f
        val theta = Math.toRadians(angleDeg.toDouble())
        val x = cx + outerRadius * cos(theta).toFloat()
        val y = cy + outerRadius * sin(theta).toFloat()

        val rotation = angleDeg + if (rotateClockwiseTangent) 90f else -90f

        Box(modifier = Modifier
            .graphicsLayer {
                translationX = x - iconPx / 2f
                translationY = y - iconPx / 2f
            }
            .size(iconSize + 1.dp)
            .clip(CircleShape)
            .background(MaterialTheme.colorScheme.background),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                painter = painterResource(R.drawable.baseline_link_24),
                contentDescription = null,
                tint = tint,
                modifier = Modifier
                    .size(iconSize)
                    .graphicsLayer {
                        rotationZ = rotation
                    }
            )
        }
    }
}
