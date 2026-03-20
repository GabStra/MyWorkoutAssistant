package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.border
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import androidx.wear.tooling.preview.devices.WearDevices
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.FormatTime
import com.gabstra.myworkoutassistant.data.HapticsHelper
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.presentation.theme.MyWorkoutAssistantTheme
import com.gabstra.myworkoutassistant.screens.setCurrentWorkoutState
import com.gabstra.myworkoutassistant.screens.setFieldValue
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Orange
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.ExerciseChildItem
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateContainer
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateMachine
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateSequenceItem
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.util.UUID

private fun resolveExerciseOrSupersetId(viewModel: AppViewModel, exerciseId: UUID): UUID =
    viewModel.supersetIdByExerciseId[exerciseId] ?: exerciseId

private fun getRepresentativeExercise(viewModel: AppViewModel, exerciseOrSupersetId: UUID): Exercise {
    val supersetExercises = viewModel.exercisesBySupersetId[exerciseOrSupersetId]
    return if (supersetExercises != null) {
        supersetExercises.first()
    } else {
        viewModel.exercisesById[exerciseOrSupersetId]!!
    }
}

internal sealed class PageExercisesItem {
    abstract val representativeExercise: Exercise

    data class ExercisePage(
        val exercise: Exercise,
    ) : PageExercisesItem() {
        override val representativeExercise: Exercise = exercise
    }

    data class SupersetPage(
        val supersetId: UUID,
        val exercises: List<Exercise>,
    ) : PageExercisesItem() {
        override val representativeExercise: Exercise = exercises.first()
    }

    data class RestPage(
        val restState: WorkoutState.Rest,
        override val representativeExercise: Exercise,
    ) : PageExercisesItem()
}

internal fun resolvePageExercisesActiveState(
    workoutState: WorkoutState?,
    fallbackSetState: WorkoutState.Set? = null,
): WorkoutState? {
    if (workoutState !is WorkoutState.Rest || workoutState.exerciseId == null) return workoutState

    return when (val nextExecutableState = workoutState.nextState ?: fallbackSetState) {
        is WorkoutState.Set -> nextExecutableState
        is WorkoutState.CalibrationLoadSelection -> nextExecutableState
        is WorkoutState.CalibrationRIRSelection -> nextExecutableState
        is WorkoutState.AutoRegulationRIRSelection -> nextExecutableState
        else -> workoutState
    }
}

private fun resolveRestPageRepresentativeExercise(
    viewModel: AppViewModel,
    restState: WorkoutState.Rest,
): Exercise? {
    val nextExerciseId = when (val nextState = restState.nextState ?: return null) {
        is WorkoutState.Set -> nextState.exerciseId
        is WorkoutState.CalibrationLoadSelection -> nextState.exerciseId
        is WorkoutState.CalibrationRIRSelection -> nextState.exerciseId
        is WorkoutState.AutoRegulationRIRSelection -> nextState.exerciseId
        else -> null
    } ?: return null
    return viewModel.exercisesById[nextExerciseId]
}

internal fun buildPageExercisesItems(viewModel: AppViewModel): List<PageExercisesItem> {
    return viewModel.getWorkoutSequenceItems().mapNotNull { item ->
        when (item) {
            is WorkoutStateSequenceItem.Container -> {
                when (val container = item.container) {
                    is WorkoutStateContainer.ExerciseState -> {
                        viewModel.exercisesById[container.exerciseId]?.let(PageExercisesItem::ExercisePage)
                    }
                    is WorkoutStateContainer.SupersetState -> {
                        viewModel.exercisesBySupersetId[container.supersetId]
                            ?.takeIf { it.isNotEmpty() }
                            ?.let { exercises ->
                                PageExercisesItem.SupersetPage(
                                    supersetId = container.supersetId,
                                    exercises = exercises
                                )
                            }
                    }
                }
            }
            is WorkoutStateSequenceItem.RestBetweenExercises -> {
                resolveRestPageRepresentativeExercise(viewModel, item.rest)
                    ?.let { exercise -> PageExercisesItem.RestPage(item.rest, exercise) }
            }
        }
    }
}

