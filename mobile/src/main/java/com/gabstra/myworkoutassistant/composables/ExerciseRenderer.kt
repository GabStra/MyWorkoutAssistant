package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.screens.CompactMovementPreview
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.getNewSetFromSetHistory
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.CalibrationHelper
import com.gabstra.myworkoutassistant.shared.workout.calibration.CalibrationUiLabels
import com.gabstra.myworkoutassistant.shared.workout.display.buildUnilateralSideLabel
import com.gabstra.myworkoutassistant.shared.workout.history.SessionTimelineItem
import com.gabstra.myworkoutassistant.shared.workout.history.mergeSessionTimeline
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.util.UUID

fun formatTargetRepRange(minReps: Int, maxReps: Int): String? {
    if (minReps <= 0 || maxReps < minReps) return null
    return if (minReps == maxReps) minReps.toString() else "$minReps-$maxReps"
}

@Composable
fun historyExerciseNameTextStyle(): TextStyle =
    MaterialTheme.typography.titleMedium

fun buildExerciseTemplateRows(
    sets: List<Set>,
    exercise: Exercise,
    equipment: WeightLoadedEquipment?,
): List<SetTableRowUiModel> =
    buildExerciseTemplatePreviewItems(
        sets = sets,
        exercise = exercise,
        equipment = equipment,
    ).flatMap { it.rows }

fun buildExerciseTemplatePreviewItems(
    sets: List<Set>,
    exercise: Exercise,
    equipment: WeightLoadedEquipment?,
): List<SetPreviewItemUiModel> {
    val previewItems = mutableListOf<SetPreviewItemUiModel>()
    val identifierCounter = SetRowIdentifierCounter()
    sets.forEach { set ->
        when (set) {
            is RestSet -> {
                previewItems += SetPreviewItemUiModel(
                    setId = set.id,
                    rows = listOf(
                        SetTableRowUiModel.Rest(
                            text = "REST ${formatTime(set.timeInSeconds)}",
                        )
                    ),
                )
            }

            is WeightSet -> {
                val subCategory = resolveSetSubCategory(set)
                val isCalibrationManagedWorkSet = CalibrationHelper.isCalibrationManagedWorkSet(
                    exercise = exercise,
                    set = set
                )
                val weightText = if (isCalibrationManagedWorkSet) {
                    CalibrationUiLabels.Tbd
                } else {
                    equipment?.formatWeight(set.weight) ?: "${set.weight} kg"
                }
                previewItems += buildTemplatePreviewItem(
                    set = set,
                    exercise = exercise,
                    row = SetTableRowUiModel.Data(
                        identifier = identifierCounter.nextIdentifier(subCategory),
                        primaryValue = weightText,
                        secondaryValue = "${set.reps}",
                    ),
                )
            }

            is BodyWeightSet -> {
                val subCategory = resolveSetSubCategory(set)
                val isCalibrationManagedWorkSet = CalibrationHelper.isCalibrationManagedWorkSet(
                    exercise = exercise,
                    set = set
                )
                val weightText = when {
                    isCalibrationManagedWorkSet -> CalibrationUiLabels.Tbd
                    set.additionalWeight > 0 -> equipment?.formatWeight(set.additionalWeight)
                        ?: "${set.additionalWeight} kg"
                    else -> "BW"
                }
                previewItems += buildTemplatePreviewItem(
                    set = set,
                    exercise = exercise,
                    row = SetTableRowUiModel.Data(
                        identifier = identifierCounter.nextIdentifier(subCategory),
                        primaryValue = weightText,
                        secondaryValue = "${set.reps}",
                    ),
                )
            }

            is TimedDurationSet -> {
                val targetWeightText = set.targetWeight?.let { equipment?.formatWeight(it) ?: "$it kg" }
                previewItems += SetPreviewItemUiModel(
                    setId = set.id,
                    rows = listOf(
                        SetTableRowUiModel.Data(
                            identifier = identifierCounter.nextIdentifier(null),
                            primaryValue = targetWeightText ?: formatTime(set.timeInMillis / 1000),
                            secondaryValue = targetWeightText?.let { formatTime(set.timeInMillis / 1000) },
                            primaryLabel = if (targetWeightText != null) "LOAD" else "DURATION",
                            secondaryLabel = if (targetWeightText != null) "DURATION" else null,
                        )
                    ),
                )
            }

            is EnduranceSet -> {
                val targetWeightText = set.targetWeight?.let { equipment?.formatWeight(it) ?: "$it kg" }
                previewItems += SetPreviewItemUiModel(
                    setId = set.id,
                    rows = listOf(
                        SetTableRowUiModel.Data(
                            identifier = identifierCounter.nextIdentifier(null),
                            primaryValue = targetWeightText ?: formatTime(set.timeInMillis / 1000),
                            secondaryValue = targetWeightText?.let { formatTime(set.timeInMillis / 1000) },
                            primaryLabel = if (targetWeightText != null) "LOAD" else "DURATION",
                            secondaryLabel = if (targetWeightText != null) "DURATION" else null,
                        )
                    ),
                )
            }
        }
    }
    return previewItems
}

