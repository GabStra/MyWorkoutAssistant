package com.gabstra.myworkoutassistant.screens

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.composables.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composables.CustomHorizontalPager
import com.gabstra.myworkoutassistant.composables.ExerciseDetail
import com.gabstra.myworkoutassistant.composables.ExerciseIndicator
import com.gabstra.myworkoutassistant.composables.PageButtons
import com.gabstra.myworkoutassistant.composables.PageExercises
import com.gabstra.myworkoutassistant.composables.PageNotes
import com.gabstra.myworkoutassistant.composables.PagePlates
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Orange
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

enum class PageType {
    PLATES, EXERCISE_DETAIL, EXERCISES, NOTES, BUTTONS
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun ExerciseScreen(
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
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

    val exercisesPageIndex = remember(pageTypes) {
        pageTypes.indexOf(PageType.EXERCISES)
    }

    val exerciseDetailPageIndex = remember(pageTypes) {
        pageTypes.indexOf(PageType.EXERCISE_DETAIL)
    }

    val platesPageIndex = remember(pageTypes) {
        pageTypes.indexOf(PageType.PLATES)
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

    val scope = rememberCoroutineScope()
    var goBackJob by remember { mutableStateOf<Job?>(null) }

    fun restartGoBack() {
        goBackJob?.cancel()

        goBackJob = scope.launch {
            delay(10000)
            val isOnExerciseDetailPage = pagerState.currentPage == exerciseDetailPageIndex
            val isOnPlatesPage = pagerState.currentPage == platesPageIndex
            if (!isOnExerciseDetailPage && !isOnPlatesPage) {
                pagerState.scrollToPage(exerciseDetailPageIndex)
            }
        }
    }

    var marqueeEnabled by remember { mutableStateOf(false) }

    val typography = MaterialTheme.typography
    val captionStyle = remember { typography.body1.copy(fontSize = typography.body1.fontSize * 0.625f) }

    val exerciseOrSupersetIds = remember { viewModel.setsByExerciseId.keys.toList().map { if(viewModel.supersetIdByExerciseId.containsKey(it)) viewModel.supersetIdByExerciseId[it] else it }.distinct() }
    val exerciseOrSupersetId = remember(state.exerciseId) { if(viewModel.supersetIdByExerciseId.containsKey(state.exerciseId)) viewModel.supersetIdByExerciseId[state.exerciseId] else state.exerciseId }
    val currentExerciseOrSupersetIndex = remember(exerciseOrSupersetId) { exerciseOrSupersetIds.indexOf(exerciseOrSupersetId) }
    val isSuperset =  remember(exerciseOrSupersetId) { viewModel.exercisesBySupersetId.containsKey(exerciseOrSupersetId) }

    var selectedExerciseOrSupersetIndex by remember { mutableStateOf<Int?>(null) }

    val context = LocalContext.current

    LaunchedEffect(pagerState.currentPage) {
        val isOnPlatesPage = pagerState.currentPage == platesPageIndex

        if (isOnPlatesPage) {
            viewModel.setDimming(false)
        } else {
            viewModel.reEvaluateDimmingForCurrentState()
        }

        if(pagerState.currentPage != exercisesPageIndex){
            selectedExerciseOrSupersetIndex = null
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(top = 30.dp, start = 50.dp, end = 50.dp, bottom = 30.dp),
        contentAlignment = Alignment.Center
    ) {
        AnimatedContent(
            targetState = state,
            transitionSpec = {
                fadeIn(animationSpec = tween(500)) togetherWith fadeOut(animationSpec = tween(500))
            }, label = ""
        ) { updatedState ->
            val setIndex = remember(updatedState.set.id) { exerciseSetIds.indexOf(updatedState.set.id)  }

            val exerciseTitleComposable: @Composable (onLongClick: () -> Unit) -> Unit = { providedOnLongClick ->
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(5.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Text(
                        modifier = Modifier
                            .fillMaxWidth()
                            .combinedClickable(
                                onClick = {
                                    hapticsViewModel.doGentleVibration()
                                    marqueeEnabled = !marqueeEnabled
                                },
                                onLongClick = {
                                    providedOnLongClick.invoke()
                                }
                            )
                            .then(if (marqueeEnabled) Modifier.basicMarquee(iterations = Int.MAX_VALUE) else Modifier),
                        text = exercise.name,
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.body1.copy(fontWeight = FontWeight.Bold),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }
            }

            ExerciseDetail(
                updatedState = updatedState,
                viewModel = viewModel,
                onEditModeDisabled = { allowHorizontalScrolling = true },
                onEditModeEnabled = {  allowHorizontalScrolling = false },
                onTimerDisabled = { },
                onTimerEnabled = { },
                extraInfo = { _ ->
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
                            if(updatedState.isWarmupSet){
                                Text(
                                    text = "WARM-UP",
                                    style = captionStyle,
                                    color = Orange
                                )
                            }

                            if(updatedState.intraSetTotal != null){
                                Text(
                                    textAlign = TextAlign.Center,
                                    text =  "${updatedState.intraSetCounter}/${updatedState.intraSetTotal}",
                                    style = captionStyle
                                )
                            }
                        }
                    }
                },
                exerciseTitleComposable = exerciseTitleComposable,
                hapticsViewModel = hapticsViewModel,
                customComponentWrapper = { content ->
                    CustomHorizontalPager(
                        modifier = Modifier
                            .fillMaxSize()
                            .pointerInput(Unit) {
                                awaitPointerEventScope {
                                    while (true) {
                                        val event = awaitPointerEvent()
                                        if (event.changes.any { it.pressed }) {
                                            restartGoBack()
                                        }
                                    }
                                }
                            },
                        pagerState = pagerState,
                        userScrollEnabled = allowHorizontalScrolling,
                    ) { pageIndex ->
                        // Get the page type for the current index
                        val pageType = pageTypes[pageIndex]


                        when (pageType) {
                            PageType.PLATES -> PagePlates(updatedState, equipment)
                            PageType.EXERCISE_DETAIL -> content()
                            PageType.EXERCISES -> PageExercises(
                                updatedState,
                                viewModel, hapticsViewModel,
                                exercise,
                                onSelectionChange = {
                                selectedExerciseOrSupersetIndex = it
                            })
                            PageType.NOTES -> PageNotes(exercise.notes)
                            PageType.BUTTONS -> PageButtons(updatedState, viewModel,hapticsViewModel)
                        }
                    }
                }
            )

            CustomDialogYesOnLongPress(
                show = showNextDialog,
                title =  if(updatedState.intraSetTotal != null && updatedState.intraSetCounter < updatedState.intraSetTotal!!) "Continue Set" else "Complete Set",
                message = "Do you want to proceed?",
                handleYesClick = {

                    if(updatedState.intraSetTotal != null){
                        updatedState.intraSetCounter++
                    }

                    hapticsViewModel.doGentleVibration()
                    viewModel.storeSetData()
                    viewModel.pushAndStoreWorkoutData(false, context) {
                        viewModel.goToNextState()
                        viewModel.lightScreenUp()
                    }

                    viewModel.closeCustomDialog()
                },
                handleNoClick = {
                    viewModel.closeCustomDialog()
                    hapticsViewModel.doGentleVibration()
                },
                closeTimerInMillis = 5000,
                handleOnAutomaticClose = {
                    viewModel.closeCustomDialog()
                },
                holdTimeInMillis = 1000,
                onVisibilityChange = { isVisible ->
                    if (isVisible) {
                        viewModel.setDimming(false)
                    } else {
                        viewModel.reEvaluateDimmingForCurrentState()
                    }
                }
            )
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize(),
        contentAlignment = Alignment.Center
    ) {
        ExerciseIndicator(
            viewModel,
            state,
            selectedExerciseOrSupersetIndex
        )

        hearthRateChart()
    }

    DisposableEffect(Unit) {
        onDispose {
            goBackJob?.cancel()
        }
    }
}
