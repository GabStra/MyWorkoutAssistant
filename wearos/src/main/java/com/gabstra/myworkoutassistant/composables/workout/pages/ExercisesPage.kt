package com.gabstra.myworkoutassistant.composables.workout.pages

import com.gabstra.myworkoutassistant.composables.*

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.wrapContentHeight
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnScope
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnState
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.IconButton
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
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.display.ExerciseSetDisplayRow
import com.gabstra.myworkoutassistant.shared.workout.display.buildSupersetSetDisplayRows
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

internal sealed class ExercisesPageItem {
    abstract val representativeExercise: Exercise

    data class ExercisePage(
        val exercise: Exercise,
    ) : ExercisesPageItem() {
        override val representativeExercise: Exercise = exercise
    }

    data class SupersetPage(
        val supersetId: UUID,
        val exercises: List<Exercise>,
    ) : ExercisesPageItem() {
        override val representativeExercise: Exercise = exercises.first()
    }

    data class RestPage(
        val restState: WorkoutState.Rest,
        val previousDisplayName: AnnotatedString,
        val nextDisplayName: AnnotatedString,
        override val representativeExercise: Exercise,
    ) : ExercisesPageItem()
}

private data class ExercisesPageStateMatchKey(
    val type: String,
    val exerciseId: UUID?,
    val setLikeId: UUID?,
    val order: UInt?,
)

private fun buildExercisesPageStateMatchKey(state: WorkoutState?): ExercisesPageStateMatchKey? = when (state) {
    is WorkoutState.Set -> ExercisesPageStateMatchKey(
        type = "set",
        exerciseId = state.exerciseId,
        setLikeId = state.set.id,
        order = state.setIndex
    )
    is WorkoutState.Rest -> ExercisesPageStateMatchKey(
        type = "rest",
        exerciseId = state.exerciseId,
        setLikeId = state.set.id,
        order = state.order
    )
    is WorkoutState.CalibrationLoadSelection -> ExercisesPageStateMatchKey(
        type = "calibration_load",
        exerciseId = state.exerciseId,
        setLikeId = state.calibrationSet.id,
        order = state.setIndex
    )
    is WorkoutState.CalibrationRIRSelection -> ExercisesPageStateMatchKey(
        type = "calibration_rir",
        exerciseId = state.exerciseId,
        setLikeId = state.calibrationSet.id,
        order = state.setIndex
    )
    is WorkoutState.AutoRegulationRIRSelection -> ExercisesPageStateMatchKey(
        type = "auto_regulation_rir",
        exerciseId = state.exerciseId,
        setLikeId = state.workSet.id,
        order = state.setIndex
    )
    else -> null
}

