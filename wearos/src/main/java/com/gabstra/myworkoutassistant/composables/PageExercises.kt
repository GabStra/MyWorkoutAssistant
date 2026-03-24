package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.border
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnScope
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.ScrollIndicator
import androidx.wear.compose.material3.ScrollIndicatorDefaults
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.lazy.ResponsiveTransformationSpec
import androidx.wear.compose.material3.lazy.TransformationVariableSpec
import androidx.wear.compose.material3.lazy.rememberTransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import androidx.wear.tooling.preview.devices.WearDevices
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.FormatTime
import com.gabstra.myworkoutassistant.data.HapticsHelper
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.presentation.theme.MyWorkoutAssistantTheme
import com.gabstra.myworkoutassistant.screens.setCurrentWorkoutState
import com.gabstra.myworkoutassistant.screens.setFieldValue
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
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
        val previousDisplayName: AnnotatedString,
        val nextDisplayName: AnnotatedString,
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

private fun resolveSequenceItemRepresentativeExercise(
    viewModel: AppViewModel,
    item: WorkoutStateSequenceItem,
): Exercise? {
    return when (item) {
        is WorkoutStateSequenceItem.Container -> {
            when (val container = item.container) {
                is WorkoutStateContainer.ExerciseState -> viewModel.exercisesById[container.exerciseId]
                is WorkoutStateContainer.SupersetState ->
                    viewModel.exercisesBySupersetId[container.supersetId]?.firstOrNull()
            }
        }
        is WorkoutStateSequenceItem.RestBetweenExercises -> resolveRestPageRepresentativeExercise(viewModel, item.rest)
    }
}

private fun resolveSequenceItemDisplayName(
    viewModel: AppViewModel,
    item: WorkoutStateSequenceItem,
): AnnotatedString? {
    return when (item) {
        is WorkoutStateSequenceItem.Container -> {
            when (val container = item.container) {
                is WorkoutStateContainer.ExerciseState ->
                    viewModel.exercisesById[container.exerciseId]?.let { AnnotatedString(it.name) }
                is WorkoutStateContainer.SupersetState ->
                    viewModel.exercisesBySupersetId[container.supersetId]
                        ?.takeIf { it.isNotEmpty() }
                        ?.let(::buildSupersetDisplayName)
            }
        }
        is WorkoutStateSequenceItem.RestBetweenExercises -> null
    }
}

internal fun buildPageExercisesItems(viewModel: AppViewModel): List<PageExercisesItem> {
    val sequenceItems = viewModel.getWorkoutSequenceItems()
    return sequenceItems.mapIndexedNotNull { index, item ->
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
                val nextExercise = resolveRestPageRepresentativeExercise(viewModel, item.rest) ?: return@mapIndexedNotNull null
                val previousItem = sequenceItems
                    .subList(0, index)
                    .asReversed()
                    .firstOrNull { previousItem ->
                        resolveSequenceItemRepresentativeExercise(viewModel, previousItem) != null
                    } ?: return@mapIndexedNotNull null
                val previousDisplayName = resolveSequenceItemDisplayName(viewModel, previousItem)
                    ?: return@mapIndexedNotNull null
                val nextSequenceItem = sequenceItems
                    .drop(index + 1)
                    .firstOrNull()
                val nextDisplayName = nextSequenceItem
                    ?.let { resolveSequenceItemDisplayName(viewModel, it) }
                    ?: AnnotatedString(nextExercise.name)

                PageExercisesItem.RestPage(
                    restState = item.rest,
                    previousDisplayName = previousDisplayName,
                    nextDisplayName = nextDisplayName,
                    representativeExercise = nextExercise
                )
            }
        }
    }
}

internal fun resolvePageExercisesItemIndex(
    items: List<PageExercisesItem>,
    selectedExercise: Exercise,
    viewModel: AppViewModel,
): Int {
    val selectedExerciseOrSupersetId = resolveExerciseOrSupersetId(viewModel, selectedExercise.id)

    val directExerciseOrSupersetIndex = items.indexOfFirst { page ->
        when (page) {
            is PageExercisesItem.ExercisePage -> page.exercise.id == selectedExercise.id
            is PageExercisesItem.SupersetPage -> page.supersetId == selectedExerciseOrSupersetId
            is PageExercisesItem.RestPage -> false
        }
    }
    if (directExerciseOrSupersetIndex >= 0) return directExerciseOrSupersetIndex

    val restIndex = items.indexOfFirst { page ->
        page is PageExercisesItem.RestPage && page.representativeExercise.id == selectedExercise.id
    }
    return restIndex.takeIf { it >= 0 } ?: 0
}