private fun buildTemplatePreviewItem(
    set: Set,
    exercise: Exercise,
    row: SetTableRowUiModel.Data,
): SetPreviewItemUiModel {
    if (!shouldDuplicateUnilateralTemplateRow(exercise, set)) {
        return SetPreviewItemUiModel(
            setId = set.id,
            rows = listOf(row),
        )
    }

    val intraSetRestSeconds = exercise.intraSetRestInSeconds ?: 0
    val leftBadge = buildUnilateralSideLabel(sideIndex = 1u, intraSetTotal = 2u).orEmpty()
    val rightBadge = buildUnilateralSideLabel(sideIndex = 2u, intraSetTotal = 2u).orEmpty()
    val groupedRows = mutableListOf<SetTableRowUiModel>()
    groupedRows += row.copy(identifier = row.identifier + leftBadge)
    if (intraSetRestSeconds > 0) {
        groupedRows += SetTableRowUiModel.Rest("REST ${formatTime(intraSetRestSeconds)}")
    }
    groupedRows += row.copy(identifier = row.identifier + rightBadge)
    return SetPreviewItemUiModel(
        setId = set.id,
        rows = groupedRows,
        usesDashedContainer = true,
        isGroupedUnilateral = true,
    )
}

internal fun buildExerciseHistoryRows(
    exercise: Exercise,
    equipment: WeightLoadedEquipment?,
    setHistories: List<SetHistory>,
    intraExerciseRestHistories: List<RestHistory>,
    showRest: Boolean,
): List<SetTableRowUiModel> {
    val rows = mutableListOf<SetTableRowUiModel>()
    val mergedTimeline = mergeSessionTimeline(
        completedSetHistories(setHistories),
        intraExerciseRestHistories,
    )
    val identifierResolver = HistoricalSetDisplayIdentifierResolver(
        setHistories = mergedTimeline.mapNotNull { item ->
            val setStep = item as? SessionTimelineItem.SetStep ?: return@mapNotNull null
            setStep.history.takeUnless { it.setData is RestSetData }
        }
    )
    var index = 0
    while (index < mergedTimeline.size) {
        val item = mergedTimeline[index]
        when (item) {
            is SessionTimelineItem.RestStep -> {
                if (showRest) {
                    rows += SetTableRowUiModel.Rest(
                        text = formatRestHistoryDisplayLine(item.history)
                    )
                }
                index += 1
            }

            is SessionTimelineItem.SetStep -> {
                val history = item.history
                val setData = history.setData
                if (setData is RestSetData) {
                    if (showRest) {
                        rows += SetTableRowUiModel.Rest(
                            text = formatHistoricalRestValue(history)
                        )
                    }
                    index += 1
                    continue
                }

                val followingRestText = mergedTimeline.getOrNull(index + 1)
                    ?.let { nextItem ->
                        val restStep = nextItem as? SessionTimelineItem.RestStep ?: return@let null
                        if (!showRest) return@let null
                        formatRestHistoryDisplayLine(restStep.history)
                    }

                val identifier = identifierResolver.resolve(history)
                val set = getNewSetFromSetHistory(history)
                when (setData) {
                    is WeightSetData -> {
                        val weightSet = set as WeightSet
                        val isCalibrationSet = CalibrationHelper.isCalibrationSetBySubCategory(weightSet)
                        val weightText = equipment?.formatWeight(setData.actualWeight)
                            ?: "${setData.actualWeight} kg"
                        val secondaryReps = if (isCalibrationSet && setData.calibrationRIR != null) {
                            "${setData.actualReps} (RIR ${setData.calibrationRIR})"
                        } else {
                            "${setData.actualReps}"
                        }
                        appendHistoricalDataRows(
                            rows = rows,
                            exercise = exercise,
                            setData = setData,
                            followingRestText = followingRestText,
                            row = SetTableRowUiModel.Data(
                                identifier = identifier,
                                primaryValue = weightText,
                                secondaryValue = secondaryReps,
                            ),
                        )
                    }

                    is BodyWeightSetData -> {
                        val bodyWeightSet = set as BodyWeightSet
                        val isCalibrationSet = CalibrationHelper.isCalibrationSetBySubCategory(bodyWeightSet)
                        val weightText = formatHistoricalBodyWeightSetValue(
                            setData = setData,
                            equipment = equipment
                        )
                        val secondaryReps = if (isCalibrationSet && setData.calibrationRIR != null) {
                            "${setData.actualReps} (RIR ${setData.calibrationRIR})"
                        } else {
                            "${setData.actualReps}"
                        }
                        appendHistoricalDataRows(
                            rows = rows,
                            exercise = exercise,
                            setData = setData,
                            followingRestText = followingRestText,
                            row = SetTableRowUiModel.Data(
                                identifier = identifier,
                                primaryValue = weightText,
                                secondaryValue = secondaryReps,
                            ),
                        )
                    }

                    is com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData -> {
                        val actualWeightText = setData.actualWeight?.let { equipment?.formatWeight(it) ?: "$it kg" }
                        appendHistoricalDataRows(
                            rows = rows,
                            exercise = exercise,
                            setData = null,
                            followingRestText = followingRestText,
                            row = SetTableRowUiModel.Data(
                                identifier = identifier,
                                primaryValue = actualWeightText ?: formatHistoricalTimedSetValue(
                                    startTimer = setData.startTimer,
                                    endTimer = setData.endTimer,
                                ),
                                secondaryValue = actualWeightText?.let { formatHistoricalTimedSetValue(setData.startTimer, setData.endTimer) },
                                primaryLabel = if (actualWeightText != null) "LOAD" else "DURATION",
                                secondaryLabel = if (actualWeightText != null) "DURATION" else null,
                            ),
                        )
                    }

                    is com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData -> {
                        val actualWeightText = setData.actualWeight?.let { equipment?.formatWeight(it) ?: "$it kg" }
                        appendHistoricalDataRows(
                            rows = rows,
                            exercise = exercise,
                            setData = null,
                            followingRestText = followingRestText,
                            row = SetTableRowUiModel.Data(
                                identifier = identifier,
                                primaryValue = actualWeightText ?: formatHistoricalTimedSetValue(
                                    startTimer = setData.startTimer,
                                    endTimer = setData.endTimer,
                                ),
                                secondaryValue = actualWeightText?.let { formatHistoricalTimedSetValue(setData.startTimer, setData.endTimer) },
                                primaryLabel = if (actualWeightText != null) "LOAD" else "DURATION",
                                secondaryLabel = if (actualWeightText != null) "DURATION" else null,
                            ),
                        )
                    }
                }
                index += if (shouldDuplicateUnilateralHistoryRow(exercise, setData) && followingRestText != null) 2 else 1
            }
        }
    }
    return rows
}