internal fun resolveExercisesPageActiveState(
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

internal fun buildExercisesPageItems(viewModel: AppViewModel): List<ExercisesPageItem> {
    val sequenceItems = viewModel.getWorkoutSequenceItems()
    return sequenceItems.mapIndexedNotNull { index, item ->
        when (item) {
            is WorkoutStateSequenceItem.Container -> {
                when (val container = item.container) {
                    is WorkoutStateContainer.ExerciseState -> {
                        viewModel.exercisesById[container.exerciseId]?.let(ExercisesPageItem::ExercisePage)
                    }
                    is WorkoutStateContainer.SupersetState -> {
                        viewModel.exercisesBySupersetId[container.supersetId]
                            ?.takeIf { it.isNotEmpty() }
                            ?.let { exercises ->
                                ExercisesPageItem.SupersetPage(
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

                ExercisesPageItem.RestPage(
                    restState = item.rest,
                    previousDisplayName = previousDisplayName,
                    nextDisplayName = nextDisplayName,
                    representativeExercise = nextExercise
                )
            }
        }
    }
}

internal fun resolveExercisesPageItemIndex(
    items: List<ExercisesPageItem>,
    selectedExercise: Exercise,
    viewModel: AppViewModel,
): Int {
    val selectedExerciseOrSupersetId = resolveExerciseOrSupersetId(viewModel, selectedExercise.id)

    val directExerciseOrSupersetIndex = items.indexOfFirst { page ->
        when (page) {
            is ExercisesPageItem.ExercisePage -> page.exercise.id == selectedExercise.id
            is ExercisesPageItem.SupersetPage -> page.supersetId == selectedExerciseOrSupersetId
            is ExercisesPageItem.RestPage -> false
        }
    }
    if (directExerciseOrSupersetIndex >= 0) return directExerciseOrSupersetIndex

    val restIndex = items.indexOfFirst { page ->
        page is ExercisesPageItem.RestPage && page.representativeExercise.id == selectedExercise.id
    }
    return restIndex.takeIf { it >= 0 } ?: 0
}

internal fun resolveExercisesPageDisplayCounter(
    items: List<ExercisesPageItem>,
    selectedPageIndex: Int,
): String? {
    if (items.isEmpty() || selectedPageIndex !in items.indices) return null

    val countedPageIndices = items.mapIndexedNotNull { index, item ->
        index.takeIf { item !is ExercisesPageItem.RestPage }
    }
    if (countedPageIndices.size <= 1) return null

    val selectedItem = items[selectedPageIndex]
    val displayIndex = when (selectedItem) {
        is ExercisesPageItem.RestPage -> {
            countedPageIndices.indexOfFirst { index ->
                when (val item = items[index]) {
                    is ExercisesPageItem.ExercisePage ->
                        item.exercise.id == selectedItem.representativeExercise.id
                    is ExercisesPageItem.SupersetPage ->
                        item.exercises.any { exercise -> exercise.id == selectedItem.representativeExercise.id }
                    is ExercisesPageItem.RestPage -> false
                }
            }
        }
        else -> countedPageIndices.indexOf(selectedPageIndex)
    }.takeIf { it >= 0 } ?: return null

    return "${displayIndex + 1}/${countedPageIndices.size}"
}

internal fun resolveExercisesPageCurrentItemIndex(
    items: List<ExercisesPageItem>,
    workoutState: WorkoutState?,
    fallbackSetState: WorkoutState.Set? = null,
    viewModel: AppViewModel,
): Int {
    if (items.isEmpty()) return -1
    if (workoutState is WorkoutState.Rest && workoutState.exerciseId == null) {
        val restIndex = items.indexOfFirst { page ->
            page is ExercisesPageItem.RestPage && page.restState == workoutState
        }
        if (restIndex >= 0) return restIndex
    }

    val activeState = resolveExercisesPageActiveState(workoutState, fallbackSetState)
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
            is ExercisesPageItem.ExercisePage -> page.exercise.id == activeExerciseId
            is ExercisesPageItem.SupersetPage -> page.supersetId == activeExerciseOrSupersetId
            is ExercisesPageItem.RestPage -> false
        }
    }.takeIf { it >= 0 } ?: 0
}

private fun resolvePageCurrentSet(
    pageItem: ExercisesPageItem,
    activeWorkoutState: WorkoutState?,
): com.gabstra.myworkoutassistant.shared.sets.Set? {
    return when (pageItem) {
        is ExercisesPageItem.RestPage -> when (activeWorkoutState) {
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

private fun shouldUseWeightHeader(
    viewModel: AppViewModel,
    pageItem: ExercisesPageItem,
): Boolean {
    if (pageItem is ExercisesPageItem.RestPage) return false

    val supersetId = (pageItem as? ExercisesPageItem.SupersetPage)?.supersetId
        ?: viewModel.supersetIdByExerciseId[pageItem.representativeExercise.id]

    if (supersetId == null) {
        return pageItem.representativeExercise.exerciseType == ExerciseType.WEIGHT ||
            pageItem.representativeExercise.exerciseType == ExerciseType.BODY_WEIGHT
    }

    return buildSupersetSetDisplayRows(viewModel = viewModel, supersetId = supersetId).any { row ->
        (row as? ExerciseSetDisplayRow.SetRow)?.state?.currentSetData?.let { setData ->
            setData is WeightSetData || setData is BodyWeightSetData
        } ?: false
    }
}

@Composable
private fun ExercisePageFixedHeader(
    modifier: Modifier = Modifier,
    pageItem: ExercisesPageItem,
    displayCounter: String?,
    useWeightHeader: Boolean,
    canSelectPrevious: Boolean,
    canSelectNext: Boolean,
    onSelectPrevious: () -> Unit,
    onSelectNext: () -> Unit,
) {
    val titleStyle = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.SemiBold)

    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.Bottom,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        ExercisesPageNavigationHeader(
            canSelectPrevious = canSelectPrevious,
            canSelectNext = canSelectNext,
            onSelectPrevious = onSelectPrevious,
            onSelectNext = onSelectNext,
        ) {
            when (pageItem) {
                is ExercisesPageItem.SupersetPage -> ExerciseNameText(
                    text = buildSupersetDisplayName(pageItem.exercises),
                    modifier = Modifier
                        .fillMaxWidth(),
                    style = titleStyle,
                    textAlign = TextAlign.Center
                )
                is ExercisesPageItem.ExercisePage -> ExerciseNameText(
                    text = AnnotatedString(pageItem.exercise.name),
                    modifier = Modifier
                        .fillMaxWidth(),
                    style = titleStyle,
                    textAlign = TextAlign.Center
                )
                is ExercisesPageItem.RestPage -> error("Rest pages use RestPageFixedHeader")
            }
        }

/*        Box(
            modifier = Modifier.fillMaxWidth(),
            contentAlignment = Alignment.Center
        ) {
            when (pageItem) {
                is ExercisesPageItem.SupersetPage -> {
                    SupersetMetadataStrip(containerLabel = displayCounter)
                }
                is ExercisesPageItem.ExercisePage -> {
                    ExerciseMetadataStrip(
                        exerciseLabel = displayCounter,
                        supersetExerciseIndex = null,
                        supersetExerciseTotal = null,
                        sideIndicator = null,
                        currentSideIndex = null
                    )
                }
                is ExercisesPageItem.RestPage -> error("Rest pages use RestPageFixedHeader")
            }
        }*/

/*        Box(
            modifier = Modifier.fillMaxSize(),
            contentAlignment = Alignment.BottomCenter
        ) {
            ExerciseSetsTableHeader(useWeightHeader = useWeightHeader)
        }*/
    }


}

@Composable
private fun RestPageFixedHeader(
    modifier: Modifier = Modifier,
    pageItem: ExercisesPageItem.RestPage,
    canSelectPrevious: Boolean,
    canSelectNext: Boolean,
    onSelectPrevious: () -> Unit,
    onSelectNext: () -> Unit,
) {
    Column(
        modifier = modifier.fillMaxWidth(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.SpaceBetween
    ) {
        ExercisesPageNavigationHeader(
            canSelectPrevious = canSelectPrevious,
            canSelectNext = canSelectNext,
            onSelectPrevious = onSelectPrevious,
            onSelectNext = onSelectNext,
        ) {
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(2.5.dp)
            ) {
                Text(
                    text = "UP NEXT",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onBackground
                )

                ExerciseNameText(
                    text = pageItem.nextDisplayName,
                    modifier = Modifier
                        .fillMaxWidth()
                        .semantics {
                            contentDescription = ExercisesPageRestSemantics.nextExerciseDescription(
                                pageItem.nextDisplayName.text
                            )
                        },
                    style = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.SemiBold),
                    textAlign = TextAlign.Center
                )
            }
        }
    }
}

@Composable
private fun ExercisesPageNavigationHeader(
    canSelectPrevious: Boolean,
    canSelectNext: Boolean,
    onSelectPrevious: () -> Unit,
    onSelectNext: () -> Unit,
    content: @Composable () -> Unit,
) {
    Box(
        modifier = Modifier.fillMaxWidth(),
        contentAlignment = Alignment.Center,
    ) {
        Box(
            modifier = Modifier.padding(horizontal = 44.dp),
            contentAlignment = Alignment.Center,
        ) {
            content()
        }
        IconButton(
            onClick = onSelectPrevious,
            modifier = Modifier
                .align(Alignment.CenterStart)
                .size(48.dp),
            enabled = canSelectPrevious,
        ) {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.KeyboardArrowLeft,
                contentDescription = "Previous workout step",
                modifier = Modifier.size(32.dp),
            )
        }
        IconButton(
            onClick = onSelectNext,
            modifier = Modifier
                .align(Alignment.CenterEnd)
                .size(48.dp),
            enabled = canSelectNext,
        ) {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
                contentDescription = "Next workout step",
                modifier = Modifier.size(32.dp),
            )
        }
    }
}

private fun TransformingLazyColumnScope.RestPageContent(
    restState: WorkoutState.Rest,
    progressState: ProgressState,
    transformationSpec: androidx.wear.compose.material3.lazy.TransformationSpec,
) {
    val restSeconds = (restState.set as? RestSet)?.timeInSeconds ?: 0
    val formattedRest = FormatTime(restSeconds)

    item {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .transformedHeight(this, transformationSpec)
                .graphicsLayer { with(transformationSpec) { applyContainerTransformation(scrollProgress) } },
            contentAlignment = Alignment.Center
        ) {
            val completedFillColor = MaterialTheme.colorScheme.onBackground
            val completedTextColor = MaterialTheme.colorScheme.background
            val borderColor: Color = when (progressState) {
                ProgressState.PAST -> completedFillColor
                ProgressState.CURRENT -> MaterialTheme.colorScheme.primary
                ProgressState.FUTURE -> MaterialTheme.colorScheme.surfaceContainerHigh
            }
            val backgroundColor: Color = when (progressState) {
                ProgressState.PAST -> completedFillColor
                ProgressState.CURRENT -> MaterialTheme.colorScheme.primary
                else -> MaterialTheme.colorScheme.background
            }
            val textColor: Color = when (progressState) {
                ProgressState.PAST -> completedTextColor
                ProgressState.CURRENT -> MaterialTheme.colorScheme.onPrimary
                else -> borderColor
            }
            val shape = RoundedCornerShape(25)
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .graphicsLayer { with(transformationSpec) { applyContentTransformation(scrollProgress) } }
                    .height(25.dp)
                    .background(backgroundColor, shape)
                    .border(BorderStroke(1.dp, borderColor), shape)
                    .semantics {
                        contentDescription = ExercisesPageRestSemantics.restDurationRowDescription(formattedRest)
                    },
                contentAlignment = Alignment.Center
            ) {
                ScalableText(
                    modifier = Modifier.padding(vertical = 2.5.dp, horizontal = 5.dp),
                    text = "REST $formattedRest",
                    style = MaterialTheme.typography.numeralMedium,
                    color = textColor,
                )
            }
        }
    }
}

