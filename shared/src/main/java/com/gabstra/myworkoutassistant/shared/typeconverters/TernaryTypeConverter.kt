package com.gabstra.myworkoutassistant.shared.typeconverters

import androidx.room.TypeConverter
import com.gabstra.myworkoutassistant.shared.utils.Ternary

class TernaryTypeConverter {
    @TypeConverter
    fun fromTernary(value: Ternary): String {
        return value.name
    }

    @TypeConverter
    fun toTernary(value: String): Ternary {
        return Ternary.valueOf(value)
    }
}

