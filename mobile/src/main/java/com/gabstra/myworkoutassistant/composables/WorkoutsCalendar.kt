package com.gabstra.myworkoutassistant.composables

import android.os.Build
import androidx.annotation.RequiresApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
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
                color = Color.White.copy(alpha = .87f),
                text = dayOfWeek.displayText(),
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}

@Composable
private fun Day(
    day: CalendarDay,
    isToday: Boolean = false,
    isSelected: Boolean = false,
    shouldHighlight: Boolean = false,
    onClick: (CalendarDay) -> Unit = {},
) {
    val isOutOfBounds = day.position in listOf(DayPosition.InDate, DayPosition.OutDate)
    Box(
        Modifier
            .padding(2.dp)
            .border(
                width = if (isSelected || isToday) 1.dp else 0.dp,
                color = if (isSelected) Color.White.copy(alpha = .87f) else (if (isToday) Color.Green else Color.Transparent),
            )
    ){
        Box(
            modifier = Modifier
                .clickable(
                    onClick = { onClick(day) },
                )
                .alpha(if (isOutOfBounds) 0.25f else 1f)

                .padding(3.dp)
        ) {
            val textColor =  if(shouldHighlight) Color.Black else Color.White.copy(alpha = .87f)

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

private val CalendarLayoutInfo.completelyVisibleMonths: List<CalendarMonth>
    @RequiresApi(Build.VERSION_CODES.VANILLA_ICE_CREAM)
    get() {
        val visibleItemsInfo = this.visibleMonthsInfo.toMutableList()
        return if (visibleItemsInfo.isEmpty()) {
            emptyList()
        } else {
            val lastItem = visibleItemsInfo.last()
            val viewportSize = this.viewportEndOffset + this.viewportStartOffset
            if (lastItem.offset + lastItem.size > viewportSize) {
                visibleItemsInfo.removeLast()
            }
            val firstItem = visibleItemsInfo.firstOrNull()
            if (firstItem != null && firstItem.offset < this.viewportStartOffset) {
                visibleItemsInfo.removeFirst()
            }
            visibleItemsInfo.map { it.month }
        }
    }

@RequiresApi(Build.VERSION_CODES.VANILLA_ICE_CREAM)
@Composable
fun rememberFirstCompletelyVisibleMonth(state: CalendarState): CalendarMonth {
    val visibleMonth = remember(state) { mutableStateOf(state.firstVisibleMonth) }
    // Only take non-null values as null will be produced when the
    // list is mid-scroll as no index will be completely visible.
    LaunchedEffect(state) {
        snapshotFlow { state.layoutInfo.completelyVisibleMonths.firstOrNull() }
            .filterNotNull()
            .collect { month -> visibleMonth.value = month }
    }
    return visibleMonth.value
}


@RequiresApi(Build.VERSION_CODES.VANILLA_ICE_CREAM)
@Composable
fun SimpleCalendarTitle(
    calendarState: CalendarState,
    currentMonth: YearMonth
) {
    val visibleMonth = rememberFirstCompletelyVisibleMonth(calendarState)
    val scope = rememberCoroutineScope()

    val isCurrentMonth = visibleMonth.yearMonth.month == currentMonth.month && visibleMonth.yearMonth.year == currentMonth.year

    Row(
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconButton(
            onClick = {
                scope.launch {
                    calendarState.animateScrollToMonth(calendarState.firstVisibleMonth.yearMonth.previousMonth)
                }
            },
        ) {
            Icon(imageVector = Icons.Filled.ArrowBack, contentDescription = "Back",tint = Color.White)
        }

        Text(
            modifier = Modifier.weight(1f),
            text = visibleMonth.yearMonth.displayText(),
            style = MaterialTheme.typography.titleMedium,
            textAlign = TextAlign.Center,
            color = Color.White.copy(alpha = .87f)
        )

        IconButton(
            enabled = !isCurrentMonth,
            onClick = {
                scope.launch {
                    calendarState.animateScrollToMonth(calendarState.firstVisibleMonth.yearMonth.nextMonth)
                }
            },
        ) {
            Icon(imageVector = Icons.Filled.ArrowForward, contentDescription = "Back",tint = if(isCurrentMonth) Color.DarkGray else Color.White)
        }
    }
}

@RequiresApi(Build.VERSION_CODES.VANILLA_ICE_CREAM)
@Composable
fun WorkoutsCalendar(
    modifier: Modifier = Modifier,
    selectedDate: CalendarDay,
    onDayClicked: (CalendarState,CalendarDay) -> Unit,
    shouldHighlight: (CalendarDay) -> Boolean,
){
    val currentDay = LocalDate.now()
    val currentMonth = remember { YearMonth.now() }

    val startMonth = remember { currentMonth.minusMonths(1200) }
    val endMonth = remember { currentMonth }

    val daysOfWeek = remember { daysOfWeek() }

    val calendarState = rememberCalendarState(
        startMonth = startMonth,
        endMonth = endMonth,
        firstVisibleMonth = currentMonth,
        firstDayOfWeek = daysOfWeek.first(),
        outDateStyle = OutDateStyle.EndOfGrid,
    )

    Column(
        modifier = modifier,
    ){
        SimpleCalendarTitle(
            calendarState = calendarState,
            currentMonth = currentMonth
        )
        DarkModeContainer(whiteOverlayAlpha = .1f) {
            HorizontalCalendar(
                modifier = Modifier.padding(5.dp),
                state = calendarState,
                calendarScrollPaged = false,
                userScrollEnabled = false,
                dayContent = { day ->
                    Day(
                        isToday = day.date == currentDay,
                        day = day,
                        isSelected = selectedDate.date == day.date,
                        shouldHighlight = shouldHighlight(day),
                    ) { selectedCalendarDay ->
                        onDayClicked(calendarState,selectedCalendarDay)
                    }
                },
                monthHeader = {
                    MonthHeader(daysOfWeek = daysOfWeek())
                },
            )
        }
    }
}