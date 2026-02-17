package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowForward
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.optionalClip
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.kizitonwose.calendar.compose.CalendarState
import com.kizitonwose.calendar.compose.HorizontalCalendar
import com.kizitonwose.calendar.compose.rememberCalendarState
import com.kizitonwose.calendar.core.CalendarDay
import com.kizitonwose.calendar.core.DayPosition
import com.kizitonwose.calendar.core.OutDateStyle
import com.kizitonwose.calendar.core.daysOfWeek
import com.kizitonwose.calendar.core.nextMonth
import com.kizitonwose.calendar.core.previousMonth
import kotlinx.coroutines.launch
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.Month
import java.time.YearMonth
import java.time.format.TextStyle
import java.util.Locale

fun YearMonth.displayText(short: Boolean = false): String {
    return "${this.month.displayText(short = short)} ${this.year}"
}

fun Month.displayText(short: Boolean = true): String {
    val style = if (short) TextStyle.SHORT else TextStyle.FULL
    return getDisplayName(style, Locale.getDefault())
}

fun DayOfWeek.displayText(uppercase: Boolean = false): String {
    return getDisplayName(TextStyle.SHORT, Locale.getDefault()).let { value ->
        if (uppercase) value.uppercase(Locale.getDefault()) else value
    }
}

@Composable
fun MonthHeader(
    modifier: Modifier = Modifier,
    daysOfWeek: List<DayOfWeek> = emptyList(),
) {
    Row(modifier.fillMaxWidth().padding(bottom = 5.dp)) {
        for (dayOfWeek in daysOfWeek) {
            Text(
                modifier = Modifier.weight(1f),
                textAlign = TextAlign.Center,
                color = MaterialTheme.colorScheme.onBackground,
                text = dayOfWeek.displayText(),
                style = MaterialTheme.typography.bodyLarge,
            )
        }
    }
}

@Composable
private fun Day(
    day: CalendarDay,
    currentDate: LocalDate,
    currentMonth: YearMonth,
    isSelected: Boolean = false,
    shouldHighlight: Boolean = false,
    onClick: (CalendarDay) -> Unit = {},
) {
    val isToday = remember(day) { day.date == currentDate }

    val isOutOfBounds = day.position in listOf(DayPosition.InDate, DayPosition.OutDate)
    val isAfterToday = remember(day) { day.date > currentDate }

    Box(
        Modifier
            .padding(horizontal = 5.dp, vertical = 2.dp)
            .border(
                width = if (isSelected || isToday) 1.dp else 0.dp,
                color = if (isSelected) MaterialTheme.colorScheme.onBackground else (if (isToday) MaterialTheme.colorScheme.secondary else Color.Transparent),
            )
    ){
        Box(
            modifier = Modifier
                .clickable(
                    interactionSource = remember { MutableInteractionSource() },
                    indication = null,
                    enabled = !isAfterToday,
                    onClick = {
                        onClick(day)
                    },
                )
                .padding(3.dp)
        ) {
            val textColor = when {
                isOutOfBounds -> DisabledContentGray
                isAfterToday -> DisabledContentGray
                shouldHighlight -> MaterialTheme.colorScheme.onPrimary
                else -> MaterialTheme.colorScheme.onBackground
            }

            val shape = if(shouldHighlight) CircleShape else null

            val backgroundColor = if(isOutOfBounds || isAfterToday) MaterialTheme.colorScheme.surfaceVariant else MaterialTheme.colorScheme.primary

            Box(
                modifier = Modifier
                    .align(Alignment.Center)
                    .optionalClip(shape)
                    .size(30.dp)
                    .background(if (shouldHighlight) backgroundColor else Color.Transparent),
                contentAlignment = Alignment.Center
            ){
                Text(
                    modifier = Modifier.fillMaxWidth(),
                    text = day.date.dayOfMonth.toString(),
                    color = textColor,
                    textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.titleMedium
                )
            }

            /*
            //set the star yellow
            Icon(
                imageVector = Icons.Default.Star,
                contentDescription = "Star",
                modifier = Modifier
                    .align(Alignment.BottomEnd)
                    .padding(0.dp, 5.dp)
                    .alpha(if (showStar) (if(isOutOfBounds) 0.5f else 1f) else 0f)
                    .size(15.dp),
                tint = Color.Yellow
            )
            */
        }
    }
}

