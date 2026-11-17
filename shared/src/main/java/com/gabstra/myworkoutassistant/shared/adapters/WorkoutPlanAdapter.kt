package com.gabstra.myworkoutassistant.shared.adapters

import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import com.google.gson.JsonDeserializationContext
import com.google.gson.JsonDeserializer
import com.google.gson.JsonElement
import java.lang.reflect.Type
import java.util.UUID

class WorkoutPlanAdapter : JsonDeserializer<WorkoutPlan> {
    override fun deserialize(
        json: JsonElement,
        typeOfT: Type,
        context: JsonDeserializationContext,
    ): WorkoutPlan {
        val obj = json.asJsonObject
        return WorkoutPlan(
            id = UUID.fromString(obj.get("id").asString),
            name = obj.get("name").asString,
            workoutIds = obj.getAsJsonArray("workoutIds")?.map { UUID.fromString(it.asString) } ?: emptyList(),
            order = obj.get("order")?.asInt ?: 0,
            suggestNextPrescription = obj.get("suggestNextPrescription")
                ?.takeUnless { it.isJsonNull }
                ?.asBoolean ?: true,
        )
    }
}
