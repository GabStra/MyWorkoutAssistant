package com.gabstra.myworkoutassistant.data

import com.google.gson.JsonDeserializationContext
import com.google.gson.JsonDeserializer
import com.google.gson.JsonElement
import com.google.gson.JsonNull
import com.google.gson.JsonPrimitive
import com.google.gson.JsonSerializationContext
import com.google.gson.JsonSerializer
import java.lang.reflect.Type
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.format.DateTimeFormatter

internal class WearLocalDateAdapter : JsonSerializer<LocalDate>, JsonDeserializer<LocalDate> {
    override fun serialize(src: LocalDate?, typeOfSrc: Type, context: JsonSerializationContext): JsonElement {
        return if (src == null) {
            JsonNull.INSTANCE
        } else {
            JsonPrimitive(src.format(DateTimeFormatter.ISO_LOCAL_DATE))
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

internal class WearLocalTimeAdapter : JsonSerializer<LocalTime>, JsonDeserializer<LocalTime> {
    override fun serialize(src: LocalTime?, typeOfSrc: Type, context: JsonSerializationContext): JsonElement {
        return if (src == null) {
            JsonNull.INSTANCE
        } else {
            JsonPrimitive(src.format(DateTimeFormatter.ISO_LOCAL_TIME))
        }
    }

    override fun deserialize(json: JsonElement, typeOfT: Type, context: JsonDeserializationContext): LocalTime? {
        return if (json.isJsonNull || (json.isJsonPrimitive && json.asString.isEmpty())) {
            null
        } else {
            LocalTime.parse(json.asString, DateTimeFormatter.ISO_LOCAL_TIME)
        }
    }
}

internal class WearLocalDateTimeAdapter : JsonSerializer<LocalDateTime>, JsonDeserializer<LocalDateTime> {
    override fun serialize(src: LocalDateTime?, typeOfSrc: Type, context: JsonSerializationContext): JsonElement {
        return if (src == null) {
            JsonNull.INSTANCE
        } else {
            JsonPrimitive(src.format(DateTimeFormatter.ISO_DATE_TIME))
        }
    }

    override fun deserialize(json: JsonElement, typeOfT: Type, context: JsonDeserializationContext): LocalDateTime? {
        return if (json.isJsonNull || (json.isJsonPrimitive && json.asString.isEmpty())) {
            null
        } else {
            LocalDateTime.parse(json.asString, DateTimeFormatter.ISO_DATE_TIME)
        }
    }
}