private fun resolvePageExercisesItemIndex(
    items: List<PageExercisesItem>,
    selectedExercise: Exercise,
    workoutState: WorkoutState?,
    viewModel: AppViewModel,
): Int {
    val selectedExerciseOrSupersetId = resolveExerciseOrSupersetId(viewModel, selectedExercise.id)
    val isCurrentInterExerciseRest = workoutState is WorkoutState.Rest && workoutState.exerciseId == null

    if (isCurrentInterExerciseRest && selectedExercise.id == resolveRestPageRepresentativeExercise(viewModel, workoutState)?.id) {
        val restIndex = items.indexOfFirst { page ->
            page is PageExercisesItem.RestPage && page.restState == workoutState
        }
        if (restIndex >= 0) return restIndex
    }

    val directIndex = items.indexOfFirst { page ->
        when (page) {
            is PageExercisesItem.ExercisePage -> page.exercise.id == selectedExercise.id
            is PageExercisesItem.SupersetPage -> page.supersetId == selectedExerciseOrSupersetId
            is PageExercisesItem.RestPage -> page.representativeExercise.id == selectedExercise.id
        }
    }
    return directIndex.takeIf { it >= 0 } ?: 0
}

internal fun resolvePageExercisesCurrentItemIndex(
    items: List<PageExercisesItem>,
    workoutState: WorkoutState?,
    fallbackSetState: WorkoutState.Set? = null,
    viewModel: AppViewModel,
): Int {
    if (items.isEmpty()) return -1
    if (workoutState is WorkoutState.Rest && workoutState.exerciseId == null) {
        val restIndex = items.indexOfFirst { page ->
            page is PageExercisesItem.RestPage && page.restState == workoutState
        }
        if (restIndex >= 0) return restIndex
    }

    val activeState = resolvePageExercisesActiveState(workoutState, fallbackSetState)
    val activeExerciseId = when (activeState) {
        is WorkoutState.Set -> activeState.exerciseId
        is WorkoutState.CalibrationLoadSelection -> activeState.exerciseId
        is WorkoutState.CalibrationRIRSelection -> activeState.exerciseId
        is WorkoutState.AutoRegulationRIRSelection -> activeState.exerciseId
        is WorkoutState.Rest -> activeState.exerciseId
        else -> null
    } ?: return 0
    val activeExerciseOrSupersetId = resolveExerciseOrSupersetId(viewModel, activeExerciseId)
    return items.indexOfFirst { page ->
        when (page) {
            is PageExercisesItem.ExercisePage -> page.exercise.id == activeExerciseId
            is PageExercisesItem.SupersetPage -> page.supersetId == activeExerciseOrSupersetId
            is PageExercisesItem.RestPage -> false
        }
    }.takeIf { it >= 0 } ?: 0
}

private fun resolvePageCurrentSet(
    pageItem: PageExercisesItem,
    activeWorkoutState: WorkoutState?,
): com.gabstra.myworkoutassistant.shared.sets.Set? {
    return when (pageItem) {
        is PageExercisesItem.RestPage -> when (activeWorkoutState) {
            is WorkoutState.Set -> activeWorkoutState.set
            is WorkoutState.CalibrationLoadSelection -> activeWorkoutState.calibrationSet
            is WorkoutState.CalibrationRIRSelection -> activeWorkoutState.calibrationSet
            is WorkoutState.AutoRegulationRIRSelection -> activeWorkoutState.workSet
            else -> null
        }
        else -> when (activeWorkoutState) {
            is WorkoutState.Set -> activeWorkoutState.set
            is WorkoutState.Rest -> activeWorkoutState.set
            is WorkoutState.CalibrationLoadSelection -> activeWorkoutState.calibrationSet
            is WorkoutState.CalibrationRIRSelection -> activeWorkoutState.calibrationSet
            is WorkoutState.AutoRegulationRIRSelection -> activeWorkoutState.workSet
            else -> null
        }
    }
}

