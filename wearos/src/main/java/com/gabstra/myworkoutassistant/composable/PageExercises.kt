package com.gabstra.myworkoutassistant.composable

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowForward
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.presentation.theme.MyColors
import com.gabstra.myworkoutassistant.shared.VibrateGentle
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.delay

@Composable
fun PageExercises(
    currentStateSet: WorkoutState.Set,
    viewModel: AppViewModel,
    currentExercise: Exercise,
) {
    val context = LocalContext.current

    val exerciseIds = viewModel.setsByExerciseId.keys.toList()
    val exerciseOrSupersetIds = remember { viewModel.setsByExerciseId.keys.toList().map { if(viewModel.supersetIdByExerciseId.containsKey(it)) viewModel.supersetIdByExerciseId[it] else it }.distinct() }

    var marqueeEnabled by remember { mutableStateOf(false) }

    val currentExerciseOrSupersetId = if(viewModel.supersetIdByExerciseId.containsKey(currentExercise.id)) viewModel.supersetIdByExerciseId[currentExercise.id] else currentExercise.id
    val currentExerciseOrSupersetIndex = exerciseOrSupersetIds.indexOf(currentExerciseOrSupersetId)

    var selectedExercise by remember { mutableStateOf(currentExercise) }

    val typography = MaterialTheme.typography
    val captionStyle = remember { typography.body1.copy(fontSize = typography.body1.fontSize * 0.625f) }

    var isNavigationLocked by remember { mutableStateOf(false) }

    val isSuperset = remember(currentExerciseOrSupersetId) { viewModel.exercisesBySupersetId.containsKey(currentExerciseOrSupersetId) }

    val overrideSetIndex = remember(isSuperset,currentExercise){
        if(isSuperset){
            viewModel.setsByExerciseId[currentExercise.id]!!.map { it.set.id }.indexOf(currentStateSet.set.id)
        }
        else null
    }

    LaunchedEffect(isNavigationLocked) {
        if (isNavigationLocked) {
            delay(500)
            isNavigationLocked = false
        }
    }

    AnimatedContent(
        modifier = Modifier.fillMaxSize(),
        targetState = selectedExercise,
        transitionSpec = {
            fadeIn(animationSpec = tween(500)) togetherWith fadeOut(animationSpec = tween(500))
        },
        label = "",
    ) { updatedExercise ->
        val updatedExerciseOrSupersetId = remember(updatedExercise) { if(viewModel.supersetIdByExerciseId.containsKey(updatedExercise.id)) viewModel.supersetIdByExerciseId[updatedExercise.id] else updatedExercise.id }
        val updatedExerciseOrSupersetIndex =  remember(updatedExerciseOrSupersetId) {exerciseOrSupersetIds.indexOf(updatedExerciseOrSupersetId) }

        val isSuperset = remember(updatedExerciseOrSupersetId) { viewModel.exercisesBySupersetId.containsKey(updatedExerciseOrSupersetId) }

        val currentIndex = remember(updatedExercise) { exerciseIds.indexOf(updatedExercise.id) }

        Row(
            modifier = Modifier.fillMaxSize(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Row(
                modifier = Modifier
                    .fillMaxHeight()
                    .clickable(enabled = !isNavigationLocked && currentIndex > 0) {
                        VibrateGentle(context)
                        val newIndex = currentIndex - 1
                        selectedExercise = viewModel.exercisesById[exerciseIds[newIndex]]!!
                        isNavigationLocked = true
                    }.then( if (exerciseIds.size > 1) Modifier else Modifier.alpha(0f)),
                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.Center) {
                Icon(
                    modifier = Modifier
                        .padding(2.dp),
                    imageVector = Icons.Filled.ArrowBack,
                    contentDescription = "Previous",
                    tint = if (currentIndex > 0) Color.White else Color.DarkGray
                )
            }



            Column(
                modifier = Modifier.fillMaxHeight().weight(1f),
                verticalArrangement = Arrangement.spacedBy(5.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable {
                            marqueeEnabled = !marqueeEnabled
                            VibrateGentle(context)
                        }
                        .then(if (marqueeEnabled) Modifier.basicMarquee(iterations = Int.MAX_VALUE) else Modifier),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = updatedExercise.name,
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.title3,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.Center
                ) {
                    Row(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                        Text(
                            textAlign = TextAlign.Center,
                            text = "${updatedExerciseOrSupersetIndex + 1}/${exerciseOrSupersetIds.size}",
                            style = captionStyle
                        )
                        if (isSuperset) {
                            val supersetExercises =
                                remember { viewModel.exercisesBySupersetId[updatedExerciseOrSupersetId]!! }
                            val supersetIndex = remember { supersetExercises.indexOf(updatedExercise) }

                            Text(
                                textAlign = TextAlign.Center,
                                text = "${supersetIndex + 1}/${supersetExercises.size}",
                                style = captionStyle
                            )
                        }

                        if (updatedExercise.id == currentExercise.id) {
                            val exerciseSetIds =
                                remember { viewModel.setsByExerciseId[updatedExercise.id]!!.map { it.set.id } }
                            val setIndex = remember { exerciseSetIds.indexOf(currentStateSet.set.id) }

                            Text(
                                textAlign = TextAlign.Center,
                                text = "${setIndex + 1}/${exerciseSetIds.size}",
                                style = captionStyle
                            )
                        }
                    }
                }

                ExerciseSetsViewer(
                    modifier =  Modifier.height(76.dp).fillMaxWidth(),
                    viewModel = viewModel,
                    exercise = updatedExercise,
                    currentSet = currentStateSet.set,
                    customColor = when{
                        updatedExerciseOrSupersetIndex < currentExerciseOrSupersetIndex -> MyColors.Orange
                        updatedExerciseOrSupersetIndex > currentExerciseOrSupersetIndex -> Color.DarkGray
                        else -> null
                    },
                    overrideSetIndex = if(updatedExerciseOrSupersetIndex == currentExerciseOrSupersetIndex) {
                        overrideSetIndex
                    }
                    else null
                )
            }

            Row(
                modifier = Modifier
                    .fillMaxHeight()
                    .clickable(enabled = !isNavigationLocked && currentIndex < exerciseIds.size - 1) {
                        VibrateGentle(context)
                        val newIndex = currentIndex + 1
                        selectedExercise = viewModel.exercisesById[exerciseIds[newIndex]]!!
                        isNavigationLocked = true
                    }.then( if (exerciseIds.size > 1) Modifier else Modifier.alpha(0f)),
                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.Center) {
                Icon(
                    modifier = Modifier
                        .padding(2.dp),
                    imageVector = Icons.Filled.ArrowForward,
                    contentDescription = "Next",
                    tint = if (currentIndex < exerciseIds.size - 1) Color.White else Color.DarkGray
                )
            }

        }
    }
}