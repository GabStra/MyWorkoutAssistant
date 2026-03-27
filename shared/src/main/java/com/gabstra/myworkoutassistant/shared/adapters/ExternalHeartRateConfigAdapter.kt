package com.gabstra.myworkoutassistant.shared.adapters

import com.gabstra.myworkoutassistant.shared.ExternalHeartRateConfig
import com.gabstra.myworkoutassistant.shared.HeartRateSource
import com.gabstra.myworkoutassistant.shared.PolarHeartRateConfig
import com.gabstra.myworkoutassistant.shared.WhoopConnectionMode
import com.gabstra.myworkoutassistant.shared.WhoopHeartRateConfig
import com.google.gson.JsonDeserializationContext
import com.google.gson.JsonDeserializer
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonParseException
import com.google.gson.JsonSerializationContext
import com.google.gson.JsonSerializer
import java.lang.reflect.Type

class ExternalHeartRateConfigAdapter :
    JsonSerializer<ExternalHeartRateConfig>,
    JsonDeserializer<ExternalHeartRateConfig> {

    override fun serialize(
        src: ExternalHeartRateConfig,
        typeOfSrc: Type,
        context: JsonSerializationContext,
    ): JsonElement {
        val jsonObject = JsonObject()
        jsonObject.addProperty("source", src.source.name)
        when (src) {
            is PolarHeartRateConfig -> {
                jsonObject.addProperty("deviceId", src.deviceId)
                src.displayName?.let { jsonObject.addProperty("displayName", it) }
            }

            is WhoopHeartRateConfig -> {
                src.deviceId?.let { jsonObject.addProperty("deviceId", it) }
                src.displayName?.let { jsonObject.addProperty("displayName", it) }
                jsonObject.addProperty("connectionMode", src.connectionMode.name)
            }
        }
        return jsonObject
    }

    override fun deserialize(
        json: JsonElement,
        typeOfT: Type,
        context: JsonDeserializationContext,
    ): ExternalHeartRateConfig {
        val jsonObject = json.asJsonObject
        val source = jsonObject.get("source")?.asString
            ?.let { value -> runCatching { HeartRateSource.valueOf(value) }.getOrNull() }
            ?: throw JsonParseException("Missing or invalid heart-rate config source")

        return when (source) {
            HeartRateSource.POLAR_BLE -> PolarHeartRateConfig(
                deviceId = jsonObject.get("deviceId")?.asString
                    ?: throw JsonParseException("Missing Polar deviceId"),
                displayName = jsonObject.get("displayName")?.takeUnless { it.isJsonNull }?.asString,
            )

            HeartRateSource.WHOOP_BLE -> WhoopHeartRateConfig(
                deviceId = jsonObject.get("deviceId")?.takeUnless { it.isJsonNull }?.asString,
                displayName = jsonObject.get("displayName")?.takeUnless { it.isJsonNull }?.asString,
                connectionMode = jsonObject.get("connectionMode")
                    ?.takeUnless { it.isJsonNull }
                    ?.asString
                    ?.let { value ->
                        runCatching { WhoopConnectionMode.valueOf(value) }.getOrDefault(
                            WhoopConnectionMode.BLE_BROADCAST
                        )
                    }
                    ?: WhoopConnectionMode.BLE_BROADCAST,
            )

            HeartRateSource.WATCH_SENSOR ->
                throw JsonParseException("WATCH_SENSOR is not a valid external heart-rate config source")
        }
    }
}
