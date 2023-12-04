package com.gabstra.myworkoutassistant.shared.utils

import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
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
        }
        jsonObject.addProperty("type", exerciseType)

        when (src) {
            is WeightSetData -> {
                jsonObject.addProperty("actualReps", src.actualReps)
                jsonObject.addProperty("actualWeight", src.actualWeight)
            }
            is BodyWeightSetData ->{
                jsonObject.addProperty("actualReps", src.actualReps)
            }
            is TimedDurationSetData ->{
                jsonObject.addProperty("actualTimeInMillis", src.actualTimeInMillis)
            }
            is EnduranceSetData ->{
                jsonObject.addProperty("actualTimeInMillis", src.actualTimeInMillis)
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
                val actualWeight = jsonObject.get("actualWeight").asFloat
                WeightSetData(actualReps, actualWeight)
            }
            "BodyWeightSetData" -> {
                val actualReps = jsonObject.get("actualReps").asInt
                BodyWeightSetData(actualReps)
            }
            "TimedDurationSetData" -> {
                val actualTimeInMillis = jsonObject.get("actualTimeInMillis").asInt
                TimedDurationSetData(actualTimeInMillis)
            }
            "EnduranceSetData" -> {
                val actualTimeInMillis = jsonObject.get("actualTimeInMillis").asInt
                EnduranceSetData(actualTimeInMillis)
            }
            else -> throw RuntimeException("Unsupported set type")
        }
    }
}