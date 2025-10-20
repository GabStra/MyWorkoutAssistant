package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.key
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.CircularProgressIndicator
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ProgressIndicatorDefaults
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import com.google.android.horologist.composables.ProgressIndicatorSegment
import com.google.android.horologist.composables.SegmentedProgressIndicator
import java.util.UUID
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin

@OptIn(ExperimentalHorologistApi::class)
@Composable
fun ExerciseIndicator(
    viewModel: AppViewModel,
    set: WorkoutState.Set,
    selectedExerciseId: UUID? = null
) {
    // --- Data & grouping ---
    val exerciseIds = remember { viewModel.setsByExerciseId.keys.toList() }
    val exerciseOrSupersetIds = remember {
        exerciseIds.map { id -> viewModel.supersetIdByExerciseId[id] ?: id }.distinct()
    }
    val exerciseCount = exerciseOrSupersetIds.size

    // Focus (for window + pointer) comes from selection when present
    val selectedOrCurrentExerciseId = selectedExerciseId?.takeIf { exerciseIds.contains(it) } ?: set.exerciseId
    val focusGroupId = viewModel.supersetIdByExerciseId[selectedOrCurrentExerciseId] ?: selectedOrCurrentExerciseId
    val focusIdx = exerciseOrSupersetIds.indexOf(focusGroupId)

    // --- Sliding window (clamped, no wrap) over GROUPS ---
    val maxVisible = 5
    val visibleCount = minOf(exerciseCount, maxVisible)
    val half = visibleCount / 2
    val startIdx = maxOf(0, minOf(focusIdx - half, exerciseCount - visibleCount))
    val endIdx = startIdx + visibleCount - 1
    val visibleIndices = (startIdx..endIdx).toList()

    // --- Edge overflow (dots) & angle reservation ---
    val hiddenLeft = startIdx
    val hiddenRight = (exerciseCount - 1) - endIdx
    val showLeftDots = hiddenLeft > 0
    val showRightDots = hiddenRight > 0

    val startingAngle = -60f
    val totalArcAngle = 120f
    val paddingAngle = 2f

    val dotAngleGapDeg = 6f
    val dotSpan = 2 * dotAngleGapDeg
    val dotsReserve = dotSpan + dotAngleGapDeg + paddingAngle

    val leftReserve = if (showLeftDots) dotsReserve else 0f
    val rightReserve = if (showRightDots) dotsReserve else 0f

    val startAngleEffective = startingAngle + leftReserve
    val totalArcEffective = totalArcAngle - leftReserve - rightReserve
    val segmentArcAngle = (totalArcEffective - (visibleCount - 1) * paddingAngle) / visibleCount

    // --- GLOBAL (per-exercise) highlighting order ---
    val flatExerciseOrder = remember(exerciseOrSupersetIds, viewModel.supersetIdByExerciseId, exerciseIds) {
        exerciseOrSupersetIds.flatMap { groupId ->
            val isSuperset = viewModel.supersetIdByExerciseId.containsValue(groupId)
            if (isSuperset) {
                exerciseIds.filter { eid -> viewModel.supersetIdByExerciseId[eid] == groupId }
            } else {
                listOf(groupId) // here groupId is an exerciseId
            }
        }
    }
    val globalIndexByExerciseId = remember(flatExerciseOrder) {
        flatExerciseOrder.withIndex().associate { (i, eid) -> eid to i }
    }
    val currentGlobalIdx = remember( set.exerciseId) { globalIndexByExerciseId[ set.exerciseId] ?: 0 }

    // --- Draw segments (window only) ---
    Box(modifier = Modifier.fillMaxSize()) {
        visibleIndices.forEachIndexed { posInWindow, globalIdx ->
            val groupId = exerciseOrSupersetIds[globalIdx]
            val isSuperset = remember(groupId) { viewModel.supersetIdByExerciseId.containsValue(groupId) }

            val startAngle = startAngleEffective + posInWindow * (segmentArcAngle + paddingAngle)
            val endAngle = startAngle + segmentArcAngle

            if (isSuperset) {
                val dotAngleGapDeg = 3f
                val dotSpan = 2 * dotAngleGapDeg
                val dotsReserve = dotSpan + dotAngleGapDeg + paddingAngle /2

                val supersetExerciseIds =
                    exerciseIds.filter { eid -> viewModel.supersetIdByExerciseId[eid] == groupId }
                val c = supersetExerciseIds.size

                // ---- sub-window within the superset (with its own overflow dots) ----
                val maxSubVisible = 3
                val visibleSubCount = minOf(c, maxSubVisible)

                val selectedOrCurrentInGroup: UUID? =
                    when {
                        selectedExerciseId != null && supersetExerciseIds.contains(selectedExerciseId) -> selectedExerciseId
                        supersetExerciseIds.contains(set.exerciseId) -> set.exerciseId
                        else -> null
                    }

                val focusSubIdx = selectedOrCurrentInGroup?.let { supersetExerciseIds.indexOf(it) } ?: 0
                val halfSub = visibleSubCount / 2
                val startSubIdx = maxOf(0, minOf(focusSubIdx - halfSub, c - visibleSubCount))
                val endSubIdx = startSubIdx + visibleSubCount - 1

                val showLeftSubDots = startSubIdx > 0
                val showRightSubDots = endSubIdx < c - 1

                val leftSubReserve = if (showLeftSubDots) dotsReserve else 0f
                val rightSubReserve = if (showRightSubDots) dotsReserve else 0f

                val subSweep =
                    (segmentArcAngle - leftSubReserve - rightSubReserve - (visibleSubCount - 1) * paddingAngle) /
                            visibleSubCount

                // draw visible sub-segments inside the superset window
                for (sub in startSubIdx..endSubIdx) {
                    val subId = supersetExerciseIds[sub]
                    val eIdx = globalIndexByExerciseId[subId] ?: Int.MAX_VALUE
                    val isCurrent = eIdx == currentGlobalIdx
                    val isCompleted = eIdx < currentGlobalIdx

                    val indicatorColor =
                        if (isCurrent) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.primary.copy(alpha = 0.65f)

                    val indicatorProgress = if (isCompleted || isCurrent) 1f else 0f

                    val sA = startAngle + leftSubReserve + (sub - startSubIdx) * (subSweep + paddingAngle)
                    val eA = sA + subSweep

                    key(subId) {   // note: key by subId to avoid duplicate keys
                        CircularProgressIndicator(
                            colors = ProgressIndicatorDefaults.colors(indicatorColor = indicatorColor),
                            progress = { indicatorProgress },
                            modifier = Modifier.fillMaxSize(),
                            strokeWidth = 4.dp,
                            startAngle = sA,
                            endAngle = eA,
                            gapSize = 0.dp
                        )
                    }
                }

                // inner overflow dots at the superset's edges
                EdgeOverflowDots(
                    angleDeg = startAngle + dotsReserve / 2,
                    show = showLeftSubDots,
                    dotAngleGapDeg = dotAngleGapDeg
                )
                EdgeOverflowDots(
                    angleDeg = endAngle - dotSpan + paddingAngle,
                    show = showRightSubDots,
                    dotAngleGapDeg = dotAngleGapDeg
                )
            } else {
                // non-superset: groupId is the exerciseId
                val eIdx = globalIndexByExerciseId[groupId] ?: Int.MAX_VALUE
                val isCurrent = eIdx == currentGlobalIdx
                val isCompleted = eIdx < currentGlobalIdx

                val indicatorColor =
                    if (isCurrent) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.primary.copy(alpha = 0.65f)

                val indicatorProgress = if (isCompleted || isCurrent) 1f else 0f

                key(groupId) {
                    CircularProgressIndicator(
                        colors = ProgressIndicatorDefaults.colors(indicatorColor = indicatorColor),
                        progress = { indicatorProgress },
                        modifier = Modifier.fillMaxSize(),
                        strokeWidth = 4.dp,
                        startAngle = startAngle,
                        endAngle = endAngle,
                        gapSize = 0.dp
                    )
                }
            }
        }

        val minVisibleIndex = visibleIndices.first()

        EdgeOverflowDots(
            angleDeg = startingAngle + dotsReserve / 2,
            show = showLeftDots,
            dotAngleGapDeg = dotAngleGapDeg,
            color = when {
                minVisibleIndex > currentGlobalIdx -> MaterialTheme.colorScheme.primary
                minVisibleIndex == currentGlobalIdx -> MaterialTheme.colorScheme.primary.copy(alpha = 0.65f)
                else ->  MaterialTheme.colorScheme.surfaceContainer
            }
        )

        EdgeOverflowDots(
            angleDeg = startingAngle + totalArcAngle - dotSpan + paddingAngle,
            show = showRightDots,
            dotAngleGapDeg = dotAngleGapDeg
        )
    }

    // --- Rotating pointer (uses the same effective angles & window) ---
    @Composable
    fun ShowRotatingIndicator(exerciseId: UUID) {
        val isSuperset = remember(exerciseId) { viewModel.supersetIdByExerciseId.containsKey(exerciseId) }
        val targetGroupId = if (isSuperset) viewModel.supersetIdByExerciseId[exerciseId]!! else exerciseId
        val globalGroupIdx = exerciseOrSupersetIds.indexOf(targetGroupId)
        val posInWindow = if (globalGroupIdx in startIdx..endIdx) globalGroupIdx - startIdx else -1
        if (posInWindow >= 0) {
            val baseStart = startAngleEffective + posInWindow * (segmentArcAngle + paddingAngle)
            val mid = if (isSuperset) {
                val supersetExerciseIds = exerciseIds.filter { viewModel.supersetIdByExerciseId[it] == targetGroupId }
                val c = supersetExerciseIds.size
                val sub = supersetExerciseIds.indexOf(exerciseId)
                val subSweep = (segmentArcAngle - (c - 1) * paddingAngle) / c
                baseStart + sub * (subSweep + paddingAngle) + subSweep / 2f
            } else {
                baseStart + segmentArcAngle / 2f
            }
            RotatingIndicator(mid, MaterialTheme.colorScheme.onBackground)
        }
    }

    if (selectedExerciseId != null && exerciseIds.contains(selectedExerciseId)) {
        ShowRotatingIndicator(selectedExerciseId)
    } else {
        ShowRotatingIndicator(set.exerciseId)
    }
}

