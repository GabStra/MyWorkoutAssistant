package com.gabstra.myworkoutassistant.screens

import android.util.Log
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.relocation.BringIntoViewRequester
import androidx.compose.foundation.relocation.bringIntoViewRequester
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.CircularProgressIndicator
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
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
import com.gabstra.myworkoutassistant.composables.PrimarySurface
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.ensureRestSeparatedByExercises
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutSchedule
import com.gabstra.myworkoutassistant.shared.workout.model.WorkoutSessionDisplayLabels
import com.gabstra.myworkoutassistant.shared.workout.model.WorkoutSessionStatus
import com.gabstra.myworkoutassistant.shared.workout.model.workoutSessionDisplayLabel
import com.gabstra.myworkoutassistant.shared.workout.ui.IncompleteWorkoutStrings
import com.gabstra.myworkoutassistant.shared.workout.ui.WorkoutResumeInfo
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.format.DateTimeFormatter
import java.util.Locale
import java.util.UUID

@Composable
@OptIn(ExperimentalFoundationApi::class)
fun WorkoutOverviewTab(
    appViewModel: AppViewModel,
    workout: Workout,
    hasWorkoutRecord: Boolean,
    isCheckingWorkoutRecord: Boolean,
    workoutResumeInfo: WorkoutResumeInfo?,
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
    onRequestDeleteIncompleteWorkout: () -> Unit,
    onRequestClearAllIncompleteSessions: () -> Unit,
    onWorkoutComponentsReordered: (List<WorkoutComponent>) -> Unit,
    workoutScheduleDao: com.gabstra.myworkoutassistant.shared.WorkoutScheduleDao,
    workoutHistoryIdForExerciseNavigation: UUID? = null,
    modifier: Modifier = Modifier
) {
    val scrollState = rememberScrollState()
    val currentLocale = Locale.getDefault()
    val resumeTimeFormatter = remember(currentLocale) {
        DateTimeFormatter.ofPattern("dd/MM/yy HH:mm", currentLocale)
    }
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
            .verticalScroll(scrollState)
            .padding(horizontal = Spacing.md)
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
                            "Add a workout item",
                            color = MaterialTheme.colorScheme.background,
                            maxLines = 1,
                            modifier = Modifier.basicMarquee(iterations = Int.MAX_VALUE)
                        )
                    }
                )
            }
        } else {
            if (workout.enabled) {
                WorkoutSessionActionCard(
                    isCheckingWorkoutRecord = isCheckingWorkoutRecord,
                    hasWorkoutRecord = hasWorkoutRecord && currentSelectedWorkoutId == workout.id,
                    workoutResumeInfo = if (currentSelectedWorkoutId == workout.id) workoutResumeInfo else null,
                    timeFormatter = resumeTimeFormatter,
                    onRequestStartWorkout = onRequestStartWorkout,
                    onResumeWorkout = onResumeWorkout,
                    onRequestDeleteIncompleteWorkout = onRequestDeleteIncompleteWorkout,
                    onRequestClearAllIncompleteSessions = onRequestClearAllIncompleteSessions
                )

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
                        text = "Show rests",
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
                        modifier = Modifier
                            .fillMaxWidth()
                            .bringIntoViewRequester(bringIntoViewRequester)
                    ) {
                        Column(
                            modifier = Modifier.fillMaxWidth(),
                            verticalArrangement = Arrangement.spacedBy(Spacing.sm),
                            horizontalAlignment = Alignment.CenterHorizontally
                        ) {
                            WorkoutComponentRenderer(
                                workout = workout,
                                workoutComponent = component,
                                showRest = showRest,
                                appViewModel = appViewModel,
                                titleModifier = Modifier.combinedClickable(
                                    onClick = onItemClick,
                                    onLongClick = onItemLongClick
                                ),
                                workoutHistoryIdForExerciseNavigation = workoutHistoryIdForExerciseNavigation,
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
                                            text = "Add rest",
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

            Box(
                modifier = Modifier.fillMaxWidth(),
                contentAlignment = Alignment.Center
            ) {
                GenericButtonWithMenu(
                    menuItems = listOf(
                        MenuItem("Add Exercise") {
                            appViewModel.setScreenData(ScreenData.NewExercise(workout.id))
                        },
                        MenuItem("Add rests between exercises") {
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
}

@Composable
private fun WorkoutSessionActionCard(
    isCheckingWorkoutRecord: Boolean,
    hasWorkoutRecord: Boolean,
    workoutResumeInfo: WorkoutResumeInfo?,
    timeFormatter: DateTimeFormatter,
    onRequestStartWorkout: () -> Unit,
    onResumeWorkout: () -> Unit,
    onRequestDeleteIncompleteWorkout: () -> Unit,
    onRequestClearAllIncompleteSessions: () -> Unit
) {
    val sessionStatus = workoutResumeInfo?.sessionStatus
    val hasResumeAction = when (sessionStatus) {
        WorkoutSessionStatus.IN_PROGRESS_ON_WEAR,
        WorkoutSessionStatus.STOPPED_ON_WEAR,
        WorkoutSessionStatus.STALE_ON_WEAR,
        WorkoutSessionStatus.IN_PROGRESS_ON_PHONE -> true
        WorkoutSessionStatus.COMPLETED,
        null -> false
    }
    val titleText = when (sessionStatus) {
        WorkoutSessionStatus.IN_PROGRESS_ON_WEAR -> "Workout in progress on watch"
        WorkoutSessionStatus.STOPPED_ON_WEAR ->
            workoutSessionDisplayLabel(WorkoutSessionStatus.STOPPED_ON_WEAR)
                ?: WorkoutSessionDisplayLabels.STOPPED_ON_WATCH
        WorkoutSessionStatus.STALE_ON_WEAR ->
            workoutSessionDisplayLabel(WorkoutSessionStatus.STALE_ON_WEAR)
                ?: WorkoutSessionDisplayLabels.STALE_ON_WATCH
        WorkoutSessionStatus.IN_PROGRESS_ON_PHONE -> IncompleteWorkoutStrings.SINGULAR
        WorkoutSessionStatus.COMPLETED,
        null -> IncompleteWorkoutStrings.SINGULAR
    }
    val primaryActionText = when (sessionStatus) {
        WorkoutSessionStatus.IN_PROGRESS_ON_WEAR,
        WorkoutSessionStatus.STOPPED_ON_WEAR,
        WorkoutSessionStatus.STALE_ON_WEAR -> "Resume on phone"
        WorkoutSessionStatus.IN_PROGRESS_ON_PHONE -> "Resume workout"
        WorkoutSessionStatus.COMPLETED,
        null -> "Resume workout"
    }

    PrimarySurface(
        modifier = Modifier.fillMaxWidth()
    ) {
        when {
            isCheckingWorkoutRecord -> {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 18.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(Spacing.sm)
                ) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(24.dp),
                        strokeWidth = 2.dp
                    )
                    Text(
                        text = IncompleteWorkoutStrings.CHECKING_SESSION,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = TextAlign.Center
                    )
                }
            }

            hasWorkoutRecord && hasResumeAction -> {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(Spacing.md)
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                        verticalAlignment = Alignment.Top
                    ) {
                        Icon(
                            imageVector = Icons.Default.Refresh,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.padding(top = 2.dp)
                        )
                        Column(
                            modifier = Modifier.weight(1f),
                            verticalArrangement = Arrangement.spacedBy(Spacing.xs)
                        ) {
                            Text(
                                text = titleText,
                                style = MaterialTheme.typography.titleMedium,
                                fontWeight = FontWeight.SemiBold,
                                color = MaterialTheme.colorScheme.onBackground
                            )
                            Text(
                                text = buildResumeDescription(workoutResumeInfo, timeFormatter),
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }

                    AppPrimaryButton(
                        modifier = Modifier.fillMaxWidth(),
                        text = primaryActionText,
                        onClick = onResumeWorkout
                    )
                    AppPrimaryOutlinedButton(
                        modifier = Modifier.fillMaxWidth(),
                        text = "Start over",
                        onClick = onRequestStartWorkout
                    )
                    AppPrimaryOutlinedButton(
                        modifier = Modifier.fillMaxWidth(),
                        text = IncompleteWorkoutStrings.DISCARD_BUTTON,
                        onClick = onRequestClearAllIncompleteSessions
                    )
                    Box(
                        modifier = Modifier.fillMaxWidth(),
                        contentAlignment = Alignment.Center
                    ) {
                        Text(
                            text = IncompleteWorkoutStrings.DELETE_BUTTON,
                            modifier = Modifier.clickable(onClick = onRequestDeleteIncompleteWorkout),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.error
                        )
                    }
                }
            }

            else -> {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(Spacing.md)
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                        verticalAlignment = Alignment.Top
                    ) {
                        Icon(
                            imageVector = Icons.Default.PlayArrow,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.padding(top = 2.dp)
                        )
                        Column(
                            modifier = Modifier.weight(1f),
                            verticalArrangement = Arrangement.spacedBy(Spacing.xs)
                        ) {
                            Text(
                                text = "Ready to work out",
                                style = MaterialTheme.typography.titleMedium,
                                fontWeight = FontWeight.SemiBold,
                                color = MaterialTheme.colorScheme.onBackground
                            )
                            Text(
                                text = "Start this workout whenever you're ready.",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }

                    AppPrimaryButton(
                        modifier = Modifier.fillMaxWidth(),
                        text = "Start workout",
                        onClick = onRequestStartWorkout
                    )
                }
            }
        }
    }
}

private fun buildResumeDescription(
    workoutResumeInfo: WorkoutResumeInfo?,
    timeFormatter: DateTimeFormatter
): String {
    if (workoutResumeInfo == null) {
        return "Resume your in-progress workout."
    }

    val sessionTime = workoutResumeInfo.startedAt?.format(timeFormatter)
    val staleTime = workoutResumeInfo.lastActiveSyncAt?.format(timeFormatter)

    return buildString {
        when (workoutResumeInfo.sessionStatus) {
            WorkoutSessionStatus.IN_PROGRESS_ON_WEAR -> append("This workout is still running on your watch. Resume on phone at ")
            WorkoutSessionStatus.STOPPED_ON_WEAR -> append("You returned home on your watch. Resume on phone at ")
            WorkoutSessionStatus.STALE_ON_WEAR -> append("Your watch stopped communicating. Resume on phone at ")
            WorkoutSessionStatus.IN_PROGRESS_ON_PHONE,
            WorkoutSessionStatus.COMPLETED -> append("Resume at ")
        }
        append(workoutResumeInfo.exerciseName)
        append(", set ")
        append(workoutResumeInfo.setNumber)
        if (sessionTime != null) {
            append(". Started ")
            append(sessionTime)
        }
        if (workoutResumeInfo.sessionStatus == WorkoutSessionStatus.STALE_ON_WEAR && staleTime != null) {
            append(". Last watch update ")
            append(staleTime)
        }
    }
}
