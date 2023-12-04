package com.gabstra.myworkoutassistant.shared.typeconverters

import androidx.room.TypeConverter
import java.time.LocalDate

class DateTypeConverter {

    @TypeConverter
    fun fromLongToDate(value: Long?): LocalDate? {
        return value?.let { LocalDate.ofEpochDay(it) }
    }

    @TypeConverter
    fun fromDateToLong(date: LocalDate?): Long? {
        return date?.toEpochDay()
    }
}