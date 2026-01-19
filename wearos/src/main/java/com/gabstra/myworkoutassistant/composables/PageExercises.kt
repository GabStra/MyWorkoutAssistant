package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.BaselineShift
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.LighterGray
import com.gabstra.myworkoutassistant.shared.MediumLighterGray
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun PageExercises(
    selectedExercise : Exercise,
    currentStateSet: WorkoutState.Set,
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    currentExercise: Exercise,
    exerciseOrSupersetIds: List<java.util.UUID>,
    onExerciseSelected: (Exercise) -> Unit
) {
    val exerciseIds = viewModel.setsByExerciseId.keys.toList()

    var marqueeEnabled by remember { mutableStateOf(false) }
    var headerMarqueeEnabled by remember { mutableStateOf(false) }

    val currentExerciseOrSupersetId =
        remember(currentExercise.id) {
            if (viewModel.supersetIdByExerciseId.containsKey(currentExercise.id)) viewModel.supersetIdByExerciseId[currentExercise.id] else currentExercise.id
        }
    val currentExerciseOrSupersetIndex = remember(currentExerciseOrSupersetId, exerciseOrSupersetIds) {
        derivedStateOf { exerciseOrSupersetIds.indexOf(currentExerciseOrSupersetId) }
    }

    val isSuperset = remember(currentExerciseOrSupersetId) {
        viewModel.exercisesBySupersetId.containsKey(currentExerciseOrSupersetId)
    }

    val overrideSetIndex = remember(isSuperset, currentExercise) {
        if (isSuperset) {
            viewModel.setsByExerciseId[currentExercise.id]!!.map { it.set.id }
                .indexOf(currentStateSet.set.id)
        } else null
    }

    // Optimize: Use setsByExerciseId which is already cached in viewModel instead of filtering allWorkoutStates
    val currentExerciseSetIds = remember(currentExercise.id) {
        viewModel.setsByExerciseId[currentExercise.id]?.map { it.set.id } ?: emptyList()
    }

    Box(modifier = Modifier.fillMaxSize()) {
        val selectedExerciseOrSupersetId = remember(selectedExercise) {
            if (viewModel.supersetIdByExerciseId.containsKey(selectedExercise.id)) viewModel.supersetIdByExerciseId[selectedExercise.id]!! else selectedExercise.id
        }
        val selectedExerciseOrSupersetIndex = remember(selectedExerciseOrSupersetId, exerciseOrSupersetIds) {
            derivedStateOf { exerciseOrSupersetIds.indexOf(selectedExerciseOrSupersetId) }
        }

        val isSuperset = remember(selectedExerciseOrSupersetId) {
            viewModel.exercisesBySupersetId.containsKey(selectedExerciseOrSupersetId)
        }

        val currentIndex = remember(selectedExercise.id, exerciseIds) {
            derivedStateOf { exerciseIds.indexOf(selectedExercise.id) }
        }

        Column(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.spacedBy(5.dp,Alignment.CenterVertically),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            ScalableText(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(20.dp)
                    .padding(horizontal = 22.5.dp)
                    .clickable {
                        marqueeEnabled = !marqueeEnabled
                        hapticsViewModel.doGentleVibration()
                    },
                text = selectedExercise.name,
                textModifier = if (marqueeEnabled) Modifier.basicMarquee(iterations = Int.MAX_VALUE) else Modifier,
                textAlign = TextAlign.Center,
                contentAlignment = Alignment.BottomCenter,
                style = MaterialTheme.typography.titleMedium.copy(
                    fontWeight = FontWeight.SemiBold
                ),
                overflow = TextOverflow.Ellipsis
            )

            val baseStyle = MaterialTheme.typography.bodySmall
            val topLine = buildAnnotatedString {
                fun pipe() {
                    withStyle(
                        baseStyle.toSpanStyle().copy(
                            color = MediumLighterGray,
                            fontWeight = FontWeight.Thin
                        )
                    ) {
                        append(" | ")
                    }
                }
                fun separator() {
                    withStyle(baseStyle.toSpanStyle().copy(
                        color = MediumLighterGray,
                        baselineShift = BaselineShift(0.18f)
                    )) { // tweak 0.12–0.25f as needed
                        append( "↔")
                    }
                }

                withStyle(baseStyle.toSpanStyle().copy(color = MediumLighterGray)) {
                    append("Ex: ")
                }
                append("${selectedExerciseOrSupersetIndex.value + 1}/${exerciseOrSupersetIds.size}")

                if(currentExercise == selectedExercise) {
                    if (currentExerciseSetIds.size > 1) {
                        pipe()
                        val setIndex = remember (currentStateSet.set.id){ currentExerciseSetIds.indexOf(currentStateSet.set.id) }
                        withStyle(baseStyle.toSpanStyle().copy(color = MediumLighterGray)) {
                            append("Set: ")
                        }
                        append("${setIndex + 1}/${currentExerciseSetIds.size}")
                    }


                    if (currentStateSet.intraSetTotal != null){
                        pipe()

                        withStyle(
                            SpanStyle(
                                color = if (currentStateSet.intraSetCounter == 1u) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceContainerHigh,
                                fontWeight = FontWeight.Bold
                            )
                        ) {
                            append("①")
                        }
                        separator()
                        withStyle(
                            SpanStyle(
                                color = if (currentStateSet.intraSetCounter == 2u) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceContainerHigh,
                                fontWeight = FontWeight.Bold
                            )
                        ) {
                            append("②")
                        }
                    }
                }

                if (isSuperset) {
                    pipe()
                    val supersetExercises =
                        remember(selectedExerciseOrSupersetId) { viewModel.exercisesBySupersetId[selectedExerciseOrSupersetId]!! }

                    val currentIdx = remember(supersetExercises, selectedExercise) {
                        supersetExercises.indexOf(selectedExercise)
                    }

                    supersetExercises.indices.forEach { i ->
                        if (i > 0) { separator() }
                        withStyle(
                            SpanStyle(
                                color = if (i == currentIdx) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceContainerHigh,
                                fontWeight = FontWeight.Bold
                            )
                        ) {
                            append(('A' + i).toString())
                        }
                    }
                }


            }

            Text(
                text = topLine,
                style = baseStyle,
                textAlign = TextAlign.Center,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.clickable {
                    headerMarqueeEnabled = !headerMarqueeEnabled
                    hapticsViewModel.doGentleVibration()
                }
                .then(if (headerMarqueeEnabled) Modifier.basicMarquee(iterations = Int.MAX_VALUE) else Modifier)
            )

            ExerciseSetsViewer(
                viewModel = viewModel,
                hapticsViewModel = hapticsViewModel,
                exercise = selectedExercise,
                currentSet = currentStateSet.set,
                customMarkAsDone = when {
                    selectedExerciseOrSupersetIndex.value < currentExerciseOrSupersetIndex.value -> true
                    selectedExerciseOrSupersetIndex.value > currentExerciseOrSupersetIndex.value -> false
                    else -> null
                },
                customBorderColor = when {
                    // Previous exercise: enforce previous set colors for ALL sets
                    selectedExerciseOrSupersetIndex.value < currentExerciseOrSupersetIndex.value -> MaterialTheme.colorScheme.onBackground
                    // Future exercise: enforce future set colors for ALL sets
                    selectedExerciseOrSupersetIndex.value > currentExerciseOrSupersetIndex.value -> MaterialTheme.colorScheme.surfaceContainerHigh
                    // Current exercise: use default logic (null = distinguish between previous/current/future sets)
                    else -> null
                },
                customTextColor = when {
                    // Previous exercise: enforce previous set colors for ALL sets
                    selectedExerciseOrSupersetIndex.value < currentExerciseOrSupersetIndex.value -> MaterialTheme.colorScheme.onBackground
                    // Future exercise: enforce future set colors for ALL sets
                    selectedExerciseOrSupersetIndex.value > currentExerciseOrSupersetIndex.value -> MaterialTheme.colorScheme.surfaceContainerHigh
                    // Current exercise: use default logic (null = distinguish between previous/current/future sets)
                    else -> null
                },
                overrideSetIndex = if (selectedExerciseOrSupersetIndex.value == currentExerciseOrSupersetIndex.value) {
                    overrideSetIndex
                } else null
            )
        }

        Box(modifier = Modifier.fillMaxSize()) {
            Row(
                modifier = Modifier
                    .fillMaxSize(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxHeight()
                        .weight(1f)
                        .clickable(
                            enabled = currentIndex.value > 0
                        ) {
                            hapticsViewModel.doGentleVibration()
                            val newIndex = currentIndex.value - 1
                            onExerciseSelected(viewModel.exercisesById[exerciseIds[newIndex]]!!)
                        }
                        .then(if (exerciseIds.size > 1) Modifier else Modifier.alpha(0f)),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.Center
                ) {
/*                    Icon(
                        modifier = backArrowModifier,
                        imageVector = Icons.Filled.ArrowBack,
                        contentDescription = "Previous",
                        tint = LightGray
                    )*/
                }
                Spacer(
                    modifier = Modifier
                        .fillMaxHeight()
                        .weight(1f)
                )
                Row(
                    modifier = Modifier
                        .fillMaxHeight()
                        .weight(1f)
                        .clickable(
                            enabled = currentIndex.value < exerciseIds.size - 1
                        ) {
                            hapticsViewModel.doGentleVibration()
                            val newIndex = currentIndex.value + 1
                            onExerciseSelected(viewModel.exercisesById[exerciseIds[newIndex]]!!)
                        }
                        .then(if (exerciseIds.size > 1) Modifier else Modifier.alpha(0f)),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.Center
                ) {
/*                    Icon(
                        modifier = forwardArrowModifier,
                        imageVector = Icons.Filled.ArrowForward,
                        contentDescription = "Next",
                        tint = LightGray
                    )*/
                }
            }
        }
    }
}