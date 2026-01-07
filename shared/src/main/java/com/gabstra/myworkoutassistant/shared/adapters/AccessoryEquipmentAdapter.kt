package com.gabstra.myworkoutassistant.shared.adapters

import com.gabstra.myworkoutassistant.shared.equipments.AccessoryEquipment
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.google.gson.JsonDeserializationContext
import com.google.gson.JsonDeserializer
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonSerializationContext
import com.google.gson.JsonSerializer
import java.lang.reflect.Type
import java.util.UUID

class AccessoryEquipmentAdapter : JsonSerializer<AccessoryEquipment>, JsonDeserializer<AccessoryEquipment> {
    override fun serialize(src: AccessoryEquipment, typeOfSrc: Type, context: JsonSerializationContext): JsonElement {
        return JsonObject().apply {
            addProperty("id", src.id.toString())
            addProperty("type", src.type.name)
            addProperty("name", src.name)
        }
    }

    override fun deserialize(json: JsonElement, typeOfT: Type, context: JsonDeserializationContext): AccessoryEquipment {
        val obj = json.asJsonObject
        val id = UUID.fromString(obj.get("id").asString)
        val name = obj.get("name").asString

        return AccessoryEquipment(
            id = id,
            name = name,
        )
    }
}

