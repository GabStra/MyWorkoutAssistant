package com.gabstra.myworkoutassistant.shared.typeconverters;

import androidx.room.TypeConverter;

import java.time.LocalTime;
import java.time.format.DateTimeFormatter;

class TimeTypeConverter {
    private val formatter = DateTimeFormatter.ofPattern("HH:mm:ss")

    @TypeConverter
    fun fromStringToLocalTime(value: String?): LocalTime? {
        return value?.let {
            LocalTime.parse(it, formatter)
        }
    }

    @TypeConverter
    fun fromLocalTimeToString(time: LocalTime?): String? {
        return time?.format(formatter)
    }
}