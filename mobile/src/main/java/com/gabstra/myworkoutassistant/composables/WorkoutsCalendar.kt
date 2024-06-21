package com.gabstra.myworkoutassistant.composables

import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.wrapContentWidth
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowForward
import androidx.compose.material.icons.filled.Star
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
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.gabstra.myworkoutassistant.optionalClip
import com.kizitonwose.calendar.compose.CalendarLayoutInfo
import com.kizitonwose.calendar.compose.CalendarState
import com.kizitonwose.calendar.compose.HorizontalCalendar
import com.kizitonwose.calendar.compose.rememberCalendarState
import com.kizitonwose.calendar.core.CalendarDay
import com.kizitonwose.calendar.core.CalendarMonth
import com.kizitonwose.calendar.core.DayPosition
import com.kizitonwose.calendar.core.OutDateStyle
import com.kizitonwose.calendar.core.daysOfWeek
import com.kizitonwose.calendar.core.nextMonth
import com.kizitonwose.calendar.core.previousMonth
import kotlinx.coroutines.flow.filterNotNull
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
    Row(modifier.fillMaxWidth()) {
        for (dayOfWeek in daysOfWeek) {
            Text(
                modifier = Modifier.weight(1f),
                textAlign = TextAlign.Center,
                fontSize = 12.sp,
                color = Color.White,
                text = dayOfWeek.displayText(),
                fontWeight = FontWeight.Light,
            )
        }
    }
}

@Composable
private fun Day(
    day: CalendarDay,
    isToday: Boolean = false,
    isSelected: Boolean = false,
    showStar: Boolean = false,
    onClick: (CalendarDay) -> Unit = {},
) {
    val isOutOfBounds = day.position in listOf(DayPosition.InDate, DayPosition.OutDate)

    Box(
        modifier = Modifier
            .clickable(
                onClick = { onClick(day) },
            )
            .aspectRatio(1f) // This is important for square-sizing!
            .alpha(if(isOutOfBounds) 0.25f else 1f)
            .border(
                width = if (isSelected || isToday) 1.dp else 0.dp,
                color = if (isSelected) Color.White else (if(isToday) Color.Green else Color.Transparent),
            )
            .padding(3.dp)

        ,
    ) {
        val textColor =  if(showStar) Color.Black else Color.White

        val shape = if(showStar) CircleShape else null

        Box(
            modifier = Modifier
                .align(Alignment.Center)
                .optionalClip(shape)
                .size(35.dp)
                .background(if (showStar) MaterialTheme.colorScheme.primary  else Color.Transparent),
            contentAlignment = Alignment.Center
        ){
            Text(
                text = day.date.dayOfMonth.toString(),
                color = textColor,
                fontSize = 15.sp,
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

private val CalendarLayoutInfo.completelyVisibleMonths: List<CalendarMonth>
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

@Composable
fun SimpleCalendarTitle(
    modifier: Modifier,
    currentMonth: YearMonth,
    goToPrevious: () -> Unit,
    goToNext: () -> Unit,
) {
    Row(
        modifier = modifier.height(40.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconButton(
            onClick = goToPrevious,
        ) {
            Icon(imageVector = Icons.Filled.ArrowBack, contentDescription = "Back")
        }

        Text(
            modifier = Modifier
                .weight(1f),
            text = currentMonth.displayText(),
            fontSize = 22.sp,
            textAlign = TextAlign.Center,
            fontWeight = FontWeight.Medium,
        )

        IconButton(
            onClick = goToNext,
        ) {
            Icon(imageVector = Icons.Filled.ArrowForward, contentDescription = "Back")
        }
    }
}

@Composable
fun WorkoutsCalendar(
    selectedDate: CalendarDay?,
    onDayClicked: (CalendarState,CalendarDay) -> Unit,
    showStar: (CalendarDay) -> Boolean,
){
    val currentDay = remember { LocalDate.now() }
    val currentMonth = remember { YearMonth.now() }
    val startMonth = remember { currentMonth.minusMonths(500) }
    val endMonth = remember { currentMonth.plusMonths(500) }

    val daysOfWeek = remember { daysOfWeek() }

    val calendarState = rememberCalendarState(
        startMonth = startMonth,
        endMonth = endMonth,
        firstVisibleMonth = currentMonth,
        firstDayOfWeek = daysOfWeek.first(),
        outDateStyle = OutDateStyle.EndOfGrid,
    )

    val visibleMonth = rememberFirstCompletelyVisibleMonth(calendarState)
    val scope = rememberCoroutineScope()

    SimpleCalendarTitle(
        modifier = Modifier,
        currentMonth = visibleMonth.yearMonth,
        goToPrevious = {
            scope.launch {
                calendarState.scrollToMonth(calendarState.firstVisibleMonth.yearMonth.previousMonth)
            }
        },
        goToNext = {
            scope.launch {
                calendarState.scrollToMonth(calendarState.firstVisibleMonth.yearMonth.nextMonth)
            }
        },
    )
    HorizontalCalendar(
        modifier = Modifier.fillMaxWidth(),
        state = calendarState,
        calendarScrollPaged= false,
        userScrollEnabled = false,
        dayContent = { day ->
            Day(
                isToday = day.date == currentDay,
                day = day,
                isSelected = selectedDate?.date == day.date,
                showStar = showStar(day),
            ) { currentDay ->
                onDayClicked(calendarState,currentDay)
            }
        },
        monthHeader = {
            MonthHeader(
                modifier = Modifier.padding(vertical = 8.dp),
                daysOfWeek = daysOfWeek(),
            )
        },
    )
}