package com.gabstra.myworkoutassistant.shared.adapters

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.getExerciseTypeFromSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import com.google.gson.JsonDeserializationContext
import com.google.gson.JsonDeserializer
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonSerializationContext
import com.google.gson.JsonSerializer
import com.google.gson.reflect.TypeToken
import java.lang.reflect.Type
import java.util.UUID

class WorkoutComponentAdapter : JsonSerializer<WorkoutComponent>, JsonDeserializer<WorkoutComponent> {
    override fun serialize(src: WorkoutComponent, typeOfSrc: Type, context: JsonSerializationContext): JsonElement {
        val jsonObject = JsonObject()
        val workoutComponentType = when (src) {
            is Exercise -> "Exercise"
            is Rest -> "Rest"
            else -> throw RuntimeException("Unsupported workout component type")
        }

        jsonObject.addProperty("id", src.id.toString())
        jsonObject.addProperty("type", workoutComponentType)
        jsonObject.addProperty("enabled", src.enabled)

        when (src) {
            is Exercise -> {
                jsonObject.addProperty("name", src.name)
                jsonObject.addProperty("doNotStoreHistory", src.doNotStoreHistory)
                jsonObject.addProperty("notes", src.notes)
                jsonObject.add("sets", context.serialize(src.sets))
                jsonObject.addProperty("exerciseType", src.exerciseType.name)

            }
            is Rest -> {
                jsonObject.addProperty("timeInSeconds", src.timeInSeconds)
            }
        }
        return jsonObject
    }

    override fun deserialize(json: JsonElement, typeOfT: Type, context: JsonDeserializationContext): WorkoutComponent {
        val jsonObject = json.asJsonObject
        val id = UUID.fromString(jsonObject.get("id").asString)
        val type = jsonObject.get("type").asString


        val enabled = jsonObject.get("enabled").asBoolean

        val doNotStoreHistory = if (jsonObject.has("doNotStoreHistory")) {
            jsonObject.get("doNotStoreHistory").asBoolean
        } else {
            false
        }

        return when (type) {
            "Exercise" -> {
                val setsType = object : TypeToken<List<Set>>() {}.type

                val sets: List<Set> = context.deserialize(jsonObject.get("sets"), setsType)

                val exerciseType = if (jsonObject.has("exerciseType")) {
                    ExerciseType.valueOf(jsonObject.get("exerciseType").asString)
                } else {
                    if (sets.isNotEmpty()) {
                        getExerciseTypeFromSet(sets.first())
                    } else {
                        ExerciseType.BODY_WEIGHT
                    }
                }
                val name = jsonObject.get("name").asString
                val notes =if (jsonObject.has("notes")) {
                    jsonObject.get("notes").asString
                } else {
                    ""
                }
                Exercise(id,enabled, name, doNotStoreHistory,notes, sets, exerciseType)
            }
            "Rest" -> {
                val timeInSeconds = jsonObject.get("timeInSeconds").asInt
                Rest(id,enabled,timeInSeconds)
            }
            else -> throw RuntimeException("Unsupported workout component type")
        }
    }
}