internal fun resolvePageExercisesDisplayCounter(
    items: List<PageExercisesItem>,
    selectedPageIndex: Int,
): String? {
    if (items.isEmpty() || selectedPageIndex !in items.indices) return null

    val countedPageIndices = items.mapIndexedNotNull { index, item ->
        index.takeIf { item !is PageExercisesItem.RestPage }
    }
    if (countedPageIndices.size <= 1) return null

    val selectedItem = items[selectedPageIndex]
    val displayIndex = when (selectedItem) {
        is PageExercisesItem.RestPage -> {
            countedPageIndices.indexOfFirst { index ->
                when (val item = items[index]) {
                    is PageExercisesItem.ExercisePage ->
                        item.exercise.id == selectedItem.representativeExercise.id
                    is PageExercisesItem.SupersetPage ->
                        item.exercises.any { exercise -> exercise.id == selectedItem.representativeExercise.id }
                    is PageExercisesItem.RestPage -> false
                }
            }
        }
        else -> countedPageIndices.indexOf(selectedPageIndex)
    }.takeIf { it >= 0 } ?: return null

    return "${displayIndex + 1}/${countedPageIndices.size}"
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

private fun TransformingLazyColumnScope.RestPageContent(
    restState: WorkoutState.Rest,
    previousDisplayName: AnnotatedString,
    nextDisplayName: AnnotatedString,
    progressState: ProgressState,
    transformationSpec: androidx.wear.compose.material3.lazy.TransformationSpec,
) {
    val restSeconds = (restState.set as? RestSet)?.timeInSeconds ?: 0

    item {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .transformedHeight(this, transformationSpec)
                .graphicsLayer { with(transformationSpec) { applyContainerTransformation(scrollProgress) } },
            contentAlignment = Alignment.Center
        ) {
            Column(
                modifier = Modifier.graphicsLayer {
                    with(transformationSpec) { applyContentTransformation(scrollProgress) }
                },
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(2.5.dp)
            ) {
                val titleStyle = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.SemiBold)
                Text(
                    text = "FROM",
                    style = MaterialTheme.typography.bodyExtraSmall,
                    color = MaterialTheme.colorScheme.onBackground,
                    textAlign = TextAlign.Center
                )
                ExerciseNameText(
                    text = previousDisplayName,
                    modifier = Modifier.fillMaxWidth(),
                    style = titleStyle,
                    textAlign = TextAlign.Center
                )
            }
        }
    }

    item {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 5.dp)
                .transformedHeight(this, transformationSpec)
                .graphicsLayer { with(transformationSpec) { applyContainerTransformation(scrollProgress) } },
            contentAlignment = Alignment.Center
        ) {
            val borderColor: Color = when (progressState) {
                ProgressState.PAST -> MaterialTheme.colorScheme.onBackground
                ProgressState.CURRENT -> Orange
                ProgressState.FUTURE -> MaterialTheme.colorScheme.surfaceContainerHigh
            }
            val shape = RoundedCornerShape(25)
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .graphicsLayer { with(transformationSpec) { applyContentTransformation(scrollProgress) } }
                    .height(25.dp)
                    .border(BorderStroke(1.dp, borderColor), shape),
                contentAlignment = Alignment.Center
            ) {
                ScalableText(
                    modifier = Modifier.padding(vertical = 2.5.dp, horizontal = 5.dp),
                    text = "REST ${FormatTime(restSeconds)}",
                    style = MaterialTheme.typography.numeralMedium,
                    color = borderColor,
                )
            }
        }
    }

    item {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .transformedHeight(this, transformationSpec)
                .graphicsLayer { with(transformationSpec) { applyContainerTransformation(scrollProgress) } },
            contentAlignment = Alignment.Center
        ) {
            Column(
                modifier = Modifier.graphicsLayer {
                    with(transformationSpec) { applyContentTransformation(scrollProgress) }
                },
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(2.5.dp)
            ) {
                val titleStyle = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.SemiBold)
                Text(
                    text = "TO",
                    style = MaterialTheme.typography.bodyExtraSmall,
                    color = MaterialTheme.colorScheme.onBackground,
                    textAlign = TextAlign.Center
                )
                ExerciseNameText(
                    text = nextDisplayName,
                    modifier = Modifier.fillMaxWidth(),
                    style = titleStyle,
                    textAlign = TextAlign.Center
                )
            }
        }
    }
}

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
    val liveWorkoutState by viewModel.workoutState.collectAsState()
    val titleStyle = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.SemiBold)
    val pageCount = pageItems.size
    val displayCounter = remember(pageItems, selectedPageIndex.value) {
        resolvePageExercisesDisplayCounter(
            items = pageItems,
            selectedPageIndex = selectedPageIndex.value
        )
    }
    val transformingLazyColumnState = rememberTransformingLazyColumnState()
    val transformationSpec = rememberTransformationSpec(
        ResponsiveTransformationSpec.smallScreen(
            containerAlpha = TransformationVariableSpec(1f),
            contentAlpha = TransformationVariableSpec(1f),
            scale = TransformationVariableSpec(0.75f)
        ),
        ResponsiveTransformationSpec.largeScreen(
            containerAlpha = TransformationVariableSpec(1f),
            contentAlpha = TransformationVariableSpec(1f),
            scale = TransformationVariableSpec(0.6f)
        )
    )

    LaunchedEffect(selectedPageIndex.value, selectedRestPageId) {
        transformingLazyColumnState.scrollToItem(0)
    }
    val firstSetListItemIndex = 2
    val selectedProgressState = when {
        selectedPageIndex.value < currentPageIndex.value -> ProgressState.PAST
        selectedPageIndex.value > currentPageIndex.value -> ProgressState.FUTURE
        else -> ProgressState.CURRENT
    }
    val selectedSetStateToMatch = if (selectedProgressState == ProgressState.CURRENT) {
        workoutState ?: liveWorkoutState
    } else {
        liveWorkoutState
    }
    val selectedPageCurrentSet = selectedPageItem?.let { page ->
        if (page is PageExercisesItem.RestPage) null else resolvePageCurrentSet(page, activeWorkoutState)
    }
    val targetItemIndex = remember(
        selectedPageItem,
        selectedPageCurrentSet?.id,
        selectedSetStateToMatch,
        firstSetListItemIndex,
        viewModel.allWorkoutStates.size
    ) {
        if (selectedPageItem == null || selectedPageItem is PageExercisesItem.RestPage || selectedPageCurrentSet == null) {
            null
        } else {
            resolveExerciseSetsScrollTargetIndex(
                viewModel = viewModel,
                exercise = selectedPageItem.representativeExercise,
                currentSet = selectedPageCurrentSet,
                stateToMatch = selectedSetStateToMatch,
                firstSetListItemIndex = firstSetListItemIndex
            )
        }
    }
    var isAutoScrolling by remember { mutableStateOf(false) }
    LaunchedEffect(targetItemIndex, selectedPageIndex.value) {
        val targetIndex = targetItemIndex ?: return@LaunchedEffect
        if (isAutoScrolling) return@LaunchedEffect
        isAutoScrolling = true
        try {
            transformingLazyColumnState.animateScrollToItem(targetIndex)
        } finally {
            isAutoScrolling = false
        }
    }

    val customAlignment = if (selectedPageItem is PageExercisesItem.RestPage){ Alignment.CenterVertically} else { Alignment.Top }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .semantics { contentDescription = "Exercise sets viewer" }
    ) {
        ScreenScaffold(
            modifier = Modifier.fillMaxSize(),
            scrollState = transformingLazyColumnState,
            scrollIndicator = {
                ScrollIndicator(
                    state = transformingLazyColumnState,
                    colors = ScrollIndicatorDefaults.colors(
                        indicatorColor = MaterialTheme.colorScheme.onBackground,
                        trackColor = MediumDarkGray
                    )
                )
            }
        ) { contentPadding ->
            TransformingLazyColumn(
                modifier = Modifier.padding(horizontal = 20.dp),
                state = transformingLazyColumnState,
                userScrollEnabled = !isAutoScrolling,
                verticalArrangement = Arrangement.spacedBy(5.dp, customAlignment),
                contentPadding = WorkoutPagerPageSafeAreaPadding
                //contentPadding = contentPadding,
            ) {
                if (selectedPageItem !is PageExercisesItem.RestPage) {
                    item {
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .transformedHeight(this, transformationSpec)
                                .graphicsLayer { with(transformationSpec) { applyContainerTransformation(scrollProgress) } },
                        ) {
                            when (selectedPageItem) {
                                is PageExercisesItem.SupersetPage -> ExerciseNameText(
                                    text = buildSupersetDisplayName(selectedPageItem.exercises),
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .height(25.dp),
                                    style = titleStyle,
                                    textAlign = TextAlign.Center
                                )
                                is PageExercisesItem.ExercisePage -> ExerciseNameText(
                                    text = AnnotatedString(selectedPageItem.exercise.name),
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .height(25.dp),
                                    style = titleStyle,
                                    textAlign = TextAlign.Center
                                )
                                else -> Unit
                            }
                        }
                    }
                }

                item {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .transformedHeight(this, transformationSpec)
                            .graphicsLayer { with(transformationSpec) { applyContainerTransformation(scrollProgress) } },
                        contentAlignment = Alignment.Center
                    ) {
                        Box(
                            modifier = Modifier.graphicsLayer {
                                with(transformationSpec) { applyContentTransformation(scrollProgress) }
                            }
                        ) {
                            when (selectedPageItem) {
                                is PageExercisesItem.SupersetPage -> {
                                    SupersetMetadataStrip(containerLabel = displayCounter)
                                }
                                is PageExercisesItem.ExercisePage -> {
                                    ExerciseMetadataStrip(
                                        exerciseLabel = displayCounter,
                                        supersetExerciseIndex = null,
                                        supersetExerciseTotal = null,
                                        sideIndicator = null,
                                        currentSideIndex = null
                                    )
                                }
                                else -> Unit
                            }
                        }
                    }
                }

                if (selectedPageItem != null) {
                    val progressState = selectedProgressState
                    when (selectedPageItem) {
                        is PageExercisesItem.RestPage -> {
                            RestPageContent(
                                restState = selectedPageItem.restState,
                                previousDisplayName = selectedPageItem.previousDisplayName,
                                nextDisplayName = selectedPageItem.nextDisplayName,
                                progressState = progressState,
                                transformationSpec = transformationSpec
                            )
                        }
                        else -> {
                            val currentSet = resolvePageCurrentSet(selectedPageItem, activeWorkoutState)
                            if (currentSet != null) {
                                ExerciseSetsViewer(
                                    viewModel = viewModel,
                                    hapticsViewModel = hapticsViewModel,
                                    exercise = selectedPageItem.representativeExercise,
                                    currentSet = currentSet,
                                    transformationSpec = transformationSpec,
                                    columnState = transformingLazyColumnState,
                                    firstSetListItemIndex = firstSetListItemIndex,
                                    stateToMatch = selectedSetStateToMatch,
                                    progressState = progressState,
                                )
                            }
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
    val supersetExercise: Exercise,
    val selectedExercise: Exercise,
    val currentExercise: Exercise,
    val firstSetState: WorkoutState.Set,
    val supersetSetState: WorkoutState.Set,
    val restState: WorkoutState.Rest,
)

private fun buildPageExercisesPreviewFixture(): PageExercisesPreviewFixture {
    val viewModel = AppViewModel()
    val firstExercise = Exercise(
        id = UUID.fromString("71000000-0000-0000-0000-000000000001"),
        enabled = true,
        name = "Bench Press",
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
            ),
            RestSet(
                id = UUID.fromString("72000000-0000-0000-0000-000000000004"),
                timeInSeconds = 160,
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
    val supersetExerciseA = Exercise(
        id = UUID.fromString("71000000-0000-0000-0000-000000000003"),
        enabled = true,
        name = "Incline Dumbbell Press",
        notes = "",
        sets = listOf(
            WeightSet(
                id = UUID.fromString("72000000-0000-0000-0000-000000000006"),
                reps = 12,
                weight = 24.0,
                subCategory = SetSubCategory.WorkSet
            )
        ),
        exerciseType = ExerciseType.WEIGHT,
        minLoadPercent = 0.0,
        maxLoadPercent = 100.0,
        minReps = 8,
        maxReps = 15,
        lowerBoundMaxHRPercent = null,
        upperBoundMaxHRPercent = null,
        equipmentId = null,
        bodyWeightPercentage = null,
        generateWarmUpSets = false,
        keepScreenOn = false,
        showCountDownTimer = false,
        requiresLoadCalibration = false
    )
    val supersetExerciseB = Exercise(
        id = UUID.fromString("71000000-0000-0000-0000-000000000004"),
        enabled = true,
        name = "One-arm Row",
        notes = "",
        sets = listOf(
            WeightSet(
                id = UUID.fromString("72000000-0000-0000-0000-000000000007"),
                reps = 12,
                weight = 22.0,
                subCategory = SetSubCategory.WorkSet
            )
        ),
        exerciseType = ExerciseType.WEIGHT,
        minLoadPercent = 0.0,
        maxLoadPercent = 100.0,
        minReps = 8,
        maxReps = 15,
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
    val supersetSetState = WorkoutState.Set(
        exerciseId = supersetExerciseA.id,
        set = supersetExerciseA.sets.first(),
        setIndex = 1u,
        previousSetData = WeightSetData(actualReps = 10, actualWeight = 22.0, volume = 220.0),
        currentSetDataState = androidx.compose.runtime.mutableStateOf(
            WeightSetData(actualReps = 12, actualWeight = 24.0, volume = 288.0)
        ),
        hasNoHistory = false,
        skipped = false,
        currentBodyWeight = 0.0,
        streak = 1,
        progressionState = null,
        isWarmupSet = false,
        equipmentId = null
    )
    val supersetPartnerSetState = WorkoutState.Set(
        exerciseId = supersetExerciseB.id,
        set = supersetExerciseB.sets.first(),
        setIndex = 1u,
        previousSetData = WeightSetData(actualReps = 10, actualWeight = 20.0, volume = 200.0),
        currentSetDataState = androidx.compose.runtime.mutableStateOf(
            WeightSetData(actualReps = 12, actualWeight = 22.0, volume = 264.0)
        ),
        hasNoHistory = false,
        skipped = false,
        currentBodyWeight = 0.0,
        streak = 1,
        progressionState = null,
        isWarmupSet = false,
        equipmentId = null
    )
    val supersetId = UUID.fromString("73000000-0000-0000-0000-000000000001")

    val sequence = listOf(
        WorkoutStateSequenceItem.Container(
            WorkoutStateContainer.ExerciseState(
                exerciseId = firstExercise.id,
                childItems = mutableListOf(
                    ExerciseChildItem.Normal(firstSetState),
                    ExerciseChildItem.Normal(firstExerciseRestState),
                    ExerciseChildItem.Normal(firstExerciseSecondSetState),
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
        ),
        WorkoutStateSequenceItem.Container(
            WorkoutStateContainer.SupersetState(
                supersetId = supersetId,
                childStates = mutableListOf(supersetSetState, supersetPartnerSetState)
            )
        )
    )
    val stateMachine = WorkoutStateMachine.fromSequence(sequence, startIndex = 1)

    viewModel.exercisesById = mapOf(
        firstExercise.id to firstExercise,
        secondExercise.id to secondExercise,
        supersetExerciseA.id to supersetExerciseA,
        supersetExerciseB.id to supersetExerciseB
    )
    viewModel.supersetIdByExerciseId = mapOf(
        supersetExerciseA.id to supersetId,
        supersetExerciseB.id to supersetId
    )
    viewModel.exercisesBySupersetId = mapOf(
        supersetId to listOf(supersetExerciseA, supersetExerciseB)
    )
    setFieldValue(viewModel, "stateMachine", stateMachine)
    setCurrentWorkoutState(viewModel, restState)

    return PageExercisesPreviewFixture(
        viewModel = viewModel,
        firstExercise = firstExercise,
        supersetExercise = supersetExerciseA,
        selectedExercise = secondExercise,
        currentExercise = firstExercise,
        firstSetState = firstSetState,
        supersetSetState = supersetSetState,
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

@Preview(
    name = "Superset Exercise Page",
    group = "PageExercises",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
private fun PageExercisesSupersetPagePreview() {
    val fixture = remember { buildPageExercisesPreviewFixture() }
    val context = LocalContext.current
    val hapticsViewModel = remember(context) { HapticsViewModel(context, HapticsHelper(context)) }

    MyWorkoutAssistantTheme {
        PageExercises(
            selectedExercise = fixture.supersetExercise,
            selectedRestPageId = null,
            workoutState = fixture.supersetSetState,
            viewModel = fixture.viewModel,
            hapticsViewModel = hapticsViewModel,
            currentExercise = fixture.supersetExercise,
            onPageSelected = { _, _ -> }
        )
    }
}
