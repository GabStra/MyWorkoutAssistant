package com.gabstra.myworkoutassistant.shared.adapters

import com.gabstra.myworkoutassistant.shared.HeartRateSource
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import com.google.gson.JsonDeserializationContext
import com.google.gson.JsonDeserializer
import com.google.gson.JsonElement
import com.google.gson.JsonParseException
import com.google.gson.reflect.TypeToken
import java.time.LocalDate
import java.lang.reflect.Type
import java.util.UUID

class WorkoutAdapter : JsonDeserializer<Workout> {
    override fun deserialize(
        json: JsonElement,
        typeOfT: Type,
        context: JsonDeserializationContext,
    ): Workout {
        val jsonObject = json.asJsonObject
        val workoutComponentsType = object : TypeToken<List<WorkoutComponent>>() {}.type
        val heartRateSource = jsonObject.get("heartRateSource")
            ?.takeUnless { it.isJsonNull }
            ?.asString
            ?.let { value -> runCatching { HeartRateSource.valueOf(value) }.getOrNull() }
            ?: if (jsonObject.get("usePolarDevice")?.asBoolean == true) {
                HeartRateSource.POLAR_BLE
            } else {
                HeartRateSource.WATCH_SENSOR
            }

        return Workout(
            id = UUID.fromString(jsonObject.get("id").asString),
            name = jsonObject.get("name").asString,
            description = jsonObject.get("description").asString,
            workoutComponents = context.deserialize(jsonObject.get("workoutComponents"), workoutComponentsType)
                ?: emptyList(),
            order = jsonObject.get("order")?.asInt ?: 0,
            enabled = jsonObject.get("enabled")?.asBoolean ?: true,
            heartRateSource = heartRateSource,
            creationDate = context.deserialize(jsonObject.get("creationDate"), LocalDate::class.java),
            previousVersionId = jsonObject.get("previousVersionId")
                ?.takeUnless { it.isJsonNull }
                ?.asString
                ?.let(UUID::fromString),
            nextVersionId = jsonObject.get("nextVersionId")
                ?.takeUnless { it.isJsonNull }
                ?.asString
                ?.let(UUID::fromString),
            isActive = jsonObject.get("isActive")?.asBoolean ?: true,
            timesCompletedInAWeek = jsonObject.get("timesCompletedInAWeek")
                ?.takeUnless { it.isJsonNull }
                ?.asInt,
            globalId = jsonObject.get("globalId")
                ?.takeUnless { it.isJsonNull }
                ?.asString
                ?.let(UUID::fromString)
                ?: UUID.randomUUID(),
            type = jsonObject.get("type")?.asInt ?: 0,
            workoutPlanId = jsonObject.get("workoutPlanId")
                ?.takeUnless { it.isJsonNull }
                ?.asString
                ?.let(UUID::fromString),
        )
    }
}
