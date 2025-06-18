package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.withTransform
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.FormatTime
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.verticalColumnScrollbar
import com.gabstra.myworkoutassistant.presentation.theme.MyColors
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch


@OptIn(ExperimentalFoundationApi::class)
@Composable
fun SetTableRow(
    hapticsViewModel: HapticsViewModel,
    viewModel: AppViewModel,
    modifier: Modifier = Modifier,
    setState: WorkoutState.Set,
    index: Int?,
    isCurrentSet: Boolean,
    color: Color = MyColors.White,
){
    val density = LocalDensity.current.density
    val triangleSize = 6f

    val typography = MaterialTheme.typography
    val captionStyle = remember(typography) { typography.body1.copy(fontSize = typography.body1.fontSize * 0.625f, fontWeight = FontWeight.Bold) }
    val itemStyle = remember(typography) { typography.body1.copy(fontWeight = FontWeight.Bold) }
    val context = LocalContext.current

    var openDialogJob by remember { mutableStateOf<Job?>(null) }
    val coroutineScope = rememberCoroutineScope()

    var showWeightInfoDialog by remember { mutableStateOf(false) }

    val equipment = setState.equipment

    fun startOpenDialogJob() {
        if( openDialogJob?.isActive == true) return
        openDialogJob?.cancel()
        openDialogJob = coroutineScope.launch {
            showWeightInfoDialog = true
            kotlinx.coroutines.delay(5000L)
            showWeightInfoDialog = false
        }
    }

    val indicatorComposable = @Composable {
        Box(modifier= Modifier.width(18.dp).fillMaxHeight(), contentAlignment = Alignment.Center){
            Canvas(modifier = Modifier.size((triangleSize * 2 / density).dp)) {
                val trianglePath = Path().apply {
                    val height = (triangleSize * 2 / density).dp.toPx()
                    val width = height

                    // Create triangle pointing upward initially
                    moveTo(width / 2, 0f)          // Top point
                    lineTo(width, height * 0.866f) // Bottom right
                    lineTo(0f, height * 0.866f)    // Bottom left
                    close()
                }

                // Calculate rotation to point in direction of movement
                // Add 90 degrees (π/2) because our triangle points up by default
                // and we want it to point in the direction of travel
                val directionAngle = 0 - Math.PI / 2 + Math.PI

                withTransform({
                    rotate(
                        degrees = Math.toDegrees(directionAngle).toFloat(),
                        pivot = center
                    )
                }) {
                    // Draw filled white triangle
                    drawPath(
                        path = trianglePath,
                        color = MyColors.White
                    )
                }
            }
        }
    }

    val warmupIndicatorComposable = @Composable{
        Box(modifier= Modifier.width(18.dp).fillMaxHeight(), contentAlignment = Alignment.Center){
            Text(
                text = "W",
                style = captionStyle,
                textAlign = TextAlign.Center,
                color = color
            )
        }
    }

    Row(
        modifier = modifier,
        verticalAlignment = Alignment.CenterVertically
    ) {
        if(isCurrentSet && !setState.isWarmupSet){
            indicatorComposable()
        }else if(setState.isWarmupSet){
            warmupIndicatorComposable()
        }else{
            Spacer(modifier = Modifier.width(18.dp))
        }
        when (setState.currentSetData) {
            is WeightSetData -> {
                val weightSetData = (setState.currentSetData as WeightSetData)
                ScalableText(
                    modifier = Modifier
                        .fillMaxHeight()
                        .weight(2f)
                        .combinedClickable(
                            onClick = {},
                            onLongClick = {
                                startOpenDialogJob()
                                hapticsViewModel.doGentleVibration()
                            },
                            onDoubleClick = {}
                    ),
                    text = equipment!!.formatWeight(weightSetData.actualWeight),
                    style = itemStyle,
                    textAlign = TextAlign.Center,
                    color = color
                )
                Text(
                    modifier = Modifier.weight(1f),
                    text = "${weightSetData.actualReps}",
                    style = itemStyle,
                    textAlign = TextAlign.Center,
                    color = color
                )

                WeightInfoDialog(
                    show = showWeightInfoDialog,
                    weight = weightSetData.getWeight(),
                    equipment = setState.equipment,
                    onClick = {
                        openDialogJob?.cancel()
                        showWeightInfoDialog = false
                    }
                )
            }

            is BodyWeightSetData -> {
                val bodyWeightSetData = (setState.currentSetData as BodyWeightSetData)
                val weightText = if(setState.equipment != null) {
                    setState.equipment!!.formatWeight(bodyWeightSetData.additionalWeight)
                }else {
                    "-"
                }

                ScalableText(
                    modifier = Modifier
                        .weight(2f)
                        .combinedClickable(
                            onClick = {},
                            onLongClick = {
                                startOpenDialogJob()
                                hapticsViewModel.doGentleVibration()
                            },
                            onDoubleClick = {}
                        ),
                    text = weightText,
                    style = itemStyle,
                    textAlign = TextAlign.Center,
                    color = color
                )
                Text(
                    modifier = Modifier.weight(1f),
                    text = "${bodyWeightSetData.actualReps}",
                    style = itemStyle,
                    textAlign = TextAlign.Center,
                    color = color
                )

                WeightInfoDialog(
                    show = showWeightInfoDialog,
                    weight = bodyWeightSetData.additionalWeight,
                    equipment = setState.equipment,
                    onClick = {
                        openDialogJob?.cancel()
                        showWeightInfoDialog = false
                    }
                )
            }

            is TimedDurationSetData -> {
                val timedDurationSetData = (setState.currentSetData as TimedDurationSetData)

                ScalableText(
                    modifier = Modifier.weight(1f),
                    text = FormatTime(timedDurationSetData.startTimer / 1000),
                    style = itemStyle,
                    textAlign = TextAlign.Center,
                    color = color
                )
                Spacer(modifier = Modifier.width(18.dp))
            }

            is EnduranceSetData -> {
                val enduranceSetData = (setState.currentSetData as EnduranceSetData)

                ScalableText(
                    modifier = Modifier.weight(1f),
                    text = FormatTime(enduranceSetData.startTimer / 1000),
                    style = itemStyle,
                    textAlign = TextAlign.Center,
                    color = color
                )
                Spacer(modifier = Modifier.width(18.dp))
            }

            else -> throw RuntimeException("Unsupported set type")
        }
    }
}

