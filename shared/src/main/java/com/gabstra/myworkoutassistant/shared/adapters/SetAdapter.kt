package com.gabstra.myworkoutassistant.shared.adapters

import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.google.gson.JsonDeserializationContext
import com.google.gson.JsonDeserializer
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonSerializationContext
import com.google.gson.JsonSerializer
import java.lang.reflect.Type
import java.util.UUID

class SetAdapter: JsonSerializer<Set>, JsonDeserializer<Set> {
    override fun serialize(src: Set, typeOfSrc: Type, context: JsonSerializationContext): JsonElement {
        val jsonObject = JsonObject()
        val exerciseType = when (src) {
            is WeightSet -> "WeightSet"
            is BodyWeightSet -> "BodyWeightSet"
            is TimedDurationSet -> "TimedDurationSet"
            is EnduranceSet -> "EnduranceSet"
            is RestSet -> "RestSet"
            else -> throw RuntimeException("Unsupported set type")
        }

        jsonObject.addProperty("id", src.id.toString())
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
            is RestSet ->{
                jsonObject.addProperty("timeInSeconds", src.timeInSeconds)
                jsonObject.addProperty("isRestPause", src.isRestPause)
            }
        }
        return jsonObject
    }

    override fun deserialize(json: JsonElement, typeOfT: Type, context: JsonDeserializationContext): Set {
        val jsonObject = json.asJsonObject

        val id = UUID.fromString(jsonObject.get("id").asString)
        val type = jsonObject.get("type").asString

        return when (type) {
            "WeightSet" -> {
                val reps = jsonObject.get("reps").asInt
                val weight = jsonObject.get("weight").asFloat
                WeightSet(id,reps, weight)
            }
            "BodyWeightSet" -> {
                val reps = jsonObject.get("reps").asInt
                BodyWeightSet(id,reps)
            }
            "TimedDurationSet" -> {
                val timeInMillis = jsonObject.get("timeInMillis").asInt
                val autoStart = jsonObject.get("autoStart").asBoolean
                val autoStop = jsonObject.get("autoStop").asBoolean
                TimedDurationSet(id,timeInMillis,autoStart,autoStop)
            }
            "EnduranceSet" -> {
                val timeInMillis = jsonObject.get("timeInMillis").asInt
                val autoStart = jsonObject.get("autoStart").asBoolean
                val autoStop = jsonObject.get("autoStop").asBoolean
                EnduranceSet(id,timeInMillis,autoStart,autoStop)
            }
            "RestSet" -> {
                val timeInSeconds = jsonObject.get("timeInSeconds").asInt
                val isRestPause =  if(jsonObject.has("isRestPause"))jsonObject.get("isRestPause").asBoolean else false
                RestSet(id,timeInSeconds,isRestPause)
            }

            else -> throw RuntimeException("Unsupported set type")
        }
    }
}