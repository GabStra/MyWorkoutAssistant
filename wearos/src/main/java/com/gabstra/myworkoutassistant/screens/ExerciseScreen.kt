package com.gabstra.myworkoutassistant.screens

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.BaselineShift
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import androidx.wear.compose.foundation.pager.rememberPagerState
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.composables.CircularEndsPillShape
import com.gabstra.myworkoutassistant.composables.CustomDialogYesOnLongPress
import com.gabstra.myworkoutassistant.composables.CustomHorizontalPager
import com.gabstra.myworkoutassistant.composables.ExerciseDetail
import com.gabstra.myworkoutassistant.composables.ExerciseIndicator
import com.gabstra.myworkoutassistant.composables.PageButtons
import com.gabstra.myworkoutassistant.composables.PageExercises
// MOVEMENT_ANIMATION disabled for now
// import com.gabstra.myworkoutassistant.composables.PageMovementAnimation
import com.gabstra.myworkoutassistant.composables.PageMuscles
import com.gabstra.myworkoutassistant.composables.PageNotes
import com.gabstra.myworkoutassistant.composables.PagePlates
import com.gabstra.myworkoutassistant.composables.PageProgressionComparison
import com.gabstra.myworkoutassistant.composables.ScalableText
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.LighterGray
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

enum class PageType {
    PLATES, EXERCISE_DETAIL, MOVEMENT_ANIMATION, MUSCLES, EXERCISES, NOTES, BUTTONS, PROGRESSION_COMPARISON
}

