package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.relocation.BringIntoViewRequester
import androidx.compose.foundation.relocation.bringIntoViewRequester
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.AppPrimaryButton
import com.gabstra.myworkoutassistant.composables.AppPrimaryOutlinedButton
import com.gabstra.myworkoutassistant.composables.GenericButtonWithMenu
import com.gabstra.myworkoutassistant.composables.GenericSelectableList
import com.gabstra.myworkoutassistant.composables.MenuItem
import com.gabstra.myworkoutassistant.ensureRestSeparatedBySets
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.utils.CalibrationHelper
import com.gabstra.myworkoutassistant.verticalColumnScrollbarContainer
import java.util.UUID

@Composable
fun ExerciseOverviewTab(
    appViewModel: AppViewModel,
    workoutId: UUID,
    exercise: Exercise,
    sets: List<Set>,
    equipments: List<WeightLoadedEquipment>,
    selectedEquipmentId: UUID?,
    showRest: Boolean,
    onShowRestChange: (Boolean) -> Unit,
    selectedSets: List<Set>,
    isSelectionModeActive: Boolean,
    onEnableSelection: () -> Unit,
    onDisableSelection: () -> Unit,
    onSelectedSetIdsChange: (kotlin.collections.Set<UUID>) -> Unit,
    onSetsReordered: (List<Set>) -> Unit,
    pendingSetBringIntoViewId: UUID?,
    onPendingSetBringIntoViewConsumed: () -> Unit,
    modifier: Modifier = Modifier
) {
    val scrollState = rememberScrollState()

    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(top = 10.dp)
            .padding(bottom = 10.dp)
            .verticalColumnScrollbarContainer(scrollState)
    ) {
        if (sets.isEmpty()) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(5.dp),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically
            ) {
                AppPrimaryButton(
                    text = "Add Set",
                    onClick = {
                        appViewModel.setScreenData(ScreenData.NewSet(workoutId, exercise.id))
                    },
                )
            }
        } else {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
                modifier = Modifier.fillMaxWidth()
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(5.dp),
                    modifier = Modifier.then(
                        if (selectedEquipmentId == null) Modifier.alpha(0f) else Modifier
                    )
                ) {
                    Text(
                        text = "Equipment:",
                        style = MaterialTheme.typography.bodyMedium
                    )
                    val selectedEquipment =
                        if (selectedEquipmentId == null) null else equipments.find { it.id == selectedEquipmentId }
                    Text(
                        text = selectedEquipment?.name ?: "None",
                        style = MaterialTheme.typography.bodyMedium
                    )
                }

                Row(
                    modifier = Modifier.padding(vertical = 15.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(15.dp)
                ) {
                    Checkbox(
                        modifier = Modifier.size(10.dp),
                        checked = showRest,
                        onCheckedChange = onShowRestChange,
                        colors = CheckboxDefaults.colors().copy(
                            checkedCheckmarkColor = MaterialTheme.colorScheme.onPrimary,
                            uncheckedBorderColor = MaterialTheme.colorScheme.primary
                        )
                    )
                    Text(
                        text = "Show Rests",
                        style = MaterialTheme.typography.bodyMedium
                    )
                }
            }

            if (exercise.requiresLoadCalibration &&
                CalibrationHelper.supportsCalibrationForExercise(exercise)
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 8.dp),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = "Waiting for calibration. Turn off \"Use Calibration mode\" to disable.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }

            GenericSelectableList(
                it = null,
                items = if (!showRest) sets.filter { it !is RestSet } else sets,
                selectedItems = selectedSets,
                isSelectionModeActive = isSelectionModeActive,
                onItemClick = {
                    if (it is RestSet) {
                        appViewModel.setScreenData(
                            ScreenData.EditRestSet(workoutId, it, exercise.id)
                        )
                    } else {
                        appViewModel.setScreenData(
                            ScreenData.EditSet(workoutId, it, exercise.id)
                        )
                    }
                },
                onEnableSelection = onEnableSelection,
                onDisableSelection = onDisableSelection,
                onSelectionChange = { newSelection ->
                    onSelectedSetIdsChange(newSelection.map { it.id }.toSet())
                },
                onOrderChange = { newComponents ->
                    if (!showRest) return@GenericSelectableList
                    val adjustedComponents = ensureRestSeparatedBySets(newComponents)
                    onSetsReordered(adjustedComponents)
                },
                isDragDisabled = true,
                itemContent = { set, onItemClick, onItemLongClick ->
                    val bringIntoViewRequester = remember { BringIntoViewRequester() }
                    LaunchedEffect(pendingSetBringIntoViewId == set.id) {
                        if (pendingSetBringIntoViewId == set.id) {
                            bringIntoViewRequester.bringIntoView()
                            onPendingSetBringIntoViewConsumed()
                        }
                    }
                    Box(
                        modifier = Modifier.bringIntoViewRequester(bringIntoViewRequester)
                    ) {
                        Column(
                            verticalArrangement = Arrangement.spacedBy(Spacing.sm)
                        ) {
                            ComponentRenderer(
                                set,
                                appViewModel,
                                exercise,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .then(
                                        if (set is RestSet) Modifier else Modifier.heightIn(min = 48.dp)
                                    )
                                    .combinedClickable(
                                        onClick = onItemClick,
                                        onLongClick = onItemLongClick
                                    )
                            )
                            if (showRest && !isSelectionModeActive && set !is RestSet) {
                                val currentIndex = sets.indexOfFirst { it.id == set.id }
                                val isNotLast = currentIndex >= 0 && currentIndex < sets.size - 1
                                val nextItem = if (isNotLast) sets[currentIndex + 1] else null
                                val shouldShowButton = isNotLast && nextItem != null && nextItem !is RestSet

                                if (shouldShowButton) {
                                    Box(
                                        modifier = Modifier.fillMaxWidth(),
                                        contentAlignment = Alignment.Center
                                    ) {
                                        AppPrimaryOutlinedButton(
                                            text = "Add Rest",
                                            onClick = {
                                                appViewModel.setScreenData(
                                                    ScreenData.InsertRestSetAfter(workoutId, exercise.id, set.id)
                                                )
                                            }
                                        )
                                    }
                                }
                            }
                        }
                    }
                },
                keySelector = { it.id }
            )

            Row(
                modifier = Modifier.fillMaxSize(),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically
            ) {
                GenericButtonWithMenu(
                    menuItems = listOf(
                        MenuItem("Add Set") {
                            appViewModel.setScreenData(ScreenData.NewSet(workoutId, exercise.id))
                        },
                        MenuItem("Add Rests between sets") {
                            appViewModel.setScreenData(ScreenData.NewRestSet(workoutId, exercise.id))
                        }
                    ),
                    content = {
                        Icon(
                            imageVector = Icons.Filled.Add,
                            contentDescription = "Add",
                            tint = MaterialTheme.colorScheme.background,
                        )
                    }
                )
            }
        }
    }
}
