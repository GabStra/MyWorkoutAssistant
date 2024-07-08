package com.gabstra.myworkoutassistant.shared.typeconverters

import androidx.room.TypeConverter
import java.time.LocalDateTime
import java.time.ZoneOffset

class DateTimeTypeConverter {
    @TypeConverter
    fun fromLongToDate(value: Long?): LocalDateTime? {
        return value?.let { LocalDateTime.ofEpochSecond(it, 0, ZoneOffset.UTC) }
    }

    @TypeConverter
    fun fromDateToLong(date: LocalDateTime?): Long? {
        return date?.toEpochSecond(ZoneOffset.UTC)
    }
}