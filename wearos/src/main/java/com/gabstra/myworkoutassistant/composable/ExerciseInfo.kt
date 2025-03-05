package com.gabstra.myworkoutassistant.composable

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowForward
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.FormatTime
import com.gabstra.myworkoutassistant.data.WorkoutState
import com.gabstra.myworkoutassistant.data.verticalColumnScrollbar
import com.gabstra.myworkoutassistant.presentation.theme.MyColors
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.launch


@Composable
fun SetTableRow(
    modifier: Modifier = Modifier,
    setState: WorkoutState.Set,
    index: Int?,
    color: Color = Color.Unspecified,
){
    Row(
        modifier = modifier,
        verticalAlignment = Alignment.CenterVertically
    ) {
/*        if(index != null){
            Text(
                modifier = Modifier.weight(1f),
                text = "${index + 1}",
                style =  MaterialTheme.typography.body1,
                textAlign = TextAlign.Center,
                color = color
            )
        }*/
        when (setState.currentSetData) {
            is WeightSetData -> {
                val weightSetData = (setState.currentSetData as WeightSetData)
                Text(
                    modifier = Modifier.weight(1f),
                    text = "${weightSetData.actualWeight}",
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
                val bodyWeightSetData = (setState.currentSetData as BodyWeightSetData)
                Text(
                    modifier = Modifier.weight(1f),
                    text = if (bodyWeightSetData.additionalWeight > 0) {
                        "${bodyWeightSetData.additionalWeight}"
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

                Text(
                    modifier = Modifier.weight(1f),
                    text = FormatTime(timedDurationSetData.startTimer / 1000),
                    style = MaterialTheme.typography.body1,
                    textAlign = TextAlign.Center,
                    color = color
                )
            }

            is EnduranceSetData -> {
                val enduranceSetData = (setState.currentSetData as EnduranceSetData)

                Text(
                    modifier = Modifier.weight(1f),
                    text = FormatTime(enduranceSetData.startTimer / 1000),
                    style = MaterialTheme.typography.body1,
                    textAlign = TextAlign.Center,
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
    currentSet: com.gabstra.myworkoutassistant.shared.sets.Set
){
    val exerciseSets = exercise.sets.filter { it !is RestSet }
    val setIndex = exerciseSets.indexOf(currentSet)
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
        if (!allItemsMeasured.value) {
            return@LaunchedEffect
        }
        // Calculate position including spacing
        val spacingHeight = with(density) { 5.dp.toPx().toInt() }
        val position = (0 until setIndex).sumOf { index ->
            (itemHeights[index] ?: 0) + spacingHeight
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
/*                Text(
                    modifier = Modifier.weight(1f),
                    text = "#",
                    style = headerStyle,
                    textAlign = TextAlign.Center
                )*/
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
                        scrollBarColor = Color.White,
                        scrollBarTrackColor = Color.DarkGray
                    )
                    .verticalScroll(scrollState),
                verticalArrangement = Arrangement.spacedBy(5.dp),
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
                        color = when{
                            index < setIndex -> Color.Unspecified
                            index == setIndex -> MyColors.Orange
                            else ->  Color.DarkGray
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
                        scrollBarColor = Color.White,
                        scrollBarTrackColor = Color.DarkGray
                    )
                    .verticalScroll(scrollState),
                verticalArrangement = Arrangement.spacedBy(5.dp),
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
                        color = when{
                            index < setIndex -> Color.Unspecified
                            index == setIndex -> MyColors.Orange
                            else ->  Color.DarkGray
                        }
                    )
                }
            }
            return
        }
    }
}

@Composable
fun ExerciseInfo(
    modifier: Modifier = Modifier,
    viewModel: AppViewModel,
    nextStateSets: List<WorkoutState.Set>,
) {
    var marqueeEnabled by remember { mutableStateOf(false) }
    var currentIndex by remember { mutableIntStateOf(0) }
    var selectedStateSet by remember { mutableStateOf(nextStateSets[currentIndex]) }

    val typography = MaterialTheme.typography
    val style = remember { typography.body1.copy(fontSize = typography.body1.fontSize * 0.625f) }

    AnimatedContent(
        modifier = modifier,
        targetState = selectedStateSet,
        transitionSpec = {
            fadeIn(animationSpec = tween(500)) togetherWith fadeOut(animationSpec = tween(500))
        }, label = ""
    ) { updatedStateSet ->
        val exercise = remember(updatedStateSet) { viewModel.exercisesById[updatedStateSet.exerciseId]!! }
        val exerciseSets = remember(updatedStateSet) {  exercise.sets.filter { it !is RestSet } }
        val setIndex = remember(updatedStateSet) { exerciseSets.indexOf(updatedStateSet.set)  }

        Column(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.spacedBy(5.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(5.dp)
            ) {
                if (nextStateSets.size > 1) {
                    Icon(
                        modifier = Modifier.clickable {
                            if (currentIndex > 0) {
                                currentIndex--
                                selectedStateSet = nextStateSets[currentIndex]
                            }
                        },
                        imageVector = Icons.Filled.ArrowBack,
                        contentDescription = "Previous",
                        tint = if (currentIndex > 0) Color.White else Color.DarkGray
                    )
                }

                Box(
                    modifier = Modifier
                        .weight(1f)
                        .clickable { marqueeEnabled = !marqueeEnabled }
                        .then(if (marqueeEnabled) Modifier.basicMarquee(iterations = Int.MAX_VALUE) else Modifier),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = exercise.name,
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.title3,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }

                if (nextStateSets.size > 1) {
                    Icon(
                        modifier = Modifier.clickable {
                            if (currentIndex < nextStateSets.size - 1) {
                                currentIndex++
                                selectedStateSet = nextStateSets[currentIndex]
                            }
                        },
                        imageVector = Icons.Filled.ArrowForward,
                        contentDescription = "Next",
                        tint = if (currentIndex < nextStateSets.size - 1) Color.White else Color.DarkGray
                    )
                }
            }

            ExerciseSetsViewer(
                modifier =  Modifier.height(80.dp),
                viewModel = viewModel,
                exercise = exercise,
                currentSet = updatedStateSet.set
            )

            Text(
                textAlign = TextAlign.Center,
                text = "SET: ${setIndex + 1}/${exerciseSets.size}",
                style = style
            )
        }
    }
}