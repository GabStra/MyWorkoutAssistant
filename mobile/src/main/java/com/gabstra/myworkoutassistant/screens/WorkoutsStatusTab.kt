package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.composables.DashedCard
import com.gabstra.myworkoutassistant.composables.ExpandableContainer
import com.gabstra.myworkoutassistant.composables.ObjectiveProgressBar
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.composables.WorkoutHistoryCard
import com.gabstra.myworkoutassistant.composables.WorkoutsCalendar
import com.gabstra.myworkoutassistant.getEndOfWeek
import com.gabstra.myworkoutassistant.getStartOfWeek
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.verticalColumnScrollbar
import com.kizitonwose.calendar.compose.CalendarState
import com.kizitonwose.calendar.core.CalendarDay
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale

@Composable
fun WorkoutsStatusTab(
    isLoading: Boolean,
    hasObjectives: Boolean,
    selectedDate: CalendarDay,
    selectedCalendarWorkouts: List<Pair<WorkoutHistory, Workout>>?,
    weeklyWorkoutsByActualTarget: Map<Workout, Pair<Int, Int>>?,
    objectiveProgress: Double,
    appViewModel: AppViewModel,
    onDayClicked: (CalendarState, CalendarDay) -> Unit,
    highlightDay: (CalendarDay) -> Boolean
) {
    val scrollState = rememberScrollState()
    val currentLocale = Locale.getDefault()
    val timeFormatter = remember(currentLocale) {
        DateTimeFormatter.ofPattern("HH:mm", currentLocale)
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 10.dp)
            .padding(bottom = 10.dp)
            .verticalColumnScrollbar(scrollState)
            .verticalScroll(scrollState)
            .padding(horizontal = 15.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        StyledCard {
            WorkoutsCalendar(
                selectedDate = selectedDate,
                onDayClicked = { calendarState, day ->
                    onDayClicked(calendarState, day)
                },
                shouldHighlight = { day -> highlightDay(day) },
            )
        }
        if (isLoading) {
            Box(
                modifier = Modifier
                    .fillMaxSize().padding(10.dp),
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
                val currentDate = selectedDate.date

                val startWeekDate = getStartOfWeek(currentDate)
                val startWeekMonth = startWeekDate.format(DateTimeFormatter.ofPattern("MMM"))
                val endWeekDate = getEndOfWeek(currentDate)
                val endWeekMonth = endWeekDate.format(DateTimeFormatter.ofPattern("MMM"))

                val dateText = if (startWeekMonth == endWeekMonth) {
                    "${startWeekDate.dayOfMonth} - ${endWeekDate.dayOfMonth} $startWeekMonth"
                } else {
                    "${startWeekDate.dayOfMonth} $startWeekMonth - ${endWeekDate.dayOfMonth} $endWeekMonth"
                }

                StyledCard {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(10.dp),
                        verticalArrangement = Arrangement.spacedBy(5.dp)
                    ) {
                        Text(
                            modifier = Modifier.fillMaxWidth(),
                            text = "Weekly progress (${dateText}):",
                            style = MaterialTheme.typography.titleMedium,
                            textAlign = TextAlign.Center,
                            color = MaterialTheme.colorScheme.onBackground
                        )
                        ExpandableContainer(
                            isOpen = false,
                            isExpandable = if (weeklyWorkoutsByActualTarget == null) false else weeklyWorkoutsByActualTarget!!.isNotEmpty(),
                            title = { modifier ->
                                Row(
                                    modifier = modifier
                                        .fillMaxWidth()
                                        .padding(10.dp),
                                    horizontalArrangement = Arrangement.Center,
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    Text(
                                        text = "${(objectiveProgress * 100).toInt()}%",
                                        style = MaterialTheme.typography.titleMedium,
                                        textAlign = TextAlign.Center,
                                        color = MaterialTheme.colorScheme.onBackground,
                                    )
                                    Spacer(modifier = Modifier.width(10.dp))
                                    ObjectiveProgressBar(
                                        Modifier.weight(1f),
                                        progress = objectiveProgress.toFloat()
                                    )
                                }
                            }, content = {
                                Column(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(10.dp),
                                    verticalArrangement = Arrangement.spacedBy(10.dp)
                                ) {
                                    weeklyWorkoutsByActualTarget?.entries?.forEachIndexed { index, (workout, pair) ->
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
                            })
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
                    val currentDate = selectedDate.date
                    val currentMonth =
                        currentDate.format(DateTimeFormatter.ofPattern("MMM"))

                    Text(
                        modifier = Modifier.fillMaxWidth(),
                        text = "Workout Histories (${currentDate.dayOfMonth} ${currentMonth}):",
                        style = MaterialTheme.typography.titleMedium,
                        textAlign = TextAlign.Center,
                        color = MaterialTheme.colorScheme.onBackground
                    )

                    if (selectedCalendarWorkouts.isNullOrEmpty()) {
                        Box(
                            modifier = Modifier.fillMaxSize(),
                            contentAlignment = Alignment.Center
                        ) {
                            Text(
                                modifier = Modifier.padding(15.dp),
                                text = "No workouts on this day",
                                textAlign = TextAlign.Center,
                                color = MaterialTheme.colorScheme.onBackground,
                            )
                        }
                    } else {
                        selectedCalendarWorkouts!!
                            .groupBy { it.second.id } // Group by workout.id
                            .forEach { (workoutId, historyAndWorkoutList) ->
                                val moreThanOneWorkout = historyAndWorkoutList.size > 1

                                if (moreThanOneWorkout) {
                                    val workout = historyAndWorkoutList[0].second
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
                                                    color = if (workout.enabled) MaterialTheme.colorScheme.onBackground else DisabledContentGray,
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
                                                    historyAndWorkoutList.forEach { (workoutHistory, workout) ->
                                                        WorkoutHistoryCard(
                                                            workoutHistory = workoutHistory,
                                                            workout = workout,
                                                            appViewModel = appViewModel,
                                                            timeFormatter = timeFormatter
                                                        )
                                                    }
                                                }
                                            }
                                        }
                                    )
                                } else {
                                    val workoutHistory = historyAndWorkoutList[0].first
                                    val workout = historyAndWorkoutList[0].second

                                    WorkoutHistoryCard(
                                        workoutHistory = workoutHistory,
                                        workout = workout,
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
}