private fun buildSupersetDisplayName(exercises: List<Exercise>): AnnotatedString {
    return buildAnnotatedString {
        exercises.forEachIndexed { index, exercise ->
            if (index > 0) append(" ↔ ")
            append(exercise.name)
            append(" ")
            append("(")
            append(('A' + index).toString())
            append(")")
        }
    }
}

@Composable
private fun RestPageContent(
    restState: WorkoutState.Rest,
    upcomingExercise: Exercise,
    progressState: ProgressState,
) {
    val borderColor: Color = when (progressState) {
        ProgressState.PAST -> MaterialTheme.colorScheme.onBackground
        ProgressState.CURRENT -> Orange
        ProgressState.FUTURE -> MaterialTheme.colorScheme.surfaceContainerHigh
    }
    val textColor = borderColor
    val restSeconds = (restState.set as? RestSet)?.timeInSeconds ?: 0
    val shape = RoundedCornerShape(25)

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 22.5.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(7.5.dp)
    ) {
        Box(
            modifier = Modifier
                .height(25.dp)
                .border(BorderStroke(1.dp, borderColor), shape),
            contentAlignment = Alignment.Center
        ) {
            ScalableText(
                modifier = Modifier.padding(2.5.dp),
                text = "REST ${FormatTime(restSeconds)}",
                style = MaterialTheme.typography.numeralSmall,
                color = textColor,
            )
        }
        Text(
            text = "UP NEXT",
            style = MaterialTheme.typography.bodyExtraSmall,
            color = MaterialTheme.colorScheme.onBackground,
            textAlign = TextAlign.Center
        )
        ExerciseNameText(
            text = AnnotatedString(upcomingExercise.name),
            modifier = Modifier.fillMaxWidth(),
            style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.SemiBold),
            textAlign = TextAlign.Center
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun PageExercises(
    selectedExercise: Exercise,
    selectedRestPageId: UUID? = null,
    workoutState: WorkoutState?,
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    currentExercise: Exercise,
    onPageSelected: (Exercise, UUID?) -> Unit
) {
    val pageItems = remember(viewModel.allWorkoutStates.size, viewModel.supersetIdByExerciseId, viewModel.exercisesBySupersetId) {
        buildPageExercisesItems(viewModel)
    }
    val activeWorkoutState = remember(workoutState, viewModel.allWorkoutStates.size) {
        resolvePageExercisesActiveState(
            workoutState = workoutState,
            fallbackSetState = viewModel.getFirstSetStateAfterCurrent()
        )
    }

    val selectedPageIndex = remember(pageItems, selectedExercise, selectedRestPageId, workoutState, viewModel.allWorkoutStates.size) {
        derivedStateOf {
            if (selectedRestPageId != null) {
                pageItems.indexOfFirst { page ->
                    page is PageExercisesItem.RestPage && page.restState.set.id == selectedRestPageId
                }.takeIf { it >= 0 } ?: 0
            } else {
                resolvePageExercisesItemIndex(
                    items = pageItems,
                    selectedExercise = selectedExercise,
                    workoutState = workoutState,
                    viewModel = viewModel
                )
            }
        }
    }
    val currentPageIndex = remember(pageItems, workoutState, currentExercise.id, viewModel.allWorkoutStates.size) {
        derivedStateOf {
            resolvePageExercisesCurrentItemIndex(
                items = pageItems,
                workoutState = workoutState,
                fallbackSetState = viewModel.getFirstSetStateAfterCurrent(),
                viewModel = viewModel
            )
        }
    }

    val selectedPageItem = pageItems.getOrNull(selectedPageIndex.value)
    val titleStyle = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.SemiBold)
    val pageCount = pageItems.size

    Box(
        modifier = Modifier
            .fillMaxSize()
            .semantics { contentDescription = "Exercise sets viewer" }
    ) {
        Column(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.spacedBy(5.dp, Alignment.Top),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth(),
                contentAlignment = Alignment.Center
            ) {
                when (selectedPageItem) {
                    is PageExercisesItem.RestPage -> {
                        Text(
                            text = "REST",
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 22.5.dp),
                            style = titleStyle,
                            textAlign = TextAlign.Center
                        )
                    }
                    is PageExercisesItem.SupersetPage -> {
                        ExerciseNameText(
                            text = buildSupersetDisplayName(selectedPageItem.exercises),
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(25.dp)
                                .padding(horizontal = 22.5.dp),
                            style = titleStyle,
                            textAlign = TextAlign.Center
                        )
                    }
                    is PageExercisesItem.ExercisePage -> {
                        ExerciseNameText(
                            text = AnnotatedString(selectedPageItem.exercise.name),
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(25.dp)
                                .padding(horizontal = 22.5.dp),
                            style = titleStyle,
                            textAlign = TextAlign.Center
                        )
                    }
                    null -> Unit
                }
            }

            Column(
                modifier = Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(5.dp)
            ) {
                when (selectedPageItem) {
                    is PageExercisesItem.SupersetPage -> {
                        SupersetMetadataStrip(
                            containerLabel = if (pageCount > 1) "${selectedPageIndex.value + 1}/$pageCount" else null
                        )
                    }
                    is PageExercisesItem.ExercisePage -> {
                        ExerciseMetadataStrip(
                            exerciseLabel = if (pageCount > 1) "${selectedPageIndex.value + 1}/$pageCount" else null,
                            supersetExerciseIndex = null,
                            supersetExerciseTotal = null,
                            sideIndicator = null,
                            currentSideIndex = null
                        )
                    }
                    is PageExercisesItem.RestPage -> {
                        if (pageCount > 1) {
                            Text(
                                text = "${selectedPageIndex.value + 1}/$pageCount",
                                style = MaterialTheme.typography.bodyExtraSmall,
                                textAlign = TextAlign.Center,
                                color = MaterialTheme.colorScheme.onBackground
                            )
                        }
                    }
                    null -> Unit
                }
            }

            if (selectedPageItem != null) {
                val progressState = when {
                    selectedPageIndex.value < currentPageIndex.value -> ProgressState.PAST
                    selectedPageIndex.value > currentPageIndex.value -> ProgressState.FUTURE
                    else -> ProgressState.CURRENT
                }
                when (selectedPageItem) {
                    is PageExercisesItem.RestPage -> {
                        RestPageContent(
                            restState = selectedPageItem.restState,
                            upcomingExercise = selectedPageItem.representativeExercise,
                            progressState = progressState
                        )
                    }
                    else -> {
                        val currentSet = resolvePageCurrentSet(selectedPageItem, activeWorkoutState)
                        if (currentSet != null) {
                            val isSelectedCurrentPage = progressState == ProgressState.CURRENT
                            ExerciseSetsViewer(
                                modifier = Modifier.padding(horizontal = 22.5.dp),
                                viewModel = viewModel,
                                hapticsViewModel = hapticsViewModel,
                                exercise = selectedPageItem.representativeExercise,
                                currentSet = currentSet,
                                progressState = progressState,
                                currentWorkoutStateOverride = if (isSelectedCurrentPage) workoutState else null
                            )
                        }
                    }
                }
            }
        }

        Row(
            modifier = Modifier.fillMaxSize(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Row(
                modifier = Modifier
                    .fillMaxHeight()
                    .weight(1f)
                    .clickable(enabled = selectedPageIndex.value > 0) {
                        hapticsViewModel.doGentleVibration()
                        val previousPage = pageItems[selectedPageIndex.value - 1]
                        onPageSelected(
                            previousPage.representativeExercise,
                            (previousPage as? PageExercisesItem.RestPage)?.restState?.set?.id
                        )
                    }
                    .then(if (pageCount > 1) Modifier else Modifier.alpha(0f)),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.Center
            ) {
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
                    .clickable(enabled = selectedPageIndex.value < pageCount - 1) {
                        hapticsViewModel.doGentleVibration()
                        val nextPage = pageItems[selectedPageIndex.value + 1]
                        onPageSelected(
                            nextPage.representativeExercise,
                            (nextPage as? PageExercisesItem.RestPage)?.restState?.set?.id
                        )
                    }
                    .then(if (pageCount > 1) Modifier else Modifier.alpha(0f)),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.Center
            ) {
            }
        }
    }
}

