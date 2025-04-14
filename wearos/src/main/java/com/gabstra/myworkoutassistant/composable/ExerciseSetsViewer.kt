package com.gabstra.myworkoutassistant.composable

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.withTransform
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.FormatTime
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


@Composable
fun SetTableRow(
    modifier: Modifier = Modifier,
    setState: WorkoutState.Set,
    index: Int?,
    isCurrentSet: Boolean,
    color: Color = Color.Unspecified,
){
    val density = LocalDensity.current.density
    val triangleSize = 6f

    val indicatorComposable = @Composable {
        Box(modifier= Modifier.width(10.dp).fillMaxHeight()){
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
                        color = Color.White
                    )
                }
            }
        }
    }

    Row(
        modifier = modifier,
        verticalAlignment = Alignment.CenterVertically
    ) {
        when (setState.currentSetData) {
            is WeightSetData -> {
                if(isCurrentSet){
                    indicatorComposable()
                }else{
                    Spacer(modifier = Modifier.width(10.dp))
                }
                val weightSetData = (setState.currentSetData as WeightSetData)
                Text(
                    modifier = Modifier.weight(1f),
                    text = "%.2f".format(weightSetData.actualWeight).replace(',','.'),
                    style = MaterialTheme.typography.body1,
                    textAlign = TextAlign.Center,
                    color = color
                )
                Text(
                    modifier = Modifier.weight(1f),
                    text = "${weightSetData.actualReps}",
                    style = MaterialTheme.typography.body1,
                    textAlign = TextAlign.Center,
                    color = color
                )
            }

            is BodyWeightSetData -> {
                if(isCurrentSet){
                    indicatorComposable()
                }else{
                    Spacer(modifier = Modifier.width(10.dp))
                }
                val bodyWeightSetData = (setState.currentSetData as BodyWeightSetData)
                Text(
                    modifier = Modifier.weight(1f),
                    text = if (bodyWeightSetData.additionalWeight > 0) {
                        "%.2f".format(bodyWeightSetData.additionalWeight).replace(',','.')
                    } else {
                        "-"
                    },
                    style = MaterialTheme.typography.body1,
                    textAlign = TextAlign.Center,
                    color = color
                )
                Text(
                    modifier = Modifier.weight(1f),
                    text = "${bodyWeightSetData.actualReps}",
                    style = MaterialTheme.typography.body1,
                    textAlign = TextAlign.Center,
                    color = color
                )
            }

            is TimedDurationSetData -> {
                val timedDurationSetData = (setState.currentSetData as TimedDurationSetData)

                Row(modifier = Modifier.weight(1f), horizontalArrangement = Arrangement.Center){
                    if(isCurrentSet){
                        indicatorComposable()
                    }else{
                        Spacer(modifier = Modifier.width(10.dp))
                    }
                }

                ScalableText(
                    modifier = Modifier.weight(2f),
                    text = FormatTime(timedDurationSetData.startTimer / 1000),
                    style = MaterialTheme.typography.body1,
                    textAlign = TextAlign.Start,
                    contentAlignment = Alignment.CenterStart,
                    color = color
                )

            }

            is EnduranceSetData -> {
                val enduranceSetData = (setState.currentSetData as EnduranceSetData)

                Row(modifier = Modifier.weight(1f), horizontalArrangement = Arrangement.Center){
                    if(isCurrentSet){
                        indicatorComposable()
                    }else{
                        Spacer(modifier = Modifier.width(10.dp))
                    }
                }

                ScalableText(
                    modifier = Modifier.weight(2f),
                    text = FormatTime(enduranceSetData.startTimer / 1000),
                    style = MaterialTheme.typography.body1,
                    textAlign = TextAlign.Start,
                    contentAlignment = Alignment.CenterStart,
                    color = color
                )
            }

            else -> throw RuntimeException("Unsupported set type")
        }
    }
}

@Composable
fun ExerciseSetsViewer(
    modifier: Modifier = Modifier,
    viewModel: AppViewModel,
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
        val spacingHeight = with(density) { 2.dp.toPx().toInt() }
        val position = (0 until setIndex).sumOf { index ->
            (itemHeights[index] ?: 0) + spacingHeight
        }
        scrollState.scrollTo(position)
    }

    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(2.dp)
    ) {
        if (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 2.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Spacer(modifier= Modifier.width(10.dp))
                Text(
                    modifier = Modifier.weight(1f),
                    text = "KG",
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
                        scrollBarColor = Color.White
                    )
                    .padding(horizontal = 2.dp)
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
                        setState = nextSetState,
                        index = index,
                        isCurrentSet = index == setIndex,
                        color = if(customColor!= null) customColor else when {
                            index < setIndex -> MyColors.Orange
                            index == setIndex -> Color.White
                            else ->  MyColors.MediumGray
                        }
                    )
                }
            }
            return
        }

        if (exercise.exerciseType == ExerciseType.COUNTUP || exercise.exerciseType == ExerciseType.COUNTDOWN) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 2.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    modifier = Modifier.weight(1f),
                    text = "TIME",
                    style = headerStyle,
                    textAlign = TextAlign.Center
                )
            }
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .verticalColumnScrollbar(
                        scrollState = scrollState,
                        scrollBarColor = Color.White
                    )
                    .padding(horizontal = 2.dp)
                    .verticalScroll(scrollState),
                verticalArrangement = Arrangement.spacedBy(3.dp),
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
                        setState = nextSetState,
                        index = index,
                        isCurrentSet = index == setIndex,
                        color = if(customColor!= null) customColor else when {
                            index < setIndex -> MyColors.Orange
                            index == setIndex -> Color.White
                            else -> MyColors.MediumGray
                        }
                    )
                }
            }
            return
        }
    }
}