private fun formatHistoricalTimedSetValue(startTimer: Int, endTimer: Int): String {
    return if (endTimer == 0) {
        formatTime(startTimer / 1000)
    } else {
        "${formatTime(startTimer / 1000)} - ${formatTime(endTimer / 1000)}"
    }
}

internal fun appendHistoricalDataRows(
    rows: MutableList<SetTableRowUiModel>,
    exercise: Exercise,
    setData: Any?,
    followingRestText: String?,
    row: SetTableRowUiModel.Data,
) {
    if (!shouldDuplicateUnilateralHistoryRow(exercise, setData)) {
        rows += row
        return
    }

    val leftBadge = buildUnilateralSideLabel(sideIndex = 1u, intraSetTotal = 2u).orEmpty()
    val rightBadge = buildUnilateralSideLabel(sideIndex = 2u, intraSetTotal = 2u).orEmpty()
    val betweenSidesRestText = followingRestText ?: exercise.intraSetRestInSeconds
        ?.takeIf { it > 0 }
        ?.let { "REST ${formatTime(it)}" }

    rows += row.copy(identifier = row.identifier + leftBadge)
    if (betweenSidesRestText != null) {
        rows += SetTableRowUiModel.Rest(betweenSidesRestText)
    }
    rows += row.copy(identifier = row.identifier + rightBadge)
}

internal fun shouldDuplicateUnilateralHistoryRow(
    exercise: Exercise,
    setData: Any?,
): Boolean {
    val intraSetRestSeconds = exercise.intraSetRestInSeconds ?: return false
    if (intraSetRestSeconds <= 0) return false
    return setData is WeightSetData || setData is BodyWeightSetData || setData == null
}