@OptIn(ExperimentalFoundationApi::class, ExperimentalLayoutApi::class)
@Composable
fun ExerciseScreen(
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    state: WorkoutState.Set,
    hearthRateChart: @Composable () -> Unit,
    navController: NavController,
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

    val accessoryEquipments = remember(exercise) {
        (exercise.requiredAccessoryEquipmentIds ?: emptyList()).mapNotNull { id ->
            viewModel.getAccessoryEquipmentById(id)
        }
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

    val hasMuscleInfo = remember(exercise) { !exercise.muscleGroups.isNullOrEmpty() }

    val showProgressionComparisonPage = remember(exercise) {
        viewModel.exerciseProgressionByExerciseId.containsKey(exercise.id) &&
                viewModel.lastSessionWorkout != null &&
                ((viewModel.lastSessionWorkout!!.workoutComponents.filterIsInstance<Exercise>() +
                        viewModel.lastSessionWorkout!!.workoutComponents.filterIsInstance<com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset>()
                            .flatMap { it.exercises }).any { it.id == exercise.id })
    }

    val pageTypes = remember(showPlatesPage, showNotesPage, showProgressionComparisonPage, hasMuscleInfo) {
        mutableListOf<PageType>().apply {
            add(PageType.EXERCISE_DETAIL)
            // MOVEMENT_ANIMATION disabled for now
            // add(PageType.MOVEMENT_ANIMATION)
            if (showPlatesPage) add(PageType.PLATES)
            if (showProgressionComparisonPage) add(PageType.PROGRESSION_COMPARISON)
            if (hasMuscleInfo) add(PageType.MUSCLES)
            if (showNotesPage) add(PageType.NOTES)
            add(PageType.EXERCISES)
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

    val progressionComparisonPageIndex = remember(pageTypes) {
        pageTypes.indexOf(PageType.PROGRESSION_COMPARISON)
    }

    // MOVEMENT_ANIMATION disabled for now
    // val movementAnimationPageIndex = remember(pageTypes) {
    //     pageTypes.indexOf(PageType.MOVEMENT_ANIMATION)
    // }

    val pagerState = rememberPagerState(
        initialPage = exerciseDetailPageIndex,
        pageCount = {
            pageTypes.size
        }
    )

    androidx.compose.runtime.LaunchedEffect(state.set.id) {
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
    var headerMarqueeEnabled by remember { mutableStateOf(false) }

    val exerciseOrSupersetIds = remember {
        viewModel.setsByExerciseId.keys.toList()
            .mapNotNull { if (viewModel.supersetIdByExerciseId.containsKey(it)) viewModel.supersetIdByExerciseId[it] else it }
            .distinct()
    }
    val exerciseOrSupersetId =
        remember(state.exerciseId) { if (viewModel.supersetIdByExerciseId.containsKey(state.exerciseId)) viewModel.supersetIdByExerciseId[state.exerciseId] else state.exerciseId }
    val currentExerciseOrSupersetIndex = remember(exerciseOrSupersetId, exerciseOrSupersetIds) {
        derivedStateOf { exerciseOrSupersetIds.indexOf(exerciseOrSupersetId) }
    }
    val isSuperset = remember(exerciseOrSupersetId) {
        viewModel.exercisesBySupersetId.containsKey(exerciseOrSupersetId)
    }

    var selectedExercise by remember(exercise.id) { mutableStateOf(exercise) }

    val context = LocalContext.current

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

    AnimatedContent(
        targetState = state,
        transitionSpec = {
            fadeIn(animationSpec = tween(250)) togetherWith fadeOut(animationSpec = tween(250))
        }, label = ""
    ) { updatedState ->
        val setIndex = remember(updatedState.set.id, exerciseSetIds) {
            derivedStateOf { exerciseSetIds.indexOf(updatedState.set.id) }
        }

        val exerciseTitleComposable: @Composable (onLongClick: () -> Unit) -> Unit =
            { providedOnLongClick ->
                ScalableText(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(20.dp)
                        .padding(horizontal = 22.5.dp)
                        .combinedClickable(
                            onClick = {
                                hapticsViewModel.doGentleVibration()
                                marqueeEnabled = !marqueeEnabled
                            },
                            onLongClick = {
                                providedOnLongClick.invoke()
                            }
                        ),
                    text = exercise.name,
                    textModifier = if (marqueeEnabled) Modifier.basicMarquee(iterations = Int.MAX_VALUE) else Modifier,
                    textAlign = TextAlign.Center,
                    overflow = TextOverflow.Ellipsis,
                    contentAlignment = Alignment.BottomCenter,
                    style = MaterialTheme.typography.titleLarge.copy(
                        fontWeight = FontWeight.SemiBold
                    ),
                )
            }

        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 22.5.dp, vertical = 30.dp)
                .clip(CircularEndsPillShape(straightWidth = 50.dp)),
        ) {
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

                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(horizontal = 15.dp)
                ) {
                    when (pageType) {
                        PageType.PLATES -> {
                            PagePlates(updatedState, equipment, hapticsViewModel)
                        }

                        PageType.EXERCISE_DETAIL -> {
                            key(pageType, pageIndex) {
                                ExerciseDetail(
                                    updatedState = updatedState,
                                    viewModel = viewModel,
                                    onEditModeDisabled = { allowHorizontalScrolling = true },
                                    onEditModeEnabled = { allowHorizontalScrolling = false },
                                    onTimerDisabled = { },
                                    onTimerEnabled = { },
                                    extraInfo = { _ ->
                                        Column(
                                            modifier = Modifier.fillMaxWidth(),
                                            horizontalAlignment = Alignment.CenterHorizontally,
                                            verticalArrangement = Arrangement.spacedBy(5.dp)
                                        ) {

                                            val baseStyle = MaterialTheme.typography.bodySmall
                                            val topLine = buildAnnotatedString {
                                                fun pipe() {
                                                    withStyle(
                                                        baseStyle.toSpanStyle().copy(
                                                            color = LighterGray,
                                                            fontWeight = FontWeight.Thin
                                                        )
                                                    ) {
                                                        append(" | ")
                                                    }
                                                }

                                                fun separator() {
                                                    withStyle(
                                                        baseStyle.toSpanStyle().copy(
                                                            color = LighterGray,
                                                            baselineShift = BaselineShift(0.18f)
                                                        )
                                                    ) { // tweak 0.12–0.25f as needed
                                                        append("↔")
                                                    }
                                                }

                                                withStyle(baseStyle.toSpanStyle().copy(color = LighterGray)) {
                                                    append("Ex: ")
                                                }
                                                append("${currentExerciseOrSupersetIndex.value + 1}/${exerciseOrSupersetIds.size}")

                                                if (exerciseSetIds.size > 1) {
                                                    pipe()
                                                    withStyle(baseStyle.toSpanStyle().copy(color = LighterGray)) {
                                                        append("Set: ")
                                                    }
                                                    append("${setIndex.value + 1}/${exerciseSetIds.size}")
                                                }

                                                if (isSuperset) {
                                                    pipe()

                                                    val supersetExercises =
                                                        remember(exerciseOrSupersetId) {
                                                            viewModel.exercisesBySupersetId[exerciseOrSupersetId]!!
                                                        }
                                                    val currentIdx =
                                                        remember(supersetExercises, exercise) {
                                                            supersetExercises.indexOf(exercise)
                                                        }

                                                    supersetExercises.indices.forEach { i ->
                                                        if (i > 0) {
                                                            separator()
                                                        }
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

                                                if (updatedState.intraSetTotal != null) {
                                                    pipe()

                                                    withStyle(
                                                        SpanStyle(
                                                            color = if (updatedState.intraSetCounter == 1u) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceContainerHigh,
                                                            fontWeight = FontWeight.Bold
                                                        )
                                                    ) {
                                                        append("①")
                                                    }
                                                    separator()
                                                    withStyle(
                                                        SpanStyle(
                                                            color = if (updatedState.intraSetCounter == 2u) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceContainerHigh,
                                                            fontWeight = FontWeight.Bold
                                                        )
                                                    ) {
                                                        append("②")
                                                    }
                                                }
                                            }

                                            Text(
                                                text = topLine,
                                                style = baseStyle,
                                                textAlign = TextAlign.Center,
                                                maxLines = 1,
                                                overflow = TextOverflow.Ellipsis,
                                                modifier = Modifier
                                                    .clickable {
                                                        headerMarqueeEnabled = !headerMarqueeEnabled
                                                        hapticsViewModel.doGentleVibration()
                                                    }
                                                    .then(
                                                        if (headerMarqueeEnabled) Modifier.basicMarquee(
                                                            iterations = Int.MAX_VALUE
                                                        ) else Modifier
                                                    )
                                            )

                                            val bottomLineBaseStyle = MaterialTheme.typography.bodySmall
                                            val bottomLine = buildAnnotatedString {
                                                var first = true

                                                @Composable
                                                fun sep() {
                                                    if (!first) {
                                                        withStyle(
                                                            bottomLineBaseStyle.toSpanStyle().copy(
                                                                color = LighterGray,
                                                                fontWeight = FontWeight.Thin
                                                            )
                                                        ) {
                                                            append(" | ")
                                                        }
                                                    }
                                                    first = false
                                                }

                                                if (equipment != null) {
                                                    sep()
                                                    withStyle(bottomLineBaseStyle.toSpanStyle().copy(color = LighterGray)) {
                                                        append("Eq: ")
                                                    }
                                                    append(equipment.name)
                                                }
                                                if (accessoryEquipments.isNotEmpty()) {
                                                    sep()
                                                    withStyle(bottomLineBaseStyle.toSpanStyle().copy(color = LighterGray)) {
                                                        append("Acc: ")
                                                    }
                                                    append(accessoryEquipments.joinToString(", ") { it.name })
                                                }
                                                val isWarmupSet =
                                                    when (val set = updatedState.set) {
                                                        is BodyWeightSet -> set.subCategory == SetSubCategory.WarmupSet
                                                        is WeightSet -> set.subCategory == SetSubCategory.WarmupSet
                                                        else -> false
                                                    }
                                                val isCalibrationSet =
                                                    when (val set = updatedState.set) {
                                                        is BodyWeightSet -> set.subCategory == SetSubCategory.CalibrationSet
                                                        is WeightSet -> set.subCategory == SetSubCategory.CalibrationSet
                                                        else -> false
                                                    }
                                                if (isWarmupSet) {
                                                    sep()
                                                    append("Warm-up")
                                                }
                                                if (isCalibrationSet) {
                                                    sep()
                                                    append("Calibration")
                                                }
                                            }

                                            if (bottomLine.text.isNotEmpty()) {
                                                Text(
                                                    text = bottomLine,
                                                    style = bottomLineBaseStyle,
                                                    textAlign = TextAlign.Center,
                                                    maxLines = 1,
                                                    overflow = TextOverflow.Ellipsis,
                                                    modifier = Modifier
                                                        .clickable {
                                                            headerMarqueeEnabled =
                                                                !headerMarqueeEnabled
                                                            hapticsViewModel.doGentleVibration()
                                                        }
                                                        .then(
                                                            if (headerMarqueeEnabled) Modifier.basicMarquee(
                                                                iterations = Int.MAX_VALUE
                                                            ) else Modifier
                                                        )
                                                )
                                            }
                                        }
                                    },
                                    exerciseTitleComposable = exerciseTitleComposable,
                                    hapticsViewModel = hapticsViewModel,
                                    customComponentWrapper = { content ->
                                        content()
                                    }
                                )
                            }
                        }

                        // MOVEMENT_ANIMATION disabled for now
                        PageType.MOVEMENT_ANIMATION -> {
                            // PageMovementAnimation disabled
                        }

                        PageType.MUSCLES -> {
                            PageMuscles(exercise = exercise)
                        }

                        PageType.EXERCISES -> {
                            key(pageType, pageIndex) {
                                PageExercises(
                                    selectedExercise,
                                    updatedState,
                                    viewModel, hapticsViewModel,
                                    exercise,
                                    exerciseOrSupersetIds = exerciseOrSupersetIds,
                                    onExerciseSelected = {
                                        selectedExercise = it
                                    })
                            }
                        }

                        PageType.PROGRESSION_COMPARISON -> {
                            PageProgressionComparison(
                                viewModel = viewModel,
                                hapticsViewModel = hapticsViewModel,
                                exercise = exercise,
                                state = updatedState,
                                isPageVisible = pagerState.currentPage == progressionComparisonPageIndex
                            )
                        }

                        PageType.NOTES -> {
                            PageNotes(exercise.notes)
                        }

                        PageType.BUTTONS -> {
                            PageButtons(updatedState, viewModel, hapticsViewModel, navController)
                        }
                    }
                }
            }
        }


        CustomDialogYesOnLongPress(
            show = showNextDialog,
            title = if (updatedState.intraSetTotal != null && updatedState.intraSetCounter < updatedState.intraSetTotal!!) "Switch side" else "Complete Set",
            message = "Do you want to proceed?",
            handleYesClick = {

                if (updatedState.intraSetTotal != null) {
                    updatedState.intraSetCounter++
                }

                hapticsViewModel.doGentleVibration()
                viewModel.storeSetData()
                val isDone = viewModel.isNextStateCompleted()
                viewModel.pushAndStoreWorkoutData(isDone, context) {
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
            onVisibilityChange = { isVisible ->
                if (isVisible) {
                    viewModel.setDimming(false)
                } else {
                    viewModel.reEvaluateDimmingForCurrentState()
                }
            }
        )

        Box(
            modifier = Modifier
                .fillMaxSize(),
            contentAlignment = Alignment.Center
        ) {
            ExerciseIndicator(
                viewModel,
                updatedState,
                selectedExercise.id
            )

            Box {
                hearthRateChart()
            }
        }

    }

    DisposableEffect(Unit) {
        onDispose {
            goBackJob?.cancel()
        }
    }
}
