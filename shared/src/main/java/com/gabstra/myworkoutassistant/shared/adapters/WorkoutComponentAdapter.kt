package com.gabstra.myworkoutassistant.shared.adapters

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.getExerciseTypeFromSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import com.gabstra.myworkoutassistant.shared.workoutcomponents.ExerciseGroup
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
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
            is ExerciseGroup -> "ExerciseGroup"
            else -> throw RuntimeException("Unsupported workout component type")
        }

        jsonObject.addProperty("id", src.id.toString())
        jsonObject.addProperty("type", workoutComponentType)
        jsonObject.addProperty("name", src.name)
        jsonObject.addProperty("restTimeInSec", src.restTimeInSec)
        jsonObject.addProperty("enabled", src.enabled)
        jsonObject.addProperty("skipWorkoutRest", src.skipWorkoutRest)

        when (src) {
            is Exercise -> {
                jsonObject.add("sets", context.serialize(src.sets))
                jsonObject.addProperty("exerciseType", src.exerciseType.name)
                jsonObject.addProperty("notes", src.notes)
            }
            is ExerciseGroup -> {
                jsonObject.add("workoutComponents", context.serialize(src.workoutComponents))
            }
        }
        return jsonObject
    }

    override fun deserialize(json: JsonElement, typeOfT: Type, context: JsonDeserializationContext): WorkoutComponent {
        val jsonObject = json.asJsonObject
        val id = jsonObject.get("id").asString
        val type = jsonObject.get("type").asString
        val name = jsonObject.get("name").asString

        val enabled = jsonObject.get("enabled").asBoolean
        val skipWorkoutRest = if (jsonObject.has("skipWorkoutRest")) {
            jsonObject.get("skipWorkoutRest").asBoolean
        } else {
            false
        }
        val restTimeInSec = jsonObject.get("restTimeInSec").asInt

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
                val notes =if (jsonObject.has("notes")) {
                    jsonObject.get("notes").asString
                } else {
                    ""
                }
                Exercise(UUID.fromString(id), name, restTimeInSec, enabled, skipWorkoutRest, notes, sets, exerciseType)
            }
            "ExerciseGroup" -> {
                val workoutComponentsType = object : TypeToken<List<WorkoutComponent>>() {}.type
                val workoutComponents: List<WorkoutComponent> = context.deserialize(jsonObject.get("workoutComponents"), workoutComponentsType)
                ExerciseGroup(UUID.fromString(id), name, restTimeInSec,enabled,skipWorkoutRest, workoutComponents)
            }
            else -> throw RuntimeException("Unsupported workout component type")
        }
    }
}