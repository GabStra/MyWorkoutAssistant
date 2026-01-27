package com.gabstra.myworkoutassistant.workout

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
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.CalibrationHelper
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise

fun FormatTime(seconds: Int): String {
    val hours = seconds / 3600
    val minutes = (seconds % 3600) / 60
    val remainingSeconds = seconds % 60
    return if (hours > 0) {
        String.format("%02d:%02d:%02d", hours, minutes, remainingSeconds)
    } else {
        String.format("%02d:%02d", minutes, remainingSeconds)
    }
}

fun Modifier.scrim(visible: Boolean, color: Color) = this.then(
    if (!visible) Modifier
    else Modifier
        .drawWithContent {
            drawContent()
            drawRect(color) // overlay on top
        }
        .pointerInput(Unit) { // swallow all pointer events while visible
            awaitPointerEventScope {
                while (true) {
                    val event = awaitPointerEvent()
                    event.changes.forEach { it.consume() }
                }
            }
        }
)

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun SetTableRow(
    hapticsViewModel: HapticsViewModel,
    viewModel: WorkoutViewModel,
    modifier: Modifier = Modifier,
    setState: WorkoutState.Set,
    index: Int?,
    isCurrentSet: Boolean,
    markAsDone: Boolean,
    color: Color = MaterialTheme.colorScheme.onBackground,
    weightTextColor: Color? = null, // Separate color for weight text (defaults to color if not specified)
    isFutureExercise: Boolean = false,
){
    val captionStyle = MaterialTheme.typography.titleSmall
    val equipment = setState.equipment

    val typography = MaterialTheme.typography
    val itemStyle = remember(typography) { typography.displayLarge.copy(fontWeight = FontWeight.Bold) }


    val warmupIndicatorComposable = @Composable{
        Box(modifier= Modifier.width(36.dp), contentAlignment = Alignment.Center){
            Text(
                text = "W",
                style = captionStyle,
                textAlign = TextAlign.Center,
                color = color
            )
        }
    }

    Box(
        modifier = modifier,
    ){
        Row(
            modifier = Modifier.fillMaxSize(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            val exercise = viewModel.exercisesById[setState.exerciseId]
            val isCalibrationEnabled = exercise?.requiresLoadCalibration ?: false
            
            val isWarmupSet = when(val set = setState.set) {
                is BodyWeightSet -> set.subCategory == SetSubCategory.WarmupSet
                is WeightSet -> set.subCategory == SetSubCategory.WarmupSet
                else -> false
            }
            
            val isCalibrationSet = when(val set = setState.set) {
                is BodyWeightSet -> set.subCategory == SetSubCategory.CalibrationSet
                is WeightSet -> set.subCategory == SetSubCategory.CalibrationSet
                else -> false
            }
            
            val currentWorkoutState by viewModel.workoutState.collectAsState()
            val isPendingCalibration = CalibrationHelper.isPendingCalibration(
                currentWorkoutState,
                viewModel.allWorkoutStates,
                setState,
                isCalibrationEnabled,
                isWarmupSet,
                isCalibrationSet,
                isFutureExercise
            )
            
            if(isWarmupSet){
                warmupIndicatorComposable()
            }else{
                Spacer(modifier = Modifier.width(36.dp))
            }
            val actualWeightTextColor = weightTextColor ?: color
            
            when (setState.currentSetData) {
                is WeightSetData -> {
                    val weightSetData = (setState.currentSetData as WeightSetData)
                    val weightText = equipment!!.formatWeight(weightSetData.actualWeight)
                    val displayWeightText = when {
                        isCalibrationSet -> "$weightText (Cal)"
                        isPendingCalibration -> "$weightText (Pending)"
                        else -> weightText
                    }
                    ScalableText(
                        modifier = Modifier
                            .weight(2f),
                        text = displayWeightText,
                        style = itemStyle,
                        textAlign = TextAlign.Center,
                        color = actualWeightTextColor
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
                    val baseWeightText = if(setState.equipment != null && bodyWeightSetData.additionalWeight != 0.0) {
                        setState.equipment!!.formatWeight(bodyWeightSetData.additionalWeight)
                    }else {
                        "-"
                    }
                    val weightText = when {
                        isCalibrationSet && setState.equipment != null && bodyWeightSetData.additionalWeight != 0.0 -> "$baseWeightText (Cal)"
                        isPendingCalibration && setState.equipment != null && bodyWeightSetData.additionalWeight != 0.0 -> "$baseWeightText (Pending)"
                        else -> baseWeightText
                    }

                    ScalableText(
                        modifier = Modifier
                            .weight(2f),
                        text = weightText,
                        style = itemStyle,
                        textAlign = TextAlign.Center,
                        color = actualWeightTextColor
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
                        style = itemStyle.copy(fontFamily = FontFamily.Monospace),
                        textAlign = TextAlign.Center,
                        color = color
                    )
                    Spacer(modifier = Modifier.width(36.dp))
                }

                is EnduranceSetData -> {
                    val enduranceSetData = (setState.currentSetData as EnduranceSetData)

                    ScalableText(
                        modifier = Modifier.weight(1f),
                        text = FormatTime(enduranceSetData.startTimer / 1000),
                        style = itemStyle.copy(fontFamily = FontFamily.Monospace),
                        textAlign = TextAlign.Center,
                        color = color
                    )
                    Spacer(modifier = Modifier.width(36.dp))
                }

                else -> throw RuntimeException("Unsupported set type")
            }
        }

        if(markAsDone){
            HorizontalDivider(
                modifier = Modifier
                    .align(Alignment.Center)
                    .padding(horizontal = 5.dp),
                color = color
            )
        }
    }


}

@Composable
fun ExerciseSetsViewer(
    modifier: Modifier = Modifier,
    viewModel: WorkoutViewModel,
    hapticsViewModel: HapticsViewModel,
    exercise: Exercise,
    currentSet: Set,
    customColor: Color? = null, // Deprecated: use customBorderColor and customTextColor instead
    customBorderColor: Color? = null,
    customTextColor: Color? = null,
    customMarkAsDone: Boolean? = null,
    overrideSetIndex: Int? = null,
    isFutureExercise: Boolean = false,
){
    val exerciseSetIds = viewModel.setsByExerciseId[exercise.id]!!.map { it.set.id }
    val setIndex = overrideSetIndex ?: exerciseSetIds.indexOf(currentSet.id)

    val exerciseSetStates = remember(exercise.id) {
        viewModel.getAllExerciseWorkoutStates(exercise.id)
            .filter { it.set !is RestSet }
            .distinctBy { it.set.id }
    }

    val headerStyle = MaterialTheme.typography.bodySmall

    val scrollState = rememberScrollState()
    val density = LocalDensity.current
    
    // Calculate item height: 30.dp (row height) + 2.5.dp (spacing) = 32.5.dp per item
    val itemHeightDp = 30.0.dp

    // Reset scroll position immediately when exercise changes
    LaunchedEffect(exercise.id) {
        scrollState.animateScrollTo(0)
    }

    // Scroll to current set when it changes
    LaunchedEffect(setIndex, exercise.id) {
        if (setIndex != -1 && setIndex < exerciseSetStates.size) {
            val scrollPosition = with(density) { (setIndex * itemHeightDp.toPx()).toInt() }
            scrollState.animateScrollTo(scrollPosition)
        } else {
            scrollState.animateScrollTo(0)
        }
    }

    @Composable
    fun MeasuredSetTableRow(
        setStateForThisRow:  WorkoutState.Set,
        rowIndex: Int,
        isFutureExerciseParam: Boolean = isFutureExercise,
    ) {
        val backgroundColor = if(rowIndex == setIndex)
            MaterialTheme.colorScheme.primary
        else
            MaterialTheme.colorScheme.surfaceVariant

        val borderColor = customBorderColor ?: customColor ?: null

        val textColor = customTextColor ?: customColor ?: when {
            rowIndex < setIndex -> MaterialTheme.colorScheme.onBackground
            rowIndex == setIndex -> MaterialTheme.colorScheme.onPrimary
            else -> MaterialTheme.colorScheme.onBackground
        }

        val weightTextColor = customTextColor ?: customColor ?: when {
            rowIndex < setIndex -> MaterialTheme.colorScheme.onBackground
            rowIndex == setIndex -> MaterialTheme.colorScheme.onPrimary
            else -> MaterialTheme.colorScheme.onBackground
        }

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(30.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            SetTableRow(
                modifier = Modifier
                    .height(27.5.dp)
                    .padding(bottom = 2.5.dp)
                    .clip(RoundedCornerShape(25))
                    .then(
                        if (borderColor != null) {
                            Modifier.border(BorderStroke(1.dp, borderColor), RoundedCornerShape(25))
                        } else {
                            Modifier
                        }
                    )
                    .background(backgroundColor),
                hapticsViewModel = hapticsViewModel, // Accessed from ExerciseSetsViewer's scope
                viewModel = viewModel,               // Accessed from ExerciseSetsViewer's scope
                setState = setStateForThisRow,
                index = rowIndex, // This 'index' prop for SetTableRow might refer to its position in the overall exercise
                isCurrentSet = rowIndex == setIndex, // setIndex from ExerciseSetsViewer's scope
                markAsDone = customMarkAsDone ?: (rowIndex < setIndex),
                color = textColor,
                weightTextColor = weightTextColor,
                isFutureExercise = isFutureExerciseParam
            )
        }
    }

    val prototypeItem = @Composable {
        MeasuredSetTableRow(setStateForThisRow = exerciseSetStates[0], rowIndex = 0)
    }

    Column{
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
                        .verticalScroll(scrollState)
                ) {
                    exerciseSetStates.forEachIndexed { index, setState ->
                        MeasuredSetTableRow(setState, index)
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
                        .verticalScroll(scrollState)
                ) {
                    exerciseSetStates.forEachIndexed { index, setState ->
                        MeasuredSetTableRow(setState, index)
                    }
                }
            }
        }
    }
}
