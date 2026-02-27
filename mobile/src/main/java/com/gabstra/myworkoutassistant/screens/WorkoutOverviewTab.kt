package com.gabstra.myworkoutassistant.screens

import android.util.Log
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.relocation.BringIntoViewRequester
import androidx.compose.foundation.relocation.bringIntoViewRequester
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.ActiveScheduleCard
import com.gabstra.myworkoutassistant.composables.AppPrimaryButton
import com.gabstra.myworkoutassistant.composables.AppPrimaryOutlinedButton
import com.gabstra.myworkoutassistant.composables.GenericButtonWithMenu
import com.gabstra.myworkoutassistant.composables.GenericSelectableList
import com.gabstra.myworkoutassistant.composables.MenuItem
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.ensureRestSeparatedByExercises
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutSchedule
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import com.gabstra.myworkoutassistant.shared.workout.ui.InterruptedWorkoutCopy
import com.gabstra.myworkoutassistant.verticalColumnScrollbarContainer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.util.UUID

@Composable
@OptIn(ExperimentalFoundationApi::class)
fun WorkoutOverviewTab(
    appViewModel: AppViewModel,
    workout: Workout,
    hasWorkoutRecord: Boolean,
    isCheckingWorkoutRecord: Boolean,
    currentSelectedWorkoutId: UUID?,
    showRest: Boolean,
    onShowRestChange: (Boolean) -> Unit,
    selectedWorkoutComponents: List<WorkoutComponent>,
    isSelectionModeActive: Boolean,
    onEnableSelection: () -> Unit,
    onDisableSelection: () -> Unit,
    onSelectedComponentIdsChange: (kotlin.collections.Set<UUID>) -> Unit,
    pendingComponentBringIntoViewId: UUID?,
    onPendingComponentBringIntoViewConsumed: () -> Unit,
    onRequestStartWorkout: () -> Unit,
    onResumeWorkout: () -> Unit,
    onRequestDeleteInterruptedWorkout: () -> Unit,
    onWorkoutComponentsReordered: (List<WorkoutComponent>) -> Unit,
    workoutScheduleDao: com.gabstra.myworkoutassistant.shared.WorkoutScheduleDao,
    modifier: Modifier = Modifier
) {
    val scrollState = rememberScrollState()
    var workoutSchedules by remember {
        mutableStateOf<List<WorkoutSchedule>>(emptyList())
    }

    LaunchedEffect(workout.globalId) {
        withContext(Dispatchers.IO) {
            workoutSchedules = workoutScheduleDao.getSchedulesByWorkoutId(workout.globalId)
        }
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .fillMaxWidth()
            .padding(top = 10.dp)
            .padding(bottom = 10.dp)
            .verticalColumnScrollbarContainer(scrollState)
    ) {
        if (workout.workoutComponents.isEmpty()) {
            Row(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(5.dp),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically
            ) {
                GenericButtonWithMenu(
                    menuItems = listOf(
                        MenuItem("Add Exercise") {
                            appViewModel.setScreenData(ScreenData.NewExercise(workout.id))
                        },
                        MenuItem("Add Superset") {
                            appViewModel.setScreenData(ScreenData.NewSuperset(workout.id))
                        }
                    ),
                    content = {
                        Text(
                            "Add Workout Component",
                            color = MaterialTheme.colorScheme.background
                        )
                    }
                )
            }
        } else {
            if (workout.enabled) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.Center
                ) {
                    AppPrimaryButton(
                        text = "Start Workout",
                        onClick = onRequestStartWorkout,
                    )
                }

                if (!isCheckingWorkoutRecord && currentSelectedWorkoutId == workout.id && hasWorkoutRecord) {
                    Spacer(Modifier.height(Spacing.sm))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.Center
                    ) {
                        AppPrimaryButton(
                            text = "Resume",
                            onClick = onResumeWorkout,
                        )
                    }
                    Spacer(Modifier.height(Spacing.sm))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.Center
                    ) {
                        AppPrimaryButton(
                            text = InterruptedWorkoutCopy.DELETE_BUTTON,
                            onClick = onRequestDeleteInterruptedWorkout,
                        )
                    }
                }

                Spacer(Modifier.height(Spacing.md))
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            }

            if (workoutSchedules.isNotEmpty()) {
                Spacer(Modifier.height(Spacing.md))
                StyledCard {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(15.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp)
                    ) {
                        Text(
                            text = "Alarms",
                            style = MaterialTheme.typography.titleMedium,
                            color = MaterialTheme.colorScheme.onBackground
                        )

                        workoutSchedules.forEachIndexed { index, schedule ->
                            ActiveScheduleCard(
                                schedule = schedule,
                                index = index,
                                workout = workout
                            )
                            if (index < workoutSchedules.size - 1) {
                                HorizontalDivider(
                                    color = MaterialTheme.colorScheme.outlineVariant,
                                    modifier = Modifier.padding(vertical = 5.dp)
                                )
                            }
                        }
                    }
                }
                Spacer(Modifier.height(Spacing.md))
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            }

            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.End,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp)
            ) {
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

            GenericSelectableList(
                it = null,
                items = if (!showRest) workout.workoutComponents.filter { it !is Rest } else workout.workoutComponents,
                selectedItems = selectedWorkoutComponents,
                isSelectionModeActive = isSelectionModeActive,
                onItemClick = {
                    Log.d("WorkoutDetailScreen", "onItemClick: component=${it::class.simpleName} id=${it.id}")
                    when (it) {
                        is Exercise -> appViewModel.setScreenData(ScreenData.ExerciseDetail(workout.id, it.id))
                        is Rest -> appViewModel.setScreenData(ScreenData.EditRest(workout.id, it))
                        is Superset -> appViewModel.setScreenData(ScreenData.EditSuperset(workout.id, it.id))
                    }
                },
                onEnableSelection = onEnableSelection,
                onDisableSelection = onDisableSelection,
                onSelectionChange = { newSelection ->
                    onSelectedComponentIdsChange(newSelection.map { it.id }.toSet())
                },
                onOrderChange = { newWorkoutComponents ->
                    if (!showRest) return@GenericSelectableList
                    val adjustedComponents = ensureRestSeparatedByExercises(newWorkoutComponents)
                    onWorkoutComponentsReordered(adjustedComponents)
                },
                itemContent = { component, onItemClick, onItemLongClick ->
                    val bringIntoViewRequester = remember { BringIntoViewRequester() }
                    LaunchedEffect(pendingComponentBringIntoViewId == component.id) {
                        if (pendingComponentBringIntoViewId == component.id) {
                            bringIntoViewRequester.bringIntoView()
                            onPendingComponentBringIntoViewConsumed()
                        }
                    }
                    Box(
                        modifier = Modifier.bringIntoViewRequester(bringIntoViewRequester)
                    ) {
                        Column(
                            verticalArrangement = Arrangement.spacedBy(Spacing.sm)
                        ) {
                            WorkoutComponentRenderer(
                                workout = workout,
                                workoutComponent = component,
                                showRest = showRest,
                                appViewModel = appViewModel,
                                titleModifier = Modifier.combinedClickable(
                                    onClick = onItemClick,
                                    onLongClick = onItemLongClick
                                )
                            )
                            if (showRest && !isSelectionModeActive && component !is Rest) {
                                val currentIndex = workout.workoutComponents.indexOfFirst { it.id == component.id }
                                val isNotLast = currentIndex >= 0 && currentIndex < workout.workoutComponents.size - 1
                                val nextComponent = if (isNotLast) workout.workoutComponents[currentIndex + 1] else null
                                val shouldShowButton = isNotLast && nextComponent != null && nextComponent !is Rest

                                if (shouldShowButton) {
                                    Box(
                                        modifier = Modifier.fillMaxWidth(),
                                        contentAlignment = Alignment.Center
                                    ) {
                                        AppPrimaryOutlinedButton(
                                            text = "Add Rest",
                                            onClick = {
                                                appViewModel.setScreenData(
                                                    ScreenData.InsertRestAfter(workout.id, component.id)
                                                )
                                            }
                                        )
                                    }
                                }
                            }
                        }
                    }
                },
                isDragDisabled = true,
                keySelector = { component -> component.id }
            )

            GenericButtonWithMenu(
                menuItems = listOf(
                    MenuItem("Add Exercise") {
                        appViewModel.setScreenData(ScreenData.NewExercise(workout.id))
                    },
                    MenuItem("Add Rests Between Exercises") {
                        appViewModel.setScreenData(ScreenData.NewRest(workout.id, null))
                    },
                    MenuItem("Add Superset") {
                        appViewModel.setScreenData(ScreenData.NewSuperset(workout.id))
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
