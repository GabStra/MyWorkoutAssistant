package com.gabstra.myworkoutassistant.shared

import java.time.DayOfWeek
import java.time.LocalDate
import java.time.YearMonth
import java.time.temporal.TemporalAdjusters

enum class FilterRange {
    LAST_WEEK,
    LAST_7_DAYS,
    LAST_30_DAYS,
    THIS_MONTH,
    LAST_3_MONTHS,
    ALL
}

fun dateRangeFor(range: FilterRange, today: LocalDate = LocalDate.now()): Pair<LocalDate, LocalDate> {
    return when (range) {
        FilterRange.LAST_WEEK -> {
            val thisMonday = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
            val lastMonday = thisMonday.minusWeeks(1)
            val lastSunday = lastMonday.plusDays(6)
            lastMonday to lastSunday
        }
        FilterRange.LAST_7_DAYS -> {
            val start = today.minusDays(6)
            start to today
        }
        FilterRange.LAST_30_DAYS -> {
            val start = today.minusDays(29)
            start to today
        }
        FilterRange.THIS_MONTH -> {
            val ym = YearMonth.from(today)
            ym.atDay(1) to ym.atEndOfMonth()
        }
        FilterRange.LAST_3_MONTHS -> {
            val start = today.minusMonths(3)
            start to today
        }
        FilterRange.ALL -> LocalDate.MIN to LocalDate.MAX
    }
}

fun List<WorkoutHistory>.filterBy(range: FilterRange, today: LocalDate = LocalDate.now()): List<WorkoutHistory> {
    val (start, end) = dateRangeFor(range, today)
    return this.filter { it.date >= start && it.date <= end }
}
