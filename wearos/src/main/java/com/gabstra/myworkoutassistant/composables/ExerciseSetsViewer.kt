package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.FormatTime
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.verticalColumnScrollbar
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
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
    markAsDone: Boolean,
    textColor: Color = MaterialTheme.colorScheme.onBackground,
){
    val captionStyle = MaterialTheme.typography.bodySmall
    val itemStyle = MaterialTheme.typography.numeralSmall

    val equipment = setState.equipment

    val warmupIndicatorComposable = @Composable{
        Box(modifier= Modifier.width(18.dp), contentAlignment = Alignment.Center){
            ScalableText(
                text = "W",
                style = captionStyle,
                textAlign = TextAlign.Center,
                color = textColor
            )
        }
    }

    Box(
        modifier = modifier,
    ){
        Row(
            modifier = Modifier.fillMaxSize().padding(1.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            val isWarmupSet = when(val set = setState.set) {
                is BodyWeightSet -> set.subCategory == SetSubCategory.WarmupSet
                is WeightSet -> set.subCategory == SetSubCategory.WarmupSet
                else -> false
            }
            if(isWarmupSet){
                warmupIndicatorComposable()
            }else{
                Spacer(modifier = Modifier.width(18.dp))
            }
            when (setState.currentSetData) {
                is WeightSetData -> {
                    val weightSetData = (setState.currentSetData as WeightSetData)
                    val previousWeightSetData = (setState.previousSetData as WeightSetData)

                    val weightTextColor = when {
                        weightSetData.actualWeight == previousWeightSetData.actualWeight -> textColor
                        weightSetData.actualWeight < previousWeightSetData.actualWeight  -> Red
                        else -> Green
                    }

                    val repsTextColor = when {
                        weightSetData.actualReps == previousWeightSetData.actualReps -> textColor
                        weightSetData.actualReps < previousWeightSetData.actualReps  -> Red
                        else -> Green
                    }

                    ScalableText(
                        modifier = Modifier.weight(2f),
                        text = equipment!!.formatWeight(weightSetData.actualWeight),
                        style = itemStyle,
                        textAlign = TextAlign.Center,
                        color = weightTextColor,
                    )
                    ScalableText(
                        modifier = Modifier.weight(1f),
                        text = "${weightSetData.actualReps}",
                        style = itemStyle,
                        textAlign = TextAlign.Center,
                        color = repsTextColor,
                    )
                }

                is BodyWeightSetData -> {
                    val bodyWeightSetData = (setState.currentSetData as BodyWeightSetData)
                    val previousBodyWeightSetData = (setState.previousSetData as BodyWeightSetData)

                    val weightText = if(setState.equipment != null && bodyWeightSetData.additionalWeight != 0.0) {
                        setState.equipment!!.formatWeight(bodyWeightSetData.additionalWeight)
                    }else {
                        "-"
                    }

                    val weightTextColor = when {
                        bodyWeightSetData.additionalWeight == previousBodyWeightSetData.additionalWeight -> textColor
                        bodyWeightSetData.additionalWeight < previousBodyWeightSetData.additionalWeight  -> Red
                        else -> Green
                    }

                    val repsTextColor = when {
                        bodyWeightSetData.actualReps == previousBodyWeightSetData.actualReps -> textColor
                        bodyWeightSetData.actualReps < previousBodyWeightSetData.actualReps  -> Red
                        else -> Green
                    }

                    ScalableText(
                        modifier = Modifier.weight(2f),
                        text = weightText,
                        style = itemStyle,
                        textAlign = TextAlign.Center,
                        color = weightTextColor
                    )
                    ScalableText(
                        modifier = Modifier.weight(1f),
                        text = "${bodyWeightSetData.actualReps}",
                        style = itemStyle,
                        textAlign = TextAlign.Center,
                        color = repsTextColor
                    )
                }

                is TimedDurationSetData -> {
                    val timedDurationSetData = (setState.currentSetData as TimedDurationSetData)

                    ScalableText(
                        modifier = Modifier.weight(1f),
                        text = FormatTime(timedDurationSetData.startTimer / 1000),
                        style = itemStyle.copy(fontFamily = FontFamily.Monospace),
                        textAlign = TextAlign.Center,
                        color = textColor
                    )
                    Spacer(modifier = Modifier.width(18.dp))
                }

                is EnduranceSetData -> {
                    val enduranceSetData = (setState.currentSetData as EnduranceSetData)

                    ScalableText(
                        modifier = Modifier.weight(1f),
                        text = FormatTime(enduranceSetData.startTimer / 1000),
                        style = itemStyle.copy(fontFamily = FontFamily.Monospace),
                        textAlign = TextAlign.Center,
                        color = textColor
                    )
                    Spacer(modifier = Modifier.width(18.dp))
                }

                else -> throw RuntimeException("Unsupported set type")
            }
        }

        if(markAsDone){
            Spacer(
                modifier = Modifier
                    .align(Alignment.Center)
                    .fillMaxWidth()
                    .padding(horizontal = 2.5.dp)
                    .height(2.dp)
                    .background(textColor)
                    .clip(RoundedCornerShape(50))
            )
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
    customMarkAsDone: Boolean? = null,
    customBackgroundColor: Color? = null,
    customTextColor: Color? = null,
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
            delay(500)
            scrollState.animateScrollTo(position)
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
    ) {
        val backgroundColor = customBackgroundColor ?: when{
            rowIndex < setIndex -> MaterialTheme.colorScheme.primary
            rowIndex == setIndex ->  MaterialTheme.colorScheme.onBackground
            else -> MaterialTheme.colorScheme.surfaceContainerHigh
        }

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(27.5.dp)
                .padding(horizontal = 10.dp)
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
            verticalAlignment = Alignment.CenterVertically
        ) {
            val shape = RoundedCornerShape(25)

            SetTableRow(
                modifier = Modifier
                    .height(25.dp)
                    .padding(bottom = 2.5.dp)
                    .border(BorderStroke(1.dp, backgroundColor), shape)
                    .clip(shape),
                hapticsViewModel = hapticsViewModel,
                viewModel = viewModel,
                setState = setStateForThisRow,
                index = rowIndex,
                isCurrentSet = rowIndex == setIndex, // setIndex from ExerciseSetsViewer's scope
                markAsDone = false, // customMarkAsDone ?: (rowIndex < setIndex),
                textColor = customTextColor
                    ?: when {
                        rowIndex < setIndex -> MaterialTheme.colorScheme.primary //.background.copy(0.75f)// MaterialTheme.colorScheme.primary, LightGray, MediumLightGray from outer scope
                        rowIndex == setIndex -> MaterialTheme.colorScheme.onBackground
                        else -> MaterialTheme.colorScheme.surfaceContainerHigh
                    }
            )
        }
    }

    val prototypeItem = @Composable {
        MeasuredSetTableRow(setStateForThisRow = exerciseSetStates[0], rowIndex = 0)
    }

    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(2.5.dp)
    ) {
        if (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 10.dp),
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
                        MeasuredSetTableRow(nextSetState, index)
                    }
                }
            }
        }

        if (exercise.exerciseType == ExerciseType.COUNTUP || exercise.exerciseType == ExerciseType.COUNTDOWN) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 10.dp),
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
                        MeasuredSetTableRow(nextSetState, index)
                    }
                }
            }
        }
    }
}