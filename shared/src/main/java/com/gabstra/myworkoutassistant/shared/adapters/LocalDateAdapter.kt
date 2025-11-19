package com.gabstra.myworkoutassistant.shared.adapters

import android.util.Log
import com.google.gson.*
import java.lang.reflect.Type
import java.time.LocalDate
import java.time.format.DateTimeFormatter

class LocalDateAdapter : JsonSerializer<LocalDate>, JsonDeserializer<LocalDate> {

    override fun serialize(src: LocalDate?, typeOfSrc: Type, context: JsonSerializationContext): JsonElement {
        return if (src == null) {
            JsonNull.INSTANCE
        } else {
            JsonPrimitive(src.format(DateTimeFormatter.ISO_LOCAL_DATE))  // Example format: "2023-10-05"
        }
    }

    override fun deserialize(json: JsonElement, typeOfT: Type, context: JsonDeserializationContext): LocalDate? {
        return if (json.isJsonNull || (json.isJsonPrimitive && json.asString.isEmpty())) {
            null
        } else {
            LocalDate.parse(json.asString, DateTimeFormatter.ISO_LOCAL_DATE)
        }
    }
}