// --- helper: 3 small dots at a given arc end (keeps segments inside total arc) ---
@Composable
private fun EdgeOverflowDots(
    angleDeg: Float,
    show: Boolean,
    ringInset: Dp = 2.dp,      // ≈ strokeWidth / 2 of your arcs
    radialGap: Dp = 0.dp,      // extra distance outside the ring
    dotSize: Dp = 4.dp,        // dot diameter
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

@OptIn(ExperimentalHorologistApi::class)
@Composable
fun SetIndicator(
    viewModel: AppViewModel,
    set: WorkoutState.Set
) {
    val exerciseIds = remember { viewModel.setsByExerciseId.keys.toList() }
    val exerciseOrSupersetIds = remember {
        exerciseIds.map { if (viewModel.supersetIdByExerciseId.containsKey(it)) viewModel.supersetIdByExerciseId[it] else it }.distinct()
    }
    val exerciseCount = exerciseOrSupersetIds.count()

    val exerciseOrSupersetId = if (viewModel.supersetIdByExerciseId.containsKey(set.exerciseId)) viewModel.supersetIdByExerciseId[set.exerciseId]!! else set.exerciseId
    val currentExerciseOrSupersetIndex = exerciseOrSupersetIds.indexOf(exerciseOrSupersetId)

    val isSuperset = remember(exerciseOrSupersetId) { viewModel.supersetIdByExerciseId.containsValue(exerciseOrSupersetId) }

    val sets: List<WorkoutState.Set> = remember(
        isSuperset,
        viewModel.allWorkoutStates,
        exerciseOrSupersetId
    ) {
        val targetExerciseIds: Set<UUID> =
            if (isSuperset) {
                viewModel.exercisesBySupersetId[exerciseOrSupersetId]
                    ?.map { it.id }
                    ?.toSet()
                    ?: emptySet()
            } else {
                setOf(exerciseOrSupersetId)   // here exerciseOrSupersetId is the exercise id
            }

        viewModel.allWorkoutStates
            .asSequence()
            .filterIsInstance<WorkoutState.Set>()
            .filter { it.exerciseId in targetExerciseIds }
            .toList()
    }

    val currentSetIndex = sets.indexOfFirst { it === set }

    val startingAngle = -50f
    val totalArcAngle = 100f
    val segmentArcAngle = (totalArcAngle - (exerciseCount - 1) * 2f) / exerciseCount

    Box(modifier = Modifier.fillMaxSize()) {
        sets.forEachIndexed { index, _ ->
            val indicatorProgress = when {
                index <= currentExerciseOrSupersetIndex -> 1.0f
                else -> 0.0f
            }

            val trackSegment = ProgressIndicatorSegment(
                weight = 1f,
                indicatorColor = if (index != currentExerciseOrSupersetIndex) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onBackground
            )

            val startAngle = startingAngle + index * (segmentArcAngle + 2f)
            val endAngle = startAngle + segmentArcAngle

            SegmentedProgressIndicator(
                trackSegments = listOf(trackSegment),
                progress = indicatorProgress,
                modifier = Modifier.fillMaxSize(),
                strokeWidth = 4.dp,
                paddingAngle = 0f,
                startAngle = startAngle,
                endAngle = endAngle,
                trackColor = MaterialTheme.colorScheme.surfaceContainer
            )
        }
    }

    val startAngle = startingAngle + currentSetIndex * (segmentArcAngle + 2f)
    val middleAngle = startAngle + (segmentArcAngle / 2f)

    RotatingIndicator(middleAngle, MaterialTheme.colorScheme.onBackground)
}