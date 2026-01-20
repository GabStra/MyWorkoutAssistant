package com.gabstra.myworkoutassistant.screens

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight.Companion.W700
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import androidx.wear.compose.foundation.pager.rememberPagerState
import androidx.wear.compose.material3.CircularProgressIndicator
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ProgressIndicatorDefaults
import com.gabstra.myworkoutassistant.composables.CircularEndsPillShape
import com.gabstra.myworkoutassistant.composables.ControlButtonsVertical
import com.gabstra.myworkoutassistant.composables.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composables.CustomHorizontalPager
import com.gabstra.myworkoutassistant.composables.ExerciseIndicator
import com.gabstra.myworkoutassistant.composables.PageButtons
import com.gabstra.myworkoutassistant.composables.PageExercises
import com.gabstra.myworkoutassistant.composables.PagePlates
import com.gabstra.myworkoutassistant.composables.PageProgressionComparison
import com.gabstra.myworkoutassistant.composables.SetValueSemantics
import com.gabstra.myworkoutassistant.composables.TimeViewer
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.reduceColorLuminance
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.google.android.horologist.annotations.ExperimentalHorologistApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.time.Duration
import java.time.LocalDateTime
import java.time.temporal.ChronoUnit

@OptIn(ExperimentalFoundationApi::class, ExperimentalHorologistApi::class)
@Composable
fun RestScreen(
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    state: WorkoutState.Rest,
    hearthRateChart: @Composable () -> Unit,
    onTimerEnd: () -> Unit,
    navController: NavController,
) {
    val set = state.set as RestSet

    val scope = rememberCoroutineScope()
    var timerJob by remember { mutableStateOf<Job?>(null) }

    DisposableEffect(Unit) {
        onDispose {
            timerJob?.cancel()
        }
    }

    var currentSetData by remember(set.id) { mutableStateOf(state.currentSetData as RestSetData) }
    var currentSeconds by remember(set.id) { mutableIntStateOf(currentSetData.startTimer) }

    var amountToWait by remember(set.id) { mutableIntStateOf(currentSetData.startTimer) }

    var currentSecondsFreeze by remember { mutableIntStateOf(0) }
    var amountToWaitFreeze by remember { mutableIntStateOf(0) }

    var isTimerInEditMode by remember { mutableStateOf(false) }

    fun computeProgress(): Float  {
        if(isTimerInEditMode){
            return currentSecondsFreeze.toFloat() / amountToWaitFreeze.toFloat()
        }else{
            return currentSeconds.toFloat() / amountToWait.toFloat()
        }
    }

    val indicatorProgress = remember { mutableFloatStateOf(computeProgress()) }

    LaunchedEffect(currentSeconds,amountToWait,currentSecondsFreeze,amountToWaitFreeze,isTimerInEditMode) {
        indicatorProgress.floatValue = computeProgress()
    }

    val exerciseOrSupersetIds = remember {
        viewModel.setsByExerciseId.keys.toList()
            .mapNotNull { if (viewModel.supersetIdByExerciseId.containsKey(it)) viewModel.supersetIdByExerciseId[it] else it }
            .distinct()
    }

    var lastInteractionTime by remember { mutableLongStateOf(System.currentTimeMillis()) }

    var hasBeenStartedOnce by remember { mutableStateOf(false) }
    val showSkipDialog by viewModel.isCustomDialogOpen.collectAsState()

    val exercise = remember(state.nextStateSets.first().exerciseId) {
        viewModel.exercisesById[state.nextStateSets.first().exerciseId]!!
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

    val showProgressionComparisonPage = remember(exercise) {
        !exercise.requiresLoadCalibration &&
                viewModel.exerciseProgressionByExerciseId.containsKey(exercise.id) &&
                viewModel.lastSessionWorkout != null &&
                ((viewModel.lastSessionWorkout!!.workoutComponents.filterIsInstance<Exercise>() +
                        viewModel.lastSessionWorkout!!.workoutComponents.filterIsInstance<com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset>()
                            .flatMap { it.exercises }).any { it.id == exercise.id })
    }

    val pageTypes = remember(showPlatesPage,showProgressionComparisonPage) {
        mutableListOf<PageType>().apply {
            add(PageType.BUTTONS)  // First item - index 0
            add(PageType.EXERCISES)
            if (showPlatesPage) add(PageType.PLATES)
            if (showProgressionComparisonPage) add(PageType.PROGRESSION_COMPARISON)
        }
    }

    val exercisesPageIndex = remember(pageTypes) {
        pageTypes.indexOf(PageType.EXERCISES)
    }

    val platesPageIndex = remember(pageTypes) {
        pageTypes.indexOf(PageType.PLATES)
    }

    val progressionComparisonPageIndex = remember(pageTypes) {
        pageTypes.indexOf(PageType.PROGRESSION_COMPARISON)
    }

    val pagerState = rememberPagerState(
        initialPage = exercisesPageIndex,
        pageCount = {
            pageTypes.size
        }
    )

    var selectedExercise by remember(exercise.id) { mutableStateOf(exercise) }

    val updateInteractionTime = {
        lastInteractionTime = System.currentTimeMillis()
    }


    LaunchedEffect(currentSetData) {
        state.currentSetData = currentSetData
    }

    LaunchedEffect(pagerState.currentPage) {
        val isOnPlatesPage = pagerState.currentPage == platesPageIndex

        if (isOnPlatesPage) {
            viewModel.setDimming(false)
        } else {
            viewModel.reEvaluateDimmingForCurrentState()
        }

        val isOnExercisesPage = pagerState.currentPage == exercisesPageIndex
        if (!isOnExercisesPage) {
            selectedExercise = exercise
        }
    }

    fun onMinusClick() {
        if (currentSeconds > 5) {
            val newTimerValue = currentSeconds - 5
            amountToWait = amountToWait - 5
            amountToWaitFreeze = amountToWait

            //currentSetData = currentSetData.copy(startTimer = currentSetData.startTimer - 5)
            currentSeconds = newTimerValue
            currentSecondsFreeze = newTimerValue
            hapticsViewModel.doGentleVibration()
        }
        updateInteractionTime()
    }

    fun onPlusClick() {
        val newTimerValue = currentSeconds + 5
        amountToWait = amountToWait + 5
        amountToWaitFreeze = amountToWait
        //currentSetData = currentSetData.copy(startTimer = currentSetData.startTimer + 5)
        currentSeconds = newTimerValue
        currentSecondsFreeze = newTimerValue
        hapticsViewModel.doGentleVibration()
        updateInteractionTime()
    }

    fun startTimerJob() {
        timerJob?.cancel()
        timerJob = scope.launch {
            while (currentSeconds > 0) {
                val now = LocalDateTime.now()
                val nextSecond = now.plusSeconds(1).truncatedTo(ChronoUnit.SECONDS)
                delay(Duration.between(now, nextSecond).toMillis())

                currentSeconds -= 1

                if(currentSeconds == 5){
                    viewModel.lightScreenUp()
                }

                currentSetData = currentSetData.copy(
                    endTimer = currentSeconds
                )
            }

            state.currentSetData = currentSetData.copy(
                endTimer = 0
            )
            hapticsViewModel.doHardVibrationWithBeep()
            onTimerEnd()
        }

        if (!hasBeenStartedOnce) {
            hasBeenStartedOnce = true
        }
    }

    LaunchedEffect(isTimerInEditMode) {
        while (isTimerInEditMode) {
            if (System.currentTimeMillis() - lastInteractionTime > 5000) {
                isTimerInEditMode = false
            }
            delay(1000) // Check every second
        }
    }

    LaunchedEffect(set.id) {
        delay(500)
        startTimerJob()

        if (state.startTime == null) {
            state.startTime = LocalDateTime.now()
        }
    }

    val isPaused by viewModel.isPaused

    LaunchedEffect(isPaused) {
        if (!hasBeenStartedOnce) {
            return@LaunchedEffect
        }

        if (isPaused) {
            timerJob?.takeIf { it.isActive }?.cancel()
        } else {
            if (timerJob?.isActive != true) {
                startTimerJob()
            }
        }
    }

    val typography = MaterialTheme.typography
    val timerTextStyle = remember(typography) {
        typography.numeralSmall.copy(
            fontWeight = W700
        )
    }

    @Composable
    fun textComposable(
        seconds: Int,
        modifier: Modifier = Modifier,
        style: TextStyle = timerTextStyle,
    ) {
        Row(
            modifier = modifier
                .fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center
        ) {
            TimeViewer(
                modifier = Modifier
                    .combinedClickable(
                        onClick = {},
                        onLongClick = {
                            currentSecondsFreeze = currentSeconds
                            amountToWaitFreeze = amountToWait
                            isTimerInEditMode = !isTimerInEditMode
                            updateInteractionTime()
                            hapticsViewModel.doGentleVibration()
                        },
                        onDoubleClick = {}
                    ),
                seconds = seconds,
                style = style,
                color = MaterialTheme.colorScheme.onBackground,
            )
        }
    }

    AnimatedContent(
        targetState = isTimerInEditMode,
        transitionSpec = {
            fadeIn(animationSpec = tween(500)) togetherWith fadeOut(animationSpec = tween(500))
        }, label = ""
    ) { updatedState ->
        if (updatedState) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(vertical = 20.dp, horizontal = 35.dp),
                contentAlignment = Alignment.Center
            ) {
                ControlButtonsVertical(
                    modifier = Modifier
                        .fillMaxSize()
                        .clickable(
                            interactionSource = null,
                            indication = null
                        ) {
                            updateInteractionTime()
                        },
                    onMinusTap = { onMinusClick() },
                    onMinusLongPress = { onMinusClick() },
                    onPlusTap = { onPlusClick() },
                    onPlusLongPress = { onPlusClick() },
                    onCloseClick = {
                        isTimerInEditMode = false
                    },
                    content = {
                        textComposable(seconds = currentSecondsFreeze)
                    }
                )
            }
        } else {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(horizontal = 22.5.dp, vertical = 30.dp)
                    .clip(CircularEndsPillShape(straightWidth = 50.dp)),
            ) {
                CustomHorizontalPager(
                    modifier = Modifier
                        .fillMaxSize(),
                    pagerState = pagerState,
                ) { pageIndex ->
                    val pageType = pageTypes[pageIndex]

                    Box(
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(horizontal = 15.dp)
                    ) {
                        when (pageType) {
                            PageType.PLATES -> PagePlates(state.nextStateSets.first(), equipment, hapticsViewModel)
                            PageType.EXERCISE_DETAIL -> {}
                            PageType.EXERCISES -> {
                                PageExercises(
                                    selectedExercise,
                                    state.nextStateSets.first(),
                                    viewModel,
                                    hapticsViewModel,
                                    exercise,
                                    exerciseOrSupersetIds = exerciseOrSupersetIds,
                                    onExerciseSelected = {
                                        selectedExercise = it
                                    }
                                )
                            }

                            PageType.BUTTONS -> PageButtons(
                                state.nextStateSets.first(),
                                viewModel,
                                hapticsViewModel,
                                navController
                            )

                            PageType.NOTES -> TODO()
                            PageType.PROGRESSION_COMPARISON -> {
                                key(pageType, pageIndex) {
                                    PageProgressionComparison(
                                        viewModel = viewModel,
                                        hapticsViewModel = hapticsViewModel,
                                        exercise = exercise,
                                        state = state.nextStateSets.first(),
                                        isPageVisible = pagerState.currentPage == progressionComparisonPageIndex
                                    )
                                }
                            }

                            PageType.MUSCLES -> {}
                            PageType.MOVEMENT_ANIMATION -> {}
                        }
                    }
                }
            }
        }
    }


    Box(
        modifier = Modifier
            .fillMaxSize()
            .semantics {
                contentDescription = SetValueSemantics.RestSetTypeDescription
            },
        contentAlignment = Alignment.Center
    ) {
        ExerciseIndicator(
            viewModel,
            state.nextStateSets.first(),
            selectedExercise.id
        )

        val primaryColor = MaterialTheme.colorScheme.primary
        val trackColor = remember(primaryColor) {
            reduceColorLuminance(primaryColor)
        }

        CircularProgressIndicator(
            progress = {
                indicatorProgress.floatValue
            },
            modifier = Modifier
                .fillMaxSize()
                .padding(10.dp),
            colors = ProgressIndicatorDefaults.colors(
                indicatorColor = primaryColor,
                trackColor = trackColor
            ),
            strokeWidth = 4.dp,
            startAngle = 125f,
            endAngle = 235f,
        )

        textComposable(
            seconds = if (isTimerInEditMode) currentSecondsFreeze else currentSeconds,
            modifier = Modifier
                .align(Alignment.BottomCenter),
            style = MaterialTheme.typography.labelMedium
        )
    }

    CustomDialogYesOnLongPress(
        show = showSkipDialog,
        title = "Skip Rest",
        message = "Do you want to proceed?",
        handleYesClick = {
            state.currentSetData = currentSetData.copy(
                endTimer = currentSeconds
            )
            hapticsViewModel.doGentleVibration()
            onTimerEnd()
            viewModel.closeCustomDialog()
        },
        handleNoClick = {
            hapticsViewModel.doGentleVibration()
            viewModel.closeCustomDialog()
            startTimerJob()
        },
        closeTimerInMillis = 5000,
        handleOnAutomaticClose = {
            viewModel.closeCustomDialog()
            startTimerJob()
        },
        onVisibilityChange = { isVisible ->
            if (isVisible) {
                viewModel.setDimming(false)
            } else {
                viewModel.reEvaluateDimmingForCurrentState()
            }
        }
    )

}
