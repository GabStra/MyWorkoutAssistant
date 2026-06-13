package com.gabstra.myworkoutassistant.shared.adapters

import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.workout.model.WorkoutSessionEndReason
import com.google.gson.JsonDeserializationContext
import com.google.gson.JsonDeserializer
import com.google.gson.JsonElement
import com.google.gson.JsonPrimitive
import java.lang.reflect.Type
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID

class WorkoutHistoryAdapter : JsonDeserializer<WorkoutHistory> {
    override fun deserialize(
        json: JsonElement,
        typeOfT: Type,
        context: JsonDeserializationContext
    ): WorkoutHistory {
        val jsonObject = json.asJsonObject
        val workoutId = context.deserialize<UUID>(jsonObject.get("workoutId"), UUID::class.java)
        return WorkoutHistory(
            id = context.deserialize(jsonObject.get("id"), UUID::class.java),
            workoutId = workoutId,
            date = context.deserialize(jsonObject.get("date"), LocalDate::class.java),
            time = context.deserialize(jsonObject.get("time"), LocalTime::class.java),
            startTime = context.deserialize(jsonObject.get("startTime"), LocalDateTime::class.java),
            duration = jsonObject.get("duration")?.asInt ?: 0,
            heartBeatRecords = jsonObject.get("heartBeatRecords")
                ?.takeIf { it.isJsonArray }
                ?.asJsonArray
                ?.mapNotNull(::parseHeartBeatRecord)
                ?: emptyList(),
            isDone = jsonObject.get("isDone")?.asBoolean ?: false,
            hasBeenSentToHealth = jsonObject.get("hasBeenSentToHealth")?.asBoolean ?: false,
            globalId = jsonObject.get("globalId")?.let {
                context.deserialize<UUID>(it, UUID::class.java)
            } ?: workoutId,
            version = jsonObject.get("version")?.asLong?.toUInt() ?: 0u,
            endReason = jsonObject.get("endReason")
                ?.takeUnless { it.isJsonNull }
                ?.asString
                ?.let { runCatching { WorkoutSessionEndReason.valueOf(it) }.getOrNull() }
                ?: WorkoutSessionEndReason.COMPLETED
        )
    }

    private fun parseHeartBeatRecord(element: JsonElement): Int? {
        val primitive = element as? JsonPrimitive ?: return null
        return when {
            primitive.isNumber -> primitive.asDouble.toInt()
            primitive.isString -> primitive.asString.toDoubleOrNull()?.toInt()
            else -> null
        }
    }
}
