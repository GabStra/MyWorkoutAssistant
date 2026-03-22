package com.gabstra.myworkoutassistant.shared.typeconverters

import androidx.room.TypeConverter
import com.gabstra.myworkoutassistant.shared.RestHistoryScope

class RestHistoryScopeTypeConverter {
    @TypeConverter
    fun fromScope(scope: RestHistoryScope): String = scope.name

    @TypeConverter
    fun toScope(value: String): RestHistoryScope = RestHistoryScope.valueOf(value)
}
