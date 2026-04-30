package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
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

@Composable
fun historyExerciseNameTextStyle(): TextStyle =
    MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.SemiBold)

fun buildExerciseTemplateRows(
    sets: List<Set>,
    exercise: Exercise,
    equipment: WeightLoadedEquipment?,
): List<SetTableRowUiModel> {
    val rows = mutableListOf<SetTableRowUiModel>()
    val identifierCounter = SetRowIdentifierCounter()
    sets.forEach { set ->
        when (set) {
            is RestSet -> {
                rows += SetTableRowUiModel.Rest(
                    text = "REST ${formatTime(set.timeInSeconds)}",
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
                appendTemplateDataRows(
                    rows = rows,
                    exercise = exercise,
                    set = set,
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
                appendTemplateDataRows(
                    rows = rows,
                    exercise = exercise,
                    set = set,
                    row = SetTableRowUiModel.Data(
                        identifier = identifierCounter.nextIdentifier(subCategory),
                        primaryValue = weightText,
                        secondaryValue = "${set.reps}",
                    ),
                )
            }

            is TimedDurationSet -> {
                rows += SetTableRowUiModel.Data(
                    identifier = identifierCounter.nextIdentifier(null),
                    primaryValue = formatTime(set.timeInMillis / 1000),
                    secondaryValue = null,
                )
            }

            is EnduranceSet -> {
                rows += SetTableRowUiModel.Data(
                    identifier = identifierCounter.nextIdentifier(null),
                    primaryValue = formatTime(set.timeInMillis / 1000),
                    secondaryValue = null,
                )
            }
        }
    }
    return rows
}

private fun appendTemplateDataRows(
    rows: MutableList<SetTableRowUiModel>,
    exercise: Exercise,
    set: Set,
    row: SetTableRowUiModel.Data,
) {
    if (!shouldDuplicateUnilateralTemplateRow(exercise, set)) {
        rows += row
        return
    }

    val intraSetRestSeconds = exercise.intraSetRestInSeconds ?: 0
    val leftBadge = buildUnilateralSideLabel(sideIndex = 1u, intraSetTotal = 2u).orEmpty()
    val rightBadge = buildUnilateralSideLabel(sideIndex = 2u, intraSetTotal = 2u).orEmpty()

    rows += row.copy(identifier = row.identifier + leftBadge)
    if (intraSetRestSeconds > 0) {
        rows += SetTableRowUiModel.Rest("REST ${formatTime(intraSetRestSeconds)}")
    }
    rows += row.copy(identifier = row.identifier + rightBadge)
}

internal fun buildExerciseHistoryRows(
    exercise: Exercise,
    equipment: WeightLoadedEquipment?,
    setHistories: List<SetHistory>,
    intraExerciseRestHistories: List<RestHistory>,
    showRest: Boolean,
): List<SetTableRowUiModel> {
    val rows = mutableListOf<SetTableRowUiModel>()
    val mergedTimeline = mergeSessionTimeline(setHistories, intraExerciseRestHistories)
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
                        val isCalibrationManagedWorkSet = CalibrationHelper.isCalibrationManagedWorkSet(
                            exercise = exercise,
                            set = weightSet
                        )
                        val weightText = if (isCalibrationManagedWorkSet) {
                            CalibrationUiLabels.Tbd
                        } else {
                            equipment?.formatWeight(setData.actualWeight) ?: "${setData.actualWeight} kg"
                        }
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
                        val isCalibrationManagedWorkSet = CalibrationHelper.isCalibrationManagedWorkSet(
                            exercise = exercise,
                            set = bodyWeightSet
                        )
                        val weightText = if (isCalibrationManagedWorkSet) {
                            CalibrationUiLabels.Tbd
                        } else {
                            formatHistoricalBodyWeightSetValue(
                                setData = setData,
                                equipment = equipment
                            )
                        }
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
                        appendHistoricalDataRows(
                            rows = rows,
                            exercise = exercise,
                            setData = null,
                            followingRestText = followingRestText,
                            row = SetTableRowUiModel.Data(
                                identifier = identifier,
                                primaryValue = formatTime(setData.startTimer / 1000),
                                secondaryValue = null,
                            ),
                        )
                    }

                    is com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData -> {
                        appendHistoricalDataRows(
                            rows = rows,
                            exercise = exercise,
                            setData = null,
                            followingRestText = followingRestText,
                            row = SetTableRowUiModel.Data(
                                identifier = identifier,
                                primaryValue = formatTime(setData.startTimer / 1000),
                                secondaryValue = null,
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

    rows += row.copy(identifier = row.identifier + leftBadge)
    if (followingRestText != null) {
        rows += SetTableRowUiModel.Rest(followingRestText)
    }
    rows += row.copy(identifier = row.identifier + rightBadge)
}

internal fun shouldDuplicateUnilateralHistoryRow(
    exercise: Exercise,
    setData: Any?,
): Boolean {
    val intraSetRestSeconds = exercise.intraSetRestInSeconds ?: return false
    if (intraSetRestSeconds <= 0) return false
    val subCategory = when (setData) {
        is WeightSetData -> setData.subCategory
        is BodyWeightSetData -> setData.subCategory
        else -> null
    }
    return subCategory != SetSubCategory.WarmupSet
}

private fun shouldDuplicateUnilateralTemplateRow(
    exercise: Exercise,
    set: Set,
): Boolean {
    val intraSetRestSeconds = exercise.intraSetRestInSeconds ?: return false
    if (intraSetRestSeconds <= 0) return false
    val subCategory = when (set) {
        is WeightSet -> set.subCategory
        is BodyWeightSet -> set.subCategory
        else -> null
    }
    return subCategory != SetSubCategory.WarmupSet
}

@Composable
private fun ExerciseTitleOnlyRow(
    exercise: Exercise,
    modifier: Modifier,
    titleModifier: Modifier,
) {
    Row(
        modifier = modifier.then(titleModifier).padding(15.dp),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 10.dp)
                .basicMarquee(iterations = Int.MAX_VALUE),
            text = exercise.name,
            maxLines = 2,
            style = historyExerciseNameTextStyle(),
            color = if (exercise.enabled) MaterialTheme.colorScheme.onBackground else DisabledContentGray,
        )
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
) {
    ExpandableContainer(
        isOpen = initiallyExpanded,
        modifier = modifier.fillMaxWidth(),
        isExpandable = true,
        titleModifier = titleModifier,
        title = title,
        content = {
            Column(
                modifier = Modifier.padding(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                val accessoryEquipments = (exercise.requiredAccessoryEquipmentIds ?: emptyList()).mapNotNull { id ->
                    appViewModel.getAccessoryEquipmentById(id)
                }
                val metadataTextColor = if (exercise.enabled) {
                    MaterialTheme.colorScheme.onSurfaceVariant
                } else {
                    DisabledContentGray
                }

                    ExerciseMetadataStrip(
                        equipmentName = equipment?.name,
                    accessoryNameList = accessoryEquipments.map { it.name },
                    textColor = metadataTextColor,
                    modifier = Modifier.fillMaxWidth(),
                )

                SetTable(
                    rows = rows,
                    enabled = exercise.enabled,
                )
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
            Text(
                modifier = m
                    .padding(horizontal = 10.dp)
                    .basicMarquee(iterations = Int.MAX_VALUE),
                text = exercise.name,
                maxLines = 2,
                style = historyExerciseNameTextStyle(),
                color = if (exercise.enabled) MaterialTheme.colorScheme.onBackground else DisabledContentGray
            )
        },
        rows = rows,
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
) {
    val equipment = exercise.equipmentId?.let { appViewModel.getEquipmentById(it) }
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
    )
}
