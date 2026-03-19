package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.composables.AppPrimaryOutlinedButton
import com.gabstra.myworkoutassistant.composables.AppSecondaryButton
import com.gabstra.myworkoutassistant.composables.DashedCard
import com.gabstra.myworkoutassistant.composables.ExpandableContainer
import com.gabstra.myworkoutassistant.composables.ObjectiveProgressBar
import com.gabstra.myworkoutassistant.composables.StandardDialog
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.composables.WorkoutHistoryCard
import com.gabstra.myworkoutassistant.composables.WorkoutsCalendar
import com.gabstra.myworkoutassistant.getEndOfWeek
import com.gabstra.myworkoutassistant.getStartOfWeek
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.WeeklyProgressSnapshot
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.Yellow
import com.gabstra.myworkoutassistant.verticalColumnScrollbarContainer
import com.kizitonwose.calendar.compose.CalendarState
import com.kizitonwose.calendar.core.CalendarDay
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale
import java.util.UUID

data class WeeklyStatusWorkoutHistory(
    val workoutHistory: WorkoutHistory,
    val workout: Workout,
    val isExcludedFromWeeklyProgress: Boolean,
)

@Composable
fun WorkoutsStatusTab(
    isLoading: Boolean,
    hasObjectives: Boolean,
    selectedDate: CalendarDay,
    selectedWeekStart: LocalDate,
    selectedWeekEnd: LocalDate,
    completedWeekStarts: Set<LocalDate>,
    selectedWeekWorkoutsByDate: Map<LocalDate, List<WeeklyStatusWorkoutHistory>>?,
    weeklyProgressSnapshot: WeeklyProgressSnapshot,
    appViewModel: AppViewModel,
    onDayClicked: (CalendarState, CalendarDay) -> Unit,
    highlightDay: (CalendarDay) -> Boolean,
    onSaveWeeklyProgressSelection: (Set<UUID>) -> Unit,
    onClearWeeklyProgressSelection: () -> Unit,
    groupedWorkoutsHistories: Map<LocalDate, List<WorkoutHistory>>? = null
) {
    val scrollState = rememberScrollState()
    val currentLocale = Locale.getDefault()
    val timeFormatter = remember(currentLocale) {
        DateTimeFormatter.ofPattern("HH:mm", currentLocale)
    }
    var showWeeklyProgressDialog by remember { mutableStateOf(false) }
    var pendingIncludedWorkoutGlobalIds by remember { mutableStateOf<Set<UUID>>(emptySet()) }

    val selectedWeekLabel = remember(selectedDate, currentLocale) {
        val currentDate = selectedDate.date
        val startWeekDate = getStartOfWeek(currentDate)
        val startWeekMonth = startWeekDate.format(DateTimeFormatter.ofPattern("MMM", currentLocale))
        val endWeekDate = getEndOfWeek(currentDate)
        val endWeekMonth = endWeekDate.format(DateTimeFormatter.ofPattern("MMM", currentLocale))

        if (startWeekMonth == endWeekMonth) {
            "${startWeekDate.dayOfMonth} - ${endWeekDate.dayOfMonth} $startWeekMonth"
        } else {
            "${startWeekDate.dayOfMonth} $startWeekMonth - ${endWeekDate.dayOfMonth} $endWeekMonth"
        }
    }

    if (showWeeklyProgressDialog) {
        val dialogScrollState = rememberScrollState()
        StandardDialog(
            onDismissRequest = { showWeeklyProgressDialog = false },
            title = "Weekly progress settings",
            body = {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    Text(
                        text = "The workouts you select will count toward weekly progress starting from $selectedWeekLabel until you save a new rule.",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodyMedium,
                    )

                    if (weeklyProgressSnapshot.isOverrideBoundary) {
                        AppSecondaryButton(
                            modifier = Modifier.fillMaxWidth(),
                            text = "Remove saved start week",
                            onClick = {
                                showWeeklyProgressDialog = false
                                onClearWeeklyProgressSelection()
                            },
                            minHeight = 40.dp,
                        )
                    }

                    if (weeklyProgressSnapshot.eligibleWorkouts.isEmpty()) {
                        Text(
                            text = "No workouts with weekly targets are available this week.",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    } else {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .heightIn(max = 320.dp)
                                .verticalScroll(dialogScrollState),
                            verticalArrangement = Arrangement.spacedBy(6.dp)
                        ) {
                            weeklyProgressSnapshot.eligibleWorkouts.forEach { workout ->
                                val isChecked = workout.globalId in pendingIncludedWorkoutGlobalIds
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .clip(MaterialTheme.shapes.small)
                                        .clickable {
                                            pendingIncludedWorkoutGlobalIds =
                                                pendingIncludedWorkoutGlobalIds.toMutableSet().apply {
                                                    if (!add(workout.globalId)) {
                                                        remove(workout.globalId)
                                                    }
                                                }
                                        }
                                        .padding(vertical = 4.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                    horizontalArrangement = Arrangement.spacedBy(10.dp)
                                ) {
                                    Checkbox(
                                        checked = isChecked,
                                        onCheckedChange = { checked ->
                                            pendingIncludedWorkoutGlobalIds =
                                                pendingIncludedWorkoutGlobalIds.toMutableSet().apply {
                                                    if (checked) {
                                                        add(workout.globalId)
                                                    } else {
                                                        remove(workout.globalId)
                                                    }
                                                }
                                        }
                                    )
                                    Column(
                                        modifier = Modifier.weight(1f),
                                        verticalArrangement = Arrangement.spacedBy(2.dp)
                                    ) {
                                        Text(
                                            text = workout.name,
                                            color = MaterialTheme.colorScheme.onSurface,
                                            style = MaterialTheme.typography.bodyLarge,
                                        )
                                        Text(
                                            text = "Target: ${(workout.timesCompletedInAWeek ?: 0)} per week",
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                            style = MaterialTheme.typography.bodySmall,
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            },
            confirmText = "Save",
            onConfirm = {
                showWeeklyProgressDialog = false
                onSaveWeeklyProgressSelection(pendingIncludedWorkoutGlobalIds)
            },
            dismissText = "Cancel",
            onDismissButton = { showWeeklyProgressDialog = false },
        )
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 10.dp)
            .padding(bottom = 10.dp)
            .verticalColumnScrollbarContainer(scrollState),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        val overrideStartLabel = remember(weeklyProgressSnapshot.effectiveOverrideWeekStart, currentLocale) {
            weeklyProgressSnapshot.effectiveOverrideWeekStart?.format(
                DateTimeFormatter.ofPattern("d MMM yyyy", currentLocale)
            )
        }
        StyledCard {
            WorkoutsCalendar(
                selectedDate = selectedDate,
                selectedWeekStart = selectedWeekStart,
                selectedWeekEnd = selectedWeekEnd,
                completedWeekStarts = completedWeekStarts,
                onDayClicked = { calendarState, day ->
                    onDayClicked(calendarState, day)
                },
                shouldHighlight = { day -> highlightDay(day) },
                groupedWorkoutsHistories = groupedWorkoutsHistories
            )
        }
        if (isLoading) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(10.dp),
                contentAlignment = Alignment.Center
            ) {
                CircularProgressIndicator(
                    modifier = Modifier.width(32.dp),
                    color = MaterialTheme.colorScheme.primary,
                    trackColor = MediumDarkGray,
                )
            }
        } else {
            if (hasObjectives) {
                StyledCard {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(10.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(
                                modifier = Modifier.weight(1f),
                                text = "Weekly progress\n($selectedWeekLabel)",
                                style = MaterialTheme.typography.titleMedium,
                                textAlign = TextAlign.Start,
                                color = MaterialTheme.colorScheme.onBackground
                            )
                            AppPrimaryOutlinedButton(
                                text = "Edit",
                                onClick = {
                                    pendingIncludedWorkoutGlobalIds =
                                        weeklyProgressSnapshot.includedWorkoutGlobalIds
                                    showWeeklyProgressDialog = true
                                },
                                minHeight = 36.dp,
                            )
                        }
/*                        if (weeklyProgressSnapshot.hasOverride && !weeklyProgressSnapshot.isOverrideBoundary) {
                            Text(
                                text = "Saved rule active since ${overrideStartLabel ?: selectedWeekLabel}",
                                color = MaterialTheme.colorScheme.primary,
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }*/
                        ExpandableContainer(
                            isOpen = false,
                            isExpandable = weeklyProgressSnapshot.hasOverride ||
                                weeklyProgressSnapshot.weeklyWorkoutsByActualTarget.isNotEmpty(),
                            title = { modifier ->
                                Row(
                                    modifier = modifier
                                        .fillMaxWidth()
                                        .padding(10.dp),
                                    horizontalArrangement = Arrangement.Center,
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    Text(
                                        text = "${(weeklyProgressSnapshot.objectiveProgress * 100).toInt()}%",
                                        style = MaterialTheme.typography.titleMedium,
                                        textAlign = TextAlign.Center,
                                        color = MaterialTheme.colorScheme.onBackground,
                                    )
                                    Spacer(modifier = Modifier.width(10.dp))
                                    ObjectiveProgressBar(
                                        Modifier.weight(1f),
                                        progress = weeklyProgressSnapshot.objectiveProgress.toFloat(),
                                        color = if (weeklyProgressSnapshot.objectiveProgress >= 1f) {
                                            Yellow
                                        } else {
                                            MaterialTheme.colorScheme.primary
                                        }
                                    )
                                }
                            },
                            content = {
                                if (weeklyProgressSnapshot.weeklyWorkoutsByActualTarget.isEmpty()) {
                                    Text(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .padding(10.dp),
                                        text = "No workouts are selected for weekly progress.",
                                        color = MaterialTheme.colorScheme.onBackground,
                                        style = MaterialTheme.typography.bodyMedium,
                                        textAlign = TextAlign.Center,
                                    )
                                } else {
                                    Column(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .padding(10.dp),
                                        verticalArrangement = Arrangement.spacedBy(10.dp)
                                    ) {
                                        weeklyProgressSnapshot.weeklyWorkoutsByActualTarget
                                            .entries
                                            .forEach { (workout, pair) ->
                                                Row(
                                                    horizontalArrangement = Arrangement.SpaceBetween
                                                ) {
                                                    Text(
                                                        text = workout.name,
                                                        modifier = Modifier.weight(1f),
                                                        color = MaterialTheme.colorScheme.onBackground,
                                                        style = MaterialTheme.typography.bodyLarge,
                                                    )
                                                    Text(
                                                        text = "${pair.first}/${pair.second}",
                                                        color = MaterialTheme.colorScheme.onBackground,
                                                        style = MaterialTheme.typography.bodyLarge,
                                                    )
                                                }
                                            }
                                    }
                                }
                            }
                        )
                    }
                }
            }
            StyledCard {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(10.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    val currentWeekStartMonth = selectedWeekStart
                        .format(DateTimeFormatter.ofPattern("MMM", currentLocale))
                    val currentWeekEndMonth = selectedWeekEnd
                        .format(DateTimeFormatter.ofPattern("MMM", currentLocale))
                    val currentWeekText = if (currentWeekStartMonth == currentWeekEndMonth) {
                        "${selectedWeekStart.dayOfMonth} - ${selectedWeekEnd.dayOfMonth} $currentWeekStartMonth"
                    } else {
                        "${selectedWeekStart.dayOfMonth} $currentWeekStartMonth - ${selectedWeekEnd.dayOfMonth} $currentWeekEndMonth"
                    }

                    Text(
                        modifier = Modifier.fillMaxWidth(),
                        text = "Workout history ($currentWeekText)",
                        style = MaterialTheme.typography.titleMedium,
                        textAlign = TextAlign.Start,
                        color = MaterialTheme.colorScheme.onBackground
                    )

                    if (selectedWeekWorkoutsByDate.isNullOrEmpty()) {
                        Box(
                            modifier = Modifier.fillMaxSize(),
                            contentAlignment = Alignment.Center
                        ) {
                            Text(
                                modifier = Modifier.padding(15.dp),
                                text = "No workouts recorded this week.",
                                textAlign = TextAlign.Center,
                                color = MaterialTheme.colorScheme.onBackground,
                            )
                        }
                    } else {
                        val dayFormatter = DateTimeFormatter.ofPattern("EEE d MMM", currentLocale)
                        selectedWeekWorkoutsByDate.entries
                            .sortedBy { it.key }
                            .forEach { (date, dayWorkouts) ->
                                Text(
                                    modifier = Modifier.fillMaxWidth(),
                                    text = date.format(dayFormatter),
                                    style = MaterialTheme.typography.titleSmall,
                                    textAlign = TextAlign.Start,
                                    color = MaterialTheme.colorScheme.onBackground
                                )
                                WorkoutHistoriesByWorkoutGroup(
                                    dayWorkouts = dayWorkouts,
                                    appViewModel = appViewModel,
                                    timeFormatter = timeFormatter
                                )
                            }
                    }
                }
            }
        }
    }
}

@Composable
private fun WorkoutHistoriesByWorkoutGroup(
    dayWorkouts: List<WeeklyStatusWorkoutHistory>,
    appViewModel: AppViewModel,
    timeFormatter: DateTimeFormatter
) {
    dayWorkouts
        .groupBy { it.workout.id }
        .forEach { (_, historyAndWorkoutList) ->
            val moreThanOneWorkout = historyAndWorkoutList.size > 1
            if (moreThanOneWorkout) {
                val workout = historyAndWorkoutList[0].workout
                ExpandableContainer(
                    title = { modifier ->
                        Row(
                            modifier = modifier,
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(10.dp)
                        ) {
                            Box(
                                modifier = Modifier
                                    .clip(CircleShape)
                                    .size(30.dp)
                                    .background(MaterialTheme.colorScheme.primary),
                                contentAlignment = Alignment.Center
                            ) {
                                Text(
                                    modifier = Modifier.fillMaxWidth(),
                                    text = historyAndWorkoutList.size.toString(),
                                    color = MaterialTheme.colorScheme.background,
                                    textAlign = TextAlign.Center,
                                    style = MaterialTheme.typography.titleMedium
                                )
                            }
                            Text(
                                modifier = Modifier
                                    .weight(1f)
                                    .padding(start = 5.dp),
                                text = workout.name,
                                color = if (workout.enabled) {
                                    MaterialTheme.colorScheme.onBackground
                                } else {
                                    DisabledContentGray
                                },
                                style = MaterialTheme.typography.bodyLarge,
                            )
                        }
                    },
                    content = {
                        DashedCard {
                            Column(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(10.dp),
                                verticalArrangement = Arrangement.spacedBy(10.dp)
                            ) {
                                historyAndWorkoutList.forEach { dayWorkout ->
                                    WorkoutHistoryCard(
                                        workoutHistory = dayWorkout.workoutHistory,
                                        workout = dayWorkout.workout,
                                        appViewModel = appViewModel,
                                        timeFormatter = timeFormatter,
                                        statusBadgeText = if (dayWorkout.isExcludedFromWeeklyProgress) {
                                            "Not counted"
                                        } else {
                                            null
                                        }
                                    )
                                }
                            }
                        }
                    }
                )
            } else {
                val dayWorkout = historyAndWorkoutList[0]
                WorkoutHistoryCard(
                    workoutHistory = dayWorkout.workoutHistory,
                    workout = dayWorkout.workout,
                    appViewModel = appViewModel,
                    timeFormatter = timeFormatter,
                    statusBadgeText = if (dayWorkout.isExcludedFromWeeklyProgress) {
                        "Not counted"
                    } else {
                        null
                    }
                )
            }
        }
}