@Composable
fun ExerciseSetsViewer(
    modifier: Modifier = Modifier,
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    exercise: Exercise,
    currentSet: com.gabstra.myworkoutassistant.shared.sets.Set,
    customColor: Color? = null,
    overrideSetIndex: Int? = null
){

    val exerciseSetIds = viewModel.setsByExerciseId[exercise.id]!!.map { it.set.id }
    val setIndex = overrideSetIndex ?: exerciseSetIds.indexOf(currentSet.id)

    val exerciseSetStates = remember(exercise.id) { viewModel.getAllExerciseWorkoutStates(exercise.id).filter { it.set !is RestSet } }

    val typography = MaterialTheme.typography
    val headerStyle = remember { typography.body1.copy(fontSize = typography.body1.fontSize * 0.625f) }

    val scrollState = rememberScrollState()
    val itemHeights = remember { mutableStateMapOf<Int, Int>() }
    val density = LocalDensity.current

    val allItemsMeasured = remember(exerciseSetStates.size) { mutableStateOf(false) }
    val measuredItems = remember(exerciseSetStates.size) { mutableStateOf(0) }

    // Effect to handle scrolling whenever heights are updated or setIndex changes
    LaunchedEffect(allItemsMeasured.value, setIndex) {
        if (!allItemsMeasured.value || setIndex == -1) {
            return@LaunchedEffect
        }
        // Calculate position including spacing
        //val spacingHeight = with(density) { 2.dp.toPx().toInt() }
        val position = (0 until setIndex).sumOf { index ->
            (itemHeights[index] ?: 0) // + spacingHeight
        }
        scrollState.scrollTo(position)
    }

    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(5.dp)
    ) {
        if (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Spacer(modifier= Modifier.width(18.dp))
                Text(
                    modifier = Modifier.weight(2f),
                    text = "WEIGHT (KG)",
                    style = headerStyle,
                    textAlign = TextAlign.Center
                )
                Text(
                    modifier = Modifier.weight(1f),
                    text = "REPS",
                    style = headerStyle,
                    textAlign = TextAlign.Center
                )
            }
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .verticalColumnScrollbar(
                        scrollState = scrollState,
                        scrollBarColor = MyColors.White,
                        enableTopFade = false,
                        enableBottomFade = false
                    )
                    .verticalScroll(scrollState),
                //verticalArrangement = Arrangement.spacedBy(0.dp),
            ) {
                exerciseSetStates.forEachIndexed { index, nextSetState ->
                    SetTableRow(
                        modifier = Modifier
                            .fillMaxWidth()
                            .onGloballyPositioned { coordinates ->
                                val height = coordinates.size.height
                                if (itemHeights[index] != height) {
                                    itemHeights[index] = height
                                    measuredItems.value++

                                    if (measuredItems.value == exerciseSetStates.size) {
                                        allItemsMeasured.value = true
                                    }
                                }
                            },
                        hapticsViewModel = hapticsViewModel,
                        viewModel = viewModel,
                        setState = nextSetState,
                        index = index,
                        isCurrentSet = index == setIndex,
                        color = if(customColor!= null) customColor else when {
                            index < setIndex -> MyColors.Orange
                            index == setIndex -> MyColors.White
                            else ->  MyColors.DarkGray
                        }
                    )
                }
            }
            return
        }

        if (exercise.exerciseType == ExerciseType.COUNTUP || exercise.exerciseType == ExerciseType.COUNTDOWN) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Spacer(modifier= Modifier.width(18.dp))
                Text(
                    modifier = Modifier.weight(1f),
                    text = "TIME (HH:MM:SS)",
                    style = headerStyle,
                    textAlign = TextAlign.Center
                )
                Spacer(modifier = Modifier.width(18.dp))
            }
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .verticalColumnScrollbar(
                        scrollState = scrollState,
                        scrollBarColor = MyColors.White
                    )
                    .verticalScroll(scrollState),
                verticalArrangement = Arrangement.spacedBy(2.dp),
            ) {
                exerciseSetStates.forEachIndexed { index, nextSetState ->
                    SetTableRow(
                        modifier = Modifier
                            .fillMaxWidth()
                            .onGloballyPositioned { coordinates ->
                                val height = coordinates.size.height
                                if (itemHeights[index] != height) {
                                    itemHeights[index] = height
                                    measuredItems.value++

                                    if (measuredItems.value == exerciseSetStates.size) {
                                        allItemsMeasured.value = true
                                    }
                                }
                            },
                        hapticsViewModel = hapticsViewModel,
                        viewModel = viewModel,
                        setState = nextSetState,
                        index = index,
                        isCurrentSet = index == setIndex,
                        color = if(customColor!= null) customColor else when {
                            index < setIndex -> MyColors.Orange
                            index == setIndex -> MyColors.White
                            else -> MyColors.DarkGray
                        }
                    )
                }
            }
            return
        }
    }
}