private data class PageExercisesPreviewFixture(
    val viewModel: AppViewModel,
    val firstExercise: Exercise,
    val selectedExercise: Exercise,
    val currentExercise: Exercise,
    val firstSetState: WorkoutState.Set,
    val restState: WorkoutState.Rest,
)

private fun buildPageExercisesPreviewFixture(): PageExercisesPreviewFixture {
    val viewModel = AppViewModel()
    val firstExercise = Exercise(
        id = UUID.fromString("71000000-0000-0000-0000-000000000001"),
        enabled = true,
        name = "Bench Press",
        doNotStoreHistory = false,
        notes = "",
        sets = listOf(
            WeightSet(
                id = UUID.fromString("72000000-0000-0000-0000-000000000001"),
                reps = 8,
                weight = 80.0,
                subCategory = SetSubCategory.WorkSet
            ),
            RestSet(
                id = UUID.fromString("72000000-0000-0000-0000-000000000004"),
                timeInSeconds = 120,
                subCategory = SetSubCategory.WorkSet
            ),
            WeightSet(
                id = UUID.fromString("72000000-0000-0000-0000-000000000005"),
                reps = 6,
                weight = 82.5,
                subCategory = SetSubCategory.WorkSet
            )
        ),
        exerciseType = ExerciseType.WEIGHT,
        minLoadPercent = 0.0,
        maxLoadPercent = 100.0,
        minReps = 6,
        maxReps = 10,
        lowerBoundMaxHRPercent = null,
        upperBoundMaxHRPercent = null,
        equipmentId = null,
        bodyWeightPercentage = null,
        generateWarmUpSets = false,
        keepScreenOn = false,
        showCountDownTimer = false,
        requiresLoadCalibration = false
    )
    val secondExercise = Exercise(
        id = UUID.fromString("71000000-0000-0000-0000-000000000002"),
        enabled = true,
        name = "Barbell Row",
        doNotStoreHistory = false,
        notes = "",
        sets = listOf(
            WeightSet(
                id = UUID.fromString("72000000-0000-0000-0000-000000000002"),
                reps = 10,
                weight = 60.0,
                subCategory = SetSubCategory.WorkSet
            )
        ),
        exerciseType = ExerciseType.WEIGHT,
        minLoadPercent = 0.0,
        maxLoadPercent = 100.0,
        minReps = 6,
        maxReps = 12,
        lowerBoundMaxHRPercent = null,
        upperBoundMaxHRPercent = null,
        equipmentId = null,
        bodyWeightPercentage = null,
        generateWarmUpSets = false,
        keepScreenOn = false,
        showCountDownTimer = false,
        requiresLoadCalibration = false
    )

    val firstSetState = WorkoutState.Set(
        exerciseId = firstExercise.id,
        set = firstExercise.sets.first(),
        setIndex = 1u,
        previousSetData = WeightSetData(actualReps = 8, actualWeight = 77.5, volume = 620.0),
        currentSetDataState = androidx.compose.runtime.mutableStateOf(
            WeightSetData(actualReps = 8, actualWeight = 80.0, volume = 640.0)
        ),
        hasNoHistory = false,
        skipped = false,
        currentBodyWeight = 0.0,
        streak = 1,
        progressionState = null,
        isWarmupSet = false,
        equipmentId = null
    )
    val secondSetState = WorkoutState.Set(
        exerciseId = secondExercise.id,
        set = secondExercise.sets.first(),
        setIndex = 1u,
        previousSetData = WeightSetData(actualReps = 10, actualWeight = 57.5, volume = 575.0),
        currentSetDataState = androidx.compose.runtime.mutableStateOf(
            WeightSetData(actualReps = 10, actualWeight = 60.0, volume = 600.0)
        ),
        hasNoHistory = false,
        skipped = false,
        currentBodyWeight = 0.0,
        streak = 1,
        progressionState = null,
        isWarmupSet = false,
        equipmentId = null
    )
    val firstExerciseRestState = WorkoutState.Rest(
        set = firstExercise.sets[1] as RestSet,
        order = 2u,
        currentSetDataState = androidx.compose.runtime.mutableStateOf(
            RestSetData(startTimer = 120, endTimer = 75)
        ),
        exerciseId = firstExercise.id
    )
    val firstExerciseSecondSetState = WorkoutState.Set(
        exerciseId = firstExercise.id,
        set = firstExercise.sets[2],
        setIndex = 3u,
        previousSetData = WeightSetData(actualReps = 6, actualWeight = 80.0, volume = 480.0),
        currentSetDataState = androidx.compose.runtime.mutableStateOf(
            WeightSetData(actualReps = 6, actualWeight = 82.5, volume = 495.0)
        ),
        hasNoHistory = false,
        skipped = false,
        currentBodyWeight = 0.0,
        streak = 1,
        progressionState = null,
        isWarmupSet = false,
        equipmentId = null
    )
    val restState = WorkoutState.Rest(
        set = RestSet(
            id = UUID.fromString("72000000-0000-0000-0000-000000000003"),
            timeInSeconds = 90,
            subCategory = SetSubCategory.WorkSet
        ),
        order = 2u,
        currentSetDataState = androidx.compose.runtime.mutableStateOf(
            RestSetData(startTimer = 90, endTimer = 45)
        ),
        exerciseId = null,
        nextState = secondSetState
    )

    val sequence = listOf(
        WorkoutStateSequenceItem.Container(
            WorkoutStateContainer.ExerciseState(
                exerciseId = firstExercise.id,
                childItems = mutableListOf(
                    ExerciseChildItem.Normal(firstSetState),
                    ExerciseChildItem.Normal(firstExerciseRestState),
                    ExerciseChildItem.Normal(firstExerciseSecondSetState)
                )
            )
        ),
        WorkoutStateSequenceItem.RestBetweenExercises(restState),
        WorkoutStateSequenceItem.Container(
            WorkoutStateContainer.ExerciseState(
                exerciseId = secondExercise.id,
                childItems = mutableListOf(ExerciseChildItem.Normal(secondSetState))
            )
        )
    )
    val stateMachine = WorkoutStateMachine.fromSequence(sequence, startIndex = 1)

    viewModel.exercisesById = mapOf(
        firstExercise.id to firstExercise,
        secondExercise.id to secondExercise
    )
    viewModel.supersetIdByExerciseId = emptyMap()
    viewModel.exercisesBySupersetId = emptyMap()
    setFieldValue(viewModel, "stateMachine", stateMachine)
    setCurrentWorkoutState(viewModel, restState)

    return PageExercisesPreviewFixture(
        viewModel = viewModel,
        firstExercise = firstExercise,
        selectedExercise = secondExercise,
        currentExercise = firstExercise,
        firstSetState = firstSetState,
        restState = restState
    )
}

