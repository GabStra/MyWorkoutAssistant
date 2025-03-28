package com.gabstra.myworkoutassistant.screens

import android.util.Log
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
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowForward
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
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
import androidx.compose.ui.tooling.preview.Devices
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.wear.compose.foundation.lazy.ScalingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberScalingLazyListState
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text

import com.gabstra.myworkoutassistant.composable.BodyWeightSetScreen
import com.gabstra.myworkoutassistant.composable.ButtonWithText
import com.gabstra.myworkoutassistant.composable.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composable.CustomHorizontalPager
import com.gabstra.myworkoutassistant.composable.EnduranceSetScreen
import com.gabstra.myworkoutassistant.composable.ExerciseIndicator
import com.gabstra.myworkoutassistant.composable.ExerciseSetsViewer
import com.gabstra.myworkoutassistant.composable.PageButtons
import com.gabstra.myworkoutassistant.composable.PageExerciseDetail
import com.gabstra.myworkoutassistant.composable.PageExercises
import com.gabstra.myworkoutassistant.composable.PageNotes
import com.gabstra.myworkoutassistant.composable.PagePlates
import com.gabstra.myworkoutassistant.composable.TimedDurationSetScreen
import com.gabstra.myworkoutassistant.composable.WeightSetScreen
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.VibrateGentle
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.gabstra.myworkoutassistant.data.circleMask
import com.gabstra.myworkoutassistant.data.verticalColumnScrollbar
import com.gabstra.myworkoutassistant.presentation.theme.MyColors
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Equipment
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.PlateCalculator
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import java.time.LocalDateTime
import java.util.UUID

