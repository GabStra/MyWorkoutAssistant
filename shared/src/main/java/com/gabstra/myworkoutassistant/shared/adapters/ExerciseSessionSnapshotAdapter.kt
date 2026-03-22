package com.gabstra.myworkoutassistant.shared.adapters

import com.gabstra.myworkoutassistant.shared.ExerciseSessionSnapshot
import com.gabstra.myworkoutassistant.shared.SessionSetSnapshot
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.exerciseSessionSnapshotFromLegacySetHistories
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
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
                            val simpleSet =
                                context.deserialize<SimpleSet?>(sessionSetObject.get("simpleSet"), simpleSetType)
                            SessionSetSnapshot(
                                setId = UUID.fromString(sessionSetObject.get("setId").asString),
                                set = deserializeSetWithLegacyFallback(
                                    sessionSetObject = sessionSetObject,
                                    sessionSetId = UUID.fromString(sessionSetObject.get("setId").asString),
                                    simpleSet = simpleSet,
                                    context = context
                                ),
                                simpleSet = simpleSet,
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

    private fun deserializeSetWithLegacyFallback(
        sessionSetObject: JsonObject,
        sessionSetId: UUID,
        simpleSet: SimpleSet?,
        context: JsonDeserializationContext
    ): Set {
        val setElement = sessionSetObject.get("set")
            ?: throw JsonParseException("ExerciseSessionSnapshot session set is missing 'set'.")

        return try {
            context.deserialize(setElement, Set::class.java)
        } catch (_: RuntimeException) {
            inferLegacySnapshotSet(setElement.asJsonObject, sessionSetId, simpleSet)
        }
    }

    private fun inferLegacySnapshotSet(
        setObject: JsonObject,
        sessionSetId: UUID,
        simpleSet: SimpleSet?
    ): Set {
        val id = setObject.get("id")?.takeIf { !it.isJsonNull }?.asString?.let(UUID::fromString) ?: sessionSetId
        val shouldReapplyHistoryToSet = setObject.get("shouldReapplyHistoryToSet")
            ?.takeIf { !it.isJsonNull }
            ?.asBoolean
        val subCategory = parseSubCategory(setObject)

        if (setObject.has("timeInSeconds")) {
            return RestSet(
                id = id,
                timeInSeconds = setObject.get("timeInSeconds").asInt,
                subCategory = subCategory,
                shouldReapplyHistoryToSet = shouldReapplyHistoryToSet ?: false
            )
        }

        if (setObject.has("timeInMillis")) {
            return TimedDurationSet(
                id = id,
                timeInMillis = setObject.get("timeInMillis").asInt,
                autoStart = setObject.get("autoStart")?.takeIf { !it.isJsonNull }?.asBoolean ?: false,
                autoStop = setObject.get("autoStop")?.takeIf { !it.isJsonNull }?.asBoolean ?: false,
                shouldReapplyHistoryToSet = shouldReapplyHistoryToSet ?: true
            )
        }

        if (setObject.has("additionalWeight")) {
            return BodyWeightSet(
                id = id,
                reps = setObject.get("reps")?.takeIf { !it.isJsonNull }?.asInt ?: simpleSet?.reps ?: 0,
                additionalWeight = setObject.get("additionalWeight")?.takeIf { !it.isJsonNull }?.asDouble ?: 0.0,
                subCategory = subCategory,
                shouldReapplyHistoryToSet = shouldReapplyHistoryToSet ?: true
            )
        }

        if (setObject.has("weight")) {
            return WeightSet(
                id = id,
                reps = setObject.get("reps")?.takeIf { !it.isJsonNull }?.asInt ?: simpleSet?.reps ?: 0,
                weight = setObject.get("weight").asDouble,
                subCategory = subCategory,
                shouldReapplyHistoryToSet = shouldReapplyHistoryToSet ?: true
            )
        }

        if (simpleSet != null) {
            return WeightSet(
                id = id,
                reps = simpleSet.reps,
                weight = simpleSet.weight,
                subCategory = subCategory,
                shouldReapplyHistoryToSet = shouldReapplyHistoryToSet ?: true
            )
        }

        if (shouldReapplyHistoryToSet == false) {
            return RestSet(
                id = id,
                timeInSeconds = 0,
                subCategory = subCategory,
                shouldReapplyHistoryToSet = false
            )
        }

        throw JsonParseException("Unsupported ExerciseSessionSnapshot set payload: $setObject")
    }

    private fun parseSubCategory(setObject: JsonObject): SetSubCategory {
        val subCategoryValue = setObject.get("subCategory")?.takeIf { !it.isJsonNull }?.asString
        if (subCategoryValue != null) {
            return try {
                SetSubCategory.valueOf(subCategoryValue)
            } catch (_: IllegalArgumentException) {
                SetSubCategory.WorkSet
            }
        }
        val isWarmupSet = setObject.get("isWarmupSet")?.takeIf { !it.isJsonNull }?.asBoolean ?: false
        val isRestPause = setObject.get("isRestPause")?.takeIf { !it.isJsonNull }?.asBoolean ?: false
        return when {
            isWarmupSet -> SetSubCategory.WarmupSet
            isRestPause -> SetSubCategory.RestPauseSet
            else -> SetSubCategory.WorkSet
        }
    }
}