@Preview(
    name = "Standalone Rest Page",
    group = "PageExercises",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
private fun PageExercisesRestPagePreview() {
    val fixture = remember { buildPageExercisesPreviewFixture() }
    val context = LocalContext.current
    val hapticsViewModel = remember(context) { HapticsViewModel(context, HapticsHelper(context)) }

    MyWorkoutAssistantTheme {
        PageExercises(
            selectedExercise = fixture.selectedExercise,
            selectedRestPageId = fixture.restState.set.id,
            workoutState = fixture.restState,
            viewModel = fixture.viewModel,
            hapticsViewModel = hapticsViewModel,
            currentExercise = fixture.currentExercise,
            onPageSelected = { _, _ -> }
        )
    }
}

@Preview(
    name = "Normal Exercise Page",
    group = "PageExercises",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
private fun PageExercisesExercisePagePreview() {
    val fixture = remember { buildPageExercisesPreviewFixture() }
    val context = LocalContext.current
    val hapticsViewModel = remember(context) { HapticsViewModel(context, HapticsHelper(context)) }

    MyWorkoutAssistantTheme {
        PageExercises(
            selectedExercise = fixture.firstExercise,
            selectedRestPageId = null,
            workoutState = fixture.firstSetState,
            viewModel = fixture.viewModel,
            hapticsViewModel = hapticsViewModel,
            currentExercise = fixture.firstExercise,
            onPageSelected = { _, _ -> }
        )
    }
}