enum class PageType {
    PLATES, EXERCISE_DETAIL, EXERCISES, NOTES, BUTTONS
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun ExerciseScreen(
    viewModel: AppViewModel,
    state: WorkoutState.Set,
    hearthRateChart: @Composable () -> Unit,
) {
    var allowHorizontalScrolling by remember { mutableStateOf(true) }
    val showNextDialog by viewModel.isCustomDialogOpen.collectAsState()

    val exercise = remember(state.exerciseId) {
        viewModel.exercisesById[state.exerciseId]!!
    }

    val exerciseSetIds = remember(exercise) {
        viewModel.setsByExerciseId[exercise.id]!!.map { it.set.id }
    }

    val equipment = remember(exercise) {
        exercise.equipmentId?.let { viewModel.getEquipmentById(it) }
    }

    val showPlatesPage = remember(exercise, equipment) {
        equipment != null
                && equipment.type == EquipmentType.BARBELL
                && equipment.name.contains("barbell", ignoreCase = true)
                && (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT)
    }

    val showNotesPage = remember(exercise) {
        exercise.notes.isNotEmpty()
    }

    val pageTypes = remember(showPlatesPage, showNotesPage) {
        mutableListOf<PageType>().apply {
            if (showPlatesPage) add(PageType.PLATES)
            add(PageType.EXERCISE_DETAIL)
            add(PageType.EXERCISES)
            if (showNotesPage) add(PageType.NOTES)
            add(PageType.BUTTONS)
        }
    }

    // Find index of exercise detail page to scroll to on changes
    val exerciseDetailPageIndex = remember(pageTypes) {
        pageTypes.indexOf(PageType.EXERCISE_DETAIL).coerceAtLeast(0)
    }

    val pagerState = rememberPagerState(
        initialPage = exerciseDetailPageIndex,
        pageCount = {
            pageTypes.size
        }
    )

    LaunchedEffect(state.set.id) {
        // Navigate to the exercise detail page
        pagerState.scrollToPage(exerciseDetailPageIndex)
        allowHorizontalScrolling = true
        viewModel.closeCustomDialog()
    }

    LaunchedEffect(allowHorizontalScrolling, pageTypes) {
        if (!allowHorizontalScrolling && pageTypes.getOrNull(pagerState.currentPage) == PageType.PLATES) {
            pagerState.scrollToPage(exerciseDetailPageIndex)
        }
    }

    var marqueeEnabled by remember { mutableStateOf(false) }

    val typography = MaterialTheme.typography
    val captionStyle = remember { typography.body1.copy(fontSize = typography.body1.fontSize * 0.625f) }

    val exerciseOrSupersetIds = remember { viewModel.setsByExerciseId.keys.toList().map { if(viewModel.supersetIdByExerciseId.containsKey(it)) viewModel.supersetIdByExerciseId[it] else it }.distinct() }
    val exerciseOrSupersetId = remember(state.exerciseId) { if(viewModel.supersetIdByExerciseId.containsKey(state.exerciseId)) viewModel.supersetIdByExerciseId[state.exerciseId] else state.exerciseId }
    val currentExerciseOrSupersetIndex = remember(exerciseOrSupersetId) { exerciseOrSupersetIds.indexOf(exerciseOrSupersetId) }
    val isSuperset =  remember(exerciseOrSupersetId) { viewModel.exercisesBySupersetId.containsKey(exerciseOrSupersetId) }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(5.dp)
            .circleMask(),
        contentAlignment = Alignment.Center
    ) {
        AnimatedContent(
            targetState = state,
            transitionSpec = {
                fadeIn(animationSpec = tween(500)) togetherWith fadeOut(animationSpec = tween(500))
            }, label = ""
        ) { updatedState ->
            val setIndex = remember(updatedState.set.id) { exerciseSetIds.indexOf(updatedState.set.id)  }

            val exerciseTitleComposable = @Composable {
                Column(modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 30.dp),
                    verticalArrangement = Arrangement.spacedBy(5.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Text(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { marqueeEnabled = !marqueeEnabled }
                            .then(if (marqueeEnabled) Modifier.basicMarquee(iterations = Int.MAX_VALUE) else Modifier),
                        text = exercise.name,
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.title3,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }
            }

            CustomHorizontalPager(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(vertical = 22.dp, horizontal = 15.dp),
                pagerState = pagerState,
                userScrollEnabled = allowHorizontalScrolling,
            ) { pageIndex ->
                // Get the page type for the current index
                val pageType = pageTypes[pageIndex]

                when (pageType) {
                    PageType.PLATES -> PagePlates(updatedState, equipment)
                    PageType.EXERCISE_DETAIL -> PageExerciseDetail(
                        updatedState = updatedState,
                        viewModel = viewModel,
                        onScrollEnabledChange = {
                            allowHorizontalScrolling = it
                        },
                        exerciseTitleComposable = exerciseTitleComposable,
                        extraInfoComposable = { _ ->
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.Center
                            ){
                                Row(horizontalArrangement = Arrangement.spacedBy(5.dp)){
                                    Text(
                                        textAlign = TextAlign.Center,
                                        text =  "${currentExerciseOrSupersetIndex + 1}/${exerciseOrSupersetIds.size}",
                                        style = captionStyle
                                    )
                                    if(isSuperset){
                                        val supersetExercises = viewModel.exercisesBySupersetId[exerciseOrSupersetId]!!
                                        val supersetIndex = supersetExercises.indexOf(exercise)

                                        Text(
                                            textAlign = TextAlign.Center,
                                            text =  "${supersetIndex + 1}/${supersetExercises.size}",
                                            style = captionStyle
                                        )
                                    }
                                    Text(
                                        textAlign = TextAlign.Center,
                                        text =  "${setIndex + 1}/${exerciseSetIds.size}",
                                        style = captionStyle
                                    )
                                }
                            }
                        }
                    )
                    PageType.EXERCISES -> PageExercises(updatedState, viewModel, exercise)
                    PageType.NOTES -> PageNotes(exercise.notes)
                    PageType.BUTTONS -> PageButtons(updatedState, viewModel)
                }
            }
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize(),
        contentAlignment = Alignment.Center
    ) {
        ExerciseIndicator(
            modifier = Modifier.fillMaxSize(),
            viewModel,
            state
        )

        hearthRateChart()
    }

    val context = LocalContext.current

    CustomDialogYesOnLongPress(
        show = showNextDialog,
        title = "Complete Set",
        message = "Do you want to proceed?",
        handleYesClick = {
            VibrateGentle(context)
            viewModel.storeSetData()
            viewModel.pushAndStoreWorkoutData(false, context) {
                viewModel.upsertWorkoutRecord(state.set.id)
                viewModel.goToNextState()
                viewModel.lightScreenUp()
            }

            viewModel.closeCustomDialog()
        },
        handleNoClick = {
            viewModel.closeCustomDialog()
            VibrateGentle(context)
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            viewModel.closeCustomDialog()
        },
        holdTimeInMillis = 1000
    )
}
