package com.gabstra.myworkoutassistant.shared.adapters

import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.google.gson.JsonDeserializationContext

import com.google.gson.JsonDeserializer
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonSerializationContext
import com.google.gson.JsonSerializer
import java.lang.reflect.Type

class SetDataAdapter: JsonSerializer<SetData>, JsonDeserializer<SetData> {
    override fun serialize(src: SetData, typeOfSrc: Type, context: JsonSerializationContext): JsonElement {
        val jsonObject = JsonObject()
        val exerciseType = when (src) {
            is WeightSetData -> "WeightSetData"
            is BodyWeightSetData -> "BodyWeightSetData"
            is TimedDurationSetData -> "TimedDurationSetData"
            is EnduranceSetData -> "EnduranceSetData"
            is RestSetData -> "RestSetData"
            else -> throw RuntimeException("Unsupported set type")
        }
        jsonObject.addProperty("type", exerciseType)

        when (src) {
            is WeightSetData -> {
                jsonObject.addProperty("actualReps", src.actualReps)
                jsonObject.addProperty("actualWeight", src.actualWeight)
                jsonObject.addProperty("volume", src.volume)
                jsonObject.addProperty("isRestPause", src.isRestPause)
            }
            is BodyWeightSetData ->{
                jsonObject.addProperty("actualReps", src.actualReps)
                jsonObject.addProperty("additionalWeight", src.additionalWeight)
                jsonObject.addProperty("relativeBodyWeightInKg", src.relativeBodyWeightInKg)
                jsonObject.addProperty("volume", src.volume)
                jsonObject.addProperty("isRestPause", src.isRestPause)
            }
            is TimedDurationSetData ->{
                jsonObject.addProperty("startTimer", src.startTimer)
                jsonObject.addProperty("endTimer", src.endTimer)
                jsonObject.addProperty("autoStart",src.autoStart)
                jsonObject.addProperty("autoStop",src.autoStop)
            }
            is EnduranceSetData ->{
                jsonObject.addProperty("startTimer", src.startTimer)
                jsonObject.addProperty("endTimer", src.endTimer)
                jsonObject.addProperty("autoStart",src.autoStart)
                jsonObject.addProperty("autoStop",src.autoStop)
            }
            is RestSetData ->{
                jsonObject.addProperty("startTimer", src.startTimer)
                jsonObject.addProperty("endTimer", src.endTimer)
            }
        }
        return jsonObject
    }

    override fun deserialize(json: JsonElement, typeOfT: Type, context: JsonDeserializationContext): SetData {
        val jsonObject = json.asJsonObject
        val type = jsonObject.get("type").asString

        return when (type) {
            "WeightSetData" -> {
                val actualReps = jsonObject.get("actualReps").asInt
                val actualWeight = jsonObject.get("actualWeight").asDouble
                val volume = if(jsonObject.has("volume")) jsonObject.get("volume").asDouble else 0.0
                val isRestPause =  if(jsonObject.has("isRestPause"))jsonObject.get("isRestPause").asBoolean else false
                WeightSetData(actualReps, actualWeight, volume,isRestPause)
            }
            "BodyWeightSetData" -> {
                val actualReps = jsonObject.get("actualReps").asInt
                val additionalWeight = if(jsonObject.has("additionalWeight")) jsonObject.get("additionalWeight").asDouble else 0.0
                val relativeBodyWeightInKg = if(jsonObject.has("relativeBodyWeightInKg")) jsonObject.get("relativeBodyWeightInKg").asDouble else 0.0
                val volume =  if(jsonObject.has("volume")) jsonObject.get("volume").asDouble else 0.0
                val isRestPause =  if(jsonObject.has("isRestPause"))jsonObject.get("isRestPause").asBoolean else false
                BodyWeightSetData(actualReps,additionalWeight,relativeBodyWeightInKg,volume,isRestPause)
            }
            "TimedDurationSetData" -> {
                val startTimer = jsonObject.get("startTimer").asInt
                val endTimer = jsonObject.get("endTimer").asInt
                val autoStart = if(jsonObject.has("autoStart")) jsonObject.get("autoStart").asBoolean else false
                val autoStop = if(jsonObject.has("autoStop")) jsonObject.get("autoStop").asBoolean else false
                TimedDurationSetData(startTimer,endTimer,autoStart,autoStop)
            }
            "EnduranceSetData" -> {
                val startTimer = jsonObject.get("startTimer").asInt
                val endTimer = jsonObject.get("endTimer").asInt
                val autoStart = if(jsonObject.has("autoStart")) jsonObject.get("autoStart").asBoolean else false
                val autoStop = if(jsonObject.has("autoStop")) jsonObject.get("autoStop").asBoolean else false
                EnduranceSetData(startTimer,endTimer,autoStart,autoStop)
            }
            "RestSetData" -> {
                val startTimer = jsonObject.get("startTimer").asInt
                val endTimer = jsonObject.get("endTimer").asInt
                RestSetData(startTimer,endTimer)
            }
            else -> throw RuntimeException("Unsupported set type")
        }
    }
}