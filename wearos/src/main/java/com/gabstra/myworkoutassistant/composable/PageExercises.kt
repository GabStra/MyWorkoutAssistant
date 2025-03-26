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
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowForward
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.presentation.theme.MyColors
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.delay

@Composable
fun PageExercises(
    currentStateSet: WorkoutState.Set,
    viewModel: AppViewModel,
    currentExercise: Exercise,
) {
    val exerciseIds = viewModel.setsByExerciseId.keys.toList()
    val exerciseOrSupersetIds = remember { viewModel.setsByExerciseId.keys.toList().map { if(viewModel.supersetIdByExerciseId.containsKey(it)) viewModel.supersetIdByExerciseId[it] else it }.distinct() }

    var marqueeEnabled by remember { mutableStateOf(false) }

    val currentExerciseIndex = exerciseIds.indexOf(currentExercise.id)

    val currentExerciseOrSupersetId = if(viewModel.supersetIdByExerciseId.containsKey(currentExercise.id)) viewModel.supersetIdByExerciseId[currentExercise.id] else currentExercise.id
    val currentExerciseOrSupersetIndex = exerciseOrSupersetIds.indexOf(currentExerciseOrSupersetId)

    var currentIndex by remember { mutableIntStateOf(currentExerciseIndex) }
    var selectedExercise by remember { mutableStateOf(currentExercise) }

    val typography = MaterialTheme.typography
    val captionStyle = remember { typography.body1.copy(fontSize = typography.body1.fontSize * 0.625f) }

    var isNavigationLocked by remember { mutableStateOf(false) }

    val isSuperset = remember(currentExerciseOrSupersetId) { viewModel.exercisesBySupersetId.containsKey(currentExerciseOrSupersetId) }

    val overrideSetIndex = remember(isSuperset,currentExercise){
        if(isSuperset){
            currentExercise.sets.filter { it !is RestSet }.indexOf(currentStateSet.set)
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
        val updatedExerciseOrSupersetId = if(viewModel.supersetIdByExerciseId.containsKey(updatedExercise.id)) viewModel.supersetIdByExerciseId[updatedExercise.id] else updatedExercise.id
        val updatedExerciseOrSupersetIndex = exerciseOrSupersetIds.indexOf(updatedExerciseOrSupersetId)

        val isSuperset = viewModel.exercisesBySupersetId.containsKey(updatedExerciseOrSupersetId)

        Column(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.spacedBy(5.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 25.dp)
                    .clickable { marqueeEnabled = !marqueeEnabled }
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
                Text(
                    textAlign = TextAlign.Center,
                    text = "${updatedExerciseOrSupersetIndex + 1}/${exerciseOrSupersetIds.size}",
                    style = captionStyle
                )
                if(isSuperset){
                    Spacer(modifier = Modifier.width(5.dp))

                    val supersetExercises = remember { viewModel.exercisesBySupersetId[updatedExerciseOrSupersetId]!!  }
                    val supersetIndex = remember { supersetExercises.indexOf(updatedExercise) }

                    Text(
                        textAlign = TextAlign.Center,
                        text = "${supersetIndex + 1}/${supersetExercises.size}",
                        style = captionStyle
                    )
                }
            }

            Row(
                modifier = Modifier.height(80.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(5.dp)
            ) {
                Icon(
                    modifier = Modifier
                        .fillMaxHeight()
                        .clickable(enabled = !isNavigationLocked && currentIndex > 0) {
                            currentIndex--
                            selectedExercise = viewModel.exercisesById[exerciseIds[currentIndex]]!!
                            isNavigationLocked = true
                        }.then( if (exerciseIds.size > 1) Modifier else Modifier.alpha(0f)),
                    imageVector = Icons.Filled.ArrowBack,
                    contentDescription = "Previous",
                    tint = if (currentIndex > 0) Color.White else MyColors.MediumGray
                )

                ExerciseSetsViewer(
                    modifier =  Modifier.fillMaxHeight().weight(1f),
                    viewModel = viewModel,
                    exercise = updatedExercise,
                    currentSet = currentStateSet.set,
                    customColor =   when{
                        updatedExerciseOrSupersetIndex < currentExerciseOrSupersetIndex -> MyColors.Orange
                        updatedExerciseOrSupersetIndex > currentExerciseOrSupersetIndex -> MyColors.MediumGray
                        else -> null
                    },
                    overrideSetIndex = if(updatedExerciseOrSupersetIndex == currentExerciseOrSupersetIndex) {
                        overrideSetIndex
                    }
                    else null
                )

                Icon(
                    modifier = Modifier
                        .fillMaxHeight()
                        .clickable(enabled = !isNavigationLocked && currentIndex < exerciseIds.size - 1) {
                            currentIndex++
                            selectedExercise = viewModel.exercisesById[exerciseIds[currentIndex]]!!
                            isNavigationLocked = true
                        }.then( if (exerciseIds.size > 1) Modifier else Modifier.alpha(0f)),
                    imageVector = Icons.Filled.ArrowForward,
                    contentDescription = "Next",
                    tint = if (currentIndex < exerciseIds.size - 1) Color.White else MyColors.MediumGray
                )
            }
        }
    }
}