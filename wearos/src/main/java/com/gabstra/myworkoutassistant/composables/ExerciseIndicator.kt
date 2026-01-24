package com.gabstra.myworkoutassistant.composables

import android.annotation.SuppressLint
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
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
import androidx.compose.ui.tooling.preview.Devices
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.CircularProgressIndicator
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ProgressIndicatorDefaults
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.reduceColorLuminance
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import java.util.LinkedList
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
    // --- Flattened order: every exercise once; supersets kept contiguous ---
    // Derive exerciseIds from allWorkoutStates to ensure workout order (not map key order)
    val exerciseIds = viewModel.allWorkoutStates
        .filterIsInstance<WorkoutState.Set>()
        .map { it.exerciseId }
        .distinct()
        .toList()

    // Helper function to find active timer set for an exercise
    fun findActiveTimerSet(exerciseId: UUID, currentSet: WorkoutState.Set): WorkoutState.Set? {
        val allExerciseSets = viewModel.getAllExerciseWorkoutStates(exerciseId)
            .filterNot { it.shouldIgnoreCalibration() }
        
        // Find the first set that:
        // 1. Hasn't been completed (is at or after current set in workout flow)
        // 2. Has startTime set (timer started)
        // 3. Has timer registered in service
        // 4. Is a TimedDurationSet or EnduranceSet
        val currentSetIndex = viewModel.allWorkoutStates.indexOfFirst { 
            it is WorkoutState.Set && it.set.id == currentSet.set.id 
        }
        
        return allExerciseSets.firstOrNull { exerciseSet ->
            val setIndex = viewModel.allWorkoutStates.indexOfFirst { 
                it is WorkoutState.Set && it.set.id == exerciseSet.set.id 
            }
            val isNotCompleted = setIndex >= currentSetIndex
            val hasTimerStarted = exerciseSet.startTime != null
            val hasTimerRegistered = viewModel.workoutTimerService.isTimerRegistered(exerciseSet.set.id)
            val isTimerSet = exerciseSet.set is TimedDurationSet || exerciseSet.set is EnduranceSet
            
            isNotCompleted && hasTimerStarted && hasTimerRegistered && isTimerSet
        }
    }

    // Helper function to find time exercise set for selected exercise (doesn't require timer to be started)
    fun findTimeExerciseSet(exerciseId: UUID, currentSet: WorkoutState.Set): WorkoutState.Set? {
        val allExerciseSets = viewModel.getAllExerciseWorkoutStates(exerciseId)
            .filterNot { it.shouldIgnoreCalibration() }
        
        // Find the first set that:
        // 1. Hasn't been completed (is at or after current set in workout flow)
        // 2. Is a TimedDurationSet or EnduranceSet
        val currentSetIndex = viewModel.allWorkoutStates.indexOfFirst { 
            it is WorkoutState.Set && it.set.id == currentSet.set.id 
        }
        
        return allExerciseSets.firstOrNull { exerciseSet ->
            val setIndex = viewModel.allWorkoutStates.indexOfFirst { 
                it is WorkoutState.Set && it.set.id == exerciseSet.set.id 
            }
            val isNotCompleted = setIndex >= currentSetIndex
            val isTimerSet = exerciseSet.set is TimedDurationSet || exerciseSet.set is EnduranceSet
            
            isNotCompleted && isTimerSet
        }
    }

    // Calculate indicator progress
    // derivedStateOf automatically tracks all state reads, so reading currentSetData from
    // active timer sets will trigger recomposition when timer service updates them
    val indicatorProgressByExerciseId by derivedStateOf {
        exerciseIds.associateWith { id ->
            val completed = viewModel.getAllExerciseCompletedSetsBefore(set)
                .filterNot { it.shouldIgnoreCalibration() }
                .count { it.exerciseId == id }
            val total = viewModel.getAllExerciseWorkoutStates(id)
                .filterNot { it.shouldIgnoreCalibration() }
                .distinctBy { it.set.id }
                .size

            // Determine which set to use for timer progress calculation
            val timerSet: WorkoutState.Set? = when {
                // 1. Current exercise: use timer progress only if total == 1 and it's a time exercise
                id == set.exerciseId -> {
                    if (total == 1 && (set.set is TimedDurationSet || set.set is EnduranceSet)) {
                        // Check if currentSetData is a time exercise type - read state directly to ensure tracking
                        when (set.currentSetDataState.value) {
                            is TimedDurationSetData, is EnduranceSetData -> set
                            else -> null
                        }
                    } else {
                        null
                    }
                }
                // 2. Selected exercise: find time exercise set and use its currentSetData
                selectedExerciseId != null && id == selectedExerciseId -> {
                    findTimeExerciseSet(id, set)
                }
                // 3. All other exercises: no timer tracking
                else -> null
            }

            if (timerSet != null) {
                // Calculate progress based on timer - read state value directly to ensure Compose tracks it
                // Reading currentSetDataState.value ensures state changes are tracked even when screen isn't visible
                when (val d = timerSet.currentSetDataState.value) {
                    is EnduranceSetData -> {
                        // EnduranceSet counts up, progress is endTimer / startTimer
                        (d.endTimer / d.startTimer.toFloat()).coerceIn(0f, 1f)
                    }
                    is TimedDurationSetData -> {
                        // TimedDurationSet counts down, progress is 1 - (endTimer / startTimer)
                        (1 - (d.endTimer / d.startTimer.toFloat())).coerceIn(0f, 1f)
                    }
                    else -> completed.toFloat() / total.toFloat()
                }
            } else {
                // No timer tracking, use completed/total ratio
                completed.toFloat() / total.toFloat()
            }
        }
    }

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

    val startingAngle = -50f
    val totalArcAngle = 100f
    val paddingAngle = 1f

    val dotAngleGapDeg = 4f
    val dotSpan = 2 * dotAngleGapDeg
    val dotsReserve = dotSpan + dotAngleGapDeg + paddingAngle

    val leftReserve = if (showLeftDots) dotsReserve else 0f
    val rightReserve = if (showRightDots) dotsReserve else 0f

    val startAngleEffective = startingAngle + leftReserve
    val totalArcEffective = totalArcAngle - leftReserve - rightReserve
    val segmentArcAngle = (totalArcEffective - (visibleCount - 1) * paddingAngle) / visibleCount

    @Composable
    fun ShowRotatingIndicator(exerciseId: UUID, color: Color = MaterialTheme.colorScheme.onBackground) {
        val idx = globalIndexByExerciseId[exerciseId] ?: return
        val posInWindow = if (idx in startIdx..endIdx) idx - startIdx else -1
        if (posInWindow >= 0) {
            val baseStart = startAngleEffective + posInWindow * (segmentArcAngle + paddingAngle)
            val mid = baseStart + segmentArcAngle / 2f
            RotatingIndicator(mid, color)
        }
    }

    Box(
        modifier = Modifier.fillMaxSize().padding(3.dp)
    ) {
        // --- OUTER RING for visible superset ranges (drawn first) ---
        OuterSupersetOverlay(
            visibleIndices = visibleIndices,
            flatExerciseOrder = flatExerciseOrder,
            supersetIdByExerciseId = viewModel.supersetIdByExerciseId,
            startAngleEffective = startAngleEffective,
            segmentArcAngle = segmentArcAngle,
            paddingAngle = paddingAngle,
            currentGlobalIdx = currentGlobalIdx,
            ringInset = 0.dp, //ringInset = 12.dp,
            strokeWidth = 1.dp,
            tickWidth = 1.dp,
            tickLength = 3.dp,
            arcColor = MaterialTheme.colorScheme.onBackground,
            badgeColor = MaterialTheme.colorScheme.onBackground
        )
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(10.dp)
    ) {
        // --- INNER segments: every exercise gets same arc ---
        visibleIndices.forEachIndexed { posInWindow, globalIdx ->
            val eid = flatExerciseOrder[globalIdx]
            val eIdx = globalIndexByExerciseId[eid] ?: Int.MAX_VALUE
            val isCurrent = eIdx == currentGlobalIdx

            val indicatorProgress = indicatorProgressByExerciseId[eid]!!

            val startA = startAngleEffective + posInWindow * (segmentArcAngle + paddingAngle)
            val endA = startA + segmentArcAngle

            key(eid,indicatorProgress) {
                val indicatorColor = when {
                    isCurrent -> MaterialTheme.colorScheme.primary // Current exercise: bright gray/white
                    indicatorProgress >= 1.0f -> MaterialTheme.colorScheme.onBackground // Previous exercise (completed): green
                    indicatorProgress == 0.0f -> MediumDarkGray // Future exercise (not started): subtle gray
                    else -> MaterialTheme.colorScheme.primary // In progress (shouldn't happen for non-current): orange
                }
                
                val trackColor = remember(isCurrent, indicatorColor) {
                    if (isCurrent) {
                        reduceColorLuminance(indicatorColor, 0.3f)
                    } else {
                        MediumDarkGray
                    }
                }
                
                CircularProgressIndicator(
                    colors = ProgressIndicatorDefaults.colors(
                        indicatorColor = indicatorColor,
                        trackColor = trackColor
                    ),
                    progress = { indicatorProgress },
                    modifier = Modifier.fillMaxSize(),
                    strokeWidth = 4.dp,
                    startAngle = startA,
                    endAngle = endA
                )
            }
        }

        // Edge dots (global)
        val minVisibleIndex = visibleIndices.first()
        val maxVisibleIndex = visibleIndices.last()
        EdgeOverflowDots(
            angleDeg = startingAngle + (dotsReserve / 2),
            show = showLeftDots,
            dotAngleGapDeg = dotAngleGapDeg,
            color = when {
                minVisibleIndex > currentGlobalIdx -> MediumDarkGray // Future exercises: MediumDarkGray
                minVisibleIndex == currentGlobalIdx -> MaterialTheme.colorScheme.primary // Current exercise: primary
                else -> MaterialTheme.colorScheme.onBackground // Previous exercises (completed): primary
            }
        )
        EdgeOverflowDots(
            angleDeg = startingAngle + totalArcAngle - (dotSpan + dotAngleGapDeg + paddingAngle) / 2f,
            show = showRightDots,
            dotAngleGapDeg = dotAngleGapDeg,
            color = when {
                maxVisibleIndex < currentGlobalIdx -> MaterialTheme.colorScheme.onBackground // Previous exercises (completed): primary
                else -> MediumDarkGray // Future exercises: MediumDarkGray
            }
        )
    }

    Box(modifier = Modifier.fillMaxSize().padding(18.dp)) {
        if (selectedExerciseId != null && flatExerciseOrder.contains(selectedExerciseId) && set.exerciseId != selectedExerciseId) {
            ShowRotatingIndicator(selectedExerciseId)
        } else {
            ShowRotatingIndicator(set.exerciseId)
        }
    }
}

