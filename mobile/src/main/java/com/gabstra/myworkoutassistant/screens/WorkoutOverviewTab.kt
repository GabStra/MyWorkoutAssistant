package com.gabstra.myworkoutassistant.screens

import android.util.Log
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
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
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalLocale
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.ScreenData
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.ActiveScheduleCard
import com.gabstra.myworkoutassistant.composables.AppFilledTonalButton
import com.gabstra.myworkoutassistant.composables.AppListFilterToggle
import com.gabstra.myworkoutassistant.composables.AppPrimaryButton
import com.gabstra.myworkoutassistant.composables.AppPrimaryOutlinedButton
import com.gabstra.myworkoutassistant.composables.GenericButtonWithMenu
import com.gabstra.myworkoutassistant.composables.GenericSelectableList
import com.gabstra.myworkoutassistant.composables.MenuItem
import com.gabstra.myworkoutassistant.composables.PrimarySurface
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.composables.labelRes
import com.gabstra.myworkoutassistant.ensureRestSeparatedByExercises
import com.gabstra.myworkoutassistant.shared.R as SharedR
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutSchedule
import com.gabstra.myworkoutassistant.shared.workout.model.WorkoutSessionStatus
import com.gabstra.myworkoutassistant.shared.workout.model.workoutSessionDisplayLabel
import com.gabstra.myworkoutassistant.shared.workout.ui.WorkoutResumeInfo
import com.gabstra.myworkoutassistant.shared.workout.ui.WorkoutResumeSetLabel
import com.gabstra.myworkoutassistant.shared.workout.ui.WorkoutResumeSetType
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import com.gabstra.myworkoutassistant.ui.theme.MyWorkoutAssistantTheme
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
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
    hideDisabledWorkoutComponents: Boolean,
    onHideDisabledWorkoutComponentsChange: (Boolean) -> Unit,
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
    onSetWatchMotionCaptureEnabled: (Boolean) -> Unit,
    onWorkoutComponentsReordered: (List<WorkoutComponent>) -> Unit,
    workoutSchedules: List<WorkoutSchedule>,
    modifier: Modifier = Modifier,
    workoutHistoryIdForExerciseNavigation: UUID? = null,
) {
    val scrollState = rememberScrollState()
    val disabledWorkoutComponentCount = remember(workout.workoutComponents) {
        workout.workoutComponents.count { !it.enabled }
    }
    val displayComponents = remember(
        workout.workoutComponents,
        showRest,
        hideDisabledWorkoutComponents
    ) {
        workout.workoutComponents.filter { component ->
            (showRest || component !is Rest) &&
                (!hideDisabledWorkoutComponents || component.enabled)
        }
    }
    val currentLocale = LocalLocale.current.platformLocale
    val resumeTimeFormatter = remember(currentLocale) {
        DateTimeFormatter.ofPattern("dd/MM/yy HH:mm", currentLocale)
    }
    Column(
        modifier = modifier
            .fillMaxSize()
            .fillMaxWidth()
            .padding(vertical = Spacing.md)
            .verticalScroll(scrollState)
            .padding(horizontal = Spacing.md)
    ) {
        if (workout.workoutComponents.isEmpty()) {
            Row(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(vertical = Spacing.xs),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically
            ) {
                GenericButtonWithMenu(
                    menuItems = listOf(
                        MenuItem(stringResource(R.string.loc_scr_add_exercise)) {
                            appViewModel.setScreenData(ScreenData.NewExercise(workout.id))
                        },
                        MenuItem(stringResource(R.string.loc_scr_add_superset)) {
                            appViewModel.setScreenData(ScreenData.NewSuperset(workout.id))
                        }
                    ),
                    content = {
                        Text(
                            stringResource(R.string.loc_scr_add_workout_item),
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
                    onRequestClearAllIncompleteSessions = onRequestClearAllIncompleteSessions,
                    onSetWatchMotionCaptureEnabled = onSetWatchMotionCaptureEnabled
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
                            .padding(Spacing.md),
                        verticalArrangement = Arrangement.spacedBy(Spacing.sm)
                    ) {
                        Text(
                            text = stringResource(R.string.workout_form_alarms_title),
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
                                    modifier = Modifier.padding(vertical = Spacing.xs)
                                )
                            }
                        }
                    }
                }
                Spacer(Modifier.height(Spacing.md))
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            }

            AppListFilterToggle(
                label = stringResource(R.string.loc_scr_show_rests),
                checked = showRest,
                onCheckedChange = onShowRestChange,
            )

            if (disabledWorkoutComponentCount > 0) {
                AppListFilterToggle(
                    label = stringResource(R.string.workout_hide_disabled),
                    checked = hideDisabledWorkoutComponents,
                    onCheckedChange = onHideDisabledWorkoutComponentsChange,
                )
            }

            GenericSelectableList(
                it = null,
                items = displayComponents,
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
                    if (!showRest || hideDisabledWorkoutComponents) return@GenericSelectableList
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
                                            text = stringResource(R.string.loc_scr_add_rest),
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

            Spacer(Modifier.height(Spacing.md))

            Box(
                modifier = Modifier.fillMaxWidth(),
                contentAlignment = Alignment.Center
            ) {
                GenericButtonWithMenu(
                    menuItems = listOf(
                        MenuItem(stringResource(R.string.loc_scr_add_exercise)) {
                            appViewModel.setScreenData(ScreenData.NewExercise(workout.id))
                        },
                        MenuItem(
                            label = stringResource(R.string.loc_scr_rest_between_all_exercises),
                            description = stringResource(R.string.loc_scr_rest_between_all_exercises_desc)
                        ) {
                            appViewModel.setScreenData(ScreenData.NewRest(workout.id, null))
                        },
                        MenuItem(stringResource(R.string.loc_scr_add_superset)) {
                            appViewModel.setScreenData(ScreenData.NewSuperset(workout.id))
                        }
                    ),
                    content = {
                        Icon(
                            imageVector = Icons.Filled.Add,
                            contentDescription = stringResource(R.string.loc_add_cd),
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
    onRequestClearAllIncompleteSessions: () -> Unit,
    onSetWatchMotionCaptureEnabled: (Boolean) -> Unit = {}
) {
    val sessionStatus = workoutResumeInfo?.sessionStatus
    val compactSessionLabel = workoutSessionDisplayLabel(sessionStatus)
    val compactSessionTitle = compactSessionLabel?.let { stringResource(it.labelRes()) }
    val hasResumeAction = when (sessionStatus) {
        WorkoutSessionStatus.IN_PROGRESS_ON_WEAR,
        WorkoutSessionStatus.STOPPED_ON_WEAR,
        WorkoutSessionStatus.STALE_ON_WEAR,
        WorkoutSessionStatus.IN_PROGRESS_ON_PHONE -> true
        WorkoutSessionStatus.INTERRUPTED -> false
        WorkoutSessionStatus.COMPLETED,
        null -> false
    }
    val titleText = when (sessionStatus) {
        WorkoutSessionStatus.IN_PROGRESS_ON_WEAR -> stringResource(R.string.loc_scr_workout_in_progress_on_watch)
        WorkoutSessionStatus.STOPPED_ON_WEAR,
        WorkoutSessionStatus.STALE_ON_WEAR,
        WorkoutSessionStatus.INTERRUPTED ->
            compactSessionTitle ?: stringResource(SharedR.string.incomplete_workout_singular)
        WorkoutSessionStatus.IN_PROGRESS_ON_PHONE -> stringResource(SharedR.string.incomplete_workout_singular)
        WorkoutSessionStatus.COMPLETED,
        null -> stringResource(SharedR.string.incomplete_workout_singular)
    }
    val primaryActionText = when (sessionStatus) {
        WorkoutSessionStatus.IN_PROGRESS_ON_WEAR,
        WorkoutSessionStatus.STOPPED_ON_WEAR,
        WorkoutSessionStatus.STALE_ON_WEAR -> stringResource(R.string.loc_scr_resume_on_phone)
        WorkoutSessionStatus.IN_PROGRESS_ON_PHONE -> stringResource(R.string.loc_scr_resume_workout)
        WorkoutSessionStatus.INTERRUPTED -> stringResource(R.string.loc_scr_resume_workout)
        WorkoutSessionStatus.COMPLETED,
        null -> stringResource(R.string.loc_scr_resume_workout)
    }

    PrimarySurface(
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
        ) {
            when {
            isCheckingWorkoutRecord -> {
                // Match the "Ready to work out" card footprint so the list below does not jump
                // when session data finishes loading; taller resume layouts animate smoothly.
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
                                text = stringResource(SharedR.string.incomplete_workout_checking_session_progress),
                                style = MaterialTheme.typography.titleMedium,
                                fontWeight = FontWeight.SemiBold,
                                color = MaterialTheme.colorScheme.onBackground
                            )
                            Text(
                                text = stringResource(SharedR.string.incomplete_workout_checking_session),
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = 48.dp),
                        contentAlignment = Alignment.Center
                    ) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(24.dp),
                            strokeWidth = 2.dp
                        )
                    }
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
                        onClick = onResumeWorkout,
                        textAlign = TextAlign.Center
                    )

                    val watchMotionEnabled = workoutResumeInfo?.motionCaptureEnabled
                    if (
                        sessionStatus == WorkoutSessionStatus.IN_PROGRESS_ON_WEAR &&
                        watchMotionEnabled != null
                    ) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(12.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Column(
                                modifier = Modifier.weight(1f),
                                verticalArrangement = Arrangement.spacedBy(Spacing.xs)
                            ) {
                                Text(
                                    text = stringResource(R.string.loc_scr_record_motion),
                                    style = MaterialTheme.typography.bodyLarge,
                                    color = MaterialTheme.colorScheme.onBackground
                                )
                                Text(
                                    text = if (watchMotionEnabled) {
                                        stringResource(R.string.loc_scr_on_for_this_workout)
                                    } else {
                                        stringResource(R.string.loc_scr_off_for_this_workout)
                                    },
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                            Switch(
                                checked = watchMotionEnabled,
                                onCheckedChange = onSetWatchMotionCaptureEnabled
                            )
                        }
                    }

                    AppFilledTonalButton(
                        modifier = Modifier.fillMaxWidth(),
                        text = stringResource(R.string.loc_scr_start_over),
                        onClick = onRequestStartWorkout,
                        textAlign = TextAlign.Center
                    )

                    HorizontalDivider(
                        modifier = Modifier.padding(vertical = Spacing.sm),
                        color = MaterialTheme.colorScheme.outlineVariant
                    )

                    AppFilledTonalButton(
                        modifier = Modifier.fillMaxWidth(),
                        text = stringResource(SharedR.string.incomplete_workout_discard),
                        onClick = onRequestDeleteIncompleteWorkout,
                        textAlign = TextAlign.Center
                    )
                    AppFilledTonalButton(
                        modifier = Modifier.fillMaxWidth(),
                        text = stringResource(SharedR.string.incomplete_workout_clear_menu),
                        onClick = onRequestClearAllIncompleteSessions,
                        textAlign = TextAlign.Center
                    )
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
                                text = stringResource(R.string.loc_scr_ready_to_work_out),
                                style = MaterialTheme.typography.titleMedium,
                                fontWeight = FontWeight.SemiBold,
                                color = MaterialTheme.colorScheme.onBackground
                            )
                            Text(
                                text = stringResource(R.string.loc_scr_start_workout_hint),
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }

                    AppPrimaryButton(
                        modifier = Modifier.fillMaxWidth(),
                        text = stringResource(R.string.loc_scr_start_workout),
                        onClick = onRequestStartWorkout
                    )
                }
            }
            }
        }
    }
}

