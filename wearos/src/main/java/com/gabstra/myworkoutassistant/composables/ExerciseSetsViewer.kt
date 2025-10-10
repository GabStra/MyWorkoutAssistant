package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.withTransform
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.FormatTime
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.scrim
import com.gabstra.myworkoutassistant.data.verticalColumnScrollbar
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.delay


@OptIn(ExperimentalFoundationApi::class)
@Composable
fun SetTableRow(
    hapticsViewModel: HapticsViewModel,
    viewModel: AppViewModel,
    modifier: Modifier = Modifier,
    setState: WorkoutState.Set,
    index: Int?,
    isCurrentSet: Boolean,
    color: Color = MaterialTheme.colorScheme.onBackground,
){
    val density = LocalDensity.current.density
    val triangleSize = 6f

    val captionStyle = MaterialTheme.typography.bodySmall
    val itemStyle = MaterialTheme.typography.numeralSmall

    val equipment = setState.equipment

    val indicatorColor = MaterialTheme.colorScheme.onBackground

    val indicatorComposable = @Composable {
        Box(modifier= Modifier.width(18.dp), contentAlignment = Alignment.Center){
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
                        color = indicatorColor
                    )
                }
            }
        }
    }

    val warmupIndicatorComposable = @Composable{
        Box(modifier= Modifier.width(18.dp), contentAlignment = Alignment.Center){
            Text(
                text = "W",
                style = captionStyle,
                textAlign = TextAlign.Center,
                color = color
            )
        }
    }

    Row(
        modifier = modifier.height(20.dp),
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
                        .weight(2f),
                    text = equipment!!.formatWeight(weightSetData.actualWeight),
                    style = itemStyle,
                    textAlign = TextAlign.Center,
                    color = color
                )
                ScalableText(
                    modifier = Modifier.weight(1f),
                    text = "${weightSetData.actualReps}",
                    style = itemStyle,
                    textAlign = TextAlign.Center,
                    color = color
                )
            }

            is BodyWeightSetData -> {
                val bodyWeightSetData = (setState.currentSetData as BodyWeightSetData)
                val weightText = if(setState.equipment != null && bodyWeightSetData.additionalWeight != 0.0) {
                    setState.equipment!!.formatWeight(bodyWeightSetData.additionalWeight)
                }else {
                    "-"
                }

                ScalableText(
                    modifier = Modifier
                        .weight(2f),
                    text = weightText,
                    style = itemStyle,
                    textAlign = TextAlign.Center,
                    color = color
                )
                ScalableText(
                    modifier = Modifier.weight(1f),
                    text = "${bodyWeightSetData.actualReps}",
                    style = itemStyle,
                    textAlign = TextAlign.Center,
                    color = color
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

    val exerciseSetStates = remember(exercise.id) {
        viewModel.getAllExerciseWorkoutStates(exercise.id)
            .filter { it.set !is RestSet }
            .distinctBy { it.set.id }
    }

    val headerStyle = MaterialTheme.typography.bodyExtraSmall

    val scrollState = rememberScrollState()

    val itemHeights = remember(exercise.id)  { mutableStateMapOf<Int, Int>() }
    var allItemsMeasured by remember(exercise.id) { mutableStateOf(false) }
    var measuredItems by remember(exercise.id) { mutableIntStateOf(0) }

    var readyToBeShown by remember(exercise.id) { mutableStateOf(false) }

    LaunchedEffect(allItemsMeasured, setIndex) {
        if (!allItemsMeasured) {
            return@LaunchedEffect
        }

        if(setIndex != -1) {
            val position = (0 until setIndex).sumOf { index ->
                (itemHeights[index] ?: 0) // + spacingHeight
            }
            scrollState.scrollTo(position)
        }else{
            scrollState.scrollTo(0)
        }

        delay(100)
        readyToBeShown = true
    }

    @Composable
    fun MeasuredSetTableRow(
        setStateForThisRow:  WorkoutState.Set,
        rowIndex: Int,
        rowBackgroundColor: Color
    ) {
        SetTableRow(
            modifier = Modifier
                .fillMaxWidth()
                .background(rowBackgroundColor)
                .onGloballyPositioned { coordinates ->
                    val height = coordinates.size.height
                    if (itemHeights[rowIndex] != height) {
                        itemHeights[rowIndex] = height
                        measuredItems++

                        if (measuredItems == exerciseSetStates.size) {
                            allItemsMeasured = true
                        }
                    }
                },
            hapticsViewModel = hapticsViewModel, // Accessed from ExerciseSetsViewer's scope
            viewModel = viewModel,               // Accessed from ExerciseSetsViewer's scope
            setState = setStateForThisRow,
            index = rowIndex, // This 'index' prop for SetTableRow might refer to its position in the overall exercise
            isCurrentSet = rowIndex == setIndex, // setIndex from ExerciseSetsViewer's scope
            color = customColor
                ?: when {
                    rowIndex < setIndex -> MaterialTheme.colorScheme.primary // MaterialTheme.colorScheme.primary, LightGray, MediumLightGray from outer scope
                    rowIndex == setIndex -> MaterialTheme.colorScheme.onBackground
                    else -> MaterialTheme.colorScheme.onBackground.copy(alpha = 0.6f)
                }
        )
    }

    val prototypeItem = @Composable {
        MeasuredSetTableRow(setStateForThisRow = exerciseSetStates[0], rowIndex = 0, rowBackgroundColor = Color.Transparent)
    }

    Column(
        modifier = modifier.scrim(!readyToBeShown,MaterialTheme.colorScheme.background),
        verticalArrangement = Arrangement.spacedBy(2.5.dp),
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

            DynamicHeightColumn(
                modifier = Modifier
                    .weight(1f) // Fills remaining vertical space
                    .fillMaxWidth(), // Still need to fill width
                prototypeItem = { prototypeItem() } // Pass the item for measurement
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .verticalColumnScrollbar(
                            scrollState = scrollState,
                            scrollBarColor = MaterialTheme.colorScheme.onBackground,
                            enableTopFade = false,
                            enableBottomFade = false
                        )
                        .verticalScroll(scrollState)
                ) {
                    exerciseSetStates.forEachIndexed { index, nextSetState ->
                        val backgroundColor = if (index % 2 == 0) {
                            MaterialTheme.colorScheme.onBackground.copy(alpha = 0.3f)
                        } else {
                            Color.Transparent
                        }

                        MeasuredSetTableRow(nextSetState, index, backgroundColor)
                    }
                }
            }
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
            DynamicHeightColumn(
                modifier = Modifier
                    .weight(1f) // Fills remaining vertical space
                    .fillMaxWidth(), // Still need to fill width
                prototypeItem = { prototypeItem() } // Pass the item for measurement
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .verticalColumnScrollbar(
                            scrollState = scrollState,
                            scrollBarColor = MaterialTheme.colorScheme.onBackground,
                            enableTopFade = false,
                            enableBottomFade = false
                        )
                        .verticalScroll(scrollState),
                ) {
                    exerciseSetStates.forEachIndexed { index, nextSetState ->
                        val backgroundColor = if (index % 2 == 0) {
                            MaterialTheme.colorScheme.onBackground.copy(alpha = 0.3f)
                        } else {
                            Color.Transparent
                        }

                        MeasuredSetTableRow(nextSetState, index, backgroundColor)
                    }
                }
            }
        }
    }
}