private fun shouldDuplicateUnilateralTemplateRow(
    exercise: Exercise,
    set: Set,
): Boolean {
    val intraSetRestSeconds = exercise.intraSetRestInSeconds ?: return false
    if (intraSetRestSeconds <= 0) return false
    return set is WeightSet || set is BodyWeightSet
}

@Composable
private fun ExerciseTitleOnlyRow(
    exercise: Exercise,
    modifier: Modifier,
    titleModifier: Modifier,
    appViewModel: AppViewModel,
) {
    WorkoutExerciseHeader(
        exercise = exercise,
        appViewModel = appViewModel,
        modifier = modifier.then(titleModifier),
    )
}

@Composable
internal fun WorkoutExerciseHeader(
    exercise: Exercise,
    appViewModel: AppViewModel,
    modifier: Modifier = Modifier,
    previewSize: androidx.compose.ui.unit.Dp = 72.dp,
    horizontalPadding: androidx.compose.ui.unit.Dp = 16.dp,
    verticalPadding: androidx.compose.ui.unit.Dp = 8.dp,
) {
    val linkedDefinition = exercise.exerciseDefinitionId?.let { definitionId ->
        appViewModel.workoutStore.exerciseDefinitions.firstOrNull { it.id == definitionId }
    }
    val familyName = linkedDefinition?.name ?: exercise.name
    val nameOverride = exercise.nameOverride?.trim()?.takeIf { it.isNotEmpty() }
    val movementRef = exercise.movementRef ?: linkedDefinition?.movementRef
    val textColor = if (exercise.enabled) MaterialTheme.colorScheme.onBackground else DisabledContentGray

    Row(
        modifier = modifier.padding(horizontal = horizontalPadding, vertical = verticalPadding),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        CompactMovementPreview(
            movementRef = movementRef,
            contentDescription = if (movementRef == null) {
                "No movement available for $familyName"
            } else {
                "Movement preview for $familyName"
            },
            modifier = Modifier.size(previewSize),
        )
        Spacer(Modifier.width(14.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                modifier = Modifier.basicMarquee(iterations = Int.MAX_VALUE),
                text = nameOverride ?: familyName,
                maxLines = 1,
                style = historyExerciseNameTextStyle(),
                color = textColor,
            )
            if (nameOverride != null) {
                Text(
                    text = familyName,
                    maxLines = 1,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun ExerciseExpandableSetTableBody(
    exercise: Exercise,
    modifier: Modifier,
    titleModifier: Modifier,
    initiallyExpanded: Boolean,
    equipment: WeightLoadedEquipment?,
    appViewModel: AppViewModel,
    title: @Composable (Modifier) -> Unit,
    rows: List<SetTableRowUiModel>,
    contentBeforeMetadata: (@Composable () -> Unit)? = null,
    showHistorySections: Boolean = false,
    equipmentNameOverride: String? = null,
    collapsedSummary: String? = null,
    setTablePresentation: SetTablePresentation = SetTablePresentation.COMPACT,
) {
    ExpandableContainer(
        isOpen = initiallyExpanded,
        modifier = modifier.fillMaxWidth(),
        isExpandable = true,
        titleModifier = titleModifier,
        title = title,
        collapsedContent = {
            collapsedSummary?.let { summary ->
                Text(
                    text = summary,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(start = 16.dp, end = 48.dp, bottom = 14.dp),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
        content = {
            Column(
                modifier = Modifier.padding(
                    start = 16.dp,
                    end = 16.dp,
                    top = 6.dp,
                    bottom = 16.dp,
                ),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                val accessoryNames = (exercise.requiredAccessoryEquipmentIds ?: emptyList()).mapNotNull { id ->
                    appViewModel.getLinkedSupportName(id)
                }
                val repRange = formatTargetRepRange(exercise.minReps, exercise.maxReps)

                if (showHistorySections) {
                    contentBeforeMetadata?.let { targetContent ->
                        ExerciseRendererHistorySection("Targets") {
                            targetContent()
                        }
                    }
                    SetTable(
                        rows = rows,
                        enabled = exercise.enabled,
                        presentation = setTablePresentation,
                    )
                } else {
                    contentBeforeMetadata?.invoke()
                    val linkedDefinitionName = exercise.exerciseDefinitionId
                        ?.let { definitionId ->
                            appViewModel.workoutStore.exerciseDefinitions
                                .firstOrNull { it.id == definitionId }
                                ?.name
                        }
                    ExerciseVariationInfo(
                        exerciseType = exercise.exerciseType,
                        targetRepRange = repRange,
                        equipmentName = equipmentNameOverride ?: equipment?.name,
                        accessoryNames = accessoryNames,
                        definitionName = linkedDefinitionName,
                        displayName = exercise.name,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    SetTable(
                        rows = rows,
                        enabled = exercise.enabled,
                        presentation = setTablePresentation,
                    )
                }
            }
        }
    )
}

@Composable
fun ExerciseTemplateRenderer(
    exercise: Exercise,
    modifier: Modifier = Modifier,
    showRest: Boolean,
    appViewModel: AppViewModel,
    titleModifier: Modifier = Modifier,
) {
    var sets = exercise.sets
    if (!showRest) {
        sets = sets.filter { it !is RestSet }
    }

    if (sets.isEmpty()) {
        ExerciseTitleOnlyRow(
            exercise = exercise,
            modifier = modifier,
            titleModifier = titleModifier,
            appViewModel = appViewModel,
        )
        return
    }

    val equipment = exercise.equipmentId?.let { appViewModel.getEquipmentById(it) }
    val rows = remember(exercise.id, showRest, sets, equipment?.id) {
        buildExerciseTemplateRows(sets, exercise, equipment)
    }

    ExerciseExpandableSetTableBody(
        exercise = exercise,
        modifier = modifier,
        titleModifier = titleModifier,
        initiallyExpanded = false,
        equipment = equipment,
        appViewModel = appViewModel,
        title = { m ->
            WorkoutExerciseHeader(
                exercise = exercise,
                appViewModel = appViewModel,
                modifier = m,
            )
        },
        rows = rows,
        setTablePresentation = SetTablePresentation.REVIEW,
    )
}

@Composable
fun ExerciseHistoryRenderer(
    exercise: Exercise,
    modifier: Modifier = Modifier,
    showRest: Boolean,
    appViewModel: AppViewModel,
    titleModifier: Modifier = Modifier,
    setHistories: List<SetHistory>,
    intraExerciseRestHistories: List<RestHistory> = emptyList(),
    customTitle: (@Composable (Modifier) -> Unit)? = null,
    contentBeforeMetadata: (@Composable () -> Unit)? = null,
    showHistorySections: Boolean = false,
    collapsedSummary: String? = null,
) {
    val firstHistory = setHistories.firstOrNull()
    val equipment = firstHistory?.equipmentIdSnapshot
        ?.let { appViewModel.getEquipmentById(it) }
        ?: exercise.equipmentId?.let { appViewModel.getEquipmentById(it) }
    val historicalEquipmentName = firstHistory?.equipmentNameSnapshot?.takeIf { it.isNotBlank() }
    val rows = remember(
        exercise.id,
        showRest,
        equipment?.id,
        setHistories,
        intraExerciseRestHistories,
    ) {
        buildExerciseHistoryRows(
            exercise = exercise,
            equipment = equipment,
            setHistories = setHistories,
            intraExerciseRestHistories = intraExerciseRestHistories,
            showRest = showRest,
        )
    }
    if (rows.isEmpty()) {
        ExerciseTitleOnlyRow(
            exercise = exercise,
            modifier = modifier,
            titleModifier = titleModifier,
            appViewModel = appViewModel,
        )
        return
    }

    ExerciseExpandableSetTableBody(
        exercise = exercise,
        modifier = modifier,
        titleModifier = titleModifier,
        initiallyExpanded = true,
        equipment = equipment,
        appViewModel = appViewModel,
        title = { m ->
            if (customTitle != null) {
                customTitle(m)
            } else {
                Text(
                    modifier = m
                        .padding(horizontal = 10.dp)
                        .basicMarquee(iterations = Int.MAX_VALUE),
                    text = exercise.name,
                    maxLines = 2,
                    style = historyExerciseNameTextStyle(),
                    color = if (exercise.enabled) MaterialTheme.colorScheme.onBackground else DisabledContentGray
                )
            }
        },
        rows = rows,
        contentBeforeMetadata = contentBeforeMetadata,
        showHistorySections = showHistorySections,
        equipmentNameOverride = historicalEquipmentName,
        collapsedSummary = collapsedSummary,
        setTablePresentation = SetTablePresentation.REVIEW,
    )
}

@Composable
private fun ExerciseRendererHistorySection(
    title: String,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        content()
    }
}
