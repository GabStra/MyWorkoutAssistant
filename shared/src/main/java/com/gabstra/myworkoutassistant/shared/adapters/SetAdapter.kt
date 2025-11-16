package com.gabstra.myworkoutassistant.shared.adapters

import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
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
                jsonObject.addProperty("subCategory", src.subCategory.name)
            }
            is BodyWeightSet ->{
                jsonObject.addProperty("reps", src.reps)
                jsonObject.addProperty("additionalWeight", src.additionalWeight)
                jsonObject.addProperty("subCategory", src.subCategory.name)
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
                jsonObject.addProperty("subCategory", src.subCategory.name)
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
                val weight = jsonObject.get("weight").asDouble
                val subCategory = if(jsonObject.has("subCategory")) {
                    try {
                        SetSubCategory.valueOf(jsonObject.get("subCategory").asString)
                    } catch (e: IllegalArgumentException) {
                        SetSubCategory.WorkSet
                    }
                } else {
                    // Legacy migration: convert isWarmupSet and isRestPause to subCategory
                    val isWarmupSet = if(jsonObject.has("isWarmupSet")) jsonObject.get("isWarmupSet").asBoolean else false
                    val isRestPause = if(jsonObject.has("isRestPause")) jsonObject.get("isRestPause").asBoolean else false
                    when {
                        isWarmupSet -> SetSubCategory.WarmupSet
                        isRestPause -> SetSubCategory.RestPauseSet
                        else -> SetSubCategory.WorkSet
                    }
                }
                WeightSet(id,reps, weight,subCategory)
            }
            "BodyWeightSet" -> {
                val reps = jsonObject.get("reps").asInt
                val additionalWeight = if(jsonObject.has("additionalWeight")) jsonObject.get("additionalWeight").asDouble else 0.0
                val subCategory = if(jsonObject.has("subCategory")) {
                    try {
                        SetSubCategory.valueOf(jsonObject.get("subCategory").asString)
                    } catch (e: IllegalArgumentException) {
                        SetSubCategory.WorkSet
                    }
                } else {
                    // Legacy migration: convert isWarmupSet and isRestPause to subCategory
                    val isWarmupSet = if(jsonObject.has("isWarmupSet")) jsonObject.get("isWarmupSet").asBoolean else false
                    val isRestPause = if(jsonObject.has("isRestPause")) jsonObject.get("isRestPause").asBoolean else false
                    when {
                        isWarmupSet -> SetSubCategory.WarmupSet
                        isRestPause -> SetSubCategory.RestPauseSet
                        else -> SetSubCategory.WorkSet
                    }
                }
                BodyWeightSet(id,reps,additionalWeight,subCategory)
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
                val subCategory = if(jsonObject.has("subCategory")) {
                    try {
                        SetSubCategory.valueOf(jsonObject.get("subCategory").asString)
                    } catch (e: IllegalArgumentException) {
                        SetSubCategory.WorkSet
                    }
                } else {
                    // Legacy migration: convert isRestPause to subCategory
                    val isRestPause = if(jsonObject.has("isRestPause")) jsonObject.get("isRestPause").asBoolean else false
                    if (isRestPause) SetSubCategory.RestPauseSet else SetSubCategory.WorkSet
                }
                RestSet(id,timeInSeconds,subCategory)
            }

            else -> throw RuntimeException("Unsupported set type")
        }
    }
}