private fun WorkoutState.Set.shouldIgnoreCalibration(): Boolean {
    val isCalibrationSet = when (val workoutSet = set) {
        is BodyWeightSet -> workoutSet.subCategory == SetSubCategory.CalibrationSet
        is WeightSet -> workoutSet.subCategory == SetSubCategory.CalibrationSet
        else -> false
    }

    // Ignore calibration set if it's not in execution state (i.e., if we're in LoadSelection or RIRSelection states)
    // With new state types, calibration sets are only shown when isCalibrationSet == true (execution state)
    return isCalibrationSet && !this.isCalibrationSet
}

// Create ViewModel outside composable to avoid "Constructing a view model in a composable" warning
private val previewAppViewModel = AppViewModel()

@SuppressLint("UnrememberedMutableState")
@Preview(device = Devices.WEAR_OS_SMALL_ROUND, showBackground = true)
@Composable
private fun ExerciseIndicatorPreview() {
    MaterialTheme {
        // Create mock exercise IDs
        val exercise1Id = UUID.fromString("11111111-1111-1111-1111-111111111111")
        val exercise2Id = UUID.fromString("22222222-2222-2222-2222-222222222222")
        val exercise3Id = UUID.fromString("33333333-3333-3333-3333-333333333333")
        val exercise4Id = UUID.fromString("44444444-4444-4444-4444-444444444444")
        val supersetId = UUID.fromString("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        
        // Create mock sets
        val set1_1 = WeightSet(UUID.randomUUID(), 10, 100.0, SetSubCategory.WorkSet)
        val set1_2 = WeightSet(UUID.randomUUID(), 10, 100.0, SetSubCategory.WorkSet)
        val set1_3 = WeightSet(UUID.randomUUID(), 10, 100.0, SetSubCategory.WorkSet)
        
        val set2_1 = WeightSet(UUID.randomUUID(), 8, 80.0, SetSubCategory.WorkSet)
        val set2_2 = WeightSet(UUID.randomUUID(), 8, 80.0, SetSubCategory.WorkSet)
        
        val set3_1 = WeightSet(UUID.randomUUID(), 12, 60.0, SetSubCategory.WorkSet)
        val set3_2 = WeightSet(UUID.randomUUID(), 12, 60.0, SetSubCategory.WorkSet)
        val set3_3 = WeightSet(UUID.randomUUID(), 12, 60.0, SetSubCategory.WorkSet)
        val set3_4 = WeightSet(UUID.randomUUID(), 12, 60.0, SetSubCategory.WorkSet)
        
        val set4_1 = WeightSet(UUID.randomUUID(), 15, 40.0, SetSubCategory.WorkSet)
        
        // Create mock WorkoutState.Set instances
        val workoutState1_1 = WorkoutState.Set(
            exerciseId = exercise1Id,
            set = set1_1,
            setIndex = 0u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(WeightSetData(10, 100.0, 1000.0)),
            hasNoHistory = true,
            startTime = null,
            skipped = false,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            currentBodyWeight = 70.0,
            plateChangeResult = null,
            streak = 0,
            progressionState = null,
            isWarmupSet = false,
            equipment = null,
            isUnilateral = false,
            intraSetTotal = null,
            intraSetCounter = 0u
        )
        
        val workoutState1_2 = workoutState1_1.copy(
            set = set1_2,
            setIndex = 1u,
            previousSetData = WeightSetData(10, 100.0, 1000.0)
        )
        
        val workoutState1_3 = workoutState1_1.copy(
            set = set1_3,
            setIndex = 2u,
            previousSetData = WeightSetData(10, 100.0, 1000.0)
        )
        
        val workoutState2_1 = workoutState1_1.copy(
            exerciseId = exercise2Id,
            set = set2_1,
            setIndex = 0u,
            currentSetDataState = mutableStateOf(WeightSetData(8, 80.0, 640.0))
        )
        
        val workoutState2_2 = workoutState2_1.copy(
            set = set2_2,
            setIndex = 1u,
            previousSetData = WeightSetData(8, 80.0, 640.0)
        )
        
        val workoutState3_1 = workoutState1_1.copy(
            exerciseId = exercise3Id,
            set = set3_1,
            setIndex = 0u,
            currentSetDataState = mutableStateOf(WeightSetData(12, 60.0, 720.0))
        )
        
        val workoutState3_2 = workoutState3_1.copy(
            set = set3_2,
            setIndex = 1u,
            previousSetData = WeightSetData(12, 60.0, 720.0)
        )
        
        val workoutState3_3 = workoutState3_1.copy(
            set = set3_3,
            setIndex = 2u,
            previousSetData = WeightSetData(12, 60.0, 720.0)
        )
        
        val workoutState3_4 = workoutState3_1.copy(
            set = set3_4,
            setIndex = 3u,
            previousSetData = WeightSetData(12, 60.0, 720.0)
        )
        
        val workoutState4_1 = workoutState1_1.copy(
            exerciseId = exercise4Id,
            set = set4_1,
            setIndex = 0u,
            currentSetDataState = mutableStateOf(WeightSetData(15, 40.0, 600.0))
        )
        
        // Set up ViewModel state using reflection
        val viewModel = previewAppViewModel
        
        // Populate allWorkoutStates (accessible as open val)
        viewModel.allWorkoutStates.clear()
        viewModel.allWorkoutStates.addAll(listOf(
            workoutState1_1, workoutState1_2, workoutState1_3,
            workoutState2_1, workoutState2_2,
            workoutState3_1, workoutState3_2, workoutState3_3, workoutState3_4,
            workoutState4_1
        ))
        
        // Populate setStates using reflection (protected field)
        try {
            val setStatesField = viewModel::class.java.superclass
                ?.declaredFields?.find { it.name == "setStates" }
            setStatesField?.isAccessible = true
            val setStates = setStatesField?.get(viewModel) as? LinkedList<WorkoutState.Set>
            setStates?.clear()
            setStates?.addAll(listOf(
                workoutState1_1, workoutState1_2, workoutState1_3,
                workoutState2_1, workoutState2_2,
                workoutState3_1, workoutState3_2, workoutState3_3, workoutState3_4,
                workoutState4_1
            ))
        } catch (e: Exception) {
            // If reflection fails, the preview may not work perfectly but won't crash
        }
        
        // Populate workoutStateHistory using reflection (protected field)
        try {
            val historyField = viewModel::class.java.superclass
                ?.declaredFields?.find { it.name == "workoutStateHistory" }
            historyField?.isAccessible = true
            val history = historyField?.get(viewModel) as? MutableList<WorkoutState>
            history?.clear()
            // Mark first exercise's first two sets as completed
            history?.addAll(listOf(workoutState1_1, workoutState1_2))
        } catch (e: Exception) {
            // If reflection fails, the preview may not work perfectly but won't crash
        }
        
        // Set up superset mapping (exercise2 and exercise3 are in a superset)
        viewModel.supersetIdByExerciseId = mapOf(
            exercise2Id to supersetId,
            exercise3Id to supersetId
        )
        
        // Current set is the third set of exercise 1 (middle of workout)
        val currentSet = workoutState1_3
        
        Box(modifier = Modifier.fillMaxSize()) {
            ExerciseIndicator(
                viewModel = viewModel,
                set = currentSet,
                selectedExerciseId = null
            )
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
    color: Color
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
    currentGlobalIdx: Int,
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
                val innerR = r - tickLen / 2f - tickLengthPx
                val outerR = r + tickLen / 2f

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


            // Determine color based on position relative to current exercise
            val dotsColor = when {
                globalStart > currentGlobalIdx -> MediumDarkGray // Future exercises: MediumDarkGray
                globalStart <= currentGlobalIdx && globalEnd >= currentGlobalIdx -> MaterialTheme.colorScheme.primary // Current exercise: primary
                else ->  MaterialTheme.colorScheme.onBackground // Previous exercises (completed): primary
            }

            // Left overlay dots (centered within its reserve)
            EdgeOverflowDots(
                angleDeg = groupStartRaw + dotsReserve / 2f,
                show = startsBeforeWindow,
                ringInset = dotsRingInsetForOverlay,
                dotAngleGapDeg = dotAngleGapDeg,
                color = dotsColor,
            )

            // Right overlay dots (mirrors global formula)
            EdgeOverflowDots(
                angleDeg = groupStartRaw + groupSweepRaw + (dotSpan + dotAngleGapDeg + paddingAngle) / 2f,
                show = endsAfterWindow,
                ringInset = dotsRingInsetForOverlay,
                dotAngleGapDeg = dotAngleGapDeg,
                color = dotsColor,
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