private fun TransformingLazyColumnScope.InvisibleListSpacer(height: Dp) {
    item {
        Spacer(
            modifier = Modifier
                .fillMaxWidth()
                .height(height)
        )
    }
}

@Composable
fun ExercisesPage(
    selectedExercise: Exercise,
    selectedRestPageId: UUID? = null,
    workoutState: WorkoutState?,
    viewModel: AppViewModel,
    hapticsViewModel: HapticsViewModel,
    currentExercise: Exercise,
    showAllAsCompleted: Boolean = false,
    onPageSelected: (Exercise, UUID?) -> Unit
) {
    val pageItems = remember(viewModel.allWorkoutStates.size, viewModel.supersetIdByExerciseId, viewModel.exercisesBySupersetId) {
        buildExercisesPageItems(viewModel)
    }
    val activeWorkoutState = remember(workoutState, viewModel.allWorkoutStates.size) {
        resolveExercisesPageActiveState(
            workoutState = workoutState,
            fallbackSetState = viewModel.getFirstSetStateAfterCurrent()
        )
    }

    val selectedPageIndex = remember(pageItems, selectedExercise, selectedRestPageId, workoutState, viewModel.allWorkoutStates.size) {
        derivedStateOf {
            if (selectedRestPageId != null) {
                pageItems.indexOfFirst { page ->
                    page is ExercisesPageItem.RestPage && page.restState.set.id == selectedRestPageId
                }.takeIf { it >= 0 } ?: 0
            } else {
                resolveExercisesPageItemIndex(
                    items = pageItems,
                    selectedExercise = selectedExercise,
                    viewModel = viewModel
                )
            }
        }
    }
    val currentPageIndex = remember(pageItems, workoutState, currentExercise.id, viewModel.allWorkoutStates.size) {
        derivedStateOf {
            resolveExercisesPageCurrentItemIndex(
                items = pageItems,
                workoutState = workoutState,
                fallbackSetState = viewModel.getFirstSetStateAfterCurrent(),
                viewModel = viewModel
            )
        }
    }

    val selectedPageItem = pageItems.getOrNull(selectedPageIndex.value)
    val liveWorkoutState by viewModel.workoutState.collectAsState()
    val pageCount = pageItems.size
    val selectPageAt: (Int) -> Unit = { pageIndex ->
        pageItems.getOrNull(pageIndex)?.let { page ->
            hapticsViewModel.doGentleVibration()
            onPageSelected(
                page.representativeExercise,
                (page as? ExercisesPageItem.RestPage)?.restState?.set?.id
            )
        }
    }
    val displayCounter = remember(pageItems, selectedPageIndex.value) {
        resolveExercisesPageDisplayCounter(
            items = pageItems,
            selectedPageIndex = selectedPageIndex.value
        )
    }
    val selectedStepLabel = remember(pageItems, selectedPageIndex.value) {
        if (pageItems.isEmpty() || selectedPageIndex.value !in pageItems.indices) {
            null
        } else {
            "Step: ${selectedPageIndex.value + 1}/${pageItems.size}"
        }
    }
    // Item 0 is the spacer used to reserve room for the fixed header overlay.
    val firstSetListItemIndex = 1
    val selectedProgressState = when {
        showAllAsCompleted -> ProgressState.PAST
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
        if (page is ExercisesPageItem.RestPage) null else resolvePageCurrentSet(page, activeWorkoutState)
    }
    val selectedPagePreparedRowsKey = remember(
        selectedPageItem,
        selectedPageCurrentSet,
        selectedSetStateToMatch,
        viewModel.allWorkoutStates.size
    ) {
        Triple(
            selectedPageItem,
            selectedPageCurrentSet?.id,
            buildExercisesPageStateMatchKey(selectedSetStateToMatch) to viewModel.allWorkoutStates.size
        )
    }
    val selectedPagePreparedRows = remember(
        selectedPagePreparedRowsKey
    ) {
        val pageItem = selectedPageItem
        val currentSet = selectedPageCurrentSet
        if (pageItem != null && pageItem !is ExercisesPageItem.RestPage && currentSet != null) {
            buildExercisesPagePreparedRows(
                viewModel = viewModel,
                exercise = pageItem.representativeExercise,
                currentSet = currentSet,
                stateToMatch = selectedSetStateToMatch
            )
        } else {
            null
        }
    }
    val targetItemIndex = remember(
        selectedPageItem,
        selectedPagePreparedRows,
        firstSetListItemIndex,
    ) {
        when {
            selectedPageItem == null -> null
            selectedPageItem is ExercisesPageItem.RestPage -> firstSetListItemIndex
            selectedPagePreparedRows == null -> null
            else -> (firstSetListItemIndex + selectedPagePreparedRows.setIndex).coerceAtLeast(firstSetListItemIndex)
        }
    }
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
    var isAutoScrolling by remember { mutableStateOf(false) }

    val useWeightHeader = remember(selectedPageItem, viewModel.allWorkoutStates.size) {
        selectedPageItem?.let { pageItem ->
            shouldUseWeightHeader(viewModel = viewModel, pageItem = pageItem)
        } ?: false
    }
    val isSelectedPageScrollable = remember(selectedPageItem, selectedPagePreparedRows) {
        when (selectedPageItem) {
            is ExercisesPageItem.RestPage,
            null -> false
            else -> (selectedPagePreparedRows?.rowModels?.size ?: 0) > 1
        }
    }
    val headerOverlayHeightDp = 40.dp
    val density = LocalDensity.current

    BoxWithConstraints(
        modifier = Modifier
            .fillMaxSize()
            .semantics { contentDescription = "Exercise sets viewer" }
    ) {
        val topSection = headerOverlayHeightDp + WorkoutPagerPageSafeAreaPadding.calculateTopPadding()
        val stepIndicatorReservedHeightDp = 30.dp
        val listContentPadding = PaddingValues(
            top = WorkoutPagerPageSafeAreaPadding.calculateTopPadding(),
            bottom = stepIndicatorReservedHeightDp,
        )
        val selectedRowHeightDp = 25.dp
        val itemSpacingDp = 5.dp
        val selectedRowScrollOffsetPx = with(density) {
            ((maxHeight / 2) - (selectedRowHeightDp / 2) - topSection - itemSpacingDp/2).roundToPx()
        }
        val initialAnchorItemIndex = targetItemIndex ?: 0
        val transformingLazyColumnState: TransformingLazyColumnState = remember(
            selectedPageIndex.value,
            initialAnchorItemIndex,
            selectedRowScrollOffsetPx
        ) {
            TransformingLazyColumnState(
                initialAnchorItemIndex = initialAnchorItemIndex,
                initialAnchorItemScrollOffset = selectedRowScrollOffsetPx
            )
        }
        val rowMaxWidth = (maxWidth - 40.dp).coerceAtLeast(0.dp)
        val fittedRows = rememberExercisesPageFittedRows(
            preparedRows = selectedPagePreparedRows,
            rowMaxWidth = rowMaxWidth,
            rowMaxHeight = selectedRowHeightDp,
        )
        val bottomSpacerHeightDp = (
            maxHeight -
                topSection -
                selectedRowHeightDp -
                itemSpacingDp -
                stepIndicatorReservedHeightDp
            ).coerceAtLeast(0.dp)

        val maximumVisibleRows = 4
        val visibleRowsHeight =
            selectedRowHeightDp * maximumVisibleRows +
                    itemSpacingDp * (maximumVisibleRows - 1)

        // One spacing exists between the invisible header spacer and the first row.
        val firstRowTop = topSection + itemSpacingDp

        val footerMaskHeight = (
                maxHeight - firstRowTop - visibleRowsHeight
                ).coerceAtLeast(stepIndicatorReservedHeightDp)

        LaunchedEffect(targetItemIndex, selectedPageIndex.value, selectedRowScrollOffsetPx) {
            val targetIndex = targetItemIndex ?: return@LaunchedEffect
            if (isAutoScrolling) return@LaunchedEffect
            isAutoScrolling = true
            try {
                transformingLazyColumnState.scrollToItem(
                    index = targetIndex,
                    scrollOffset = selectedRowScrollOffsetPx
                )
            } finally {
                isAutoScrolling = false
            }
        }

        ScreenScaffold(
            modifier = Modifier.fillMaxSize(),
            scrollState = transformingLazyColumnState,
            scrollIndicator = {
                if (isSelectedPageScrollable) {
                    ScrollIndicator(
                        state = transformingLazyColumnState,
                        colors = ScrollIndicatorDefaults.colors(
                            indicatorColor = MaterialTheme.colorScheme.onBackground,
                            trackColor = MediumDarkGray
                        )
                    )
                }
            }
        ) { _ ->
            if (selectedPageItem is ExercisesPageItem.RestPage) {
                TransformingLazyColumn(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(horizontal = 20.dp),
                    state = transformingLazyColumnState,
                    userScrollEnabled = false,
                    verticalArrangement = Arrangement.spacedBy(itemSpacingDp, Alignment.Top),
                    contentPadding = listContentPadding
                ) {
                    InvisibleListSpacer(headerOverlayHeightDp)
                    RestPageContent(
                        restState = selectedPageItem.restState,
                        progressState = selectedProgressState,
                        transformationSpec = transformationSpec
                    )
                    InvisibleListSpacer(bottomSpacerHeightDp)
                }
            } else if (selectedPageItem != null) {
                val currentSet = resolvePageCurrentSet(selectedPageItem, activeWorkoutState)
                if (currentSet != null) {
                    TransformingLazyColumn(
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(horizontal = 20.dp),
                        state = transformingLazyColumnState,
                        userScrollEnabled = isSelectedPageScrollable && !isAutoScrolling,
                        verticalArrangement = Arrangement.spacedBy(itemSpacingDp, Alignment.Top),
                        contentPadding = listContentPadding
                    ) {
                        InvisibleListSpacer(headerOverlayHeightDp)
                        ExerciseSetsViewer(
                            viewModel = viewModel,
                            exercise = selectedPageItem.representativeExercise,
                            currentSet = currentSet,
                            transformationSpec = transformationSpec,
                            stateToMatch = selectedSetStateToMatch,
                            progressState = selectedProgressState,
                            preparedRows = selectedPagePreparedRows,
                            fittedRows = fittedRows,
                            enableFadingText = !transformingLazyColumnState.isScrollInProgress,
                        )
                        InvisibleListSpacer(bottomSpacerHeightDp)
                    }
                }
            }
        }

        if (selectedPageItem != null) {
            Column(
                modifier = Modifier
                    .align(Alignment.TopCenter)
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp)
                    .background(MaterialTheme.colorScheme.background)
            ) {
                when (selectedPageItem) {
                    is ExercisesPageItem.RestPage -> RestPageFixedHeader(
                        modifier = Modifier
                            .padding(top = WorkoutPagerPageSafeAreaPadding.calculateTopPadding())
                            .height(headerOverlayHeightDp)
                            .padding(bottom = 2.5.dp),
                        pageItem = selectedPageItem,
                        canSelectPrevious = selectedPageIndex.value > 0,
                        canSelectNext = selectedPageIndex.value < pageCount - 1,
                        onSelectPrevious = { selectPageAt(selectedPageIndex.value - 1) },
                        onSelectNext = { selectPageAt(selectedPageIndex.value + 1) },
                    )
                    else -> ExercisePageFixedHeader(
                        modifier = Modifier
                            .padding(top = WorkoutPagerPageSafeAreaPadding.calculateTopPadding())
                            .height(headerOverlayHeightDp)
                            .padding(bottom = 2.5.dp),
                        pageItem = selectedPageItem,
                        displayCounter = displayCounter,
                        useWeightHeader = useWeightHeader,
                        canSelectPrevious = selectedPageIndex.value > 0,
                        canSelectNext = selectedPageIndex.value < pageCount - 1,
                        onSelectPrevious = { selectPageAt(selectedPageIndex.value - 1) },
                        onSelectNext = { selectPageAt(selectedPageIndex.value + 1) },
                    )
                }
            }
        }

        Box(
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth()
                .height(footerMaskHeight)
                .background(MaterialTheme.colorScheme.background)
        ) {
            WorkoutStepIndicatorText(
                stepLabel = selectedStepLabel,
                modifier = Modifier
                    .fillMaxWidth()
                    //.offset(y = -WorkoutPagerLayoutTokens.BottomIndicatorSpacing)
                    .padding(horizontal = 20.dp)
                    .height(stepIndicatorReservedHeightDp)
                    .wrapContentHeight(Alignment.Top)
            )
        }

    }
}