@Preview(
    name = "Resume workout card",
    showBackground = true,
    widthDp = 412,
    heightDp = 620
)
@Composable
private fun WorkoutSessionActionCardPreview() {
    MyWorkoutAssistantTheme {
        Box(
            modifier = Modifier
                .background(MaterialTheme.colorScheme.background)
                .padding(16.dp)
        ) {
            WorkoutSessionActionCard(
                isCheckingWorkoutRecord = false,
                hasWorkoutRecord = true,
                workoutResumeInfo = WorkoutResumeInfo(
                    exerciseName = "Barbell bench press",
                    setLabel = WorkoutResumeSetLabel(
                        type = WorkoutResumeSetType.WORK,
                        setNumber = 2
                    ),
                    startedAt = LocalDateTime.of(2026, 8, 3, 18, 30),
                    sessionStatus = WorkoutSessionStatus.IN_PROGRESS_ON_PHONE,
                    lastActiveSyncAt = null
                ),
                timeFormatter = DateTimeFormatter.ofPattern("dd/MM/yy HH:mm"),
                onRequestStartWorkout = {},
                onResumeWorkout = {},
                onRequestDeleteIncompleteWorkout = {},
                onRequestClearAllIncompleteSessions = {}
            )
        }
    }
}

@Composable
private fun buildResumeDescription(
    workoutResumeInfo: WorkoutResumeInfo?,
    timeFormatter: DateTimeFormatter
): String {
    if (workoutResumeInfo == null) {
        return stringResource(R.string.loc_scr_resume_in_progress)
    }

    val sessionTime = workoutResumeInfo.startedAt?.format(timeFormatter)
    val staleTime = workoutResumeInfo.lastActiveSyncAt?.format(timeFormatter)

    return buildList {
        add(
            when (workoutResumeInfo.sessionStatus) {
                WorkoutSessionStatus.IN_PROGRESS_ON_WEAR -> stringResource(R.string.loc_scr_active_on_watch)
                WorkoutSessionStatus.STOPPED_ON_WEAR -> stringResource(R.string.loc_scr_left_watch_home)
                WorkoutSessionStatus.STALE_ON_WEAR -> stringResource(R.string.loc_scr_watch_stopped_updates)
                WorkoutSessionStatus.IN_PROGRESS_ON_PHONE,
                WorkoutSessionStatus.INTERRUPTED,
                WorkoutSessionStatus.COMPLETED -> stringResource(R.string.loc_scr_continue_where_left)
            }
        )
        add(stringResource(R.string.loc_scr_resume_from))
        add(
            workoutResumeInfo.exerciseName
                ?: stringResource(R.string.loc_resume_current_exercise)
        )
        add(localizedResumeSetLabel(workoutResumeInfo.setLabel))
        if (sessionTime != null) {
            add(stringResource(R.string.loc_scr_started_at, sessionTime))
        }
        if (workoutResumeInfo.sessionStatus == WorkoutSessionStatus.STALE_ON_WEAR && staleTime != null) {
            add(stringResource(R.string.loc_scr_last_watch_update, staleTime))
        }
    }.joinToString(separator = "\n")
}

@Composable
private fun localizedResumeSetLabel(setLabel: WorkoutResumeSetLabel): String {
    val typeLabel = stringResource(setLabel.type.labelRes())
    return setLabel.setNumber?.let { setNumber ->
        stringResource(R.string.loc_resume_set_numbered, typeLabel, setNumber)
    } ?: typeLabel
}

private fun WorkoutResumeSetType.labelRes(): Int = when (this) {
    WorkoutResumeSetType.WORK -> R.string.loc_resume_set_work
    WorkoutResumeSetType.WARM_UP -> R.string.loc_resume_set_warm_up
    WorkoutResumeSetType.BACK_OFF -> R.string.loc_resume_set_back_off
    WorkoutResumeSetType.REST_PAUSE -> R.string.loc_resume_set_rest_pause
    WorkoutResumeSetType.CALIBRATION -> R.string.loc_resume_set_calibration
    WorkoutResumeSetType.REST -> R.string.loc_resume_set_rest
}
