package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowForward
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.gabstra.myworkoutassistant.getEndOfWeek
import com.gabstra.myworkoutassistant.getStartOfWeek
import com.gabstra.myworkoutassistant.optionalClip
import com.kizitonwose.calendar.compose.CalendarLayoutInfo
import com.kizitonwose.calendar.compose.CalendarState
import com.kizitonwose.calendar.compose.HorizontalCalendar
import com.kizitonwose.calendar.compose.WeekCalendar
import com.kizitonwose.calendar.compose.rememberCalendarState
import com.kizitonwose.calendar.compose.weekcalendar.WeekCalendarState
import com.kizitonwose.calendar.compose.weekcalendar.rememberWeekCalendarState
import com.kizitonwose.calendar.core.CalendarDay
import com.kizitonwose.calendar.core.CalendarMonth
import com.kizitonwose.calendar.core.DayPosition
import com.kizitonwose.calendar.core.OutDateStyle
import com.kizitonwose.calendar.core.WeekDay
import com.kizitonwose.calendar.core.WeekDayPosition
import com.kizitonwose.calendar.core.atStartOfMonth
import com.kizitonwose.calendar.core.daysOfWeek
import com.kizitonwose.calendar.core.nextMonth
import com.kizitonwose.calendar.core.previousMonth
import com.kizitonwose.calendar.core.yearMonth
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.launch
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.Month
import java.time.YearMonth
import java.time.format.DateTimeFormatter
import java.time.format.TextStyle
import java.time.temporal.TemporalAdjusters
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
    Row(modifier.fillMaxWidth()) {
        for (dayOfWeek in daysOfWeek) {
            Text(
                modifier = Modifier.weight(1f),
                textAlign = TextAlign.Center,
                color = Color.White.copy(alpha = .6f),
                text = dayOfWeek.displayText(),
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}

@Composable
private fun Day(
    day: WeekDay,
    isToday: Boolean = false,
    isSelected: Boolean = false,
    shouldHighlight: Boolean = false,
    onClick: (WeekDay) -> Unit = {},
) {
    val isOutOfBounds = day.position in listOf(WeekDayPosition.InDate, WeekDayPosition.OutDate)
    Box(Modifier.padding(5.dp)){
        Box(
            modifier = Modifier
                .clickable(
                    onClick = { onClick(day) },
                )
                .alpha(if (isOutOfBounds) 0.25f else 1f)
                .border(
                    width = if (isSelected || isToday) 1.dp else 0.dp,
                    color = if (isSelected) Color.White.copy(alpha = .87f) else (if (isToday) Color.Green else Color.Transparent),
                )
                .padding(3.dp)

            ,
        ) {
            val textColor =  if(shouldHighlight) Color.Black else Color.White.copy(alpha = .6f)

            val shape = if(shouldHighlight) CircleShape else null

            Box(
                modifier = Modifier
                    .align(Alignment.Center)
                    .optionalClip(shape)
                    .size(30.dp)
                    .background(if (shouldHighlight) MaterialTheme.colorScheme.primary else Color.Transparent),
                contentAlignment = Alignment.Center
            ){
                Text(
                    text = day.date.dayOfMonth.toString(),
                    color = textColor,
                    style = MaterialTheme.typography.bodyMedium,
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
    currentDay: WeekDay,
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
    ) {

        Text(
            modifier = Modifier
                .weight(1f)
                .padding(10.dp),
            text = "${currentDay.date.dayOfMonth} ${currentDay.date.yearMonth.displayText()}",
            style = MaterialTheme.typography.titleMedium,
            textAlign = TextAlign.Center,
            color = Color.White.copy(alpha = .87f)
        )
    }
}

@Composable
fun WorkoutsCalendar(
    selectedDate: WeekDay,
    onDayClicked: (WeekCalendarState,WeekDay) -> Unit,
    shouldHighlight: (WeekDay) -> Boolean,
){
    val currentDay = LocalDate.now()

    val weekCalendarState = rememberWeekCalendarState(
        startDate = currentDay.minusMonths(12),
        endDate = currentDay
    )

    val scope = rememberCoroutineScope()

    Column(modifier = Modifier.padding(5.dp)){
        SimpleCalendarTitle(
            currentDay = selectedDate,
        )
        Spacer(modifier = Modifier.height(5.dp))
        WeekCalendar(
            state = weekCalendarState,
            calendarScrollPaged = false,
            userScrollEnabled = true,
            dayContent = { day ->
                Day(
                    isToday = day.date == currentDay,
                    day = day,
                    isSelected = selectedDate.date == day.date,
                    shouldHighlight = shouldHighlight(day),
                ) { selectedWeekDay ->
                    onDayClicked(weekCalendarState,selectedWeekDay)
                    scope.launch {
                        weekCalendarState.animateScrollToWeek(selectedWeekDay.date)
                    }
                }
            },
            weekHeader = {
                MonthHeader(daysOfWeek = daysOfWeek())
            },
        )
    }
}