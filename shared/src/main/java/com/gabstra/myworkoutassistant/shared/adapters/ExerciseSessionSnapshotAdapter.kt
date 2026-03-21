package com.gabstra.myworkoutassistant.shared.adapters

import com.gabstra.myworkoutassistant.shared.ExerciseSessionSnapshot
import com.gabstra.myworkoutassistant.shared.SessionSetSnapshot
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.exerciseSessionSnapshotFromLegacySetHistories
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.google.gson.JsonArray
import com.google.gson.JsonDeserializationContext
import com.google.gson.JsonDeserializer
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonParseException
import com.google.gson.JsonSerializationContext
import com.google.gson.JsonSerializer
import com.google.gson.reflect.TypeToken
import java.lang.reflect.Type
import java.util.UUID

class ExerciseSessionSnapshotAdapter :
    JsonSerializer<ExerciseSessionSnapshot>,
    JsonDeserializer<ExerciseSessionSnapshot> {

    private val legacyListType: Type = object : TypeToken<List<SetHistory>>() {}.type
    private val simpleSetType: Type = object : TypeToken<SimpleSet>() {}.type

    override fun serialize(
        src: ExerciseSessionSnapshot?,
        typeOfSrc: Type?,
        context: JsonSerializationContext
    ): JsonElement {
        val snapshot = src ?: ExerciseSessionSnapshot()
        return JsonObject().apply {
            add(
                "sets",
                JsonArray().apply {
                    snapshot.sets.forEach { sessionSet ->
                        add(
                            JsonObject().apply {
                                addProperty("setId", sessionSet.setId.toString())
                                add("set", context.serialize(sessionSet.set, Set::class.java))
                                add("simpleSet", context.serialize(sessionSet.simpleSet, simpleSetType))
                                addProperty("wasExecuted", sessionSet.wasExecuted)
                                addProperty("wasSkipped", sessionSet.wasSkipped)
                            }
                        )
                    }
                }
            )
        }
    }

    override fun deserialize(
        json: JsonElement?,
        typeOfT: Type?,
        context: JsonDeserializationContext
    ): ExerciseSessionSnapshot {
        if (json == null || json.isJsonNull) {
            return ExerciseSessionSnapshot()
        }
        return when {
            json.isJsonArray -> {
                val legacySetHistories: List<SetHistory> = context.deserialize(json, legacyListType)
                exerciseSessionSnapshotFromLegacySetHistories(legacySetHistories)
            }

            json.isJsonObject -> {
                val jsonObject = json.asJsonObject
                if (!jsonObject.has("sets")) {
                    throw JsonParseException("ExerciseSessionSnapshot json object is missing 'sets'.")
                }
                ExerciseSessionSnapshot(
                    sets = jsonObject
                        .getAsJsonArray("sets")
                        ?.map { sessionSetElement ->
                            val sessionSetObject = sessionSetElement.asJsonObject
                            SessionSetSnapshot(
                                setId = UUID.fromString(sessionSetObject.get("setId").asString),
                                set = context.deserialize(sessionSetObject.get("set"), Set::class.java),
                                simpleSet = context.deserialize(sessionSetObject.get("simpleSet"), simpleSetType),
                                wasExecuted = sessionSetObject.get("wasExecuted")?.asBoolean ?: false,
                                wasSkipped = sessionSetObject.get("wasSkipped")?.asBoolean ?: false,
                            )
                        }
                        ?: emptyList()
                )
            }

            else -> throw JsonParseException("Unsupported ExerciseSessionSnapshot payload: $json")
        }
    }
}