private data class ExercisesPagePreviewFixture(
    val viewModel: AppViewModel,
    val firstExercise: Exercise,
    val supersetExercise: Exercise,
    val selectedExercise: Exercise,
    val currentExercise: Exercise,
    val firstSetState: WorkoutState.Set,
    val firstExerciseSecondSetState: WorkoutState.Set,
    val supersetSetState: WorkoutState.Set,
    val restState: WorkoutState.Rest,
)

private data class ExercisesPageManySetsPreviewFixture(
    val viewModel: AppViewModel,
    val exercise: Exercise,
    val lastSetState: WorkoutState.Set,
)

private fun buildExercisesPagePreviewFixture(): ExercisesPagePreviewFixture {
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

    return ExercisesPagePreviewFixture(
        viewModel = viewModel,
        firstExercise = firstExercise,
        supersetExercise = supersetExerciseA,
        selectedExercise = secondExercise,
        currentExercise = firstExercise,
        firstSetState = firstSetState,
        firstExerciseSecondSetState = firstExerciseSecondSetState,
        supersetSetState = supersetSetState,
        restState = restState
    )
}

private fun buildExercisesPageManySetsPreviewFixture(): ExercisesPageManySetsPreviewFixture {
    val viewModel = AppViewModel()
    val exerciseId = UUID.fromString("74000000-0000-0000-0000-000000000001")
    val sets = (1..18).map { index ->
        WeightSet(
            id = UUID.fromString("75000000-0000-0000-0000-${index.toString().padStart(12, '0')}"),
            reps = 8,
            weight = 80.0 + index,
            subCategory = SetSubCategory.WorkSet
        )
    }
    val exercise = Exercise(
        id = exerciseId,
        enabled = true,
        name = "Long Set List",
        notes = "",
        sets = sets,
        exerciseType = ExerciseType.WEIGHT,
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
    val setStates = sets.mapIndexed { index, set ->
        val setNumber = index + 1
        WorkoutState.Set(
            exerciseId = exercise.id,
            set = set,
            setIndex = setNumber.toUInt(),
            previousSetData = WeightSetData(
                actualReps = 8,
                actualWeight = set.weight - 2.5,
                volume = (set.weight - 2.5) * 8
            ),
            currentSetDataState = androidx.compose.runtime.mutableStateOf(
                WeightSetData(
                    actualReps = 8,
                    actualWeight = set.weight,
                    volume = set.weight * 8
                )
            ),
            hasNoHistory = false,
            skipped = false,
            currentBodyWeight = 0.0,
            streak = 1,
            progressionState = null,
            isWarmupSet = false,
            equipmentId = null
        )
    }
    val sequence = listOf(
        WorkoutStateSequenceItem.Container(
            WorkoutStateContainer.ExerciseState(
                exerciseId = exercise.id,
                childItems = setStates.map { state ->
                    ExerciseChildItem.Normal(state)
                }.toMutableList()
            )
        )
    )
    val lastSetState = setStates.last()

    viewModel.exercisesById = mapOf(exercise.id to exercise)
    setFieldValue(viewModel, "stateMachine", WorkoutStateMachine.fromSequence(sequence, startIndex = setStates.lastIndex))
    setCurrentWorkoutState(viewModel, lastSetState)

    return ExercisesPageManySetsPreviewFixture(
        viewModel = viewModel,
        exercise = exercise,
        lastSetState = lastSetState
    )
}

@Preview(
    name = "Standalone Rest Page",
    group = "ExercisesPage",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
private fun ExercisesPageRestPagePreview() {
    val fixture = remember { buildExercisesPagePreviewFixture() }
    val context = LocalContext.current
    val hapticsViewModel = remember(context) { HapticsViewModel(context, HapticsHelper(context)) }

    MyWorkoutAssistantTheme {
        ExercisesPage(
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
    group = "ExercisesPage",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
private fun ExercisesPageExercisePagePreview() {
    val fixture = remember { buildExercisesPagePreviewFixture() }
    val context = LocalContext.current
    val hapticsViewModel = remember(context) { HapticsViewModel(context, HapticsHelper(context)) }

    MyWorkoutAssistantTheme {
        ExercisesPage(
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
    name = "Exercise Page Done Sets Filled",
    group = "ExercisesPage",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
private fun ExercisesPageExercisePageDoneSetsPreview() {
    val fixture = remember { buildExercisesPagePreviewFixture() }
    val context = LocalContext.current
    val hapticsViewModel = remember(context) { HapticsViewModel(context, HapticsHelper(context)) }

    MyWorkoutAssistantTheme {
        ExercisesPage(
            selectedExercise = fixture.firstExercise,
            selectedRestPageId = null,
            workoutState = fixture.firstExerciseSecondSetState,
            viewModel = fixture.viewModel,
            hapticsViewModel = hapticsViewModel,
            currentExercise = fixture.firstExercise,
            onPageSelected = { _, _ -> }
        )
    }
}

@Preview(
    name = "Superset Exercise Page",
    group = "ExercisesPage",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
private fun ExercisesPageSupersetPagePreview() {
    val fixture = remember { buildExercisesPagePreviewFixture() }
    val context = LocalContext.current
    val hapticsViewModel = remember(context) { HapticsViewModel(context, HapticsHelper(context)) }

    MyWorkoutAssistantTheme {
        ExercisesPage(
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

@Preview(
    name = "Many Sets Last Selected",
    group = "ExercisesPage",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
private fun ExercisesPageManySetsLastSelectedPreview() {
    val fixture = remember { buildExercisesPageManySetsPreviewFixture() }
    val context = LocalContext.current
    val hapticsViewModel = remember(context) { HapticsViewModel(context, HapticsHelper(context)) }

    MyWorkoutAssistantTheme {
        ExercisesPage(
            selectedExercise = fixture.exercise,
            selectedRestPageId = null,
            workoutState = fixture.lastSetState,
            viewModel = fixture.viewModel,
            hapticsViewModel = hapticsViewModel,
            currentExercise = fixture.exercise,
            onPageSelected = { _, _ -> }
        )
    }
}