@Composable
fun SimpleCalendarTitle(
    calendarState: CalendarState,
    currentMonth: YearMonth, // Assuming this is the actual current real-world month
    startMonth: YearMonth,
    endMonth: YearMonth
) {
    val context = LocalContext.current

    val scope = rememberCoroutineScope()

    // Use the Month from the state, not the initial currentMonth param for comparison logic
    var currentVisibleMonthYearMonth by remember(calendarState.firstVisibleMonth.yearMonth) { mutableStateOf(calendarState.firstVisibleMonth.yearMonth) }

    // Check if we can navigate backward (previous month >= startMonth)
    val canGoBack = remember(currentVisibleMonthYearMonth, startMonth) {
        currentVisibleMonthYearMonth.previousMonth >= startMonth
    }

    // Check if we can navigate forward (next month <= endMonth)
    val canGoForward = remember(currentVisibleMonthYearMonth, endMonth) {
        currentVisibleMonthYearMonth.nextMonth <= endMonth
    }

    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.fillMaxWidth() // Good practice for Rows like this
    ) {
        val navIconColors = IconButtonDefaults.iconButtonColors(
            contentColor = MaterialTheme.colorScheme.onBackground,
            disabledContentColor = DisabledContentGray
        )
        Box(
            modifier = Modifier.size(48.dp),
            contentAlignment = Alignment.Center
        ) {
            if (canGoBack) {
                IconButton(
                    onClick = {
                        scope.launch {
                            currentVisibleMonthYearMonth = calendarState.firstVisibleMonth.yearMonth.previousMonth
                            calendarState.scrollToMonth(calendarState.firstVisibleMonth.yearMonth.previousMonth)
                        }
                    },
                    colors = navIconColors
                ) {
                    Icon(
                        imageVector = Icons.Filled.ArrowBack,
                        contentDescription = "Previous Month"
                    )
                }
            }
        }

        Text(
            modifier = Modifier.weight(1f),
            text = currentVisibleMonthYearMonth.displayText(), // Use the animated month
            style = MaterialTheme.typography.titleMedium,
            textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onBackground
        )

        Box(
            modifier = Modifier.size(48.dp),
            contentAlignment = Alignment.Center
        ) {
            if (canGoForward) {
                IconButton(
                    onClick = {
                        scope.launch {
                            currentVisibleMonthYearMonth = calendarState.firstVisibleMonth.yearMonth.nextMonth
                            calendarState.scrollToMonth(calendarState.firstVisibleMonth.yearMonth.nextMonth)
                        }
                    },
                    colors = navIconColors
                ) {
                    Icon(
                        imageVector = Icons.Filled.ArrowForward,
                        contentDescription = "Next Month"
                    )
                }
            }
        }
    }


}

@Composable
fun WorkoutsCalendar(
    modifier: Modifier = Modifier,
    selectedDate: CalendarDay,
    onDayClicked: (CalendarState,CalendarDay) -> Unit,
    shouldHighlight: (CalendarDay) -> Boolean,
    groupedWorkoutsHistories: Map<LocalDate, List<WorkoutHistory>>? = null,
){
    val currentDate = remember { LocalDate.now() }
    val currentMonth = remember { YearMonth.now() }

    // Calculate available months from groupedWorkoutsHistories
    val availableMonths = remember(groupedWorkoutsHistories) {
        groupedWorkoutsHistories?.keys
            ?.map { YearMonth.from(it) }  // Convert LocalDate to YearMonth using YearMonth.from()
            ?.distinct()
            ?.sorted()
    }

    val startMonth = remember(availableMonths, currentMonth) {
        availableMonths?.firstOrNull() ?: currentMonth
    }
    val endMonth = remember(availableMonths, currentMonth) {
        availableMonths?.lastOrNull() ?: currentMonth
    }

    val daysOfWeek = remember { daysOfWeek() }

    val calendarState = rememberCalendarState(
        startMonth = startMonth,
        endMonth = endMonth,
        firstVisibleMonth = currentMonth,
        outDateStyle = OutDateStyle.EndOfGrid,
    )

    Column(
        modifier = modifier,
    ){
        SimpleCalendarTitle(
            calendarState = calendarState,
            currentMonth = currentMonth,
            startMonth = startMonth,
            endMonth = endMonth
        )
        HorizontalCalendar(
            modifier = Modifier.padding(5.dp),
            state = calendarState,
            calendarScrollPaged = false,
            userScrollEnabled = false,
            dayContent = { day ->
                Day(
                    day = day,
                    currentDate = currentDate,
                    currentMonth = currentMonth,
                    isSelected = selectedDate.date == day.date,
                    shouldHighlight = shouldHighlight(day),
                ) { selectedCalendarDay ->
                    onDayClicked(calendarState,selectedCalendarDay)
                }
            },
            monthHeader = {
                MonthHeader(daysOfWeek = daysOfWeek)
            },
        )
    }


}

