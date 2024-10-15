package com.gabstra.myworkoutassistant.shared.typeconverters

import androidx.room.TypeConverter

class UIntConverter {
    @TypeConverter
    fun fromUInt(value: UInt): Int {
        return value.toInt() // Convert UInt to Int for storing
    }

    @TypeConverter
    fun toUInt(value: Int): UInt {
        return value.toUInt() // Convert Int back to UInt when retrieving
    }
}