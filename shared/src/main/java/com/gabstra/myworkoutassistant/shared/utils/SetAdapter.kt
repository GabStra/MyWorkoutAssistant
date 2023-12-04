package com.gabstra.myworkoutassistant.shared.utils

import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.google.gson.JsonDeserializationContext
import com.google.gson.JsonDeserializer
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonSerializationContext
import com.google.gson.JsonSerializer
import java.lang.reflect.Type

class SetAdapter: JsonSerializer<Set>, JsonDeserializer<Set> {
    override fun serialize(src: Set, typeOfSrc: Type, context: JsonSerializationContext): JsonElement {
        val jsonObject = JsonObject()
        val exerciseType = when (src) {
            is WeightSet -> "WeightSet"
            is BodyWeightSet -> "BodyWeightSet"
            is TimedDurationSet -> "TimedDurationSet"
            is EnduranceSet -> "EnduranceSet"
        }
        jsonObject.addProperty("type", exerciseType)

        when (src) {
            is WeightSet -> {
                jsonObject.addProperty("reps", src.reps)
                jsonObject.addProperty("weight", src.weight)
            }
            is BodyWeightSet ->{
                jsonObject.addProperty("reps", src.reps)
            }
            is TimedDurationSet ->{
                jsonObject.addProperty("timeInMillis", src.timeInMillis)
                jsonObject.addProperty("autoStart", src.autoStart)
                jsonObject.addProperty("autoStop", src.autoStop)
            }
            is EnduranceSet ->{
                jsonObject.addProperty("timeInMillis", src.timeInMillis)
                jsonObject.addProperty("autoStart", src.autoStart)
                jsonObject.addProperty("autoStop", src.autoStop)
            }
        }
        return jsonObject
    }

    override fun deserialize(json: JsonElement, typeOfT: Type, context: JsonDeserializationContext): Set {
        val jsonObject = json.asJsonObject
        val type = jsonObject.get("type").asString

        return when (type) {
            "WeightSet" -> {
                val reps = jsonObject.get("reps").asInt
                val weight = jsonObject.get("weight").asFloat
                WeightSet(reps, weight)
            }
            "BodyWeightSet" -> {
                val reps = jsonObject.get("reps").asInt
                BodyWeightSet(reps)
            }
            "TimedDurationSet" -> {
                val timeInMillis = jsonObject.get("timeInMillis").asInt
                val autoStart = jsonObject.get("autoStart").asBoolean
                val autoStop = jsonObject.get("autoStop").asBoolean
                TimedDurationSet(timeInMillis,autoStart,autoStop)
            }
            "EnduranceSet" -> {
                val timeInMillis = jsonObject.get("timeInMillis").asInt
                val autoStart = jsonObject.get("autoStart").asBoolean
                val autoStop = jsonObject.get("autoStop").asBoolean
                EnduranceSet(timeInMillis,autoStart,autoStop)
            }
            else -> throw RuntimeException("Unsupported set type")
        }
    }
}